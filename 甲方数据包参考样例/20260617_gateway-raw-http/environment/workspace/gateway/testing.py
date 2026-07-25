"""Reusable mock upstream for tests and examples.

A `make_scripted_mock(scenarios)` builder turns a list of `Scenario`
declarations into a FastAPI app that emulates OpenAI Chat Completions
and Anthropic Messages. Each scenario declares:

  - a `match(body, ctx) -> bool` predicate over the incoming request
  - a `respond(body, ctx) -> dict` that produces the JSON response
  - optional `stream_chunks` for SSE-shaped streaming
  - optional `status` (4xx/5xx) and `delay_ms` (artificial latency)

Scenarios are evaluated in order; the first match wins. If none match,
the mock returns 500 with a "no scenario matched" error so missing
coverage is loud, not silent.

The mock is stateful: it carries a `MockContext` that scenarios can
read/write — that is how multi-turn and tool-call flows are simulated.

Why a public module: both `tests/conftest.py` and downstream users
writing their own v2+ tests need this. Keeping it out of conftest.py
makes it importable from anywhere.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request, Response


# ----- public data types -----------------------------------------------


@dataclass
class MockContext:
    """Mutable state visible to every scenario.

    `history` records every matched request the mock has processed (in order).
    `turn_count` is incremented AFTER a request is fully processed, so during
    a scenario's `respond` callback, `turn_count` is the 0-indexed number
    of the current turn (0 for the first call, 1 for the second, …).
    Scenarios can read prior turns to simulate stateful behavior
    (e.g. a tool-call round-trip where turn 2 sees the tool result from
    turn 1).
    """

    history: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0

    def last_user_message(self) -> str | None:
        """Return the most recent user message text, or None."""
        for req in reversed(self.history):
            for msg in reversed(req.get("messages", [])):
                if msg.get("role") == "user":
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                return block.get("text")
        return None


# A scenario's `match` gets the parsed request body and the context.
# A scenario's `respond` gets the same and must return a dict (JSON body).
# Both can be sync or async; we always await the result.
MatchFn = Callable[[dict[str, Any], MockContext], bool | Awaitable[bool]]
RespondFn = Callable[[dict[str, Any], MockContext], dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass
class Scenario:
    """One scripted response, gated by a predicate over the request."""

    name: str
    match: MatchFn
    respond: RespondFn
    # Where this scenario lives. The mock app dispatches to the right
    # route based on which upstream style the request targets.
    style: str = "openai"  # "openai" | "anthropic"
    # If set, the mock returns a streaming response with these chunks
    # instead of the static `respond` output.
    stream_chunks: list[dict[str, Any]] | None = None
    # Non-200 responses (e.g. 429, 500) — status code is returned as-is.
    status: int = 200
    # Artificial latency before responding. Useful for timeout tests.
    delay_ms: int = 0


# ----- the mock app builder --------------------------------------------


def make_scripted_mock(
    scenarios: list[Scenario],
    *,
    openai_route: str = "/v1/chat/completions",
    anthropic_route: str = "/v1/messages",
) -> tuple[FastAPI, MockContext]:
    """Build a FastAPI app that serves scripted OpenAI + Anthropic responses.

    Returns (app, ctx) where `ctx` is the live MockContext; tests inspect
    `ctx.history` to verify the mock received the right requests.
    """
    app = FastAPI(title="scripted-mock-upstream")
    ctx = MockContext()

    async def _maybe_await(value: Any) -> Any:
        if asyncio.iscoroutine(value):
            return await value
        return value

    async def _dispatch(request: Request, style: str, route_name: str) -> Response:
        try:
            body = await request.json()
        except Exception as exc:  # malformed JSON from the gateway
            return Response(
                content=json.dumps({"error": f"mock: bad JSON: {exc}"}),
                status_code=400,
                media_type="application/json",
            )

        for sc in scenarios:
            if sc.style != style:
                continue
            if not await _maybe_await(sc.match(body, ctx)):
                continue
            # Add the request to history. `ctx.turn_count` is the
            # 0-indexed turn number of the current request — i.e. it's
            # how many requests have been FULLY processed before this
            # one, so conversation_scenario can use it as `responses[i]`
            # without an off-by-one.
            ctx.history.append(body)
            if sc.delay_ms:
                await asyncio.sleep(sc.delay_ms / 1000)
            if sc.stream_chunks is not None and body.get("stream"):
                response = _streaming_response(sc.stream_chunks, style, sc.status)
                break
            payload = await _maybe_await(sc.respond(body, ctx))
            response = Response(
                content=json.dumps(payload),
                status_code=sc.status,
                media_type="application/json",
            )
            break
        else:
            return Response(
                content=json.dumps(
                    {
                        "error": "no scenario matched",
                        "received_keys": sorted(body.keys()),
                        "available": [s.name for s in scenarios if s.style == style],
                    }
                ),
                status_code=500,
                media_type="application/json",
            )

        # Bump the turn counter only after a successful match. Unmatched
        # requests don't pollute the count.
        ctx.turn_count += 1
        return response

    @app.post(openai_route)
    async def _openai(request: Request) -> Response:
        return await _dispatch(request, "openai", openai_route)

    @app.post(anthropic_route)
    async def _anthropic(request: Request) -> Response:
        return await _dispatch(request, "anthropic", anthropic_route)

    @app.get("/__mock/turn_count", include_in_schema=False)
    async def _turn_count() -> dict[str, int]:
        return {"turn_count": ctx.turn_count}

    return app, ctx


def _streaming_response(
    chunks: list[dict[str, Any]], style: str, status: int
) -> Response:
    """Wrap a chunk list as an SSE response in the right format."""
    from fastapi.responses import StreamingResponse

    async def gen() -> Any:
        for c in chunks:
            if style == "anthropic":
                yield f"event: {c.get('type', 'message')}\ndata: {json.dumps(c)}\n\n".encode()
            else:
                yield f"data: {json.dumps(c)}\n\n".encode()
        if style == "openai":
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        status_code=status,
        media_type="text/event-stream",
    )


# ----- scenario factories ---------------------------------------------
# These cover the most common shapes an agent test would want. Each
# returns a single Scenario; the caller composes them into a list.


def echo_scenario(
    text: str = "Hello from scripted mock!",
    style: str = "openai",
    usage: dict[str, int] | None = None,
) -> Scenario:
    """Always respond with the same text. Non-streaming only."""
    usage = usage or {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    model = "claude-3-5-sonnet-20241022" if style == "anthropic" else "gpt-4o"

    def _respond(body: dict[str, Any], _ctx: MockContext) -> dict[str, Any]:
        if style == "anthropic":
            return {
                "id": "msg-mock",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "model": model,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"]},
            }
        return {
            "id": "cmpl-mock",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }

    return Scenario(
        name=f"echo({text!r})",
        match=lambda _b, _c: True,
        respond=_respond,
        style=style,
    )


def tool_call_roundtrip_scenario(
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result_text: str,
    final_text: str = "Done — used the tool.",
    style: str = "openai",
) -> Scenario:
    """A two-turn scenario:
       - Turn 1: agent has only user messages → respond with a tool_call.
       - Turn 2: agent's last message is a tool result → respond with final text.

    Tests using this should send 2 LLM calls and assert both are recorded.
    """
    model = "claude-3-5-sonnet-20241022" if style == "anthropic" else "gpt-4o"

    def _has_tool_result(body: dict[str, Any], style: str) -> bool:
        msgs = body.get("messages", [])
        if not msgs:
            return False
        last = msgs[-1]
        if style == "anthropic":
            content = last.get("content", [])
            if isinstance(content, list):
                return any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                )
            return False
        # OpenAI: tool role
        return last.get("role") == "tool"

    def _respond(body: dict[str, Any], _ctx: MockContext) -> dict[str, Any]:
        if _has_tool_result(body, style):
            # Final answer after seeing the tool result.
            if style == "anthropic":
                return {
                    "id": "msg-mock-final",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": final_text}],
                    "model": model,
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 30, "output_tokens": 12},
                }
            return {
                "id": "cmpl-mock-final",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": final_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42},
            }
        # First call: emit the tool_call.
        if style == "anthropic":
            return {
                "id": "msg-mock-tool",
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": f"Let me call {tool_name}."},
                    {
                        "type": "tool_use",
                        "id": "toolu_mock_001",
                        "name": tool_name,
                        "input": tool_args,
                    },
                ],
                "model": model,
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 20, "output_tokens": 15},
            }
        return {
            "id": "cmpl-mock-tool",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_mock_001",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_args),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35},
        }

    return Scenario(
        name=f"tool_call({tool_name})",
        match=lambda _b, _c: True,
        respond=_respond,
        style=style,
    )


def error_scenario(
    status: int,
    body: dict[str, Any] | None = None,
    style: str = "openai",
) -> Scenario:
    """Return a non-2xx response (e.g. 429, 500, 400)."""
    body = body or {"error": {"message": "mock error", "type": "mock"}}

    async def _respond(_b: dict[str, Any], _c: MockContext) -> dict[str, Any]:
        return body

    return Scenario(
        name=f"error({status})",
        match=lambda _b, _c: True,
        respond=_respond,
        style=style,
        status=status,
    )


def conversation_scenario(
    responses: list[str],
    style: str = "openai",
) -> Scenario:
    """Stateful: respond with responses[ctx.turn_count] for each successive call.

    Use this when the test wants to verify that the gateway records a
    multi-turn conversation in order.
    """
    model = "claude-3-5-sonnet-20241022" if style == "anthropic" else "gpt-4o"

    def _respond(_b: dict[str, Any], ctx: MockContext) -> dict[str, Any]:
        idx = min(ctx.turn_count, len(responses) - 1)
        text = responses[idx]
        if style == "anthropic":
            return {
                "id": f"msg-{idx}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "model": model,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10 + idx, "output_tokens": 5 + idx},
            }
        return {
            "id": f"cmpl-{idx}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10 + idx,
                "completion_tokens": 5 + idx,
                "total_tokens": 15 + 2 * idx,
            },
        }

    return Scenario(
        name=f"conversation({len(responses)} turns)",
        match=lambda _b, _c: True,
        respond=_respond,
        style=style,
    )
