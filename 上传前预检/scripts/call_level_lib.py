"""Merge Claude Code session JSONL + Gateway API captures into 甲方 call-level records.

Field mapping (交付规范 §7 / delivery.go / local-cc storage):

  session.jsonl assistant.message  → response.response_data (when Gateway stream incomplete)
  local-cc Call.request.body       → request (Anthropic Messages body)
  local-cc Call.id / startedAt     → request_id / timestamp
  local-cc Call.sessionId          → session_id
  Event.upstream.request_body.body_raw_json → request
  Event request_id/session_id/timestamp    → top-level ids
  output_config.effort / metadata  → thinking_effort (default high + warn)

Forbidden delivery shapes: claude-trace wrappers, SSE body_raw, request.url.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

VALID_EFFORTS = frozenset({"high", "xhigh", "max"})
VALID_STOP = frozenset({"end_turn", "tool_use", "max_tokens", "stop_sequence"})
MAIN_SESSION_NAMES = frozenset({"session.jsonl"})
AUX_JSONL_NAMES = frozenset({"call_level.jsonl", "calls.jsonl"})


@dataclass
class Issue:
    level: str  # PASS | WARN | FAIL
    code: str
    message: str


@dataclass
class GatewayCall:
    source: str  # local-cc | event
    request_id: str
    session_id: str
    timestamp: str
    model: str
    request: dict[str, Any]
    response_data: dict[str, Any] | None
    status_code: int
    path: str
    is_candidate: bool
    skip_reason: str = ""
    effort_defaulted: bool = False


@dataclass
class AssistantTurn:
    message_id: str
    model: str
    content: list[Any]
    stop_reason: str | None
    usage: dict[str, Any] | None
    timestamp: str
    role: str = "assistant"


@dataclass
class MergeReport:
    session_id: str = ""
    gateway_source: str = ""
    gateway_files: int = 0
    candidates: int = 0
    assistant_turns: int = 0
    records: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    pairings: list[dict[str, Any]] = field(default_factory=list)

    def add(self, level: str, code: str, message: str) -> None:
        self.issues.append(Issue(level=level, code=code, message=message))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["issues"] = [asdict(i) for i in self.issues]
        return d


def _parse_json_maybe(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


def _as_list(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    return None


def _system_text_blob(system: Any) -> str:
    if isinstance(system, str):
        return system
    parts: list[str] = []
    if isinstance(system, list):
        for b in system:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif isinstance(b, str):
                parts.append(b)
    return "\n".join(parts)


def _is_subagent_request(request: dict[str, Any]) -> bool:
    blob = _system_text_blob(request.get("system"))
    return "cc_is_subagent=true" in blob or "cc_is_subagent\":true" in blob


def extract_effort(request: dict[str, Any], metadata: dict[str, Any] | None = None) -> tuple[str, bool]:
    if metadata:
        for key in ("route_effort", "thinking_effort", "effort"):
            v = metadata.get(key)
            if isinstance(v, str) and v in VALID_EFFORTS:
                return v, False
    oc = request.get("output_config")
    if isinstance(oc, dict):
        v = oc.get("effort")
        if isinstance(v, str) and v in VALID_EFFORTS:
            return v, False
    thinking = request.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") in ("adaptive", "enabled", "high"):
        return "high", True
    return "high", True


def response_from_gateway_payload(resp_obj: dict[str, Any] | None, body_text: str = "", raw_sse: str = "") -> dict[str, Any] | None:
    if not resp_obj and not body_text and not raw_sse:
        return None
    if resp_obj:
        # local-cc Response shape or Event response body
        body = resp_obj.get("body")
        if body is None and "content" in resp_obj and "stop_reason" in resp_obj:
            return resp_obj if isinstance(resp_obj, dict) else None
        parsed = _parse_json_maybe(body)
        if isinstance(parsed, dict) and ("content" in parsed or "stop_reason" in parsed):
            return parsed
        bt = resp_obj.get("bodyText") or body_text
        if isinstance(bt, str) and bt.strip().startswith("{"):
            parsed = _parse_json_maybe(bt)
            if isinstance(parsed, dict) and ("content" in parsed or "stop_reason" in parsed):
                return parsed
        sse = resp_obj.get("response_raw_sse") or raw_sse
        if isinstance(sse, str) and sse.strip():
            return decode_sse(sse)
    if raw_sse.strip():
        return decode_sse(raw_sse)
    return None


def decode_sse(raw: str) -> dict[str, Any] | None:
    """Port of delivery.go decodeSSE (text / thinking / tool_use)."""
    response: dict[str, Any] | None = None
    blocks: dict[int, dict[str, Any]] = {}
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        et = event.get("type")
        if et == "message_start":
            msg = event.get("message")
            if isinstance(msg, dict):
                response = copy.deepcopy(msg)
        elif et == "content_block_start":
            idx = event.get("index")
            block = event.get("content_block")
            if isinstance(idx, int) and isinstance(block, dict):
                blocks[idx] = copy.deepcopy(block)
        elif et == "content_block_delta":
            idx = event.get("index")
            delta = event.get("delta")
            if isinstance(idx, int) and isinstance(delta, dict) and idx in blocks:
                _merge_delta(blocks[idx], delta)
        elif et == "content_block_stop":
            idx = event.get("index")
            if isinstance(idx, int) and idx in blocks:
                _decode_tool_input(blocks[idx])
        elif et == "message_delta" and response is not None:
            delta = event.get("delta")
            if isinstance(delta, dict):
                response.update(delta)
            usage = event.get("usage")
            if isinstance(usage, dict):
                response["usage"] = usage
    if response is None:
        return None
    content = []
    for i in range(0, max(blocks.keys()) + 1 if blocks else 0):
        if i in blocks:
            content.append(blocks[i])
    response["content"] = content
    return response


def _merge_delta(block: dict[str, Any], delta: dict[str, Any]) -> None:
    for key, value in delta.items():
        if key == "type":
            continue
        if isinstance(value, str):
            if key in ("text", "thinking", "partial_json", "signature"):
                block[key] = (block.get(key) or "") + value
            else:
                block[key] = value
        else:
            block[key] = value


def _decode_tool_input(block: dict[str, Any]) -> None:
    partial = block.get("partial_json")
    if isinstance(partial, str) and partial:
        try:
            block["input"] = json.loads(partial)
        except json.JSONDecodeError:
            pass
        block.pop("partial_json", None)


def load_gateway_dir(gateway_dir: Path) -> tuple[list[GatewayCall], MergeReport]:
    report = MergeReport()
    calls: list[GatewayCall] = []
    if not gateway_dir.is_dir():
        report.add("FAIL", "GW_DIR", f"Gateway 目录不存在：{gateway_dir}")
        return calls, report

    files = sorted(gateway_dir.glob("*.json"))
    report.gateway_files = len(files)
    if not files:
        report.add("FAIL", "GW_EMPTY", f"Gateway 目录无 *.json：{gateway_dir}")
        return calls, report

    sources: set[str] = set()
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            report.skipped.append({"path": str(path), "reason": f"parse_error:{e}"})
            continue
        if not isinstance(raw, dict):
            report.skipped.append({"path": str(path), "reason": "not_object"})
            continue

        gc: GatewayCall | None = None
        if "upstream" in raw or "capture_version" in raw:
            gc = _from_event(raw, path)
            sources.add("event")
        elif "request" in raw and ("sessionId" in raw or "id" in raw):
            gc = _from_local_cc(raw, path)
            sources.add("local-cc")
        else:
            report.skipped.append({"path": str(path), "reason": "unknown_schema"})
            continue

        if gc is None:
            continue
        if not gc.is_candidate:
            report.skipped.append({"path": str(path), "reason": gc.skip_reason or "not_candidate"})
            continue
        calls.append(gc)

    report.gateway_source = ",".join(sorted(sources)) or "unknown"
    if calls:
        report.session_id = calls[0].session_id
    calls.sort(key=lambda c: c.timestamp or c.request_id)
    report.candidates = len(calls)
    if not calls:
        report.add("FAIL", "GW_NO_CANDIDATE", "无可用 LLM 调用（需 system+tools+messages 且 HTTP 2xx）")
    else:
        report.add("PASS", "GW_CANDIDATES", f"交付候选 {len(calls)} 条（源={report.gateway_source}）")
    return calls, report


def _from_local_cc(raw: dict[str, Any], path: Path) -> GatewayCall | None:
    req_wrap = raw.get("request") or {}
    body = _parse_json_maybe(req_wrap.get("body"))
    if body is None and req_wrap.get("bodyText"):
        body = _parse_json_maybe(req_wrap.get("bodyText"))
    if not isinstance(body, dict):
        return GatewayCall(
            source="local-cc",
            request_id=str(raw.get("id") or path.stem),
            session_id=str(raw.get("sessionId") or path.parent.name),
            timestamp=str(raw.get("startedAt") or ""),
            model=str(raw.get("model") or ""),
            request={},
            response_data=None,
            status_code=0,
            path=str(path),
            is_candidate=False,
            skip_reason="no_request_body",
        )
    resp = raw.get("response") if isinstance(raw.get("response"), dict) else None
    status = int((resp or {}).get("statusCode") or 0)
    response_data = response_from_gateway_payload(resp)
    ok, reason = _candidate_ok(body, status)
    effort, defaulted = extract_effort(body)
    # stash effort on call via request later when building record
    body = copy.deepcopy(body)
    body["_thinking_effort"] = effort
    body["_effort_defaulted"] = defaulted
    return GatewayCall(
        source="local-cc",
        request_id=str(raw.get("id") or path.stem),
        session_id=str(raw.get("sessionId") or path.parent.name),
        timestamp=str(raw.get("startedAt") or ""),
        model=str(raw.get("model") or body.get("model") or ""),
        request=body,
        response_data=response_data,
        status_code=status,
        path=str(path),
        is_candidate=ok,
        skip_reason=reason,
        effort_defaulted=defaulted,
    )


def _from_event(raw: dict[str, Any], path: Path) -> GatewayCall | None:
    up = raw.get("upstream") if isinstance(raw.get("upstream"), dict) else {}
    rb = up.get("request_body") if isinstance(up.get("request_body"), dict) else {}
    body = rb.get("body_raw_json")
    if body is None and rb.get("body_raw_text"):
        body = _parse_json_maybe(rb.get("body_raw_text"))
    if not isinstance(body, dict):
        return GatewayCall(
            source="event",
            request_id=str(raw.get("request_id") or raw.get("local_call_id") or path.stem),
            session_id=str(raw.get("session_id") or path.parent.name),
            timestamp=str(raw.get("timestamp") or ""),
            model="",
            request={},
            response_data=None,
            status_code=0,
            path=str(path),
            is_candidate=False,
            skip_reason="no_request_body",
        )
    status = int(up.get("response_status_code") or 0)
    resp_body = up.get("response_body") if isinstance(up.get("response_body"), dict) else {}
    response_data = response_from_gateway_payload(
        {
            "body": resp_body.get("body_raw_json"),
            "bodyText": resp_body.get("body_raw_text") or "",
        },
        raw_sse=str(up.get("response_raw_sse") or ""),
    )
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    effort, defaulted = extract_effort(body, meta)
    body = copy.deepcopy(body)
    body["_thinking_effort"] = effort
    body["_effort_defaulted"] = defaulted
    ok, reason = _candidate_ok(body, status, complete=bool(up.get("response_complete", True)))
    return GatewayCall(
        source="event",
        request_id=str(raw.get("request_id") or raw.get("local_call_id") or path.stem),
        session_id=str(raw.get("session_id") or path.parent.name),
        timestamp=str(raw.get("timestamp") or ""),
        model=str(body.get("model") or ""),
        request=body,
        response_data=response_data,
        status_code=status,
        path=str(path),
        is_candidate=ok,
        skip_reason=reason,
        effort_defaulted=defaulted,
    )


def _candidate_ok(body: dict[str, Any], status: int, complete: bool = True) -> tuple[bool, str]:
    if status and not (200 <= status < 300):
        return False, f"http_{status}"
    if not complete:
        return False, "response_incomplete"
    if _as_list(body.get("system")) is None:
        # allow string system? 甲方要求 list — skip strings as non-candidate for delivery
        if isinstance(body.get("system"), str):
            return False, "system_string_not_blocks"
        return False, "no_system"
    tools = _as_list(body.get("tools"))
    if not tools:
        return False, "no_tools"
    if _as_list(body.get("messages")) is None:
        return False, "no_messages"
    return True, ""


def load_session_assistants(session_path: Path) -> tuple[list[AssistantTurn], str, list[Issue]]:
    issues: list[Issue] = []
    if not session_path.is_file():
        issues.append(Issue("FAIL", "SESSION_MISSING", f"session 不存在：{session_path}"))
        return [], "", issues

    turns_by_id: dict[str, AssistantTurn] = {}
    order: list[str] = []
    session_id = ""
    try:
        lines = session_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        issues.append(Issue("FAIL", "SESSION_READ", str(e)))
        return [], "", issues

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        sid = row.get("sessionId") or row.get("session_id")
        if sid and not session_id:
            session_id = str(sid)
        if row.get("type") != "assistant":
            continue
        msg = row.get("message")
        if not isinstance(msg, dict):
            continue
        mid = str(msg.get("id") or row.get("uuid") or f"anon-{len(order)}")
        content = msg.get("content")
        if not isinstance(content, list):
            content = []
        if mid not in turns_by_id:
            turns_by_id[mid] = AssistantTurn(
                message_id=mid,
                model=str(msg.get("model") or ""),
                content=list(content),
                stop_reason=msg.get("stop_reason"),
                usage=msg.get("usage") if isinstance(msg.get("usage"), dict) else None,
                timestamp=str(row.get("timestamp") or ""),
            )
            order.append(mid)
        else:
            # merge content blocks from split assistant lines
            existing = turns_by_id[mid]
            existing.content.extend(content)
            if msg.get("stop_reason"):
                existing.stop_reason = msg.get("stop_reason")
            if isinstance(msg.get("usage"), dict):
                existing.usage = msg.get("usage")
            if row.get("timestamp"):
                existing.timestamp = str(row.get("timestamp"))

    turns = [turns_by_id[i] for i in order]
    if not turns:
        issues.append(Issue("FAIL", "SESSION_NO_ASSISTANT", "session 中无 assistant 轮次"))
    else:
        issues.append(Issue("PASS", "SESSION_ASSISTANT", f"assistant 轮次 {len(turns)}"))
    if not session_id:
        issues.append(Issue("WARN", "SESSION_ID_MISSING", "session.jsonl 未找到 sessionId 字段"))
    return turns, session_id, issues


def _response_usable(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    content = data.get("content")
    stop = data.get("stop_reason")
    if not isinstance(content, list) or not content:
        return False
    if stop is None or str(stop).strip() == "" or str(stop) == "null":
        return False
    return True


def _turn_to_response_data(turn: AssistantTurn) -> dict[str, Any]:
    rd: dict[str, Any] = {
        "id": turn.message_id,
        "type": "message",
        "role": "assistant",
        "content": turn.content,
        "model": turn.model,
        "stop_reason": turn.stop_reason or "end_turn",
    }
    if turn.usage:
        rd["usage"] = turn.usage
    return rd


def merge_calls(
    gateway_calls: list[GatewayCall],
    assistants: list[AssistantTurn],
    session_id: str,
    report: MergeReport,
) -> list[dict[str, Any]]:
    report.assistant_turns = len(assistants)
    # session id consistency
    gw_sids = {c.session_id for c in gateway_calls if c.session_id}
    if session_id and gw_sids and session_id not in gw_sids:
        report.add(
            "FAIL",
            "SESSION_ID_MISMATCH",
            f"sessionId「{session_id}」与 Gateway session「{sorted(gw_sids)}」不一致",
        )
        return []

    effective_sid = session_id or (next(iter(gw_sids)) if gw_sids else "")
    if not effective_sid:
        report.add("FAIL", "NO_SESSION_ID", "无法确定 session_id")
        return []
    report.session_id = effective_sid

    # Prefer non-subagent main chain for 1:1 if mixed
    main_calls = [c for c in gateway_calls if not _is_subagent_request(c.request)]
    use_calls = main_calls if main_calls else gateway_calls

    remaining = [t for t in assistants]
    records: list[dict[str, Any]] = []

    for gc in use_calls:
        req = {k: v for k, v in gc.request.items() if not str(k).startswith("_")}
        # Prefer effort still on request body so validate can see source
        effort_from_req = None
        oc = req.get("output_config") if isinstance(req.get("output_config"), dict) else None
        if isinstance(oc, dict) and oc.get("effort") in VALID_EFFORTS:
            effort_from_req = oc.get("effort")
        effort = effort_from_req
        if effort not in VALID_EFFORTS:
            report.add(
                "FAIL",
                "EFFORT_MISSING",
                f"{gc.request_id}: request.output_config.effort 缺失（甲方须 high|xhigh|max）",
            )
            effort = "high"  # placeholder so remaining structure still exportable; validate will FAIL source

        response_data = gc.response_data if _response_usable(gc.response_data) else None
        source_for_resp = "gateway"
        matched_turn: AssistantTurn | None = None

        if response_data is None:
            rid_hint = None
            if isinstance(gc.response_data, dict):
                rid_hint = gc.response_data.get("id")
            if rid_hint:
                for t in remaining:
                    if t.message_id == rid_hint:
                        matched_turn = t
                        break
            if matched_turn is None and remaining:
                matched_turn = remaining[0]
            if matched_turn is not None:
                response_data = _turn_to_response_data(matched_turn)
                remaining = [t for t in remaining if t.message_id != matched_turn.message_id]
                source_for_resp = "session"
            else:
                report.add("FAIL", "NO_RESPONSE", f"{gc.request_id}: 无 Gateway 完整响应且无剩余 assistant 轮次")
                continue

        if not _response_usable(response_data):
            if isinstance(response_data, dict) and response_data.get("content"):
                if not response_data.get("stop_reason"):
                    content = response_data.get("content") or []
                    has_tool = any(
                        isinstance(b, dict) and b.get("type") == "tool_use" for b in content
                    )
                    response_data["stop_reason"] = "tool_use" if has_tool else "end_turn"
                    report.add("WARN", "STOP_INFERRED", f"{gc.request_id}: 推断 stop_reason")
            if not _response_usable(response_data):
                report.add("FAIL", "BAD_RESPONSE", f"{gc.request_id}: response_data 不完整")
                continue

        # ensure role for 甲方
        if isinstance(response_data, dict) and not response_data.get("role"):
            response_data["role"] = "assistant"

        rec = {
            "session_id": effective_sid,
            "request_id": gc.request_id,
            "timestamp": _normalize_ts(gc.timestamp or (matched_turn.timestamp if matched_turn else "")),
            "thinking_effort": effort if effort in VALID_EFFORTS else "high",
            "request": req,
            "response": {"response_data": response_data},
        }
        if not rec["timestamp"]:
            report.add("FAIL", "TIMESTAMP", f"{gc.request_id}: timestamp 为空")
        records.append(rec)
        report.pairings.append(
            {
                "request_id": gc.request_id,
                "response_source": source_for_resp,
                "assistant_id": matched_turn.message_id if matched_turn else (response_data or {}).get("id"),
            }
        )

    unused = len(remaining)
    if unused:
        report.add(
            "WARN",
            "ASSISTANT_EXTRA",
            f"session 尚有 {unused} 条 assistant 未配对到 Gateway 候选",
        )
    if len(records) != len(use_calls):
        report.add(
            "WARN",
            "COUNT_MISMATCH",
            f"产出 {len(records)} 条 / 候选 {len(use_calls)} / assistant {len(assistants)}",
        )
    if abs(len(records) - len(assistants)) > max(2, len(assistants) // 3):
        report.add(
            "WARN",
            "ASSISTANT_DELTA",
            f"call-level 条数({len(records)}) 与 assistant 轮次({len(assistants)}) 偏差较大",
        )

    report.records = len(records)
    if records:
        report.add("PASS", "MERGE_OK", f"已合并 {len(records)} 条 call-level")
    else:
        report.add("FAIL", "MERGE_EMPTY", "未产出任何 call-level 记录")
    return records


def _normalize_ts(ts: str) -> str:
    if not ts:
        return ""
    # already ISO-ish
    if ts.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", ts):
        return ts
    if "T" in ts:
        return ts if "Z" in ts or "+" in ts else ts + "Z"
    return ts


def build_agents_payload(gateway_calls: list[GatewayCall]) -> dict[str, Any] | None:
    main = None
    sub = None
    for gc in gateway_calls:
        if not gc.is_candidate:
            continue
        payload = {
            "system": gc.request.get("system"),
            "tools": gc.request.get("tools"),
            "source": {
                "source_type": "gateway_capture",
                "gateway_source": gc.source,
                "request_id": gc.request_id,
                "session_id": gc.session_id,
                "path": gc.path,
            },
        }
        if _is_subagent_request(gc.request):
            if sub is None:
                sub = payload
        else:
            if main is None:
                main = payload
    if main is None and gateway_calls:
        # fall back first candidate
        gc = next((c for c in gateway_calls if c.is_candidate), None)
        if gc:
            main = {
                "system": gc.request.get("system"),
                "tools": gc.request.get("tools"),
                "source": {
                    "source_type": "gateway_capture",
                    "gateway_source": gc.source,
                    "request_id": gc.request_id,
                    "session_id": gc.session_id,
                    "path": gc.path,
                },
            }
    if main is None:
        return None
    out = {"main_agent": main}
    if sub is not None:
        out["subagent"] = sub
    return out


def build_snapshot(gateway_calls: list[GatewayCall], model: str = "") -> dict[str, Any] | None:
    agents = build_agents_payload(gateway_calls)
    if not agents:
        return None
    main = agents["main_agent"]
    return {
        "session_id": main["source"]["session_id"],
        "model": model or "",
        "system_prompt": main.get("system"),
        "system_prompt_capture_status": "captured",
        "system_prompt_source": main.get("source"),
        "tools": main.get("tools"),
        "tool_schema_source": main.get("source"),
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_agents(agents_out: Path, payload: dict[str, Any]) -> None:
    agents_out.mkdir(parents=True, exist_ok=True)
    main = payload.get("main_agent")
    if main:
        (agents_out / "main_agent.json").write_text(
            json.dumps(main, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    sub = payload.get("subagent")
    if sub:
        (agents_out / "subagent.json").write_text(
            json.dumps(sub, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def validate_call_level_records(
    records: list[dict[str, Any]],
    assistant_count: int | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    if not records:
        issues.append(Issue("FAIL", "EMPTY", "call-level 无记录"))
        return issues

    issues.append(Issue("PASS", "COUNT", f"记录数 {len(records)}"))
    for i, rec in enumerate(records):
        prefix = f"L{i+1}"
        for key in ("session_id", "request_id", "timestamp", "thinking_effort", "request", "response"):
            if key not in rec or rec[key] in (None, ""):
                issues.append(Issue("FAIL", f"{prefix}_MISSING_{key}", f"缺少 {key}"))
        effort = rec.get("thinking_effort")
        if effort not in VALID_EFFORTS:
            issues.append(Issue("FAIL", f"{prefix}_EFFORT", f"thinking_effort 非法：{effort!r}"))
        ts = rec.get("timestamp") or ""
        if isinstance(ts, str) and ts and "T" not in ts:
            issues.append(Issue("WARN", f"{prefix}_TS", f"timestamp 非 ISO8601 形态：{ts!r}"))

        req = rec.get("request")
        if isinstance(req, dict):
            if "url" in req:
                issues.append(Issue("FAIL", f"{prefix}_TRACE_URL", "禁止 claude-trace request.url"))
            if "body" in req and "messages" not in req:
                issues.append(Issue("FAIL", f"{prefix}_NESTED_BODY", "request 仍含 body 包装，须提升为 request.*"))
            if not str(req.get("model") or "").strip():
                issues.append(Issue("FAIL", f"{prefix}_MODEL", "request.model 缺失"))
            system = req.get("system")
            if not isinstance(system, list):
                issues.append(Issue("FAIL", f"{prefix}_SYSTEM", "request.system 须为 content blocks 列表"))
            elif not system:
                issues.append(Issue("FAIL", f"{prefix}_SYSTEM_EMPTY", "request.system 为空"))
            else:
                has_text = False
                for b in system:
                    if isinstance(b, dict) and str(b.get("text") or "").strip():
                        has_text = True
                        break
                    if isinstance(b, str) and b.strip():
                        has_text = True
                        break
                if not has_text:
                    issues.append(Issue("FAIL", f"{prefix}_SYSTEM_TEXT", "request.system 无实质 text 内容"))
            tools = req.get("tools")
            if not isinstance(tools, list) or not tools:
                issues.append(Issue("FAIL", f"{prefix}_TOOLS", "request.tools 须为非空列表"))
            else:
                for ti, tool in enumerate(tools):
                    if not isinstance(tool, dict):
                        issues.append(Issue("FAIL", f"{prefix}_TOOL_{ti}", "tool 非对象"))
                        continue
                    if not tool.get("name") or not tool.get("description"):
                        issues.append(Issue("FAIL", f"{prefix}_TOOL_{ti}", "tool 缺 name/description"))
                    if not isinstance(tool.get("input_schema"), dict):
                        issues.append(Issue("FAIL", f"{prefix}_TOOL_{ti}_SCHEMA", "tool 缺 input_schema 对象"))
            if not isinstance(req.get("messages"), list):
                issues.append(Issue("FAIL", f"{prefix}_MESSAGES", "request.messages 须为列表"))
            # thinking_effort 须能在 request 中找到来源（甲方：客户端实际档位，禁止 silently default）
            oc = req.get("output_config") if isinstance(req.get("output_config"), dict) else {}
            effort_src = oc.get("effort") if isinstance(oc, dict) else None
            if effort_src not in VALID_EFFORTS and effort in VALID_EFFORTS:
                issues.append(
                    Issue(
                        "FAIL",
                        f"{prefix}_EFFORT_SOURCE",
                        "thinking_effort 非来自 request.output_config.effort（禁止缺省硬填 high）",
                    )
                )
        else:
            issues.append(Issue("FAIL", f"{prefix}_REQUEST", "request 非对象"))

        resp = rec.get("response")
        if isinstance(resp, dict):
            if "status_code" in resp or "body_raw" in resp:
                issues.append(Issue("FAIL", f"{prefix}_TRACE_RESP", "禁止 status_code/body_raw 形态"))
            rd = resp.get("response_data")
            if not isinstance(rd, dict):
                issues.append(Issue("FAIL", f"{prefix}_RD", "缺少 response.response_data"))
            else:
                role = rd.get("role")
                if role is not None and role != "assistant":
                    issues.append(Issue("FAIL", f"{prefix}_ROLE", f"response_data.role 须为 assistant，当前={role!r}"))
                content = rd.get("content")
                if not isinstance(content, list) or not content:
                    issues.append(Issue("FAIL", f"{prefix}_CONTENT", "response_data.content 须非空列表"))
                else:
                    # 众包预检：须有 type=thinking 块；signature 非空（thinking 正文可为空）
                    thinking_blocks = [
                        b
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "thinking"
                    ]
                    if not thinking_blocks:
                        issues.append(
                            Issue(
                                "FAIL",
                                f"{prefix}_THINKING",
                                "response_data.content 须含至少一块 type=thinking",
                            )
                        )
                    else:
                        for ti, tb in enumerate(thinking_blocks):
                            sig = tb.get("signature")
                            if not isinstance(sig, str) or not sig.strip():
                                issues.append(
                                    Issue(
                                        "FAIL",
                                        f"{prefix}_THINKING_SIG_{ti}",
                                        "thinking.signature 不得为空（thinking 文本可空，signature 必填非空）",
                                    )
                                )
                stop = rd.get("stop_reason")
                if stop not in VALID_STOP:
                    issues.append(Issue("FAIL", f"{prefix}_STOP", f"stop_reason 非法或空：{stop!r}"))
        else:
            issues.append(Issue("FAIL", f"{prefix}_RESPONSE", "response 非对象"))

    if assistant_count is not None and assistant_count > 0:
        delta = abs(len(records) - assistant_count)
        if delta > max(2, assistant_count // 3):
            issues.append(
                Issue(
                    "WARN",
                    "ASSISTANT_DELTA",
                    f"call-level 条数({len(records)}) 与 session assistant({assistant_count}) 偏差较大",
                )
            )
    fails = sum(1 for x in issues if x.level == "FAIL")
    if fails == 0:
        issues.append(Issue("PASS", "SCHEMA", "字段校验通过（交付规范 §7 摘要）"))
        issues.append(Issue("PASS", "CLIENT_CALL_LEVEL", "满足甲方 call-level 字段检测标准"))
    else:
        issues.append(
            Issue(
                "FAIL",
                "CLIENT_CALL_LEVEL",
                f"未通过甲方 call-level 字段检测（FAIL={fails}）",
            )
        )
    return issues


def validate_call_level_file(path: Path, assistant_count: int | None = None) -> list[Issue]:
    if not path.is_file():
        return [Issue("FAIL", "FILE", f"不存在：{path}")]
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            return [Issue("FAIL", "JSONL", f"坏行：{e}")]
    return validate_call_level_records(records, assistant_count=assistant_count)


def issues_verdict(issues: list[Issue]) -> str:
    if any(i.level == "FAIL" for i in issues):
        return "VALIDATE_FAIL"
    if any(i.level == "WARN" for i in issues):
        return "VALIDATE_WARN"
    return "VALIDATE_PASS"


def main_session_jsonl_files(model_dir: Path) -> list[Path]:
    """Top-level session files only (exclude call_level)."""
    found: list[Path] = []
    if not model_dir.is_dir():
        return found
    for p in sorted(model_dir.glob("*.jsonl")):
        if p.name in AUX_JSONL_NAMES:
            continue
        found.append(p)
    # Prefer session.jsonl first
    found.sort(key=lambda p: (0 if p.name in MAIN_SESSION_NAMES else 1, p.name))
    return found


@dataclass
class ResolvedPaths:
    """Paths resolved from session-root + gateway-root + session-id.

    Claude Code 原生布局（常见）：
      <session_root>/<sessionId>.jsonl          # 主 Agent
      <session_root>/<sessionId>/               # 有 subagent 时的同名单目录
        subagents/*.jsonl
        或 *.jsonl

    Gateway（local-cc）布局：
      <gateway_root>/<sessionId>/*.json         # 该 session 的全部 API call
    """

    session_id: str
    session_root: Path
    gateway_root: Path
    main_session: Path | None
    subagent_jsonls: list[Path]
    gateway_dir: Path | None
    issues: list[Issue] = field(default_factory=list)

    def has_fatal(self) -> bool:
        return any(i.level == "FAIL" for i in self.issues)


def resolve_by_session_id(
    session_root: Path,
    gateway_root: Path,
    session_id: str,
) -> ResolvedPaths:
    """From the two roots + Session ID, find main/sub session files and Gateway call dir."""
    sid = (session_id or "").strip()
    root = session_root.expanduser().resolve()
    gw_root = gateway_root.expanduser().resolve()
    issues: list[Issue] = []
    sub_files: list[Path] = []
    main: Path | None = None

    if not sid:
        issues.append(Issue("FAIL", "SID_EMPTY", "session_id 为空"))
        return ResolvedPaths(sid, root, gw_root, None, [], None, issues)

    if not root.is_dir():
        issues.append(Issue("FAIL", "SESSION_ROOT", f"session 根目录不存在：{root}"))
    if not gw_root.is_dir():
        issues.append(Issue("FAIL", "GATEWAY_ROOT", f"Gateway 根目录不存在：{gw_root}"))

    # Main: <sid>.jsonl preferred; also allow bare <sid> file without suffix (rare)
    cand_main = [
        root / f"{sid}.jsonl",
        root / f"{sid}.json",
        root / sid if (root / sid).is_file() else None,
    ]
    for p in cand_main:
        if p is not None and p.is_file():
            main = p
            break
    if main is None:
        issues.append(
            Issue(
                "FAIL",
                "MAIN_SESSION",
                f"未找到主会话文件：{root / (sid + '.jsonl')}（Claude Code 主 session 与 Session ID 同名）",
            )
        )
    else:
        issues.append(Issue("PASS", "MAIN_SESSION", f"主会话：{main}"))

    # Same-name folder: subagents / sidechains
    sid_dir = root / sid
    if sid_dir.is_dir():
        issues.append(Issue("PASS", "SESSION_DIR", f"存在同名 session 目录（常含 subagent）：{sid_dir}"))
        sub_root = sid_dir / "subagents"
        search_roots = [sub_root] if sub_root.is_dir() else []
        search_roots.append(sid_dir)
        seen: set[Path] = set()
        for d in search_roots:
            if not d.is_dir():
                continue
            for p in sorted(d.rglob("*.jsonl")):
                if p in seen:
                    continue
                if main is not None and p.resolve() == main.resolve():
                    continue
                seen.add(p)
                sub_files.append(p)
        if sub_files:
            issues.append(
                Issue("PASS", "SUBAGENT_FILES", f"subagent 轨迹 {len(sub_files)} 个：" + ", ".join(p.name for p in sub_files))
            )
        else:
            issues.append(Issue("PASS", "SUBAGENT_NONE", "同名目录下未见 subagent .jsonl"))
    else:
        issues.append(Issue("PASS", "SESSION_DIR_ABSENT", "无同名 session 目录（无 subagent 时正常）"))

    # Gateway: root/<sid>/  or root is already the session folder
    gw_dir: Path | None = None
    cand_gw = [
        gw_root / sid,
        gw_root if gw_root.name == sid else None,
    ]
    for p in cand_gw:
        if p is not None and p.is_dir() and list(p.glob("*.json")):
            gw_dir = p
            break
    if gw_dir is None and (gw_root / sid).is_dir():
        gw_dir = gw_root / sid  # empty dir still — load will FAIL
    if gw_dir is None:
        issues.append(
            Issue(
                "FAIL",
                "GATEWAY_SESSION_DIR",
                f"未找到 Gateway 会话目录：{gw_root / sid}（文件夹名须 = Session ID）",
            )
        )
    else:
        n = len(list(gw_dir.glob("*.json")))
        issues.append(Issue("PASS", "GATEWAY_SESSION_DIR", f"Gateway 会话目录：{gw_dir}（{n} 个 *.json call）"))

    return ResolvedPaths(
        session_id=sid,
        session_root=root,
        gateway_root=gw_root,
        main_session=main,
        subagent_jsonls=sub_files,
        gateway_dir=gw_dir,
        issues=issues,
    )


def full_merge(
    session_path: Path,
    gateway_dir: Path,
    out_path: Path | None = None,
    agents_out: Path | None = None,
    snapshot_out: Path | None = None,
    model: str = "",
    subagent_jsonls: list[Path] | None = None,
    subagent_out_dir: Path | None = None,
    expected_session_id: str = "",
) -> tuple[list[dict[str, Any]], MergeReport]:
    assistants, sid, sess_issues = load_session_assistants(session_path)
    gw_calls, report = load_gateway_dir(gateway_dir)
    for iss in sess_issues:
        report.issues.append(iss)
    report.assistant_turns = len(assistants)

    if expected_session_id:
        exp = expected_session_id.strip()
        if sid and exp and sid != exp:
            report.add("FAIL", "SID_JSONL", f"主会话内 sessionId「{sid}」与参数 session-id「{exp}」不一致")
        if not sid:
            sid = exp
        # Gateway folder name
        if gateway_dir.name and gateway_dir.name != exp and gateway_dir.name not in (
            "traces",
            "projects",
            "cc-gateway-log",  # 交卷包内固定目录名，不以目录名当 sid
        ):
            if gw_calls and any(c.session_id == exp for c in gw_calls):
                pass
            elif gateway_dir.name != exp:
                report.add(
                    "WARN",
                    "GW_DIR_NAME",
                    f"Gateway 目录名「{gateway_dir.name}」与 session-id「{exp}」不同，已按目录内 sessionId 校验",
                )

    if not gw_calls or not assistants:
        if not any(i.level == "FAIL" for i in report.issues):
            report.add("FAIL", "INPUT", "session 或 gateway 数据不足，无法合并")
        return [], report

    # Main agent chain only for primary call_level
    main_gw = [c for c in gw_calls if not _is_subagent_request(c.request)]
    use_gw = main_gw if main_gw else gw_calls
    records = merge_calls(use_gw, assistants, sid, report)
    if out_path and records:
        write_jsonl(out_path, records)
        report.add("PASS", "WRITE_JSONL", f"写出主 call-level：{out_path}")

    # Subagent jsonl → optional separate call_level using subagent-flagged gateway calls
    sub_files = list(subagent_jsonls or [])
    sub_gw = [c for c in gw_calls if _is_subagent_request(c.request)]
    if sub_files:
        report.add("PASS", "SUBAGENT_INPUT", f"主会话侧 subagent 文件 {len(sub_files)} 个")
    if sub_gw:
        report.add("PASS", "SUBAGENT_GW", f"Gateway 中 subagent call {len(sub_gw)} 条")
    if sub_files and sub_gw and subagent_out_dir:
        subagent_out_dir.mkdir(parents=True, exist_ok=True)
        for sfile in sub_files:
            s_ass, s_sid, s_iss = load_session_assistants(sfile)
            for iss in s_iss:
                if iss.level != "PASS":
                    report.issues.append(
                        Issue(iss.level, f"SUB_{iss.code}", f"{sfile.name}: {iss.message}")
                    )
            if not s_ass:
                continue
            sub_report = MergeReport(session_id=s_sid or sid)
            sub_recs = merge_calls(sub_gw, s_ass, s_sid or sid, sub_report)
            for iss in sub_report.issues:
                if iss.code.startswith("MERGE") or iss.level != "PASS":
                    report.issues.append(
                        Issue(iss.level, f"SUB_{iss.code}", f"{sfile.name}: {iss.message}")
                    )
            if sub_recs:
                out_sub = subagent_out_dir / f"{sfile.stem}_call_level.jsonl"
                write_jsonl(out_sub, sub_recs)
                report.add("PASS", "WRITE_SUB_JSONL", f"写出 subagent call-level：{out_sub}")
    elif sub_files and not sub_gw:
        report.add(
            "WARN",
            "SUBAGENT_NO_GW",
            "有 subagent session 文件，但 Gateway 未标出 is_subagent call；subagent 未单独合成",
        )

    agents_payload = build_agents_payload(gw_calls)
    # Prefer first subagent jsonl capture existence for noting
    if agents_payload and sub_files and "subagent" not in agents_payload:
        report.add(
            "WARN",
            "SUBAGENT_AGENT_CFG",
            "有 subagent 轨迹文件，但 Gateway tools 抓包未分出 subagent system；仅写 main_agent.json",
        )
    if agents_out and agents_payload:
        write_agents(agents_out, agents_payload)
        report.add("PASS", "WRITE_AGENTS", f"写出 agents → {agents_out}")
    elif agents_out and not agents_payload:
        report.add("WARN", "AGENTS_SKIP", "无法从 Gateway 提取 system/tools，未写 agents/")

    if snapshot_out and agents_payload:
        snap = build_snapshot(gw_calls, model=model)
        if snap:
            snapshot_out.parent.mkdir(parents=True, exist_ok=True)
            snapshot_out.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report.add("PASS", "WRITE_SNAPSHOT", f"写出 {snapshot_out}")

    v_issues = validate_call_level_records(records, assistant_count=len(assistants))
    for iss in v_issues:
        report.issues.append(iss)
    return records, report


def full_merge_by_session_id(
    session_root: Path,
    gateway_root: Path,
    session_id: str,
    out_path: Path | None = None,
    agents_out: Path | None = None,
    snapshot_out: Path | None = None,
    model: str = "",
    subagent_out_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], MergeReport, ResolvedPaths]:
    """Primary API: two roots + Session ID (preferred user-facing entry)."""
    resolved = resolve_by_session_id(session_root, gateway_root, session_id)
    report = MergeReport(session_id=session_id.strip())
    for iss in resolved.issues:
        report.issues.append(iss)
    if resolved.has_fatal() or not resolved.main_session or not resolved.gateway_dir:
        return [], report, resolved

    # Default subagent output next to main out
    sub_out = subagent_out_dir
    if sub_out is None and out_path is not None and resolved.subagent_jsonls:
        sub_out = out_path.parent / "subagents"

    records, merge_report = full_merge(
        session_path=resolved.main_session,
        gateway_dir=resolved.gateway_dir,
        out_path=out_path,
        agents_out=agents_out,
        snapshot_out=snapshot_out,
        model=model,
        subagent_jsonls=resolved.subagent_jsonls,
        subagent_out_dir=sub_out,
        expected_session_id=session_id,
    )
    # prepend resolve issues already in report; merge_report has merge issues
    # Prefer merge_report but keep resolve PASS/FAIL at front
    seen = {(i.level, i.code, i.message) for i in merge_report.issues}
    for iss in report.issues:
        key = (iss.level, iss.code, iss.message)
        if key not in seen:
            merge_report.issues.insert(0, iss)
            seen.add(key)
    merge_report.session_id = merge_report.session_id or session_id
    return records, merge_report, resolved


PACKAGE_SESSION_DIR = "session"
PACKAGE_GATEWAY_DIR = "cc-gateway-log"
PACKAGE_MODEL_ALIASES = {
    "claude-opus-4.8": ("claude-opus-4-8", "claude-opus-4.8"),
    "claude-opus-4-8": ("claude-opus-4-8", "claude-opus-4.8"),
}
REQUIRED_TRAJ_MODELS = ("claude-opus-4.8", "qwen-3.7-max", "glm-5.2")


def package_traj_root(package: Path) -> Path:
    return package.expanduser().resolve() / "trajectories"


def discover_package_model_dirs(package: Path) -> list[Path]:
    """Return model trajectory dirs present under package/trajectories/ (v1.1 names)."""
    traj = package_traj_root(package)
    if not traj.is_dir():
        return []
    present = {p.name: p for p in traj.iterdir() if p.is_dir()}
    out: list[Path] = []
    seen: set[Path] = set()
    for model in REQUIRED_TRAJ_MODELS:
        aliases = PACKAGE_MODEL_ALIASES.get(model, (model,))
        for a in aliases:
            if a in present:
                d = present[a]
                if d not in seen:
                    out.append(d)
                    seen.add(d)
                break
    return out


def resolve_package_model(model_dir: Path) -> ResolvedPaths:
    """Resolve merge inputs from 交卷包 trajectories/<model>/ 布局.

    trajectories/<model>/
      session/session.jsonl       # 或 <sid>.jsonl
      session/subagents/*.jsonl   # 可选
      cc-gateway-log/*.json       # 本场抓包
    """
    model_dir = model_dir.expanduser().resolve()
    session_dir = model_dir / PACKAGE_SESSION_DIR
    gw_dir = model_dir / PACKAGE_GATEWAY_DIR
    issues: list[Issue] = []
    sub_files: list[Path] = []
    main: Path | None = None
    sid = ""

    if not model_dir.is_dir():
        issues.append(Issue("FAIL", "MODEL_DIR", f"模型轨迹目录不存在：{model_dir}"))
        return ResolvedPaths("", model_dir, model_dir, None, [], None, issues)

    if not session_dir.is_dir():
        issues.append(
            Issue(
                "FAIL",
                "PKG_SESSION_DIR",
                f"缺少 {model_dir.name}/{PACKAGE_SESSION_DIR}/（须放主会话 .jsonl）",
            )
        )
    else:
        issues.append(Issue("PASS", "PKG_SESSION_DIR", f"存在 {session_dir}"))

    if not gw_dir.is_dir():
        issues.append(
            Issue(
                "FAIL",
                "PKG_GATEWAY_DIR",
                f"缺少 {model_dir.name}/{PACKAGE_GATEWAY_DIR}/（须放 cc-gateway 抓包 *.json）",
            )
        )
    else:
        n = len(list(gw_dir.glob("*.json")))
        if n == 0:
            issues.append(
                Issue("FAIL", "PKG_GATEWAY_EMPTY", f"{PACKAGE_GATEWAY_DIR}/ 下无 *.json：{gw_dir}")
            )
        else:
            issues.append(
                Issue("PASS", "PKG_GATEWAY_DIR", f"存在 {gw_dir}（{n} 个 *.json）")
            )

    if session_dir.is_dir():
        mains = main_session_jsonl_files(session_dir)
        if not mains:
            issues.append(
                Issue(
                    "FAIL",
                    "MAIN_SESSION",
                    f"{PACKAGE_SESSION_DIR}/ 下未找到主会话 .jsonl：{session_dir}",
                )
            )
        else:
            main = mains[0]
            issues.append(Issue("PASS", "MAIN_SESSION", f"主会话：{main}"))
            if len(mains) > 1:
                issues.append(
                    Issue(
                        "WARN",
                        "MULTI_MAIN",
                        f"{PACKAGE_SESSION_DIR}/ 有多条顶层 .jsonl，仅用 {main.name}",
                    )
                )
            # peek sessionId
            _, sid, sid_issues = load_session_assistants(main)
            for iss in sid_issues:
                if iss.code == "SESSION_ID_MISSING":
                    issues.append(iss)
                # ignore assistant-related fail for resolve-only; full_merge re-reads
            for p in sorted((session_dir / "subagents").glob("*.jsonl")) if (session_dir / "subagents").is_dir() else []:
                sub_files.append(p)
            if sub_files:
                issues.append(
                    Issue("PASS", "SUBAGENT_FILES", f"session/subagents 共 {len(sub_files)} 个文件")
                )

    return ResolvedPaths(
        session_id=sid,
        session_root=session_dir if session_dir.is_dir() else model_dir,
        gateway_root=gw_dir if gw_dir.is_dir() else model_dir,
        main_session=main,
        subagent_jsonls=sub_files,
        gateway_dir=gw_dir if gw_dir.is_dir() else None,
        issues=issues,
    )


def full_merge_package_model(
    model_dir: Path,
    out_path: Path | None = None,
    agents_out: Path | None = None,
    snapshot_out: Path | None = None,
    model: str = "",
    subagent_out_dir: Path | None = None,
    *,
    write_into_package: bool = False,
) -> tuple[list[dict[str, Any]], MergeReport, ResolvedPaths]:
    """交卷包内单模型合并：只读 session/ + cc-gateway-log/，不回源本机 projects。

    默认不把产物写进用户包（须显式提供 out_path，或 write_into_package=True 时才写
    model_dir/call_level.jsonl）。
    """
    resolved = resolve_package_model(model_dir)
    report = MergeReport(session_id=resolved.session_id)
    for iss in resolved.issues:
        report.issues.append(iss)
    if resolved.has_fatal() or not resolved.main_session or not resolved.gateway_dir:
        return [], report, resolved

    model_dir = model_dir.expanduser().resolve()
    if out_path is None:
        if write_into_package:
            out_path = model_dir / "call_level.jsonl"
        else:
            out_path = None  # in-memory only unless caller sets path

    if subagent_out_dir is None and write_into_package and resolved.subagent_jsonls:
        subagent_out_dir = model_dir / "subagents_call_level"
    elif not write_into_package and subagent_out_dir is None:
        # keep subagent merge off-package unless out_path parent exists and caller set subagent dir
        subagent_out_dir = None

    records, merge_report = full_merge(
        session_path=resolved.main_session,
        gateway_dir=resolved.gateway_dir,
        out_path=out_path,
        agents_out=agents_out,
        snapshot_out=snapshot_out,
        model=model or model_dir.name,
        subagent_jsonls=resolved.subagent_jsonls if write_into_package or subagent_out_dir else resolved.subagent_jsonls,
        subagent_out_dir=subagent_out_dir,
        expected_session_id=resolved.session_id,
    )
    seen = {(i.level, i.code, i.message) for i in merge_report.issues}
    for iss in report.issues:
        key = (iss.level, iss.code, iss.message)
        if key not in seen:
            merge_report.issues.insert(0, iss)
            seen.add(key)
    merge_report.session_id = merge_report.session_id or resolved.session_id
    return records, merge_report, resolved


def full_merge_package(
    package: Path,
    models: list[str] | None = None,
    write_agents: bool = False,
    *,
    out_root: Path | None = None,
    write_into_package: bool = False,
) -> list[tuple[str, list[dict[str, Any]], MergeReport, ResolvedPaths, Path | None]]:
    """合并数据包 trajectories 下全部（或选定）模型。

    默认产物写到 out_root（临时目录）；write_into_package=True 时才写包内 call_level.jsonl。
    默认不写 package/agents/。

    Returns list of (model_dir_name, records, report, resolved, out_path|None).
    """
    package = package.expanduser().resolve()
    traj = package_traj_root(package)
    results: list[tuple[str, list[dict[str, Any]], MergeReport, ResolvedPaths, Path | None]] = []
    if not traj.is_dir():
        rep = MergeReport()
        rep.add("FAIL", "TRAJ_ROOT", f"数据包缺少 trajectories/：{package}")
        dummy = ResolvedPaths("", package, package, None, [], None, list(rep.issues))
        results.append(("", [], rep, dummy, None))
        return results

    model_dirs = discover_package_model_dirs(package)
    if models:
        wanted: set[str] = set()
        for m in models:
            wanted.update(PACKAGE_MODEL_ALIASES.get(m, (m,)))
            wanted.add(m)
        model_dirs = [d for d in model_dirs if d.name in wanted]
        if not model_dirs:
            for m in models:
                p = traj / m
                if p.is_dir():
                    model_dirs.append(p)

    agents_out = package / "agents" if write_agents and write_into_package else None
    if write_agents and out_root is not None and not write_into_package:
        agents_out = out_root / "agents"

    for i, md in enumerate(model_dirs):
        if write_into_package:
            out: Path | None = md / "call_level.jsonl"
            sub_out = md / "subagents_call_level" if (md / "session" / "subagents").is_dir() else None
        elif out_root is not None:
            safe = md.name.replace("/", "_")
            out = out_root / safe / "call_level.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            sub_out = out_root / safe / "subagents_call_level"
        else:
            out = None
            sub_out = None
        ao = agents_out if write_agents and i == 0 else None
        recs, rep, resolved = full_merge_package_model(
            model_dir=md,
            out_path=out,
            agents_out=ao,
            model=md.name,
            subagent_out_dir=sub_out,
            write_into_package=write_into_package,
        )
        results.append((md.name, recs, rep, resolved, out))
    if not model_dirs:
        rep = MergeReport()
        rep.add("FAIL", "NO_MODELS", f"trajectories/ 下未找到 opus/qwen/glm 模型目录：{traj}")
        dummy = ResolvedPaths("", traj, traj, None, [], None, list(rep.issues))
        results.append(("", [], rep, dummy, None))
    return results
