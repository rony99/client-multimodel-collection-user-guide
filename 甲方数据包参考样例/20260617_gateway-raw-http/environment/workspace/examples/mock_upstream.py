"""Tiny mock upstream for local demos.

Stands up a FastAPI app on 127.0.0.1:9100 that speaks both OpenAI
Chat Completions and Anthropic Messages. Run alongside the gateway
in `examples/run_local.sh`.

This is intentionally separate from `tests/conftest.py` so the example
runs without a pytest install and stays easy to read.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="lightweight-gateway mock upstream")


@app.post("/v1/chat/completions")
async def openai_chat(request: Request) -> object:
    body = await request.json()
    if body.get("stream"):
        chunks = [
            {
                "id": "cmpl-mock",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model", "gpt-4o"),
                "choices": [
                    {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                ],
            },
            {
                "id": "cmpl-mock",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model", "gpt-4o"),
                "choices": [
                    {"index": 0, "delta": {"content": "Hello "}, "finish_reason": None}
                ],
            },
            {
                "id": "cmpl-mock",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model", "gpt-4o"),
                "choices": [
                    {"index": 0, "delta": {"content": "world!"}, "finish_reason": "stop"}
                ],
            },
        ]

        async def gen() -> AsyncIterator[bytes]:
            for c in chunks:
                yield f"data: {json.dumps(c)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")
    return {
        "id": "cmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "gpt-4o"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from mock!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


@app.post("/v1/messages")
async def anthropic_messages(request: Request) -> object:
    body = await request.json()
    if body.get("stream"):
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg-mock",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": body.get("model", "claude-3-5-sonnet"),
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
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 7},
            },
            {"type": "message_stop"},
        ]

        async def gen() -> AsyncIterator[bytes]:
            for e in events:
                yield f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode("utf-8")

        return StreamingResponse(gen(), media_type="text/event-stream")
    return {
        "id": "msg-mock",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello from mock!"}],
        "model": body.get("model", "claude-3-5-sonnet"),
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9100, log_level="warning")
