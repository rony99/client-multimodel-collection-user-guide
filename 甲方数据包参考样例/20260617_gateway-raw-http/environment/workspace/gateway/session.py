"""Session ID resolution and path building.

A "session" here is one agent run. All completions inside a session
share a session_id and end up in the same per-session directory on disk.

Resolution priority (mirrors Polar's src/polar/gateway/session.py:215-244):
    1. `?session_id=` query param (explicit, top priority)
    2. `X-Session-Id` header
    3. `_proxy_session_id` field in the JSON body
    4. `Authorization: Bearer …` value, if a registry already knows it
    5. Generated UUID (new session)

We deliberately do NOT maintain a server-side "session registry" in v1:
the file system *is* the registry. If a request comes in with an
Authorization token we've never seen, we just generate a new UUID —
the agent's next call (carrying the same `X-Session-Id` it now gets
back in our response header) will resolve to the same session.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

# Conservative: matches Polar's SESSION_ID_PATTERN.
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
SESSION_ID_MAX_LEN = 128

# Project IDs get the same pattern; they're user-supplied so be strict.
PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
PROJECT_ID_MAX_LEN = 64

# Header names we recognize, in priority order.
SESSION_HEADERS = (
    "x-session-id",
    "x_session_id",
    "proxy-x-session-id",
    "proxy_x_session_id",
)


def generate_session_id() -> str:
    """Return a fresh session ID (UUID4 hex, 32 chars)."""
    return uuid.uuid4().hex


def is_valid_session_id(value: str) -> bool:
    return bool(SESSION_ID_PATTERN.fullmatch(value))


def is_valid_project_id(value: str) -> bool:
    return bool(PROJECT_ID_PATTERN.fullmatch(value))


def resolve_session_id(
    headers: dict[str, str],
    body: dict | None,
    query: dict[str, str] | None = None,
) -> str:
    """Pick a session_id from the inbound request.

    Headers are passed in lower-cased keys. Body is the JSON-decoded
    request body (or None). Query is the parsed query-string mapping.
    Returns a session ID, generating a UUID if nothing matched.
    """
    if query:
        sid = query.get("session_id") or query.get("key")
        if sid and is_valid_session_id(sid):
            return sid

    for h in SESSION_HEADERS:
        v = headers.get(h)
        if v and is_valid_session_id(v):
            return v

    if body:
        sid = body.get("_proxy_session_id")
        if isinstance(sid, str) and is_valid_session_id(sid):
            return sid

    return generate_session_id()


def build_session_dir(log_dir: Path, project_id: str, session_id: str) -> Path:
    """Return the per-session directory path. Does not create it."""
    if not is_valid_project_id(project_id):
        raise ValueError(f"invalid project_id: {project_id!r}")
    if not is_valid_session_id(session_id):
        raise ValueError(f"invalid session_id: {session_id!r}")
    return log_dir / project_id / session_id


def completions_path(session_dir: Path) -> Path:
    return session_dir / "completions.jsonl"


def meta_path(session_dir: Path) -> Path:
    return session_dir / "meta.json"
