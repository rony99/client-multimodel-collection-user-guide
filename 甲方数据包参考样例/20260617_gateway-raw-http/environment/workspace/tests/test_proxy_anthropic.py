"""End-to-end tests for the proxy: Anthropic-style upstream."""

from __future__ import annotations

import json



async def test_anthropic_non_streaming_round_trip(http_client, gateway_env) -> None:
    resp = await http_client.post(
        "/v1/messages?project_id=acme&model_id=claude-3-5-sonnet",
        headers={"X-Session-Id": "anth-1"},
        json={
            "model": "claude-3-5-sonnet",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"][0]["text"] == "Hello from mock!"
    assert body["stop_reason"] == "end_turn"

    # Upstream got the rewritten model name.
    assert len(gateway_env["calls"]["anthropic"]) == 1
    sent = gateway_env["calls"]["anthropic"][0]
    assert sent["model"] == "claude-3-5-sonnet-mock"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]

    # Trajectory: token usage mapped from {input, output} to {prompt, completion}.
    rec = json.loads(
        (gateway_env["log_dir"] / "acme" / "anth-1" / "completions.jsonl").read_text().strip()
    )
    assert rec["is_streaming"] is False
    assert rec["token_usage"]["prompt_tokens"] == 11
    assert rec["token_usage"]["completion_tokens"] == 7
    assert rec["token_usage"]["total_tokens"] == 18


async def test_anthropic_streaming_passthrough(http_client, gateway_env) -> None:
    body = {
        "model": "claude-3-5-sonnet",
        "max_tokens": 256,
        "messages": [{"role": "user", "content": "stream me"}],
        "stream": True,
    }
    async with http_client.stream(
        "POST",
        "/v1/messages?project_id=acme&model_id=claude-3-5-sonnet",
        headers={"X-Session-Id": "anth-stream"},
        json=body,
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        chunks = []
        async for chunk in resp.aiter_bytes():
            chunks.append(chunk)
        full = b"".join(chunks).decode("utf-8")
    # The default mock emits 6 events for anthropic streaming.
    assert full.count("event:") >= 5
    assert "Hello world!" in full

    rec = json.loads(
        (
            gateway_env["log_dir"] / "acme" / "anth-stream" / "completions.jsonl"
        ).read_text().strip()
    )
    assert rec["is_streaming"] is True
    assert rec["chunk_count"] == 6
    assert rec["response_raw"] is not None
    # The mock message_delta carries usage; v1 best-effort scan picks it up.
    # (If upstream stopped emitting usage in the stream, token_usage may be None.)
    if rec["token_usage"] is not None:
        assert rec["token_usage"]["completion_tokens"] == 7
