"""Shared pytest fixtures.

The big one is `mock_upstream_app`: a FastAPI app that pretends to be
both OpenAI Chat Completions and Anthropic Messages, so the gateway
can be tested end-to-end without any real LLM calls.

We start the mock on a real OS port via `uvicorn` (in a thread) so the
gateway can talk to it the same way it would talk to api.openai.com.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request

from gateway.app import create_app
from gateway.config import (
    GatewayConfig,
    LogConfig,
    RouteConfig,
    ServerConfig,
    UpstreamConfig,
)


# ----- mock upstream ---------------------------------------------------


def make_mock_upstream_app(
    *,
    openai_response: dict[str, Any] | None = None,
    openai_stream_chunks: list[dict[str, Any]] | None = None,
    anthropic_response: dict[str, Any] | None = None,
    anthropic_stream_chunks: list[dict[str, Any]] | None = None,
    openai_delay_ms: int = 0,
    anthropic_delay_ms: int = 0,
    record_calls: bool = True,
) -> tuple[FastAPI, dict[str, list[dict[str, Any]]]]:
    """Build a FastAPI app that mimics OpenAI + Anthropic.

    Returns (app, calls) where `calls["openai"]` and `calls["anthropic"]`
    are populated with the request bodies received (for assertions).
    """
    app = FastAPI()
    calls: dict[str, list[dict[str, Any]]] = {"openai": [], "anthropic": []}

    default_openai = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from mock!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    default_anthropic = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello from mock!"}],
        "model": "claude-3-5-sonnet-20241022",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }

    @app.post("/v1/chat/completions")
    async def openai_chat(request: Request) -> Any:
        body = await request.json()
        if record_calls:
            calls["openai"].append(body)
        if openai_delay_ms:
            await asyncio.sleep(openai_delay_ms / 1000)
        if body.get("stream"):
            chunks = openai_stream_chunks or [
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": body.get("model", "gpt-4o"),
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                },
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": body.get("model", "gpt-4o"),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "Hello "},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": body.get("model", "gpt-4o"),
                    "choices": [{"index": 0, "delta": {"content": "world!"}, "finish_reason": "stop"}],
                },
            ]
            from fastapi.responses import StreamingResponse

            async def gen() -> AsyncIterator[bytes]:
                for c in chunks:
                    yield f"data: {json.dumps(c)}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        return default_openai if openai_response is None else openai_response

    @app.post("/v1/messages")
    async def anthropic_messages(request: Request) -> Any:
        body = await request.json()
        if record_calls:
            calls["anthropic"].append(body)
        if anthropic_delay_ms:
            await asyncio.sleep(anthropic_delay_ms / 1000)
        if body.get("stream"):
            chunks = anthropic_stream_chunks or [
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": body.get("model", "claude-3-5-sonnet-20241022"),
                        "stop_reason": None,
                        "usage": {"input_tokens": 11, "output_tokens": 0},
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello world!"},
                },
                {
                    "type": "content_block_stop",
                    "index": 0,
                },
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 7},
                },
                {"type": "message_stop"},
            ]
            from fastapi.responses import StreamingResponse

            async def gen() -> AsyncIterator[bytes]:
                for c in chunks:
                    yield f"event: {c.get('type', 'message')}\ndata: {json.dumps(c)}\n\n".encode("utf-8")

            return StreamingResponse(gen(), media_type="text/event-stream")
        return default_anthropic if anthropic_response is None else anthropic_response

    return app, calls


# ----- server fixtures -------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _ServerThread:
    """Run a uvicorn server in a background thread; stop on .stop()."""

    def __init__(self, app: FastAPI, port: int) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        # Wait for "started" flag.
        for _ in range(100):
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("mock upstream did not start in time")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


@pytest.fixture
def mock_upstream() -> Iterator[tuple[str, dict[str, list[dict[str, Any]]]]]:
    """Spin up a default mock upstream on a free port; yield (base_url, calls)."""
    app, calls = make_mock_upstream_app()
    port = _free_port()
    server = _ServerThread(app, port)
    server.start()
    try:
        yield f"http://127.0.0.1:{port}", calls
    finally:
        server.stop()


# ----- gateway fixture --------------------------------------------------


def _build_gateway_config(
    log_dir: Any,
    upstream_base_url: str,
    *,
    openai_upstream_name: str = "openai-mock",
    anthropic_upstream_name: str = "anthropic-mock",
    openai_model: str = "gpt-4o",
    anthropic_model: str = "claude-3-5-sonnet",
) -> GatewayConfig:
    return GatewayConfig(
        server=ServerConfig(host="127.0.0.1", port=9000, log_level="WARNING"),
        log=LogConfig(dir=log_dir),
        upstreams=[
            UpstreamConfig(
                name=openai_upstream_name,
                style="openai",
                base_url=upstream_base_url,  # type: ignore[arg-type]
                api_key="test-key",
                timeout_seconds=5.0,
            ),
            UpstreamConfig(
                name=anthropic_upstream_name,
                style="anthropic",
                base_url=upstream_base_url,  # type: ignore[arg-type]
                api_key="test-key",
                timeout_seconds=5.0,
                version="2023-06-01",
            ),
        ],
        routes=[
            RouteConfig(
                model_id=openai_model,
                upstream=openai_upstream_name,
                upstream_model="gpt-4o-mock",
            ),
            RouteConfig(
                model_id=anthropic_model,
                upstream=anthropic_upstream_name,
                upstream_model="claude-3-5-sonnet-mock",
            ),
            # Test route with NO upstream_model rewrite.
            RouteConfig(
                model_id="gpt-4o-passthrough",
                upstream=openai_upstream_name,
            ),
        ],
    )


@pytest.fixture
async def gateway_env(
    tmp_path, mock_upstream
) -> AsyncIterator[dict[str, Any]]:
    """Build a full gateway environment: app, gateway state, base url."""
    upstream_base_url, calls = mock_upstream
    cfg = _build_gateway_config(tmp_path / "logs", upstream_base_url)
    app = create_app(cfg)

    # Trigger lifespan startup manually.
    async with _lifespan(app):
        yield {
            "app": app,
            "cfg": cfg,
            "log_dir": cfg.log.dir,
            "upstream_base_url": upstream_base_url,
            "calls": calls,
        }


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Drive the FastAPI lifespan context for tests that build an app
    without going through the real uvicorn lifespan."""
    async with app.router.lifespan_context(app):
        yield


@pytest.fixture
async def http_client(gateway_env) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx client bound to the gateway's ASGI app (no real socket)."""
    transport = httpx.ASGITransport(app=gateway_env["app"])
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        yield client
