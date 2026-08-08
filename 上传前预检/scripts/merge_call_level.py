#!/usr/bin/env python3
"""Merge Claude session + Gateway captures → 甲方 call-level JSONL，再做字段校验。

正式预检（推荐）：
  只读包内 trajectories/<模型>/session/ + cc-gateway-log/
  合并结果只写入**系统临时目录**（或显式 --scratch-dir，且不得落在数据包内）。
  **禁止**对用户数据包做任何写入（无写回 call_level / agents）。

  python3 merge_call_level.py --package <task_dir> --check

兼容（本机原生日志 / 调试）：
  --session-root + --gateway-root + --session-id
  或 --session + --gateway-dir
  输出也勿指向用户数据包目录。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from call_level_lib import (  # noqa: E402
    full_merge,
    full_merge_by_session_id,
    full_merge_package,
    full_merge_package_model,
    path_is_within,
    validate_call_level_records,
    write_jsonl,
)


def _refuse_write_into_package(package: Path, *targets: Path | None) -> int | None:
    """若任一写路径落在数据包内，打印错误并返回 2；否则 None。"""
    package = package.expanduser().resolve()
    for t in targets:
        if t is None:
            continue
        p = t.expanduser().resolve()
        if path_is_within(p, package):
            print(
                f"ERROR: 预检 skill 禁止对用户数据包写入：{p}\n"
                f"  数据包：{package}\n"
                f"  请改用临时目录（默认 mkdtemp，或 --scratch-dir 在包外）。",
                file=sys.stderr,
            )
            return 2
    return None


def _print_issues(issues) -> tuple[int, int]:
    fails = sum(1 for i in issues if i.level == "FAIL")
    warns = sum(1 for i in issues if i.level == "WARN")
    for i in issues:
        text = i.display() if hasattr(i, "display") else i.message
        print(f"  - [{i.level}] {i.code}: {text}")
    return fails, warns


def _check_result(records, issues) -> int:
    """Validate merged call-level records against 甲方 schema."""
    v_issues = validate_call_level_records(records)
    fail_msgs = []
    for i in issues:
        if i.level == "FAIL":
            fail_msgs.append(i)
    for i in v_issues:
        if i.level == "FAIL":
            if not any(x.code == i.code and x.message == i.message for x in fail_msgs):
                fail_msgs.append(i)
    client_ok = len(records) > 0 and not fail_msgs
    print(f"- check: {'VALIDATE_PASS' if client_ok else 'VALIDATE_FAIL'}")
    print(f"- 甲方 call-level（合并后）: {'PASS' if client_ok else 'FAIL'}")
    if not client_ok:
        print(
            "  （须 session+gateway 合并成功；system/tools/effort；"
            "有 thinking 时 Opus 才强制 signature 非空，GLM/千问不强制；"
            "无 thinking 块不查 sig）"
        )
    for i in v_issues:
        if i.code in ("COUNT", "SCHEMA", "CLIENT_CALL_LEVEL") or i.level == "FAIL":
            text = i.display() if hasattr(i, "display") else i.message
            print(f"  - [{i.level}] {i.code}: {text}")
    for i in issues:
        if i.level == "FAIL" and not any(
            x.code == i.code and x.message == i.message for x in v_issues if x.level == "FAIL"
        ):
            text = i.display() if hasattr(i, "display") else i.message
            print(f"  - [{i.level}] {i.code}: {text}")
    return 0 if client_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="包内 session/ + cc-gateway-log/ → 临时 call-level → 甲方字段校验"
    )
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
        "--write-into-package",
        action="store_true",
        help=argparse.SUPPRESS,  # 已禁用；见下文硬拒绝
    )
    parser.add_argument(
        "--write-agents",
        action="store_true",
        help="（可选）在临时目录写出 agents/；禁止指向用户包内",
    )
    parser.add_argument(
        "--scratch-dir",
        type=Path,
        default=None,
        help="合并产物根目录（必须在数据包外）；默认 mkdtemp",
    )
    # Compat: native roots
    parser.add_argument("--session-root", type=Path, default=None, help="（兼容调试）")
    parser.add_argument("--gateway-root", type=Path, default=None, help="（兼容调试）")
    parser.add_argument("--session-id", type=str, default=None, help="（兼容调试）")
    parser.add_argument("--session", type=Path, default=None, help="（兼容）session.jsonl")
    parser.add_argument("--gateway-dir", type=Path, default=None, help="（兼容）gateway 目录")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="单模型/兼容模式输出路径（须在数据包外）；包模式优先用 --scratch-dir",
    )
    parser.add_argument("--agents-out", type=Path, default=None, help="写出 agents/ 目录（包外）")
    parser.add_argument("--snapshot-out", type=Path, default=None, help="写出 snapshot（包外）")
    parser.add_argument("--subagent-out-dir", type=Path, default=None, help="subagent call_level 输出目录（包外）")
    parser.add_argument("--report", type=Path, default=None, help="写出 merge_report.json（包外）")
    parser.add_argument(
        "--check",
        action="store_true",
        help="对**合并后的** call-level 做甲方字段校验；失败退出码 1",
    )
    # legacy alias: --no-agents ignored (default already no agents)
    parser.add_argument("--no-agents", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    # --- Package mode (preferred) ---
    if args.package is not None:
        package = args.package.expanduser().resolve()
        if args.write_into_package:
            print(
                "ERROR: --write-into-package 已禁用。预检 skill 禁止对用户数据包做任何写入。",
                file=sys.stderr,
            )
            return 2
        models = args.model
        if args.scratch_dir is not None:
            scratch = args.scratch_dir.expanduser().resolve()
            bad = _refuse_write_into_package(package, scratch)
            if bad is not None:
                return bad
            scratch.mkdir(parents=True, exist_ok=True)
        else:
            scratch = Path(tempfile.mkdtemp(prefix="cc-calllevel-merge-"))
        print("# merge_call_level（包内 session/ + cc-gateway-log → 临时合并后校验）")
        print(f"- package: {package}（只读，禁止写入）")
        print(f"- scratch（临时产物，在包外）: {scratch}")

        if models and len(models) == 1:
            traj = package / "trajectories"
            name = models[0]
            model_dir = traj / name
            if not model_dir.is_dir():
                for alt in ("claude-opus-4-8", "claude-opus-4.8"):
                    if name in (alt, "claude-opus-4.8", "opus") and (traj / alt).is_dir():
                        model_dir = traj / alt
                        break
            safe = model_dir.name if model_dir.is_dir() else name
            out = (
                args.out.expanduser().resolve()
                if args.out
                else scratch / safe / "call_level.jsonl"
            )
            agents = (
                args.agents_out.expanduser().resolve()
                if args.agents_out
                else (scratch / "agents" if args.write_agents else None)
            )
            snap = args.snapshot_out.expanduser().resolve() if args.snapshot_out else None
            sub_out = (
                args.subagent_out_dir.expanduser().resolve()
                if args.subagent_out_dir
                else (scratch / safe / "subagents_call_level")
            )
            rp = args.report.expanduser().resolve() if args.report else None
            bad = _refuse_write_into_package(package, out, agents, snap, sub_out, rp)
            if bad is not None:
                return bad
            out.parent.mkdir(parents=True, exist_ok=True)
            records, report, resolved = full_merge_package_model(
                model_dir=model_dir,
                out_path=out,
                agents_out=agents,
                snapshot_out=snap,
                model=model_dir.name if model_dir.is_dir() else name,
                subagent_out_dir=sub_out,
                write_into_package=False,
            )
            # ensure temp write even if full_merge deferred without path
            if records and out and not out.is_file():
                write_jsonl(out, records)
            print(f"- model: {model_dir}")
            print(f"- 包内 session: {resolved.main_session}")
            print(f"- 包内 gateway: {resolved.gateway_dir}")
            print(f"- session-id: {resolved.session_id or '(unknown)'}")
            print(f"- merged call-level: {out}")
            print(f"- records: {len(records)}")
            fails, warns = _print_issues(report.issues)
            print(f"- merge FAIL={fails} WARN={warns}")
            if rp is not None:
                rp.parent.mkdir(parents=True, exist_ok=True)
                rp.write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            if args.check:
                return _check_result(records, report.issues)
            return 0 if records and fails == 0 else 1

        if args.out or args.agents_out or args.snapshot_out or args.subagent_out_dir:
            bad = _refuse_write_into_package(
                package,
                args.out.expanduser().resolve() if args.out else None,
                args.agents_out.expanduser().resolve() if args.agents_out else None,
                args.snapshot_out.expanduser().resolve() if args.snapshot_out else None,
                args.subagent_out_dir.expanduser().resolve() if args.subagent_out_dir else None,
            )
            if bad is not None:
                return bad
        rp = args.report.expanduser().resolve() if args.report else None
        bad = _refuse_write_into_package(package, rp)
        if bad is not None:
            return bad

        results = full_merge_package(
            package=package,
            models=models,
            write_agents=bool(args.write_agents),
            out_root=scratch,
            write_into_package=False,
        )
        any_fail = False
        all_ok_check = True
        for name, records, report, resolved, out in results:
            print(f"\n## model: {name or '(none)'}")
            print(f"- 包内 session: {resolved.main_session}")
            print(f"- 包内 gateway: {resolved.gateway_dir}")
            print(f"- session-id: {resolved.session_id or '(unknown)'}")
            print(f"- merged call-level: {out or '(memory only)'}")
            print(f"- records: {len(records)}")
            fails, warns = _print_issues(report.issues)
            print(f"- merge FAIL={fails} WARN={warns}")
            if fails or not records:
                any_fail = True
            if args.check:
                code = _check_result(records, report.issues)
                if code != 0:
                    all_ok_check = False
        if rp is not None and results:
            rp.parent.mkdir(parents=True, exist_ok=True)
            summary = {
                "package": str(package),
                "scratch": str(scratch),
                "write_into_package": False,
                "package_readonly": True,
                "models": [
                    {
                        "name": n,
                        "out": str(o) if o else None,
                        "records": len(r),
                        "session_id": rep.session_id,
                        "fail": sum(1 for i in rep.issues if i.level == "FAIL"),
                        "issues": [
                            {"level": i.level, "code": i.code, "message": i.message}
                            for i in rep.issues
                        ],
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
        missing = [
            x
            for x, v in [
                ("--session-root", args.session_root),
                ("--gateway-root", args.gateway_root),
                ("--session-id", args.session_id),
            ]
            if not v
        ]
        if missing:
            print(f"ERROR: 兼容模式须同时提供：{', '.join(missing)}", file=sys.stderr)
            return 2
        if not args.out:
            scratch = Path(tempfile.mkdtemp(prefix="cc-calllevel-merge-"))
            out = scratch / "call_level.jsonl"
            print(f"- scratch: {scratch}")
        else:
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
            scratch = Path(tempfile.mkdtemp(prefix="cc-calllevel-merge-"))
            out = scratch / "call_level.jsonl"
            print(f"- scratch: {scratch}")
        else:
            out = args.out.expanduser().resolve()
        session = args.session.expanduser().resolve()
        gw = args.gateway_dir.expanduser().resolve()
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
        "ERROR: 正式预检请使用：\n"
        "  python3 merge_call_level.py --package <任务包> --check\n"
        "  （只读数据包；合并产物仅写系统临时目录）\n"
        "单模型：\n"
        "  python3 merge_call_level.py --package <任务包> --model claude-opus-4-8 --check\n",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
