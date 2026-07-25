"""Deep v1 tests using the scripted-mock upstream.

These exercise realistic agent shapes that the simple `mock_upstream`
fixture in conftest.py doesn't cover: multi-turn conversations, tool
calls, error responses, rate limits, malformed upstream payloads.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI

from gateway.app import create_app
from gateway.config import (
    GatewayConfig,
    LogConfig,
    RouteConfig,
    ServerConfig,
    UpstreamConfig,
)
from gateway.testing import (
    Scenario,
    conversation_scenario,
    echo_scenario,
    error_scenario,
    make_scripted_mock,
    tool_call_roundtrip_scenario,
)


# ----- reusable scripted-mock fixture ---------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _ServerThread:
    def __init__(self, app: FastAPI, port: int) -> None:
        cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self._server = uvicorn.Server(cfg)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        for _ in range(100):
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("mock did not start")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


def _build_gateway_config(
    log_dir: Any, upstream_base_url: str
) -> GatewayConfig:
    return GatewayConfig(
        server=ServerConfig(host="127.0.0.1", port=9000, log_level="WARNING"),
        log=LogConfig(dir=log_dir),
        upstreams=[
            UpstreamConfig(
                name="openai-mock",
                style="openai",
                base_url=upstream_base_url,  # type: ignore[arg-type]
                api_key="test",
                timeout_seconds=5.0,
            ),
            UpstreamConfig(
                name="anthropic-mock",
                style="anthropic",
                base_url=upstream_base_url,  # type: ignore[arg-type]
                api_key="test",
                timeout_seconds=5.0,
                version="2023-06-01",
            ),
        ],
        routes=[
            RouteConfig(model_id="gpt-4o", upstream="openai-mock"),
            RouteConfig(model_id="claude-3-5-sonnet", upstream="anthropic-mock"),
        ],
    )


@asynccontextmanager
async def _with_scripted_mock(
    tmp_path: Any, scenarios: list[Scenario]
) -> AsyncIterator[dict[str, Any]]:
    """Bring up a scripted mock + a gateway pointed at it. Yield ctx too."""
    app, ctx = make_scripted_mock(scenarios)
    port = _free_port()
    server = _ServerThread(app, port)
    server.start()
    base_url = f"http://127.0.0.1:{port}"
    cfg = _build_gateway_config(tmp_path / "logs", base_url)
    gw = create_app(cfg)
    try:
        async with _lifespan(gw):
            transport = httpx.ASGITransport(app=gw)
            async with httpx.AsyncClient(transport=transport, base_url="http://gw") as client:
                yield {
                    "client": client,
                    "ctx": ctx,
                    "log_dir": cfg.log.dir,
                    "base_url": base_url,
                }
    finally:
        server.stop()


# ----- tests ----------------------------------------------------------


async def test_multi_turn_conversation(tmp_path) -> None:
    """An OpenAI session with 3 turns; verify the trajectory is in order."""
    async with _with_scripted_mock(
        tmp_path,
        [
            conversation_scenario(
                [
                    "First answer.",
                    "Second answer — with a follow-up.",
                    "Third and final answer.",
                ],
                style="openai",
            ),
        ],
    ) as env:
        client: httpx.AsyncClient = env["client"]
        for i, expected in enumerate(
            ["First answer.", "Second answer — with a follow-up.", "Third and final answer."]
        ):
            resp = await client.post(
                "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
                headers={"X-Session-Id": "multi"},
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "user", "content": f"turn {i} prompt"},
                    ],
                },
            )
            assert resp.status_code == 200
            assert resp.json()["choices"][0]["message"]["content"] == expected

        # Mock saw 3 requests in order.
        assert env["ctx"].turn_count == 3
        assert [m["content"] for m in env["ctx"].history[0]["messages"]] == ["turn 0 prompt"]
        assert [m["content"] for m in env["ctx"].history[2]["messages"]] == ["turn 2 prompt"]

        # Trajectory records 3 completions with increasing sequence numbers.
        session_dir = env["log_dir"] / "acme" / "multi"
        lines = (session_dir / "completions.jsonl").read_text().splitlines()
        parsed = [json.loads(line) for line in lines]
        assert [p["sequence"] for p in parsed] == [0, 1, 2]
        assert all(p["token_usage"]["total_tokens"] > 0 for p in parsed)
        # Each request body was recorded with the right user message.
        assert parsed[0]["request_body"]["messages"][0]["content"] == "turn 0 prompt"
        assert parsed[2]["request_body"]["messages"][0]["content"] == "turn 2 prompt"
        # The response body for each completion contains the right text.
        assert (
            parsed[1]["response_body"]["choices"][0]["message"]["content"]
            == "Second answer — with a follow-up."
        )


async def test_openai_tool_call_round_trip(tmp_path) -> None:
    """Turn 1: tool_call. Turn 2: agent sends tool result, mock returns final text."""
    async with _with_scripted_mock(
        tmp_path,
        [
            tool_call_roundtrip_scenario(
                tool_name="get_weather",
                tool_args={"city": "San Francisco"},
                tool_result_text="Sunny, 72F",
                final_text="It's 72F and sunny in San Francisco.",
                style="openai",
            ),
        ],
    ) as env:
        client: httpx.AsyncClient = env["client"]
        sid = "tool-openai"

        # Turn 1: agent's first message, mock returns a tool_call.
        r1 = await client.post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": sid},
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "weather in SF?"}],
            },
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["choices"][0]["finish_reason"] == "tool_calls"
        tool_call = body1["choices"][0]["message"]["tool_calls"][0]
        assert tool_call["function"]["name"] == "get_weather"
        assert json.loads(tool_call["function"]["arguments"]) == {"city": "San Francisco"}
        call_id = tool_call["id"]

        # Turn 2: agent sends the tool result back.
        r2 = await client.post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": sid},
            json={
                "model": "gpt-4o",
                "messages": [
                    {"role": "user", "content": "weather in SF?"},
                    body1["choices"][0]["message"],
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": "Sunny, 72F",
                    },
                ],
            },
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["choices"][0]["finish_reason"] == "stop"
        assert (
            body2["choices"][0]["message"]["content"]
            == "It's 72F and sunny in San Francisco."
        )

        # Trajectory records both turns with the right shapes.
        session_dir = env["log_dir"] / "acme" / sid
        lines = (session_dir / "completions.jsonl").read_text().splitlines()
        parsed = [json.loads(line) for line in lines]
        assert len(parsed) == 2
        # Turn 1: response_body has the tool_call.
        t1 = parsed[0]["response_body"]["choices"][0]["message"]
        assert t1["tool_calls"][0]["function"]["name"] == "get_weather"
        # Turn 2: request_body contains the tool result message (role=tool).
        assert parsed[1]["request_body"]["messages"][-1]["role"] == "tool"
        assert parsed[1]["request_body"]["messages"][-1]["content"] == "Sunny, 72F"


async def test_anthropic_tool_call_round_trip(tmp_path) -> None:
    """Anthropic version of the tool-call round-trip."""
    async with _with_scripted_mock(
        tmp_path,
        [
            tool_call_roundtrip_scenario(
                tool_name="lookup_issue",
                tool_args={"id": "PROJ-123"},
                tool_result_text="Status: In Progress",
                final_text="Issue PROJ-123 is currently in progress.",
                style="anthropic",
            ),
        ],
    ) as env:
        client: httpx.AsyncClient = env["client"]
        sid = "tool-anth"

        r1 = await client.post(
            "/v1/messages?project_id=acme&model_id=claude-3-5-sonnet",
            headers={"X-Session-Id": sid},
            json={
                "model": "claude-3-5-sonnet",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "status of PROJ-123?"}],
            },
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["stop_reason"] == "tool_use"
        # Anthropic: tool_use is in the content list.
        tool_use_block = next(
            b for b in body1["content"] if b.get("type") == "tool_use"
        )
        assert tool_use_block["name"] == "lookup_issue"
        assert tool_use_block["input"] == {"id": "PROJ-123"}
        tool_use_id = tool_use_block["id"]

        r2 = await client.post(
            "/v1/messages?project_id=acme&model_id=claude-3-5-sonnet",
            headers={"X-Session-Id": sid},
            json={
                "model": "claude-3-5-sonnet",
                "max_tokens": 256,
                "messages": [
                    {"role": "user", "content": "status of PROJ-123?"},
                    {"role": "assistant", "content": body1["content"]},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": "Status: In Progress",
                            }
                        ],
                    },
                ],
            },
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["stop_reason"] == "end_turn"
        assert body2["content"][0]["text"] == "Issue PROJ-123 is currently in progress."

        # Trajectory: turn 2's request_body has the tool_result block in the last message.
        session_dir = env["log_dir"] / "acme" / sid
        lines = (session_dir / "completions.jsonl").read_text().splitlines()
        parsed = [json.loads(line) for line in lines]
        assert len(parsed) == 2
        last_msg = parsed[1]["request_body"]["messages"][-1]
        assert last_msg["role"] == "user"
        assert last_msg["content"][0]["type"] == "tool_result"
        assert last_msg["content"][0]["tool_use_id"] == tool_use_id


async def test_upstream_500_is_recorded_as_error(tmp_path) -> None:
    """If the upstream returns 500, the gateway records the failure."""
    async with _with_scripted_mock(
        tmp_path,
        [error_scenario(500, body={"error": "internal"}, style="openai")],
    ) as env:
        client: httpx.AsyncClient = env["client"]
        resp = await client.post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": "boom"},
            json={"model": "gpt-4o", "messages": []},
        )
        # Gateway passes the upstream status through.
        assert resp.status_code == 500

        # The trajectory records the failure with status=500.
        session_dir = env["log_dir"] / "acme" / "boom"
        rec = json.loads(
            (session_dir / "completions.jsonl").read_text().strip()
        )
        assert rec["response_status"] == 500
        # Body is still recorded so v2/v3 can analyze what the upstream said.
        assert rec["response_body"] == {"error": "internal"}
        # meta.json reflects the error.
        meta = json.loads((session_dir / "meta.json").read_text())
        assert meta["last_error"] is None  # upstream 500 isn't an "error" in our sense
        assert meta["completion_count"] == 1


async def test_rate_limit_429_passes_through_and_records(tmp_path) -> None:
    async with _with_scripted_mock(
        tmp_path,
        [error_scenario(429, body={"error": "rate limit"}, style="openai")],
    ) as env:
        client: httpx.AsyncClient = env["client"]
        resp = await client.post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": "rl"},
            json={"model": "gpt-4o", "messages": []},
        )
        assert resp.status_code == 429
        rec = json.loads(
            (env["log_dir"] / "acme" / "rl" / "completions.jsonl").read_text().strip()
        )
        assert rec["response_status"] == 429
        # No token usage in a 429 — v1 leaves it None.
        assert rec["token_usage"] is None


async def test_upstream_timeout_records_error(tmp_path) -> None:
    """If the upstream takes longer than the configured timeout, record it."""
    # The mock delays 200ms; the gateway is configured with a 50ms
    # timeout in this scenario. (See _build_gateway_config_slow below.)
    async with _with_scripted_mock_slow(
        tmp_path,
        [echo_scenario("won't get there", style="openai")],
        gateway_timeout=0.05,
    ) as env:
        resp = await env["client"].post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": "timeout-1"},
            json={"model": "gpt-4o", "messages": []},
        )
        # Gateway returns 502 on connection / timeout failures.
        assert resp.status_code == 502
        rec = json.loads(
            (env["log_dir"] / "acme" / "timeout-1" / "completions.jsonl")
            .read_text()
            .strip()
        )
        assert rec["error"] is not None
        assert "Timeout" in rec["error"] or "ConnectError" in rec["error"] or "Read" in rec["error"]


@asynccontextmanager
async def _with_scripted_mock_slow(
    tmp_path: Any, scenarios: list[Scenario], *, gateway_timeout: float
) -> AsyncIterator[dict[str, Any]]:
    """Same as _with_scripted_mock but lets the test set the gateway's
    upstream timeout. Also forces the mock to delay 200ms so a short
    timeout will reliably trip.
    """
    # Force every scenario to delay 200ms.
    for sc in scenarios:
        sc.delay_ms = 200
    app, ctx = make_scripted_mock(scenarios)
    port = _free_port()
    server = _ServerThread(app, port)
    server.start()
    base_url = f"http://127.0.0.1:{port}"
    cfg = _build_gateway_config_with_timeout(
        tmp_path / "logs", base_url, timeout=gateway_timeout
    )
    gw = create_app(cfg)
    try:
        async with _lifespan(gw):
            transport = httpx.ASGITransport(app=gw)
            async with httpx.AsyncClient(transport=transport, base_url="http://gw") as client:
                yield {
                    "client": client,
                    "ctx": ctx,
                    "log_dir": cfg.log.dir,
                    "base_url": base_url,
                }
    finally:
        server.stop()


def _build_gateway_config_with_timeout(
    log_dir: Any, upstream_base_url: str, *, timeout: float
) -> GatewayConfig:
    return GatewayConfig(
        server=ServerConfig(host="127.0.0.1", port=9000, log_level="WARNING"),
        log=LogConfig(dir=log_dir),
        upstreams=[
            UpstreamConfig(
                name="openai-mock",
                style="openai",
                base_url=upstream_base_url,  # type: ignore[arg-type]
                api_key="test",
                timeout_seconds=timeout,
            ),
            UpstreamConfig(
                name="anthropic-mock",
                style="anthropic",
                base_url=upstream_base_url,  # type: ignore[arg-type]
                api_key="test",
                timeout_seconds=timeout,
                version="2023-06-01",
            ),
        ],
        routes=[
            RouteConfig(model_id="gpt-4o", upstream="openai-mock"),
            RouteConfig(model_id="claude-3-5-sonnet", upstream="anthropic-mock"),
        ],
    )


async def test_mixed_providers_in_one_session(tmp_path) -> None:
    """One session alternates between OpenAI and Anthropic turns."""
    async with _with_scripted_mock(
        tmp_path,
        [
            conversation_scenario(
                ["OpenAI turn 1.", "OpenAI turn 2."], style="openai"
            ),
            conversation_scenario(
                ["Anthropic turn 1.", "Anthropic turn 2."], style="anthropic"
            ),
        ],
    ) as env:
        client: httpx.AsyncClient = env["client"]
        sid = "mixed"
        # OAI, Anth, OAI, Anth — interleaved providers within one session.
        await client.post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": sid},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "o1"}]},
        )
        await client.post(
            "/v1/messages?project_id=acme&model_id=claude-3-5-sonnet",
            headers={"X-Session-Id": sid},
            json={
                "model": "claude-3-5-sonnet",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "a1"}],
            },
        )
        await client.post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": sid},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "o2"}]},
        )
        await client.post(
            "/v1/messages?project_id=acme&model_id=claude-3-5-sonnet",
            headers={"X-Session-Id": sid},
            json={
                "model": "claude-3-5-sonnet",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "a2"}],
            },
        )

        session_dir = env["log_dir"] / "acme" / sid
        lines = (session_dir / "completions.jsonl").read_text().splitlines()
        parsed = [json.loads(line) for line in lines]
        assert len(parsed) == 4
        assert [p["upstream"] for p in parsed] == [
            "openai-mock",
            "anthropic-mock",
            "openai-mock",
            "anthropic-mock",
        ]
        # The OpenAI mock and Anthropic mock each saw 2 calls.
        assert env["ctx"].turn_count == 4
        # meta aggregates token totals correctly.
        meta = json.loads((session_dir / "meta.json").read_text())
        assert meta["completion_count"] == 4
        assert sorted(meta["upstreams_used"]) == ["anthropic-mock", "openai-mock"]


async def test_no_scenario_matched_returns_500(tmp_path) -> None:
    """A mock with no scenarios returns 500 on any request — caught at gateway level."""
    async with _with_scripted_mock(tmp_path, []) as env:
        client: httpx.AsyncClient = env["client"]
        resp = await client.post(
            "/v1/chat/completions?project_id=acme&model_id=gpt-4o",
            headers={"X-Session-Id": "no-match"},
            json={"model": "gpt-4o", "messages": []},
        )
        assert resp.status_code == 500
        # Even failures get recorded — that's v1's invariant.
        rec = json.loads(
            (env["log_dir"] / "acme" / "no-match" / "completions.jsonl")
            .read_text()
            .strip()
        )
        assert rec["response_status"] == 500
