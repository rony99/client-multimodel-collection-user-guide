#!/usr/bin/env python3
"""Convert raw HTTP JSON logs to ShareGPT JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _pair_request_response(records: list[dict[str, Any]]) -> list[tuple[dict, dict]]:
    sorted_records = sorted(records, key=lambda r: r.get("timestamp", ""))
    pairs: list[tuple[dict, dict]] = []
    pending: dict[str, Any] | None = None
    for rec in sorted_records:
        direction = rec.get("direction")
        if direction == "request":
            pending = rec
        elif direction == "response" and pending is not None:
            pairs.append((pending, rec))
            pending = None
    return pairs


def _extract_user_text(request_body: dict[str, Any]) -> str | None:
    messages = request_body.get("messages") or []
    user_parts = [m.get("content", "") for m in messages if m.get("role") == "user"]
    if not user_parts:
        return None
    last = user_parts[-1]
    return last if isinstance(last, str) else str(last)


def _extract_assistant_text(response_body: dict[str, Any]) -> str | None:
    choices = response_body.get("choices") or []
    if not choices:
        return None
    message = choices[0].get("message") or {}
    content = message.get("content")
    if content is None:
        return None
    return content if isinstance(content, str) else str(content)


def records_to_conversations(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    conversations: list[dict[str, str]] = []
    for req, resp in _pair_request_response(records):
        req_body = req.get("body") or {}
        resp_body = resp.get("body") or {}
        if not isinstance(req_body, dict):
            req_body = {}
        if not isinstance(resp_body, dict):
            resp_body = {}

        user_text = _extract_user_text(req_body)
        if user_text:
            conversations.append({"from": "human", "value": user_text})

        assistant_text = _extract_assistant_text(resp_body)
        if assistant_text:
            conversations.append({"from": "gpt", "value": assistant_text})
    return conversations


def convert_file(input_path: Path) -> dict[str, Any]:
    records = _load_records(input_path)
    return {"conversations": records_to_conversations(records)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert raw HTTP logs to ShareGPT JSONL")
    parser.add_argument("input", type=Path, help="Raw HTTP log file (JSON array or JSONL)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output ShareGPT JSONL path")
    parser.add_argument(
        "--subagent-mode",
        choices=["split", "merge"],
        default="merge",
        help="Optional subagent trace split (writes main output at minimum)",
    )
    args = parser.parse_args()

    record = convert_file(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.subagent_mode == "split" and args.output.parent.is_dir():
        # v1: main trace only; subagent files use {session_id}-subid_{n} when present in input.
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
