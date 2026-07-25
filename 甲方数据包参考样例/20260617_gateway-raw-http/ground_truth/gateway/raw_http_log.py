"""Append-only raw HTTP request/response logger grouped by session_id."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .session import is_valid_session_id


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_headers(headers: dict[str, Any]) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in headers.items()}


class RawHttpLogger:
    """Write full HTTP request/response records (including headers) per session."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        env_dir = os.environ.get("GATEWAY_RAW_HTTP_DIR", "").strip()
        chosen = base_dir if base_dir is not None else env_dir
        self.base_dir = Path(chosen).expanduser().resolve() if chosen else None

    @property
    def enabled(self) -> bool:
        return self.base_dir is not None

    def _log_path(self, session_id: str) -> Path:
        if not self.base_dir or not is_valid_session_id(session_id):
            raise ValueError(f"invalid session_id for raw log: {session_id!r}")
        path = self.base_dir / session_id / "raw_http.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _append(self, session_id: str, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self._log_path(session_id)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_request(
        self,
        *,
        session_id: str,
        method: str,
        url: str,
        headers: dict[str, Any],
        body: Any,
    ) -> None:
        self._append(
            session_id,
            {
                "timestamp": _utcnow_iso(),
                "direction": "request",
                "method": method,
                "url": url,
                "headers": _normalize_headers(headers),
                "body": body,
            },
        )

    def log_response(
        self,
        *,
        session_id: str,
        status: int,
        headers: dict[str, Any],
        body: Any,
    ) -> None:
        self._append(
            session_id,
            {
                "timestamp": _utcnow_iso(),
                "direction": "response",
                "status": status,
                "headers": _normalize_headers(headers),
                "body": body,
            },
        )
