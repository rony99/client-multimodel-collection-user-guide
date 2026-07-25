"""Core catch-all proxy route.

Flow per request:

    agent --POST /v1/chat/completions?project_id=...&model_id=...--->
        [proxy]
        1. parse query: project_id, model_id
        2. resolve session_id  (header > query > body > auth > uuid)
        3. router.resolve(model_id) -> (upstream, upstream_model)
        4. read body, strip hop-by-hop headers, optionally rewrite model
        5. detect streaming: Accept: text/event-stream OR body.stream=true
        6. forward to upstream
              non-stream: capture full body, extract usage
              stream    : forward chunks + buffer for log, write on end
        7. write CompletionRecord to the session's JSONL
        8. return response with X-Polar-Session-Id set
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .models import CompletionRecord, TokenUsage
from .routing import UnknownModelIdError
from .session import is_valid_project_id, resolve_session_id
from .writer import TrajectoryWriter, utcnow_iso

logger = logging.getLogger(__name__)

router = APIRouter()

# Hop-by-hop / connection-specific headers we must strip before forwarding.
# (RFC 7230 §6.1 + a few extras that confuse upstream clients.)
_HOP_BY_HOP = frozenset(
    {
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

# Maximum bytes we'll buffer from a streaming response for the log.
# Beyond this we truncate (writer.py handles that) to avoid OOM.
MAX_STREAM_BUFFER_BYTES = 16 * 1024 * 1024

# Status header on every successful response so the agent can keep using
# the same session without round-tripping the session_id back through us.
SESSION_HEADER = "X-Polar-Session-Id"


def get_state(request: Request) -> Any:
    """Pull the gateway state attached in app.py lifespan."""
    return request.app.state.gateway


def _filter_request_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


def _parse_query_lower(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.query_params.items()}


def _maybe_json_body(raw: bytes) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _detect_streaming(body: dict[str, Any] | None, accept: str | None) -> bool:
    if body and isinstance(body.get("stream"), bool) and body["stream"]:
        return True
    if accept and "text/event-stream" in accept.lower():
        return True
    return False


def _extract_usage_openai(body: dict[str, Any] | None) -> TokenUsage | None:
    if not body:
        return None
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    return TokenUsage(
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
    )


def _extract_usage_anthropic(body: dict[str, Any] | None) -> TokenUsage | None:
    if not body:
        return None
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("input_tokens")
    completion = usage.get("output_tokens")
    total = (prompt or 0) + (completion or 0) if (prompt is not None or completion is not None) else None
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def _extract_usage(style: str, body: dict[str, Any] | None) -> TokenUsage | None:
    if style == "anthropic":
        return _extract_usage_anthropic(body)
    return _extract_usage_openai(body)


def _rewrite_model_in_body(body: dict[str, Any] | None, new_model: str) -> bytes:
    """Return the request body with the `model` field replaced. If the
    body isn't parseable as a JSON object, fall back to bytes unchanged
    — the proxy has already validated it earlier.
    """
    if body is None or new_model == body.get("model"):
        return json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else b""
    body = dict(body)
    body["model"] = new_model
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


# ----- the route --------------------------------------------------------


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy_route(request: Request, path: str) -> Response:
    state = get_state(request)
    started = time.perf_counter()

    # ---- 1. parse query params ----------------------------------------
    query = _parse_query_lower(request)
    project_id = query.get("project_id")
    model_id = query.get("model_id")
    if not project_id or not is_valid_project_id(project_id):
        return _bad_request("missing or invalid `project_id` query param")
    if not model_id:
        return _bad_request("missing `model_id` query param")

    # ---- 2. resolve route + session -----------------------------------
    try:
        route = state.router.resolve(model_id)
    except UnknownModelIdError as exc:
        return _bad_request(str(exc))

    # ---- 3. read body + headers ---------------------------------------
    raw_body = await request.body()
    body_json = _maybe_json_body(raw_body)
    inbound_headers = _filter_request_headers(dict(request.headers))

    # ---- 4. resolve session id ----------------------------------------
    session_id = resolve_session_id(
        headers={k.lower(): v for k, v in inbound_headers.items()},
        body=body_json,
        query=query,
    )

    # ---- 5. choose upstream + maybe rewrite model --------------------
    upstream = state.pool.get(route.upstream)
    forward_body = _rewrite_model_in_body(body_json, route.upstream_model)
    accept = inbound_headers.get("accept")
    is_stream = _detect_streaming(body_json, accept)
    content_type = "application/json"
    if is_stream:
        # Hint upstream to stream.
        inbound_headers["accept"] = "text/event-stream"

    # ---- 6. build upstream request ------------------------------------
    upstream_req = upstream.request(
        request.method,
        path,
        headers={**inbound_headers, "content-type": content_type},
        content=forward_body,
    )

    logger.info(
        "← %s %s | project=%s session=%s model=%s -> %s stream=%s",
        request.method,
        path,
        project_id,
        session_id,
        model_id,
        upstream.name,
        is_stream,
    )

    # ---- 7. dispatch --------------------------------------------------
    if is_stream:
        return await _proxy_streaming(
            request=request,
            state=state,
            upstream=upstream,
            upstream_req=upstream_req,
            route=route,
            session_id=session_id,
            project_id=project_id,
            model_id=model_id,
            request_body=body_json or {},
            started=started,
        )
    return await _proxy_non_streaming(
        request=request,
        state=state,
        upstream=upstream,
        upstream_req=upstream_req,
        route=route,
        session_id=session_id,
        project_id=project_id,
        model_id=model_id,
        request_body=body_json or {},
        started=started,
    )


# ----- non-streaming handler --------------------------------------------


async def _proxy_non_streaming(
    *,
    request: Request,
    state: Any,
    upstream: Any,
    upstream_req: httpx.Request,
    route: Any,
    session_id: str,
    project_id: str,
    model_id: str,
    request_body: dict[str, Any],
    started: float,
) -> Response:
    record_seq = await state.writer.next_sequence(project_id, session_id)  # type: ignore[attr-defined]
    try:
        upstream_resp = await upstream.send(upstream_req, stream=False)
    except Exception as exc:  # network / timeout
        await _record_failure(
            state.writer,
            project_id=project_id,
            session_id=session_id,
            model_id=model_id,
            route=route,
            request_body=request_body,
            started=started,
            sequence=record_seq,
            error=f"{type(exc).__name__}: {exc}",
        )
        return JSONResponse({"error": "upstream unreachable"}, status_code=502)

    response_bytes = upstream_resp.content
    response_json: dict[str, Any] | None = None
    if "application/json" in (upstream_resp.headers.get("content-type") or ""):
        try:
            response_json = json.loads(response_bytes)
        except (ValueError, UnicodeDecodeError):
            response_json = None

    # ---- raw HTTP trace log (non-streaming) ----
    raw_logger = getattr(state, "raw_http_logger", None)
    if raw_logger is not None:
        try:
            await raw_logger.log_pair(
                session_id,
                request=upstream_req,
                response=upstream_resp,
            )
        except Exception:  # pragma: no cover - never break the proxy
            logger.exception("raw HTTP trace logging failed (non-streaming)")

    timing_ms = (time.perf_counter() - started) * 1000
    record = CompletionRecord(
        completion_id=uuid.uuid4().hex,
        sequence=record_seq,
        timestamp=utcnow_iso(),
        project_id=project_id,
        session_id=session_id,
        model_id=model_id,
        upstream=route.upstream,
        upstream_model=route.upstream_model,
        request_body=request_body,
        response_body=response_json,
        response_status=upstream_resp.status_code,
        is_streaming=False,
        timing_ms=timing_ms,
        token_usage=_extract_usage(upstream.style, response_json),
    )
    await state.writer.append(record)

    # Strip hop-by-hop from the upstream response before sending back.
    resp_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    resp_headers[SESSION_HEADER] = session_id
    return Response(
        content=response_bytes,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


# ----- streaming handler (real SSE passthrough) -------------------------


async def _proxy_streaming(
    *,
    request: Request,
    state: Any,
    upstream: Any,
    upstream_req: httpx.Request,
    route: Any,
    session_id: str,
    project_id: str,
    model_id: str,
    request_body: dict[str, Any],
    started: float,
) -> Response:
    record_seq = await state.writer.next_sequence(project_id, session_id)  # type: ignore[attr-defined]

    # Open the upstream stream eagerly so we can fail fast on connection errors
    # and record the failure before returning 502 to the agent.
    try:
        upstream_resp = await upstream.send(upstream_req, stream=True)
    except Exception as exc:
        await _record_failure(
            state.writer,
            project_id=project_id,
            session_id=session_id,
            model_id=model_id,
            route=route,
            request_body=request_body,
            started=started,
            sequence=record_seq,
            error=f"{type(exc).__name__}: {exc}",
        )
        return JSONResponse({"error": "upstream unreachable"}, status_code=502)

    chunks: list[bytes] = []
    chunk_count = 0
    upstream_status = upstream_resp.status_code
    upstream_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    upstream_error: str | None = None

    async def iterator() -> Any:
        nonlocal chunk_count, upstream_error
        try:
            async for chunk in upstream_resp.aiter_bytes():
                chunk_count += 1
                chunks.append(chunk)
                yield chunk
        except Exception as exc:
            upstream_error = f"{type(exc).__name__}: {exc}"
            logger.warning("streaming upstream error: %s", upstream_error)
        finally:
            # httpx 0.28+ requires explicit aclose to release the connection.
            await upstream_resp.aclose()
            # Write the log record after the stream is done.
            timing_ms = (time.perf_counter() - started) * 1000
            raw = b"".join(chunks).decode("utf-8", errors="replace")
            # Best-effort: scan SSE data lines for a usage-bearing chunk.
            last_json = _scan_sse_for_usage(raw, upstream.style)
            record = CompletionRecord(
                completion_id=uuid.uuid4().hex,
                sequence=record_seq,
                timestamp=utcnow_iso(),
                project_id=project_id,
                session_id=session_id,
                model_id=model_id,
                upstream=route.upstream,
                upstream_model=route.upstream_model,
                request_body=request_body,
                response_body=last_json if last_json else None,
                response_raw=raw,
                is_streaming=True,
                chunk_count=chunk_count,
                response_status=upstream_status,
                error=upstream_error,
                timing_ms=timing_ms,
                token_usage=_extract_usage(upstream.style, last_json),
            )
            try:
                await state.writer.append(record)
            except Exception:  # pragma: no cover - never fail the client side
                logger.exception("failed to persist streaming record")

            # ---- raw HTTP trace log (streaming) ----
            raw_logger = getattr(state, "raw_http_logger", None)
            if raw_logger is not None:
                try:
                    await raw_logger.log_pair(
                        session_id,
                        request=upstream_req,
                        response=upstream_resp,
                        response_body_raw=b"".join(chunks),
                    )
                except Exception:  # pragma: no cover
                    logger.exception("raw HTTP trace logging failed (streaming)")

    media_type = upstream_headers.get("content-type") or "text/event-stream"
    resp_headers = dict(upstream_headers)
    resp_headers[SESSION_HEADER] = session_id
    return StreamingResponse(
        iterator(),
        status_code=upstream_status,
        headers=resp_headers,
        media_type=media_type,
    )


# ----- helpers ----------------------------------------------------------


def _bad_request(msg: str) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=400)


_SSE_DATA_PREFIX = "data: "


def _scan_sse_for_usage(raw: str, style: str) -> dict[str, Any] | None:
    """Walk an SSE stream and return the last JSON object that contains
    a `usage` field, if any. Cheap and best-effort; v3 export can re-parse.
    """
    if not raw:
        return None
    last: dict[str, Any] | None = None
    for line in raw.splitlines():
        if not line.startswith(_SSE_DATA_PREFIX):
            continue
        payload = line[len(_SSE_DATA_PREFIX):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("usage"), dict):
            last = obj
    return last


async def _record_failure(
    writer: TrajectoryWriter,
    *,
    project_id: str,
    session_id: str,
    model_id: str,
    route: Any,
    request_body: dict[str, Any],
    started: float,
    sequence: int,
    error: str,
) -> None:
    record = CompletionRecord(
        completion_id=uuid.uuid4().hex,
        sequence=sequence,
        timestamp=utcnow_iso(),
        project_id=project_id,
        session_id=session_id,
        model_id=model_id,
        upstream=route.upstream,
        upstream_model=route.upstream_model,
        request_body=request_body,
        response_status=None,
        is_streaming=False,
        timing_ms=(time.perf_counter() - started) * 1000,
        error=error,
    )
    try:
        await writer.append(record)
    except Exception:  # pragma: no cover - never propagate
        logger.exception("failed to persist failure record")
