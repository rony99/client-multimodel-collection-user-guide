#!/usr/bin/env python3
"""Validate 甲方 call-level JSONL against 交付规范 §7 field checklist."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from call_level_lib import (  # noqa: E402
    issues_verdict,
    load_session_assistants,
    validate_call_level_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 call-level.jsonl 字段")
    parser.add_argument("--call-level", type=Path, required=True, help="call_level.jsonl 路径")
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help="可选：对照 session.jsonl assistant 轮次（偏差过大 WARN）",
    )
    parser.add_argument("--json", type=Path, default=None, help="写出校验结果 JSON")
    parser.add_argument("--markdown", action="store_true", help="Markdown 输出")
    args = parser.parse_args()

    call_path = args.call_level.expanduser().resolve()
    assistant_count = None
    if args.session:
        turns, _, _ = load_session_assistants(args.session.expanduser().resolve())
        assistant_count = len(turns)

    issues = validate_call_level_file(call_path, assistant_count=assistant_count)
    verdict = issues_verdict(issues)
    summary = {
        "FAIL": sum(1 for i in issues if i.level == "FAIL"),
        "WARN": sum(1 for i in issues if i.level == "WARN"),
        "PASS": sum(1 for i in issues if i.level == "PASS"),
    }
    payload = {
        "call_level": str(call_path),
        "verdict": verdict,
        "summary": summary,
        "issues": [{"level": i.level, "code": i.code, "message": i.message} for i in issues],
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.markdown or not args.json:
        print("# call-level 校验报告")
        print()
        print(f"- 文件：`{call_path}`")
        print(f"- 结论：**{verdict}**")
        print(f"- 统计：FAIL={summary['FAIL']} / WARN={summary['WARN']} / PASS={summary['PASS']}")
        print()
        print("## 明细")
        print()
        for i in issues:
            print(f"- **{i.level}** `{i.code}` — {i.message}")
    else:
        print(json.dumps({"verdict": verdict, "summary": summary}, ensure_ascii=False))

    return 0 if verdict != "VALIDATE_FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
