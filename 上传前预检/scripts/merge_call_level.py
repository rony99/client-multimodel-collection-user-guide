#!/usr/bin/env python3
"""Merge Claude session + Gateway captures → 甲方 call-level JSONL.

优先：交卷数据包内 trajectories/<模型>/session/ + cc-gateway-log/
  --package <task_dir> [--model <name>] [--check]

兼容（本机原生日志 / 调试）：
  --session-root + --gateway-root + --session-id
  或 --session + --gateway-dir
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
    full_merge_package,
    full_merge_package_model,
    issues_verdict,
    write_jsonl,
)


def _print_issues(issues) -> tuple[int, int]:
    fails = sum(1 for i in issues if i.level == "FAIL")
    warns = sum(1 for i in issues if i.level == "WARN")
    for i in issues:
        print(f"  - [{i.level}] {i.code}: {i.message}")
    return fails, warns


def _check_result(records, issues) -> int:
    fails = sum(1 for i in issues if i.level == "FAIL")
    verdict = issues_verdict(issues)
    client_ok = verdict != "VALIDATE_FAIL" and fails == 0 and len(records) > 0
    print(f"- check: {verdict}")
    print(f"- 甲方 call-level 字段检测: {'PASS' if client_ok else 'FAIL'}")
    if not client_ok:
        print("  （缺 session/gateway、ID 不一致、无 tools、缺 effort 等 → FAIL）")
    return 0 if client_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="用数据包内 session/ + cc-gateway-log/ 合并为甲方 call-level（优先）"
    )
    # Preferred: package
    parser.add_argument(
        "--package",
        "--task-dir",
        dest="package",
        type=Path,
        default=None,
        help="甲方原格式数据包目录（含 trajectories/<模型>/session 与 cc-gateway-log）",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="仅合并指定模型目录名（可重复）；默认合并包内三模型",
    )
    parser.add_argument(
        "--no-agents",
        action="store_true",
        help="数据包模式不写 package/agents/",
    )
    # Compat: native roots
    parser.add_argument(
        "--session-root",
        type=Path,
        default=None,
        help="（兼容）本机 Claude 原生 session 根目录",
    )
    parser.add_argument(
        "--gateway-root",
        type=Path,
        default=None,
        help="（兼容）本机 Gateway 根目录（~/.claude_lproxy/projects）",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="（兼容）与原生布局同名的 Session ID",
    )
    parser.add_argument("--session", type=Path, default=None, help="（兼容）直接指定主 session.jsonl")
    parser.add_argument(
        "--gateway-dir",
        type=Path,
        default=None,
        help="（兼容）直接指定 Gateway / cc-gateway-log 目录",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出 call_level.jsonl；--package 默认写各模型目录下 call_level.jsonl",
    )
    parser.add_argument("--agents-out", type=Path, default=None, help="写出 agents/ 目录")
    parser.add_argument("--snapshot-out", type=Path, default=None, help="写出 snapshot")
    parser.add_argument("--subagent-out-dir", type=Path, default=None, help="subagent call_level 输出目录")
    parser.add_argument("--report", type=Path, default=None, help="写出 merge_report.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="合并后校验 call-level 字段；失败退出码 1",
    )
    args = parser.parse_args()

    # --- Package mode (preferred) ---
    if args.package is not None:
        package = args.package.expanduser().resolve()
        models = args.model
        print("# merge_call_level（数据包 trajectories 内 session/ + cc-gateway-log/）")
        print(f"- package: {package}")

        if models and len(models) == 1:
            # single model: allow --out override
            traj = package / "trajectories"
            name = models[0]
            model_dir = traj / name
            if not model_dir.is_dir():
                # opus alias
                for alt in ("claude-opus-4-8", "claude-opus-4.8"):
                    if name in (alt, "claude-opus-4.8", "opus") and (traj / alt).is_dir():
                        model_dir = traj / alt
                        break
            out = args.out.expanduser().resolve() if args.out else model_dir / "call_level.jsonl"
            agents = (
                None
                if args.no_agents
                else (args.agents_out.expanduser().resolve() if args.agents_out else package / "agents")
            )
            records, report, resolved = full_merge_package_model(
                model_dir=model_dir,
                out_path=out,
                agents_out=agents,
                snapshot_out=args.snapshot_out.expanduser().resolve() if args.snapshot_out else None,
                model=model_dir.name if model_dir.is_dir() else name,
                subagent_out_dir=args.subagent_out_dir.expanduser().resolve() if args.subagent_out_dir else None,
            )
            print(f"- model: {model_dir}")
            print(f"- main session: {resolved.main_session}")
            print(f"- gateway log: {resolved.gateway_dir}")
            print(f"- session-id (from package session): {resolved.session_id or '(unknown)'}")
            print(f"- out: {out}")
            print(f"- records: {len(records)}")
            fails, warns = _print_issues(report.issues)
            print(f"- FAIL={fails} WARN={warns}")
            if args.report:
                rp = args.report.expanduser().resolve()
                rp.parent.mkdir(parents=True, exist_ok=True)
                rp.write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            if args.check:
                return _check_result(records, report.issues)
            return 0 if records and fails == 0 else 1

        results = full_merge_package(
            package=package,
            models=models,
            write_agents=not args.no_agents,
        )
        any_fail = False
        all_ok_check = True
        for name, records, report, resolved, out in results:
            print(f"\n## model: {name or '(none)'}")
            print(f"- main session: {resolved.main_session}")
            print(f"- gateway log: {resolved.gateway_dir}")
            print(f"- session-id (from package session): {resolved.session_id or '(unknown)'}")
            print(f"- out: {out}")
            print(f"- records: {len(records)}")
            fails, warns = _print_issues(report.issues)
            print(f"- FAIL={fails} WARN={warns}")
            if fails or not records:
                any_fail = True
            if args.check:
                code = _check_result(records, report.issues)
                if code != 0:
                    all_ok_check = False
        if args.report and results:
            # last model's report + index
            rp = args.report.expanduser().resolve()
            rp.parent.mkdir(parents=True, exist_ok=True)
            summary = {
                "package": str(package),
                "models": [
                    {
                        "name": n,
                        "out": str(o),
                        "records": len(r),
                        "session_id": rep.session_id,
                        "fail": sum(1 for i in rep.issues if i.level == "FAIL"),
                        "issues": [{"level": i.level, "code": i.code, "message": i.message} for i in rep.issues],
                    }
                    for n, r, rep, _, o in results
                ],
            }
            rp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.check:
            return 0 if all_ok_check and not any_fail else 1
        return 1 if any_fail else 0

    # --- Legacy root + sid ---
    use_id_api = args.session_root is not None or args.gateway_root is not None or args.session_id
    if use_id_api:
        missing = [x for x, v in [
            ("--session-root", args.session_root),
            ("--gateway-root", args.gateway_root),
            ("--session-id", args.session_id),
        ] if not v]
        if missing:
            print(f"ERROR: 兼容模式须同时提供：{', '.join(missing)}", file=sys.stderr)
            return 2
        if not args.out:
            print("ERROR: 兼容模式需要 --out", file=sys.stderr)
            return 2
        out = args.out.expanduser().resolve()
        agents = args.agents_out.expanduser().resolve() if args.agents_out else None
        records, report, resolved = full_merge_by_session_id(
            session_root=args.session_root,
            gateway_root=args.gateway_root,
            session_id=args.session_id,
            out_path=out,
            agents_out=agents,
            snapshot_out=args.snapshot_out.expanduser().resolve() if args.snapshot_out else None,
            model=args.model[0] if args.model else "",
            subagent_out_dir=args.subagent_out_dir.expanduser().resolve() if args.subagent_out_dir else None,
        )
        print("# merge_call_level（兼容：本机 session-root + gateway-root + session-id）")
        print(f"- main session: {resolved.main_session}")
        print(f"- gateway: {resolved.gateway_dir}")
        print(f"- out: {out}")
        print(f"- records: {len(records)}")
        fails, _ = _print_issues(report.issues)
        if args.check:
            return _check_result(records, report.issues)
        return 0 if records and fails == 0 else 1

    # --- Direct paths ---
    if args.session and args.gateway_dir:
        if not args.out:
            print("ERROR: --session/--gateway-dir 模式需要 --out", file=sys.stderr)
            return 2
        session = args.session.expanduser().resolve()
        gw = args.gateway_dir.expanduser().resolve()
        out = args.out.expanduser().resolve()
        records, report = full_merge(
            session_path=session,
            gateway_dir=gw,
            out_path=out,
            agents_out=args.agents_out.expanduser().resolve() if args.agents_out else None,
            snapshot_out=args.snapshot_out.expanduser().resolve() if args.snapshot_out else None,
            model=args.model[0] if args.model else "",
            subagent_out_dir=args.subagent_out_dir.expanduser().resolve() if args.subagent_out_dir else None,
        )
        if records and not out.is_file():
            write_jsonl(out, records)
        print("# merge_call_level（兼容：直接路径）")
        print(f"- session: {session}")
        print(f"- gateway: {gw}")
        print(f"- out: {out}")
        print(f"- records: {len(records)}")
        fails, _ = _print_issues(report.issues)
        if args.check:
            return _check_result(records, report.issues)
        return 0 if records and fails == 0 else 1

    print(
        "ERROR: 请使用数据包模式：\n"
        "  python3 merge_call_level.py --package <任务包> --check\n"
        "或单模型：\n"
        "  python3 merge_call_level.py --package <任务包> --model claude-opus-4-8 --check\n"
        "（兼容：--session-root+--gateway-root+--session-id / --session+--gateway-dir）",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
