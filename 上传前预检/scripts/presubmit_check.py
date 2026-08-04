#!/usr/bin/env python3
"""上传前结构预检（众包用户包）。不验证集合过题比例。

交卷根目录（或直接指向）甲方原格式数据包：
  <task_id>/  — instruction / tests / trajectories（每模型 1 条）等
不再要求平级 multi-sessions/ 或同题 pass@4。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RUBRIC_TYPES = {"code_generation", "bug_fix", "code_qa", "refactor"}
REQUIRED_MODELS = ("claude-opus-4.8", "qwen-3.7-max", "glm-5.2")
ALT_OPUS = ("claude-opus-4-8", "claude-opus-4.8")

SESSIONS_DIR_NAMES = ("multi-sessions", "multi_sessions", "model_sessions")
PACKAGE_DIR_ALIASES = ("package", "task_package", "harbor_package")

SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{8,}"
)

DISCLAIMER = (
    "本检查只做**结构预检**（文件是否存在、字段是否齐全、结构是否合理），"
    "**不查集合过题比例**，**不代表结算或最终合格**。"
    "请自行核验：题量要求≥3；**每题千问均挂**；禁三模型全过、Opus≤60%、Opus−千问>20%、GLM≥1 道过等；"
    "平台不代提供模型 API；"
    "**最终以甲方实际审核为准**。"
)


@dataclass
class Finding:
    level: str  # PASS | WARN | FAIL
    code: str
    message: str


@dataclass
class Layout:
    root: Path
    package: Path | None
    sessions: Path | None


@dataclass
class Report:
    task_dir: str
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    verdict: str = "UNKNOWN"
    disclaimer: str = DISCLAIMER
    package_dir: str = ""
    sessions_dir: str = ""

    def add(self, level: str, code: str, message: str) -> None:
        self.findings.append(Finding(level=level, code=code, message=message))

    def finalize(self) -> None:
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for f in self.findings:
            counts[f.level] = counts.get(f.level, 0) + 1
        self.summary = counts
        if counts.get("FAIL", 0):
            self.verdict = "PRECHECK_FAIL"
        elif counts.get("WARN", 0):
            self.verdict = "PRECHECK_WARN"
        else:
            self.verdict = "PRECHECK_PASS"


def _pick_named_subdir(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        p = root / name
        if p.is_dir():
            return p
    return None


def _looks_like_package(d: Path) -> bool:
    return (d / "instruction.md").is_file() and (d / "tests" / "test.sh").is_file()


def _looks_like_sessions(d: Path) -> bool:
    if not d.is_dir():
        return False
    if d.name in SESSIONS_DIR_NAMES:
        return True
    names = {p.name for p in d.iterdir() if p.is_dir()}
    has_opus = bool(names & set(ALT_OPUS))
    has_qwen = "qwen-3.7-max" in names
    has_glm = "glm-5.2" in names
    return has_opus or has_qwen or has_glm


def resolve_layout(root: Path) -> Layout:
    # Case: --task-dir 直接指向甲方数据包
    if _looks_like_package(root):
        for name in SESSIONS_DIR_NAMES:
            sibling = root.parent / name
            if sibling.is_dir():
                return Layout(root=root.parent, package=root, sessions=sibling)
        return Layout(root=root.parent, package=root, sessions=None)

    sess = _pick_named_subdir(root, SESSIONS_DIR_NAMES)
    pkg = _pick_named_subdir(root, PACKAGE_DIR_ALIASES)

    kids = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if pkg is None:
        pkg_cands = [
            p
            for p in kids
            if _looks_like_package(p) and p.name not in SESSIONS_DIR_NAMES and p.name != "模板"
        ]
        if len(pkg_cands) == 1:
            pkg = pkg_cands[0]
        elif len(pkg_cands) > 1:
            # 优先非 multi-sessions
            pkg = pkg_cands[0]
    if sess is None:
        sess_cands = [p for p in kids if _looks_like_sessions(p)]
        if len(sess_cands) == 1:
            sess = sess_cands[0]

    if pkg is not None and sess is not None and pkg.resolve() == sess.resolve():
        sess = None

    return Layout(root=root, package=pkg, sessions=sess)


def check_layout(layout: Layout, report: Report) -> bool:
    """校验甲方数据包存在；勿交 multi-sessions 等旁路多 run 目录。"""
    if layout.package is None:
        report.add(
            "FAIL",
            "LAYOUT_PACKAGE",
            "缺失甲方原格式数据包目录（须含 instruction.md + tests/test.sh）",
        )
    else:
        report.add(
            "PASS",
            "LAYOUT_PACKAGE",
            f"甲方数据包：{layout.package.name}/（原格式）",
        )
        report.package_dir = str(layout.package)

    if layout.sessions is not None:
        report.add(
            "WARN",
            "LAYOUT_SESSIONS",
            f"检测到旁路 {layout.sessions.name}/：正式勿交；仅保留 trajectories/ 下每模型 1 条",
        )

    return layout.package is not None


def check_dirname(package: Path, report: Report) -> None:
    name = package.name
    if re.fullmatch(r"[A-Za-z0-9._-]+", name):
        report.add("PASS", "DIR_NAME", f"甲方数据包目录名合法：{name}")
    else:
        report.add("FAIL", "DIR_NAME", f"数据包目录名含非法字符（仅允许字母数字._-）：{name}")


def check_core_files(package: Path, report: Report) -> None:
    required = [
        ("instruction.md", "INSTRUCTION"),
        ("task.toml", "TASK_TOML"),
        ("meta.json", "META"),
        ("environment/Dockerfile", "DOCKERFILE"),
        ("environment/workspace", "WORKSPACE"),
        ("tests/test.sh", "TEST_SH"),
        ("rubrics/global_rubric.yaml", "GLOBAL_RUBRIC"),
        ("rubrics/task_rubric.yaml", "TASK_RUBRIC"),
    ]
    for rel, code in required:
        p = package / rel
        if p.exists():
            report.add("PASS", code, f"存在：{rel}")
        else:
            report.add("FAIL", code, f"缺失：{rel}")

    for rel, code in [
        ("README.md", "README"),
        ("tests/test_outputs.py", "TEST_OUTPUTS"),
        ("environment/workspace.tar.gz", "WORKSPACE_TAR"),
        ("scores/rubric_scores.json", "SCORES"),
    ]:
        p = package / rel
        if p.exists():
            report.add("PASS", code, f"存在：{rel}")
        # 缺可选文件不打 WARN，避免几乎无法 PRECHECK_PASS

    root = package.parent
    if (package / "reports").is_dir() or (root / "reports").is_dir():
        report.add("PASS", "REPORTS", "存在 reports/（package 内或根下）")

    gt = package / "ground_truth"
    solve = package / "solution" / "solve.sh"
    if gt.is_dir() or solve.is_file():
        report.add("PASS", "GT", "存在标准答案（ground_truth/ 和/或 solution/solve.sh）")
    else:
        report.add("FAIL", "GT", "缺失标准答案：需要 ground_truth/ 或 solution/solve.sh")


def check_instruction(package: Path, report: Report) -> None:
    path = package / "instruction.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) < 40:
        report.add("WARN", "INSTRUCTION_SHORT", "instruction.md 过短，请确认任务目标是否写清")
    else:
        report.add("PASS", "INSTRUCTION_LEN", "instruction.md 有实质内容")
    low = text.lower()
    for bad in ("ground_truth", "assert ", "pytest", "test.sh"):
        if bad in low and bad != "test.sh":
            report.add(
                "WARN",
                "INSTRUCTION_LEAK",
                f"instruction.md 可能提及敏感词「{bad}」，请确认未泄测试/答案",
            )
            break
    else:
        report.add("PASS", "INSTRUCTION_LEAK", "instruction.md 未见明显泄题关键词")
    if SECRET_RE.search(text):
        report.add("FAIL", "INSTRUCTION_SECRET", "instruction.md 疑似含密钥/token")


def check_task_toml(package: Path, report: Report) -> None:
    path = package / "task.toml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if SECRET_RE.search(text) or re.search(r"(?i)sk-[a-z0-9]{10,}", text):
        report.add("FAIL", "TOML_SECRET", "task.toml 疑似含真实密钥")
    else:
        report.add("PASS", "TOML_SECRET", "task.toml 未见明显硬编码密钥")


def check_meta(root: Path, package: Path, report: Report) -> None:
    path = package / "meta.json"
    if not path.is_file():
        return
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.add("FAIL", "META_JSON", f"meta.json 不是合法 JSON：{e}")
        return
    if not isinstance(meta, dict):
        report.add("FAIL", "META_JSON", "meta.json 根节点须为对象")
        return

    tid = meta.get("task_id")
    if tid:
        report.add("PASS", "META_TASK_ID", f"task_id = {tid}")
        if str(tid) not in (root.name, package.name):
            report.add(
                "WARN",
                "META_TASK_ID_MISMATCH",
                f"task_id「{tid}」建议与提交根目录名「{root.name}」一致",
            )
    else:
        report.add("FAIL", "META_TASK_ID", "缺少 task_id")

    rtt = meta.get("rubric_task_type") or meta.get("task_type")
    if rtt in RUBRIC_TYPES:
        report.add("PASS", "META_RUBRIC_TYPE", f"rubric_task_type = {rtt}")
    else:
        report.add(
            "FAIL",
            "META_RUBRIC_TYPE",
            f"rubric_task_type 须为四选一 {sorted(RUBRIC_TYPES)}，当前={rtt!r}",
        )

    labels = meta.get("labels") or meta.get("taxonomy") or {}
    if isinstance(labels, dict) and labels.get("code_lang"):
        report.add("PASS", "META_LANG", f"code_lang = {labels.get('code_lang')}")
    else:
        report.add("FAIL", "META_LANG", "缺少 labels.code_lang")

    app = labels.get("application") if isinstance(labels, dict) else None
    if app:
        report.add("PASS", "META_APP", f"application = {app}")
    else:
        report.add("FAIL", "META_APP", "缺少 labels.application")

    one = meta.get("one_liner") or meta.get("one_sentence_summary")
    if one and str(one).strip():
        report.add("PASS", "META_ONELINER", "有 one_liner")
    else:
        report.add("FAIL", "META_ONELINER", "缺少 one_liner / one_sentence_summary")

    if meta.get("difficulty") or meta.get("difficulty_assessment") or meta.get("annotator_background"):
        report.add("PASS", "META_DIFF", "有难度相关字段")
    else:
        report.add("FAIL", "META_DIFF", "缺少 difficulty / annotator_background 等难度评估")

    if "agreement_score" in meta:
        report.add("PASS", "META_AGREE", f"agreement_score = {meta.get('agreement_score')}")
    else:
        report.add("FAIL", "META_AGREE", "缺少 agreement_score")

    tags = meta.get("tags")
    if isinstance(tags, list) and tags:
        report.add("PASS", "META_TAGS", f"tags 共 {len(tags)} 项")
    else:
        report.add("FAIL", "META_TAGS", "缺少 tags（数组）")


def check_rubrics(package: Path, report: Report) -> None:
    for rel, code in [
        ("rubrics/global_rubric.yaml", "GLOBAL_RUBRIC_BODY"),
        ("rubrics/task_rubric.yaml", "TASK_RUBRIC_BODY"),
    ]:
        path = package / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 80:
            report.add("WARN", code, f"{rel} 内容过短")
        elif "correctness" in text or "criteria" in text or "items:" in text:
            report.add("PASS", code, f"{rel} 含评分相关内容")
        else:
            report.add("WARN", code, f"{rel} 请确认各维度要点非空")


def check_workspace_clean(package: Path, report: Report) -> None:
    ws = package / "environment" / "workspace"
    if not ws.is_dir():
        return
    bad = []
    for name in ("node_modules", ".venv", "dist", "build", ".next", "ground_truth"):
        if (ws / name).exists():
            bad.append(name)
    if bad:
        report.add("FAIL", "WS_DIRTY", f"workspace 不应包含：{', '.join(bad)}")
    else:
        report.add("PASS", "WS_DIRTY", "workspace 未见常见污染目录")
    files = [p for p in ws.rglob("*") if p.is_file()]
    if len(files) < 3:
        report.add("WARN", "WS_THIN", f"workspace 文件很少（{len(files)}），请确认是完整 Baseline")
    else:
        report.add("PASS", "WS_SIZE", f"workspace 文件数约 {len(files)}")


# Generated call-level / derived JSONL are not “主会话”
_AUX_TRAJ_JSONL = frozenset({"call_level.jsonl", "calls.jsonl"})


def _find_sessions(model_dir: Path) -> list[Path]:
    """Top-level main Claude session .jsonl only (exclude call_level)."""
    found: list[Path] = []
    if not model_dir.is_dir():
        return found
    for p in sorted(model_dir.glob("*.jsonl")):
        if p.name in _AUX_TRAJ_JSONL:
            continue
        found.append(p)
    # prefer session.jsonl
    found.sort(key=lambda p: (0 if p.name == "session.jsonl" else 1, p.name))
    return found


def check_model_sessions(sessions_root: Path, report: Report) -> None:
    """检查 trajectories/（或兼容传入的 sessions 根）下每模型 1 条轨迹。"""
    if not sessions_root.is_dir():
        report.add("FAIL", "TRAJ_ROOT", f"缺失轨迹目录：{sessions_root}")
        return
    present = {p.name for p in sessions_root.iterdir() if p.is_dir()}
    for model in REQUIRED_MODELS:
        candidates = [model]
        if model == "claude-opus-4.8":
            candidates = list(ALT_OPUS)
        hit = None
        for c in candidates:
            if c in present:
                hit = sessions_root / c
                break
        if hit is None:
            report.add(
                "FAIL",
                f"TRAJ_{model}",
                f"缺少模型目录 {sessions_root.name}/{model}/（opus 也可用 claude-opus-4-8）",
            )
            continue
        report.add("PASS", f"TRAJ_{model}", f"存在模型目录 {sessions_root.name}/{hit.name}")
        sessions = _find_sessions(hit)
        if not sessions:
            report.add("FAIL", f"SESSION_{model}", f"{hit.name}/ 下未找到主 session .jsonl")
            continue
        if len(sessions) == 1:
            report.add(
                "PASS",
                f"SESSION_COUNT_{model}",
                f"{hit.name}/ 含 1 条主轨迹（符合每模型只交 1 条）",
            )
        else:
            report.add(
                "FAIL",
                f"SESSION_COUNT_{model}",
                f"{hit.name}/ 含 {len(sessions)} 条顶层 .jsonl；正式须仅 1 条主会话（subagent 请放 subagents/）",
            )
        main = sessions[0]
        report.add("PASS", f"SESSION_{model}", f"主 session：{sessions_root.name}/{hit.name}/{main.name}")
        try:
            lines = main.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            report.add("WARN", f"SESSION_READ_{model}", f"无法读取 session：{e}")
            continue
        if len(lines) < 5:
            report.add("WARN", f"SESSION_SHORT_{model}", f"{hit.name} session 行数过少（{len(lines)}）")
        assistant = 0
        for line in lines:
            if '"type":"assistant"' in line or '"role":"assistant"' in line:
                assistant += 1
        if assistant >= 20:
            report.add("PASS", f"TURNS_{model}", f"{hit.name} 粗估 assistant 相关行 ≥20（≈{assistant}）")
        elif assistant > 0:
            report.add(
                "WARN",
                f"TURNS_{model}",
                f"{hit.name} 粗估 assistant 信号约 {assistant}（底线建议平均 ≥20）",
            )
        else:
            report.add(
                "WARN",
                f"TURNS_{model}",
                f"{hit.name} 未能从 jsonl 粗估轮次，请人工确认平均 assistant 执行轮次 ≥20",
            )
        call_level = hit / "call_level.jsonl"
        if call_level.is_file():
            report.add(
                "PASS",
                f"CALL_LEVEL_{model}",
                f"{hit.name}/call_level.jsonl 存在（session+Gateway 合并产物；本预检不验字段细节）",
            )
        sub_a = hit / "subagents"
        sub_b = list(hit.glob("*/subagents"))
        if sub_a.is_dir() or sub_b:
            report.add("PASS", f"SUBAGENT_{model}", f"{hit.name} 含 subagent 目录")
        # 无 subagent 不打 WARN（多数跑次无委派）

    for old in ("claude-sonnet-4.6", "glm-5.1"):
        if old in present:
            report.add(
                "WARN",
                "TRAJ_OLD_MODEL",
                f"仍有旧模型目录 {old}；v1.1 正式只需 opus / qwen-3.7-max / glm-5.2",
            )


def check_no_agents_required(package: Path, report: Report) -> None:
    agents = package / "agents"
    if agents.exists():
        main = agents / "main_agent.json"
        if main.is_file():
            report.add(
                "PASS",
                "AGENTS_PRESENT",
                "存在 agents/main_agent.json（可由 session+Gateway 合并写入；用户可不手写）",
            )
        else:
            report.add(
                "WARN",
                "AGENTS_PRESENT",
                "存在 agents/ 但无 main_agent.json；预检不强制，交付甲方时建议齐",
            )
    else:
        report.add("PASS", "AGENTS_OPTIONAL", "未要求用户手写 agents/（可用合并脚本从 Gateway 生成）")


def discover_packages(root: Path) -> list[Path]:
    """发现提交根下全部甲方数据包；若 root 本身是包则只返回它。"""
    if _looks_like_package(root):
        return [root]
    kids = [p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(".")]
    pkgs = [
        p
        for p in kids
        if _looks_like_package(p) and p.name not in SESSIONS_DIR_NAMES and p.name != "模板"
    ]
    return pkgs


def check_one_package(package: Path, root: Path, report: Report) -> None:
    report.add("PASS", "PKG_BEGIN", f"—— 检查数据包：{package.name}/ ——")
    check_dirname(package, report)
    check_core_files(package, report)
    check_instruction(package, report)
    check_task_toml(package, report)
    check_meta(root, package, report)
    check_rubrics(package, report)
    check_workspace_clean(package, report)
    traj = package / "trajectories"
    if traj.is_dir():
        if not report.sessions_dir:
            report.sessions_dir = str(traj)
        check_model_sessions(traj, report)
    else:
        report.add("FAIL", "TRAJ_ROOT", f"{package.name}/ 缺失 trajectories/（每模型正式轨迹各 1 条）")
    check_no_agents_required(package, report)


def run_check(root: Path) -> Report:
    report = Report(task_dir=str(root))
    packages = discover_packages(root)
    sess = None
    if not _looks_like_package(root):
        sess = _pick_named_subdir(root, SESSIONS_DIR_NAMES)
    else:
        for name in SESSIONS_DIR_NAMES:
            sibling = root.parent / name
            if sibling.is_dir():
                sess = sibling
                break

    if not packages:
        report.add(
            "FAIL",
            "LAYOUT_PACKAGE",
            "缺失甲方原格式数据包目录（须含 instruction.md + tests/test.sh）",
        )
        report.finalize()
        return report

    report.add(
        "PASS",
        "LAYOUT_PACKAGE",
        f"发现 {len(packages)} 个甲方数据包：" + ", ".join(p.name for p in packages),
    )
    report.package_dir = ", ".join(str(p) for p in packages)

    if sess is not None:
        report.add(
            "WARN",
            "LAYOUT_SESSIONS",
            f"检测到旁路 {sess.name}/：正式勿交；每题每模型只交 trajectories/ 下 1 条主会话",
        )

    scan_root = root if not _looks_like_package(root) else root.parent
    for package in packages:
        check_one_package(package, scan_root, report)

    report.finalize()
    return report


def format_markdown(report: Report) -> str:
    lines = [
        "# 上传前预检报告",
        "",
        f"- 提交根目录：`{report.task_dir}`",
        f"- 甲方数据包：`{report.package_dir or '（未解析）'}`",
        f"- 轨迹目录：`{report.sessions_dir or '（未解析）'}`",
        f"- 结构预检结论：**{report.verdict}**",
        f"- 统计：FAIL={report.summary.get('FAIL', 0)} / WARN={report.summary.get('WARN', 0)} / PASS={report.summary.get('PASS', 0)}",
        "",
        f"> {report.disclaimer}",
        "",
        "## 明细",
        "",
    ]
    for f in report.findings:
        lines.append(f"- **{f.level}** `{f.code}` — {f.message}")
    lines.extend(
        [
            "",
            "## 结构预检未覆盖（须自行验证；最终以甲方实际审核为准）",
            "",
            "- 集合：题量≥3；**每题千问均挂**；禁三模型全过；Opus 过题率 ≤ 60%；Opus−千问 > 20%；GLM ≥ 1 道过",
            "- 平均 assistant 执行轮次 ≥ 20；私有题意（禁止直接改造公开 GitHub Issue）",
            "- 每模型每题 1 条轨迹；平台不代提供模型 API（用户自备经 Gateway）",
            "- Docker 内 Baseline FAIL / GT PASS 的完整复现（本脚本默认不做 Docker 构建）",
            "- Rubric 人工/LLM 打分是否与测试结论一致",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="众包任务包上传前结构预检（甲方数据包 + trajectories/ 每模型 1 条）"
    )
    parser.add_argument(
        "--task-dir",
        type=Path,
        required=True,
        help="待提交根目录（内含甲方原格式数据包），或直接指向数据包目录",
    )
    parser.add_argument("--json", type=Path, default=None, help="可选：写出 JSON 报告")
    parser.add_argument("--markdown", action="store_true", help="stdout 输出 Markdown")
    args = parser.parse_args()

    task_dir = args.task_dir.expanduser().resolve()
    if not task_dir.is_dir():
        print(f"ERROR: task-dir 不存在或不是目录：{task_dir}", file=sys.stderr)
        return 2

    report = run_check(task_dir)
    payload: dict[str, Any] = {
        "task_dir": report.task_dir,
        "package_dir": report.package_dir,
        "sessions_dir": report.sessions_dir,
        "verdict": report.verdict,
        "summary": report.summary,
        "disclaimer": report.disclaimer,
        "findings": [asdict(f) for f in report.findings],
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.markdown or not args.json:
        print(format_markdown(report))
    else:
        print(json.dumps({"verdict": report.verdict, "summary": report.summary}, ensure_ascii=False))

    return 0 if report.verdict != "PRECHECK_FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
