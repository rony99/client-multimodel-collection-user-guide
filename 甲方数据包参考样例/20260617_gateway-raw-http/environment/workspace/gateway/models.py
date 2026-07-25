"""Pydantic data models for trajectory collection.

A trajectory = one agent session = an ordered sequence of LLM completions.
We deliberately store *messages* (not token IDs) in v1 — tokenization
happens later in the v3 export step. This keeps the gateway independent
of any specific tokenizer and matches Polar's separation of "capture"
and "build training-ready tokens".

Storage layout:
    <log_dir>/<project_id>/<session_id>/completions.jsonl   # append-only
    <log_dir>/<project_id>/<session_id>/meta.json           # session meta
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TokenUsage(BaseModel):
    """Token counts extracted from the upstream `usage` field.

    OpenAI shape: {"prompt_tokens", "completion_tokens", "total_tokens"}.
    Anthropic shape: {"input_tokens", "output_tokens"}.
    Both shapes are normalized to prompt/completion so downstream code
    can read them uniformly.
    """

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class CompletionRecord(BaseModel):
    """One LLM API call inside a session/trajectory.

    For non-streaming responses: `response_body` holds the parsed JSON.
    For streaming (SSE) responses: `response_raw` holds the concatenated
    SSE text and `response_body` is None — v3 export will tokenize the
    raw text. A hard cap on buffered size is enforced by the proxy
    (see writer / proxy module).
    """

    model_config = ConfigDict(extra="forbid")

    completion_id: str
    sequence: int  # monotonic per session, starts at 0
    timestamp: str  # ISO 8601, UTC
    project_id: str
    session_id: str
    model_id: str
    upstream: str
    upstream_model: str | None = None

    # The verbatim request body the agent sent (after model rewrite if any).
    # For OpenAI Chat: {"model", "messages", "tools", "stream", ...}
    # For Anthropic:  {"model", "messages", "system", "tools", "stream", ...}
    request_body: dict[str, Any] = Field(default_factory=dict)

    # Non-streaming only: the parsed JSON response from upstream.
    response_body: dict[str, Any] | None = None
    # Streaming only: the concatenated SSE text (truncated to
    # `max_stream_bytes` in the proxy).
    response_raw: str | None = None
    is_streaming: bool = False
    chunk_count: int | None = None

    # Upstream HTTP status the client ultimately received.
    response_status: int | None = None
    error: str | None = None  # populated when the call failed

    timing_ms: float
    token_usage: TokenUsage | None = None


class TrajectoryMeta(BaseModel):
    """Session-level metadata, written to <session_id>/meta.json.

    Updated on every completion append. Holds summary fields so a
    dashboard (v3+) can list sessions without reading every line of
    completions.jsonl.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    project_id: str
    created_at: str
    updated_at: str
    completion_count: int = 0
    status: Literal["active", "completed"] = "active"
    # Aggregated fields
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    models_used: list[str] = Field(default_factory=list)
    upstreams_used: list[str] = Field(default_factory=list)
    last_error: str | None = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def touch(self) -> None:
        """Update updated_at + now. Call before write."""
        self.updated_at = self.now_iso()
