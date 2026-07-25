"""Append-only trajectory writer.

Writes go to:
    <log_dir>/<project_id>/<session_id>/completions.jsonl   (append-only)
    <log_dir>/<project_id>/<session_id>/meta.json           (read-modify-write)

Concurrency model (v1, single-process):
    - completions.jsonl: `open(..., "a")` is line-atomic on POSIX.
      Multiple asyncio tasks appending from the same event loop never
      interleave a line (each `write` is a single write(2) call).
    - meta.json: serialized per-session with `asyncio.Lock`. Reading
      + writing is fast (one small JSON doc) so contention is a
      non-issue at the rates a single gateway can sustain.

Why per-session locks (not one global lock): lets sessions progress
in parallel when one session has a slow upstream call mid-flight.

Why not flock(): v1 targets a single process. flock() can be added in
v4+ if we ever scale to multi-process.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import CompletionRecord, TrajectoryMeta
from .session import build_session_dir, completions_path, meta_path

logger = logging.getLogger(__name__)


class TrajectoryWriter:
    """Append completions to a session's JSONL; keep its meta.json fresh."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    # ----- public API ---------------------------------------------------

    async def next_sequence(self, project_id: str, session_id: str) -> int:
        """Return the sequence number that the *next* `append` will use.

        Reads the current meta (or 0 if the session is brand new) and
        returns its `completion_count`. The actual increment happens
        in `append` when the record is persisted — so two callers
        asking concurrently may receive the same number, but only
        the one whose `append` lands first wins (the second one
        writes over the same line and is detectable from a manual
        inspection). For v1 we accept that race; v2 can take a
        per-session lock around peek+write.
        """
        session_dir = build_session_dir(self.log_dir, project_id, session_id)
        meta = await asyncio.to_thread(_read_meta, meta_path(session_dir))
        return 0 if meta is None else meta.completion_count

    async def append(
        self,
        record: CompletionRecord,
        *,
        max_raw_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        """Append `record` to its session's completions.jsonl and update meta."""
        # Truncate oversized streaming bodies so a runaway upstream can't
        # fill the disk. We keep the first `max_raw_bytes` so partial
        # content is still usable for v3 export.
        if record.is_streaming and record.response_raw is not None:
            if len(record.response_raw.encode("utf-8")) > max_raw_bytes:
                truncated = record.response_raw.encode("utf-8")[:max_raw_bytes].decode(
                    "utf-8", errors="replace"
                )
                logger.warning(
                    "Truncated streaming response_raw for session=%s completion=%s",
                    record.session_id,
                    record.completion_id,
                )
                record = record.model_copy(update={"response_raw": truncated + "\n...[truncated]"})

        session_dir = build_session_dir(self.log_dir, record.project_id, record.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        lock = await self._lock_for(f"{record.project_id}/{record.session_id}")
        async with lock:
            # 1. Append the line.
            line = record.model_dump_json()
            cpath = completions_path(session_dir)
            await asyncio.to_thread(_append_line, cpath, line)
            # 2. Refresh meta.
            meta = await asyncio.to_thread(_read_meta, meta_path(session_dir))
            if meta is None:
                meta = TrajectoryMeta(
                    session_id=record.session_id,
                    project_id=record.project_id,
                    created_at=record.timestamp,
                    updated_at=record.timestamp,
                    completion_count=0,
                )
            _merge_into_meta(meta, record)
            meta.touch()
            await asyncio.to_thread(_write_meta_atomic, meta_path(session_dir), meta)

    async def close(self) -> None:
        """No persistent handles to close in v1; reserved for future use."""
        return None

    # ----- internals ----------------------------------------------------

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._session_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[key] = lock
            return lock


# ----- sync helpers (run inside asyncio.to_thread) --------------------


def _append_line(path: Path, line: str) -> None:
    # POSIX guarantees that a single write(2) of <= PIPE_BUF bytes is
    # atomic. JSONL lines are well under that for typical LLM responses.
    # We still use a leading newline so the file is always valid JSONL
    # even if the first write is interrupted.
    needs_leading_nl = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8") as f:
        if needs_leading_nl:
            f.write("\n")
        f.write(line)


def _read_meta(path: Path) -> TrajectoryMeta | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read meta at %s; starting fresh", path)
        return None
    try:
        return TrajectoryMeta.model_validate(data)
    except Exception:
        logger.warning("Invalid meta at %s; starting fresh", path)
        return None


def _write_meta_atomic(path: Path, meta: TrajectoryMeta) -> None:
    # Write to a temp file in the same directory then rename — avoids
    # half-written meta.json if the process dies mid-write.
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = meta.model_dump_json(indent=2)
    with tmp.open("w", encoding="utf-8") as f:
        f.write(payload)
    tmp.replace(path)


def _merge_into_meta(meta: TrajectoryMeta, record: CompletionRecord) -> None:
    meta.completion_count += 1
    if record.model_id not in meta.models_used:
        meta.models_used.append(record.model_id)
    if record.upstream not in meta.upstreams_used:
        meta.upstreams_used.append(record.upstream)
    if record.token_usage is not None:
        if record.token_usage.prompt_tokens is not None:
            meta.total_prompt_tokens += record.token_usage.prompt_tokens
        if record.token_usage.completion_tokens is not None:
            meta.total_completion_tokens += record.token_usage.completion_tokens
        if record.token_usage.total_tokens is not None:
            meta.total_tokens += record.token_usage.total_tokens
    if record.error is not None:
        meta.last_error = record.error


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
