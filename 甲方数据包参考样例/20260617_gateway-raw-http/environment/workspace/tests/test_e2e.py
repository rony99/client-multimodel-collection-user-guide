"""End-to-end: a multi-turn session across both providers, verifying
the full session layout that v3-v6 will build on."""

from __future__ import annotations

import json
from pathlib import Path


async def test_multi_turn_session_layout(http_client, gateway_env) -> None:
    """Simulate a 3-call agent session: 2 OpenAI turns + 1 Anthropic turn."""
    sid = "multi-turn-1"
    project = "demo"

    # Turn 1: OpenAI
    r1 = await http_client.post(
        f"/v1/chat/completions?project_id={project}&model_id=gpt-4o",
        headers={"X-Session-Id": sid},
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "explain RL"}],
        },
    )
    assert r1.status_code == 200
    assert r1.headers["x-polar-session-id"] == sid

    # Turn 2: OpenAI streaming
    async with http_client.stream(
        "POST",
        f"/v1/chat/completions?project_id={project}&model_id=gpt-4o",
        headers={"X-Session-Id": sid},
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "explain RL"},
                {"role": "assistant", "content": "..."},
                {"role": "user", "content": "go deeper"},
            ],
            "stream": True,
        },
    ) as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_bytes():
            pass

    # Turn 3: Anthropic
    r3 = await http_client.post(
        f"/v1/messages?project_id={project}&model_id=claude-3-5-sonnet",
        headers={"X-Session-Id": sid},
        json={
            "model": "claude-3-5-sonnet",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": "thanks"}],
        },
    )
    assert r3.status_code == 200

    # --- Verify on-disk layout ---
    session_dir: Path = gateway_env["log_dir"] / project / sid
    assert session_dir.is_dir()

    # 3 lines in completions.jsonl
    lines = (session_dir / "completions.jsonl").read_text().splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]

    # Sequence numbers
    assert [p["sequence"] for p in parsed] == [0, 1, 2]

    # Turn 1 = non-streaming OpenAI
    assert parsed[0]["is_streaming"] is False
    assert parsed[0]["model_id"] == "gpt-4o"
    assert parsed[0]["upstream"] == "openai-mock"
    assert parsed[0]["response_body"] is not None
    assert parsed[0]["token_usage"]["total_tokens"] == 18

    # Turn 2 = streaming OpenAI
    assert parsed[1]["is_streaming"] is True
    assert parsed[1]["model_id"] == "gpt-4o"
    assert parsed[1]["response_body"] is None
    assert parsed[1]["response_raw"] is not None

    # Turn 3 = non-streaming Anthropic
    assert parsed[2]["is_streaming"] is False
    assert parsed[2]["model_id"] == "claude-3-5-sonnet"
    assert parsed[2]["upstream"] == "anthropic-mock"
    assert parsed[2]["token_usage"]["prompt_tokens"] == 11
    assert parsed[2]["token_usage"]["completion_tokens"] == 7

    # --- Verify meta.json aggregates ---
    meta = json.loads((session_dir / "meta.json").read_text())
    assert meta["completion_count"] == 3
    assert meta["project_id"] == project
    assert meta["session_id"] == sid
    assert sorted(meta["models_used"]) == ["claude-3-5-sonnet", "gpt-4o"]
    assert sorted(meta["upstreams_used"]) == ["anthropic-mock", "openai-mock"]
    # Token totals: turn 1 = 18, turn 2 = 0 (mock chunks had no usage), turn 3 = 18.
    assert meta["total_tokens"] == 18 + 0 + 18


async def test_session_isolation_across_projects(http_client, gateway_env) -> None:
    """Two projects with the same X-Session-Id do not collide."""
    sid = "shared-name"

    for project in ("alpha", "beta"):
        r = await http_client.post(
            f"/v1/chat/completions?project_id={project}&model_id=gpt-4o",
            headers={"X-Session-Id": sid},
            json={"model": "gpt-4o", "messages": []},
        )
        assert r.status_code == 200

    alpha_dir = gateway_env["log_dir"] / "alpha" / sid
    beta_dir = gateway_env["log_dir"] / "beta" / sid
    assert alpha_dir.is_dir() and beta_dir.is_dir()
    assert (alpha_dir / "completions.jsonl").is_file()
    assert (beta_dir / "completions.jsonl").is_file()
    # Each project's session has its own line.
    assert len((alpha_dir / "completions.jsonl").read_text().splitlines()) == 1
    assert len((beta_dir / "completions.jsonl").read_text().splitlines()) == 1
