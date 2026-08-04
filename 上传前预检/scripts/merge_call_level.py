#!/usr/bin/env python3
"""Merge Claude session + Gateway captures → 甲方 call-level JSONL.

Preferred inputs (用户只给两个根目录 + Session ID):
  --session-root   Claude 原生 projects 目录（其下 <sid>.jsonl 与可选同名文件夹）
  --gateway-root   Gateway 根目录（其下 <sid>/*.json）
  --session-id     两边同名的 Session ID

Legacy direct paths still work: --session + --gateway-dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from call_level_lib import (  # noqa: E402
    full_merge,
    full_merge_by_session_id,
    issues_verdict,
    write_jsonl,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="用 Claude 原生 session + Gateway 抓包合并为甲方 call-level JSONL"
    )
    # Preferred API
    parser.add_argument(
        "--session-root",
        type=Path,
        default=None,
        help="Claude 原生 session 根目录（含 <sessionId>.jsonl 与可选同名 subagent 目录）",
    )
    parser.add_argument(
        "--gateway-root",
        type=Path,
        default=None,
        help="Gateway 日志根目录（默认 local-cc: ~/.claude_lproxy/projects，其下 <sessionId>/）",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session ID（与 main jsonl 文件名、同名文件夹、Gateway 子目录名一致）",
    )
    # Legacy / direct
    parser.add_argument("--session", type=Path, default=None, help="（兼容）直接指定主 session.jsonl")
    parser.add_argument(
        "--gateway-dir",
        type=Path,
        default=None,
        help="（兼容）直接指定某 session 的 Gateway 目录",
    )
    parser.add_argument("--out", type=Path, required=True, help="输出主 call_level.jsonl")
    parser.add_argument("--agents-out", type=Path, default=None, help="写出 agents/ 目录（main_agent.json）")
    parser.add_argument(
        "--snapshot-out",
        type=Path,
        default=None,
        help="写出 agent_config_snapshot.json",
    )
    parser.add_argument(
        "--subagent-out-dir",
        type=Path,
        default=None,
        help="有 subagent 时写出各子 call_level 的目录（默认 out 旁 subagents/）",
    )
    parser.add_argument("--model", type=str, default="", help="可选 model_id（写入 snapshot）")
    parser.add_argument("--report", type=Path, default=None, help="写出 merge_report.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="合并后校验 call-level 字段；失败退出码 1",
    )
    args = parser.parse_args()

    out = args.out.expanduser().resolve()
    agents = args.agents_out.expanduser().resolve() if args.agents_out else None
    snap = args.snapshot_out.expanduser().resolve() if args.snapshot_out else None
    sub_out = args.subagent_out_dir.expanduser().resolve() if args.subagent_out_dir else None

    use_id_api = args.session_root is not None or args.gateway_root is not None or args.session_id
    if use_id_api:
        missing = []
        if not args.session_root:
            missing.append("--session-root")
        if not args.gateway_root:
            missing.append("--gateway-root")
        if not args.session_id:
            missing.append("--session-id")
        if missing:
            print(
                f"ERROR: 使用根目录模式时必须同时提供：{', '.join(missing)}",
                file=sys.stderr,
            )
            print(
                "  例：--session-root ~/.claude/projects/<enc> "
                "--gateway-root ~/.claude_lproxy/projects "
                "--session-id <uuid>",
                file=sys.stderr,
            )
            return 2
        records, report, resolved = full_merge_by_session_id(
            session_root=args.session_root,
            gateway_root=args.gateway_root,
            session_id=args.session_id,
            out_path=out,
            agents_out=agents,
            snapshot_out=snap,
            model=args.model,
            subagent_out_dir=sub_out,
        )
        print("# merge_call_level（session-root + gateway-root + session-id）")
        print(f"- session-root: {resolved.session_root}")
        print(f"- gateway-root: {resolved.gateway_root}")
        print(f"- session-id: {resolved.session_id}")
        print(f"- main session: {resolved.main_session}")
        print(f"- subagent files: {len(resolved.subagent_jsonls)}")
        for p in resolved.subagent_jsonls:
            print(f"    - {p}")
        print(f"- gateway session dir: {resolved.gateway_dir}")
    else:
        if not args.session or not args.gateway_dir:
            print(
                "ERROR: 请使用 --session-root + --gateway-root + --session-id，"
                "或兼容模式 --session + --gateway-dir",
                file=sys.stderr,
            )
            return 2
        session = args.session.expanduser().resolve()
        gw = args.gateway_dir.expanduser().resolve()
        records, report = full_merge(
            session_path=session,
            gateway_dir=gw,
            out_path=out,
            agents_out=agents,
            snapshot_out=snap,
            model=args.model,
            subagent_out_dir=sub_out,
        )
        print("# merge_call_level（直接路径兼容）")
        print(f"- session: {session}")
        print(f"- gateway: {gw}")

    if records and not out.is_file():
        write_jsonl(out, records)

    if args.report:
        report_path = args.report.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    issues = report.issues
    fails = sum(1 for i in issues if i.level == "FAIL")
    warns = sum(1 for i in issues if i.level == "WARN")
    print(f"- out: {out}")
    print(f"- records: {len(records)}")
    print(f"- FAIL={fails} WARN={warns}")
    for i in issues:
        print(f"  - [{i.level}] {i.code}: {i.message}")

    if args.check:
        verdict = issues_verdict(issues)
        client_ok = verdict != "VALIDATE_FAIL" and fails == 0 and len(records) > 0
        print(f"- check: {verdict}")
        print(f"- 甲方 call-level 字段检测: {'PASS' if client_ok else 'FAIL'}")
        if not client_ok:
            print("  （空日志/无 tools 主 call/缺 effort/字段不合规 → 不满足甲方 call-level）")
        return 0 if client_ok else 1

    return 0 if records and fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
