"""End-to-end tests for the proxy: OpenAI-style upstream."""

from __future__ import annotations

import json



async def test_openai_non_streaming_round_trip(http_client, gateway_env) -> None:
    """A non-streaming call: response returns to agent, record lands in JSONL."""
    resp = await http_client.post(
        "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
        headers={"X-Session-Id": "fixed-session-1"},
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "Hello from mock!"
    assert resp.headers.get("x-polar-session-id") == "fixed-session-1"

    # Upstream got the REWRITTEN model.
    assert len(gateway_env["calls"]["openai"]) == 1
    sent = gateway_env["calls"]["openai"][0]
    assert sent["model"] == "gpt-4o-mock"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]

    # Trajectory was written.
    session_dir = gateway_env["log_dir"] / "acme" / "fixed-session-1"
    line = (session_dir / "completions.jsonl").read_text().strip()
    rec = json.loads(line)
    assert rec["sequence"] == 0
    assert rec["model_id"] == "gpt-4o"
    assert rec["upstream_model"] == "gpt-4o-mock"
    assert rec["is_streaming"] is False
    assert rec["token_usage"]["total_tokens"] == 18
    assert rec["response_body"]["choices"][0]["message"]["content"] == "Hello from mock!"


async def test_openai_streaming_passthrough(http_client, gateway_env) -> None:
    """Streaming: chunks reach agent, then a record with response_raw is written."""
    req_body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "stream me"}],
        "stream": True,
    }
    async with http_client.stream(
        "POST",
        "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
        headers={"X-Session-Id": "stream-session"},
        json=req_body,
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        chunks = []
        async for chunk in resp.aiter_bytes():
            chunks.append(chunk)
        body = b"".join(chunks).decode("utf-8")
    # 3 chunk lines + [DONE] in the default mock generator
    assert body.count("data: ") == 4
    assert "Hello " in body
    assert "world!" in body
    assert body.strip().endswith("data: [DONE]")

    # Record was written with response_raw and chunk_count.
    session_dir = gateway_env["log_dir"] / "acme" / "stream-session"
    rec = json.loads((session_dir / "completions.jsonl").read_text().strip())
    assert rec["is_streaming"] is True
    # chunk_count counts every chunk received from upstream, including
    # the [DONE] sentinel → 3 data chunks + 1 [DONE] = 4.
    assert rec["chunk_count"] == 4
    assert rec["response_raw"].count("data: ") == 4
    assert rec["response_body"] is None
    # No usage in our default mock chunks → token_usage is None.
    assert rec["token_usage"] is None


async def test_session_id_returned_in_header(http_client) -> None:
    """First call (no session id supplied) gets a fresh UUID in the response."""
    resp = await http_client.post(
        "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    sid = resp.headers["x-polar-session-id"]
    assert len(sid) == 32  # uuid4 hex
    assert sid.isalnum()


async def test_session_id_continuity_across_calls(http_client, gateway_env) -> None:
    """Two calls with the same X-Session-Id land in the same session dir."""
    sid = "continuity-session"
    for _ in range(2):
        resp = await http_client.post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": sid},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
    session_dir = gateway_env["log_dir"] / "acme" / sid
    lines = (session_dir / "completions.jsonl").read_text().splitlines()
    assert len(lines) == 2
    meta = json.loads((session_dir / "meta.json").read_text())
    assert meta["completion_count"] == 2
    # Sequences 0 and 1.
    parsed = [json.loads(line) for line in lines]
    assert [p["sequence"] for p in parsed] == [0, 1]


async def test_missing_project_id_rejected(http_client) -> None:
    resp = await http_client.post(
        "/v1/chat/completions?model_id=gpt-4o",
        json={"model": "gpt-4o", "messages": []},
    )
    assert resp.status_code == 400
    assert "project_id" in resp.json()["error"]


async def test_missing_model_id_rejected(http_client) -> None:
    resp = await http_client.post(
        "/v1/chat/completions?project_id=acme",
        json={"model": "gpt-4o", "messages": []},
    )
    assert resp.status_code == 400
    assert "model_id" in resp.json()["error"]


async def test_unknown_model_id_rejected(http_client) -> None:
    resp = await http_client.post(
        "/v1/chat/completions?project_id=acme&model_id=not-a-real-model",
        json={"model": "not-a-real-model", "messages": []},
    )
    assert resp.status_code == 400
    assert "unknown model_id" in resp.json()["error"]


async def test_invalid_project_id_rejected(http_client) -> None:
    resp = await http_client.post(
        "/v1/chat/completions?project_id=has%20space&model_id=gpt-4o",
        json={"model": "gpt-4o", "messages": []},
    )
    assert resp.status_code == 400


async def test_model_rewrite_to_passthrough_when_not_configured(http_client, gateway_env) -> None:
    """gpt-4o-passthrough has no upstream_model → agent's model is sent as-is."""
    resp = await http_client.post(
        "/v1/chat/completions?project_id=acme&model_id=gpt-4o-passthrough",
        headers={"X-Session-Id": "passthrough-1"},
        json={"model": "gpt-4o-passthrough", "messages": []},
    )
    assert resp.status_code == 200
    sent = gateway_env["calls"]["openai"][0]
    assert sent["model"] == "gpt-4o-passthrough"
