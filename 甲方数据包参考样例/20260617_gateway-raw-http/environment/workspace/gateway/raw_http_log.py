"""Raw HTTP trace logger.

Records the full upstream HTTP request and response (including all
headers) for every proxied call, grouped by ``?session_id=`` query
param.  Each session gets its own directory::

    <raw_http_dir>/<session_id>/raw_http.jsonl

Every line in ``raw_http.jsonl`` is one JSON object with either
``"direction": "request"`` or ``"direction": "response"``.

The directory is controlled by:
  - ``GATEWAY_RAW_HTTP_DIR`` environment variable  (takes precedence)
  - ``GatewayConfig.raw_http_dir``                 (optional config field)

When neither is set, raw HTTP logging is silently disabled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_body(raw: bytes | None) -> Any:
    """Return a JSON-friendly representation of *raw* bytes.

    Tries to parse as JSON first; falls back to a UTF-8 string.
    Returns ``None`` when *raw* is ``None`` or empty.
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _headers_to_dict(headers: httpx.Headers) -> dict[str, str]:
    """Convert httpx ``Headers`` to a plain ``{str: str}`` mapping."""
    return {k: v for k, v in headers.items()}


# ---------------------------------------------------------------------------
# Public logger
# ---------------------------------------------------------------------------


class RawHttpLogger:
    """Append raw upstream HTTP request/response pairs to per-session JSONL files."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    # -- internal ----------------------------------------------------------

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    async def _append(self, session_id: str, entry: dict[str, Any]) -> None:
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        log_path = session_dir / "raw_http.jsonl"

        lock = await self._lock_for(session_id)
        async with lock:
            line = json.dumps(entry, ensure_ascii=False)
            await asyncio.to_thread(self._write_line, log_path, line)

    @staticmethod
    def _write_line(path: Path, line: str) -> None:
        needs_nl = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8") as fh:
            if needs_nl:
                fh.write("\n")
            fh.write(line)

    # -- public API --------------------------------------------------------

    async def log_request(
        self,
        session_id: str,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: Any,
    ) -> None:
        """Persist one *request* entry."""
        entry: dict[str, Any] = {
            "timestamp": _utcnow_iso(),
            "direction": "request",
            "method": method,
            "url": url,
            "headers": headers,
            "body": body,
        }
        await self._append(session_id, entry)

    async def log_response(
        self,
        session_id: str,
        *,
        status: int,
        headers: dict[str, str],
        body: Any,
    ) -> None:
        """Persist one *response* entry."""
        entry: dict[str, Any] = {
            "timestamp": _utcnow_iso(),
            "direction": "response",
            "status": status,
            "headers": headers,
            "body": body,
        }
        await self._append(session_id, entry)

    async def log_pair(
        self,
        session_id: str,
        *,
        request: httpx.Request,
        response: httpx.Response,
        response_body_raw: bytes | None = None,
    ) -> None:
        """Convenience: log a matched request + response pair.

        ``response_body_raw`` is used when the caller has already read
        the body (e.g. streaming responses where ``response.content``
        may not be populated).  Falls back to ``response.content`` when
        *None*.
        """
        req_body_bytes: bytes | None = None
        try:
            req_body_bytes = request.content
        except Exception:  # pragma: no cover - content always available for built requests
            pass

        await self.log_request(
            session_id,
            method=request.method,
            url=str(request.url),
            headers=_headers_to_dict(request.headers),
            body=_safe_body(req_body_bytes),
        )

        resp_body_bytes = response_body_raw if response_body_raw is not None else response.content
        await self.log_response(
            session_id,
            status=response.status_code,
            headers=_headers_to_dict(response.headers),
            body=_safe_body(resp_body_bytes),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_raw_http_logger(
    config_raw_http_dir: str | None = None,
) -> RawHttpLogger | None:
    """Return a ``RawHttpLogger`` or *None* if raw logging is disabled.

    Resolution order:
      1. ``GATEWAY_RAW_HTTP_DIR`` environment variable
      2. *config_raw_http_dir* argument (from ``GatewayConfig``)
    """
    raw_dir = os.environ.get("GATEWAY_RAW_HTTP_DIR") or config_raw_http_dir
    if not raw_dir:
        return None
    path = Path(raw_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return RawHttpLogger(path)
