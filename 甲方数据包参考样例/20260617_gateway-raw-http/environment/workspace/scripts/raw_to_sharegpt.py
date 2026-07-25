#!/usr/bin/env python3
"""Convert raw HTTP trace JSONL to ShareGPT format.

Reads the raw upstream HTTP request/response log produced by
``gateway.raw_http_log`` and outputs a ShareGPT-compatible JSONL file
(one JSON record per line).

Usage::

    python scripts/raw_to_sharegpt.py INPUT.jsonl -o OUTPUT.sharegpt.jsonl
    python scripts/raw_to_sharegpt.py INPUT.jsonl -o out/ --subagent-mode split

ShareGPT record schema::

    {"conversations": [
        {"from": "human", "value": "<user message>"},
        {"from": "gpt",   "value": "<assistant reply>"},
        ...
    ]}

When ``--subagent-mode split`` is given, sub-agent conversations are
written to separate files named ``{stem}-subid_{n}.sharegpt.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_entries(input_path: Path) -> list[dict[str, Any]]:
    """Load raw HTTP log entries from a JSONL or JSON-array file."""
    text = input_path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    # Try JSON array first (hand-crafted fixtures often use this format).
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass

    # Fall back to JSONL (one JSON object per line).
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort entries by timestamp (chronological order)."""
    return sorted(entries, key=lambda e: e.get("timestamp", ""))


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def pair_entries(
    entries: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Group consecutive request → response entries into pairs."""
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    pending_req: dict[str, Any] | None = None

    for entry in sort_entries(entries):
        direction = entry.get("direction")
        if direction == "request":
            pending_req = entry
        elif direction == "response" and pending_req is not None:
            pairs.append((pending_req, entry))
            pending_req = None

    return pairs


# ---------------------------------------------------------------------------
# Conversation extraction
# ---------------------------------------------------------------------------


def _extract_messages(body: Any) -> list[dict[str, str]]:
    """Pull the ``messages`` list out of a request body (dict or str)."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(body, dict):
        return []
    msgs = body.get("messages", [])
    return [m for m in msgs if isinstance(m, dict)]


def _extract_assistant_reply(response_body: Any) -> str | None:
    """Return the assistant's reply text from a chat-completions response."""
    if isinstance(response_body, str):
        try:
            response_body = json.loads(response_body)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(response_body, dict):
        return None

    # OpenAI-style: choices[0].message.content
    choices = response_body.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content:
            return str(content)

    # Anthropic-style: content[0].text
    content_list = response_body.get("content")
    if isinstance(content_list, list):
        for block in content_list:
            if isinstance(block, dict) and block.get("type") == "text":
                return str(block.get("text", ""))

    return None


def build_conversation(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[dict[str, str]]:
    """Build a single ordered conversation from all request/response pairs.

    Uses the *last* request's ``messages`` array as the base (it
    contains the full history up to that point) and appends the
    assistant's reply from the *last* response.  Earlier pairs serve
    as a fallback when the final request is missing messages.
    """
    if not pairs:
        return []

    conversation: list[dict[str, str]] = []

    # Use the last pair's request messages as the base.
    last_req, last_resp = pairs[-1]
    messages = _extract_messages(last_req.get("body"))

    if not messages and len(pairs) > 1:
        # Fallback: aggregate from all pairs.
        for req, _ in pairs:
            messages = _extract_messages(req.get("body"))
            if messages:
                break

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            conversation.append({"from": "human", "value": str(content)})
        elif role == "assistant":
            conversation.append({"from": "gpt", "value": str(content)})
        elif role == "system":
            conversation.append({"from": "system", "value": str(content)})

    # Append the assistant's reply from the last response if it's not
    # already the tail of the conversation.
    reply = _extract_assistant_reply(last_resp.get("body"))
    if reply and (not conversation or conversation[-1].get("value") != reply):
        conversation.append({"from": "gpt", "value": reply})

    return conversation


# ---------------------------------------------------------------------------
# Sub-agent detection
# ---------------------------------------------------------------------------

_SUBAGENT_RE = re.compile(r"sub[_-]?agent[_-]?(\d+)", re.IGNORECASE)


def _detect_subagent(entry: dict[str, Any]) -> int | None:
    """Return a sub-agent index if the entry belongs to one, else *None*."""
    # Check headers for sub-agent markers.
    headers = entry.get("headers", {})
    for key, value in headers.items():
        if "sub" in key.lower():
            m = _SUBAGENT_RE.search(str(value))
            if m:
                return int(m.group(1))

    # Check messages in the request body.
    body = entry.get("body", {})
    if isinstance(body, dict):
        for msg in body.get("messages", []):
            if isinstance(msg, dict):
                content = str(msg.get("content", ""))
                m = _SUBAGENT_RE.search(content)
                if m:
                    return int(m.group(1))
    return None


def detect_subagents(entries: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Group entries that belong to detected sub-agents."""
    groups: dict[int, list[dict[str, Any]]] = {}
    for entry in entries:
        idx = _detect_subagent(entry)
        if idx is not None:
            groups.setdefault(idx, []).append(entry)
    return groups


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert raw HTTP trace JSONL to ShareGPT format.",
    )
    parser.add_argument("input", help="Path to input raw HTTP JSONL file")
    parser.add_argument(
        "-o", "--output", required=True, help="Path to output ShareGPT file"
    )
    parser.add_argument(
        "--subagent-mode",
        choices=["split", "merge"],
        default="merge",
        help="How to handle sub-agent traces (default: merge)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    entries = load_entries(input_path)
    if not entries:
        print(f"No entries found in {input_path}", file=sys.stderr)
        sys.exit(1)

    if args.subagent_mode == "split":
        subagents = detect_subagents(entries)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write main trace (entries not belonging to any sub-agent).
        main_entries = [e for e in entries if _detect_subagent(e) is None]
        if main_entries:
            pairs = pair_entries(main_entries)
            conv = build_conversation(pairs)
            if conv:
                record = {"conversations": conv}
                with output_path.open("w", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Write per-subagent files: {stem}-subid_{n}.sharegpt.jsonl
        stem = output_path.stem.replace(".sharegpt", "")
        for idx, sub_entries in sorted(subagents.items()):
            sub_out = output_path.parent / f"{stem}-subid_{idx}{output_path.suffix}"
            pairs = pair_entries(sub_entries)
            conv = build_conversation(pairs)
            if conv:
                record = {"conversations": conv}
                with sub_out.open("w", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    else:
        # Merge mode: single output file with the full conversation.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pairs = pair_entries(entries)
        conv = build_conversation(pairs)
        if conv:
            record = {"conversations": conv}
            with output_path.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
