"""Tests for gateway.writer: TrajectoryWriter append + meta merge."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path


from gateway.models import CompletionRecord, TokenUsage
from gateway.writer import TrajectoryWriter, _read_meta, _write_meta_atomic
from gateway.session import meta_path


def _record(
    *,
    project_id: str = "acme",
    session_id: str = "s1",
    sequence: int = 0,
    model_id: str = "gpt-4o",
    upstream: str = "openai-mock",
    upstream_model: str = "gpt-4o-mock",
    response_body: dict | None = None,
    is_streaming: bool = False,
    response_raw: str | None = None,
    chunk_count: int | None = None,
    timing_ms: float = 100.0,
    token_usage: TokenUsage | None = None,
    error: str | None = None,
) -> CompletionRecord:
    return CompletionRecord(
        completion_id=f"c{sequence:03d}",
        sequence=sequence,
        timestamp="2026-06-17T01:23:45.000Z",
        project_id=project_id,
        session_id=session_id,
        model_id=model_id,
        upstream=upstream,
        upstream_model=upstream_model,
        request_body={"model": model_id, "messages": []},
        response_body=response_body,
        response_raw=response_raw,
        is_streaming=is_streaming,
        chunk_count=chunk_count,
        response_status=200 if error is None else None,
        timing_ms=timing_ms,
        token_usage=token_usage,
        error=error,
    )


async def test_append_creates_session_dir(tmp_path: Path) -> None:
    w = TrajectoryWriter(tmp_path)
    rec = _record(sequence=0)
    await w.append(rec)
    assert (tmp_path / "acme" / "s1" / "completions.jsonl").is_file()
    assert (tmp_path / "acme" / "s1" / "meta.json").is_file()


async def test_completions_jsonl_has_one_line_per_record(tmp_path: Path) -> None:
    w = TrajectoryWriter(tmp_path)
    for i in range(5):
        await w.append(_record(sequence=i, token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)))
    lines = (tmp_path / "acme" / "s1" / "completions.jsonl").read_text().splitlines()
    assert len(lines) == 5
    parsed = [json.loads(line) for line in lines]
    assert [p["sequence"] for p in parsed] == [0, 1, 2, 3, 4]
    assert all(p["token_usage"]["total_tokens"] == 15 for p in parsed)


async def test_meta_aggregates_token_counts(tmp_path: Path) -> None:
    w = TrajectoryWriter(tmp_path)
    await w.append(
        _record(
            sequence=0,
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
    )
    await w.append(
        _record(
            sequence=1,
            model_id="claude-3-5-sonnet",
            upstream="anthropic-mock",
            token_usage=TokenUsage(prompt_tokens=20, completion_tokens=8, total_tokens=28),
        )
    )
    meta_path_ = meta_path(tmp_path / "acme" / "s1")
    meta = json.loads(meta_path_.read_text())
    assert meta["completion_count"] == 2
    assert meta["total_prompt_tokens"] == 30
    assert meta["total_completion_tokens"] == 13
    assert meta["total_tokens"] == 43
    assert sorted(meta["models_used"]) == ["claude-3-5-sonnet", "gpt-4o"]
    assert sorted(meta["upstreams_used"]) == ["anthropic-mock", "openai-mock"]


async def test_meta_tracks_last_error(tmp_path: Path) -> None:
    w = TrajectoryWriter(tmp_path)
    await w.append(_record(sequence=0))
    await w.append(_record(sequence=1, error="ConnectionError: refused"))
    meta = json.loads(meta_path(tmp_path / "acme" / "s1").read_text())
    assert meta["last_error"] == "ConnectionError: refused"


async def test_next_sequence_starts_at_zero_and_increments(tmp_path: Path) -> None:
    w = TrajectoryWriter(tmp_path)
    assert await w.next_sequence("acme", "s1") == 0
    await w.append(_record(sequence=0))
    assert await w.next_sequence("acme", "s1") == 1
    await w.append(_record(sequence=1))
    assert await w.next_sequence("acme", "s1") == 2


async def test_concurrent_appends_for_different_sessions(tmp_path: Path) -> None:
    w = TrajectoryWriter(tmp_path)

    async def fill_session(sid: str) -> None:
        for i in range(10):
            await w.append(_record(session_id=sid, sequence=i))

    await asyncio.gather(fill_session("s-a"), fill_session("s-b"))
    for sid in ("s-a", "s-b"):
        lines = (tmp_path / "acme" / sid / "completions.jsonl").read_text().splitlines()
        assert len(lines) == 10


async def test_streaming_record_keeps_response_raw(tmp_path: Path) -> None:
    w = TrajectoryWriter(tmp_path)
    rec = _record(
        sequence=0,
        is_streaming=True,
        response_body=None,
        response_raw="data: {}\n\ndata: [DONE]\n\n",
        chunk_count=2,
    )
    await w.append(rec)
    line = (tmp_path / "acme" / "s1" / "completions.jsonl").read_text().strip()
    parsed = json.loads(line)
    assert parsed["is_streaming"] is True
    assert parsed["response_raw"].startswith("data:")
    assert parsed["chunk_count"] == 2


async def test_truncates_oversized_streaming_body(tmp_path: Path) -> None:
    w = TrajectoryWriter(tmp_path)
    big = "x" * (2 * 1024 * 1024)  # 2 MB
    rec = _record(sequence=0, is_streaming=True, response_raw=big, chunk_count=1)
    await w.append(rec, max_raw_bytes=1024)  # tiny cap
    parsed = json.loads((tmp_path / "acme" / "s1" / "completions.jsonl").read_text().strip())
    assert "[truncated]" in parsed["response_raw"]
    # The raw should not be 2 MB anymore.
    assert len(parsed["response_raw"].encode("utf-8")) < 2000


async def test_write_meta_atomic_replaces_file(tmp_path: Path) -> None:
    p = tmp_path / "meta.json"
    from gateway.models import TrajectoryMeta

    m1 = TrajectoryMeta(
        session_id="s1",
        project_id="acme",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        completion_count=0,
    )
    _write_meta_atomic(p, m1)
    assert p.is_file()
    m2 = m1.model_copy(update={"completion_count": 7})
    _write_meta_atomic(p, m2)
    reloaded = _read_meta(p)
    assert reloaded is not None
    assert reloaded.completion_count == 7
