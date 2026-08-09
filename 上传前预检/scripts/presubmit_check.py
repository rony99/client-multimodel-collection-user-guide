#!/usr/bin/env python3
"""上传前结构预检（众包用户包）。不验证集合过题比例。

交卷根目录（或直接指向）甲方原格式数据包：
  <task_id>/trajectories/<模型>/
    session/           — Claude Code 主会话 .jsonl（及有则 subagents/）
    cc-gateway-log/    — 该次 Session 的 cc-gateway 抓包 *.json
不再要求平级 multi-sessions/ 或同题 pass@4。
"""

from __future__ import annotations

import argparse
import json
import os
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

# Dockerfile 固定版本：禁止 :latest / 无 tag 的 base，以及 install @latest
FROM_LINE_RE = re.compile(
    r"^\s*FROM\s+(?:--\S+\s+)*(?P<img>\S+)",
    re.IGNORECASE | re.MULTILINE,
)
# 行内显式 :latest 或 @latest（镜像 / 包）
EXPLICIT_LATEST_RE = re.compile(
    r"(?i)(?::|@)latest(?:\s|$|[\"'])",
)
# workspace 禁止出现的目录名（含嵌套）
WS_FORBIDDEN_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        "ground_truth",
        "__pycache__",
        ".git",
    }
)
SECRET_EXTRA_RE = re.compile(
    r"(?i)(sk-[a-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9a-zA-Z-]{10,})"
)
INSTRUCTION_LEAK_HARD = (
    "ground_truth",
    "参考答案",
    "hidden test",
    "hidden_test",
)
INSTRUCTION_LEAK_SOFT = (
    "assert ",
    "assert(",
    "pytest",
    "test.sh",
    "unittest",
)
RUBRIC_DIMS = (
    "correctness",
    "code_quality",
    "reasoning",
    "tool_usage",
    "efficiency",
)
MIN_ASSISTANT_TURNS = 20

DISCLAIMER = (
    "本检查覆盖 3bench 平台 packagecheck **静态硬项**（结构/meta/轮次/scores/reports）；"
    "一项 FAIL **不阻断**其余项，一次汇总。"
    "脚本不跑 Docker；**Agent 须按 SKILL 完成 §B call-level、§D 临时拷贝 Docker、§E reports_review"
    "+ instruction_tests_audit（见 SEMANTIC_REVIEW.md）及 §C 集合自检。**"
    "完整跑完并清 FAIL 后，目标是平台预审尽量直过；≠ 甲方终审。"
    "每条 FAIL/WARN：问题/原因/违反/建议 + 下一步。"
)

# 默认「违反」短名（无 per-code 时）
DEFAULT_VIOLATION = "甲方要求说明 + 平台 packagecheck 交付/结构门槛"

# code → (原因略述, 违反短名) 补充说明；message=问题，CODE_SUGGESTIONS=建议
CODE_EXPLAIN: dict[str, tuple[str, str]] = {
    "META_ANNOTATOR": (
        "平台要求标注者背景齐全，用于可追溯与质量审核。",
        "平台 structure：annotator_background.industry/years_experience/role；甲方 §5 meta",
    ),
    "META_COMPLETION_TIME": (
        "完成本题/标注用时须可量化核对。",
        "平台 structure：completion_time_min ∈ (0, 10080] 分钟",
    ),
    "META_AGREE": (
        "根级 agreement_score 须为 [0,1] 真实数字（null/缺省不合格）。",
        "平台 structure：agreement_score 数字 [0,1]",
    ),
    "META_TASK_ID_MISMATCH": (
        "平台用目录名定位任务；与 task_id 不一致会硬挂。",
        "平台 META_TASK_ID_MISMATCH；甲方交付包命名",
    ),
    "ALL_MODELS_PASS": (
        "众包要求本题须拉开区分度，禁止三模型都测通。",
        "平台/甲方众包单题硬门槛",
    ),
    "QWEN_MUST_FAIL": (
        "千问本题过题率目标为 0。",
        "甲方/平台：Qwen 本题 eval_pass 须 false",
    ),
    "BASELINE_MUST_FAIL": (
        "未套 GT 时测试应失败，否则说明空壳测或答案已进 workspace。",
        "甲方：Baseline 须测挂",
    ),
    "GT_MUST_PASS": (
        "标准答案须能使测试全过，否则判题/答案不可验收。",
        "甲方：套用 GT 后须测通",
    ),
    "DOCKER_DAEMON": (
        "无 Docker 则无法验证可复现构建与 test.sh。",
        "甲方 Docker 可构建可验收",
    ),
}

# 平台 SoftWarningDisplay：message + 建议：suggestion。code 默认改法（显式 suggestion 优先）。
CODE_SUGGESTIONS: dict[str, str] = {
    "DOCKER_IMAGE_PIN": (
        "将 Dockerfile 的 FROM 改为固定 tag（如 ubuntu:24.04）或 @sha256:…；禁止 :latest 与无 tag。"
    ),
    "DOCKER_PIP_PIN": (
        "pip 与 -r 文件统一写成 pkg==x.y.z 定死版本；禁止裸名、>=、~=、区间；"
        "缺的 -r 文件放回 environment/ 构建上下文。"
    ),
    "DOCKER_NPM_PIN": "npm 写死 pkg@x.y.z（具体版本号）；禁止裸名与 @latest。",
    "DIR_NAME": "包目录名仅允许字母数字 . _ -（例：my_task_01）。",
    "META_TASK_ID_MISMATCH": "将 zip/包顶层文件夹改名为 meta.task_id，或改 meta.task_id 与目录同名。",
    "META_TASK_ID": "在 meta.json 填写 task_id（与顶层目录名一致）。",
    "META_RUBRIC_TYPE": "rubric_task_type 四选一：code_generation / bug_fix / code_qa / refactor。",
    "META_LANG": "meta.labels.code_lang 填语言（与 Taxonomy 一致）。",
    "META_APP": "meta.labels.application 填应用领域标签。",
    "META_ONELINER": "用 ≥20 字写清本题测什么与为何好；勿用 demo/test/todo 占位。",
    "META_ONELINER_THIN": "用 ≥20 字写清本题测什么、核心难点与为何值得对比评测。",
    "META_DIFF": "补非空 difficulty 字符串，或 difficulty_assessment 档位/文本。",
    "META_ANNOTATOR": (
        "meta.annotator_background = {industry, years_experience≥0 数字, role} 三项齐全。"
    ),
    "META_COMPLETION_TIME": (
        "填 completion_time_min：出题+标注总分钟数，数字且 ∈(0, 10080]；常见约 30–720。"
    ),
    "META_AGREE": "根级 agreement_score 填 0–1 的数字（禁止 null）。",
    "META_AGREE_ZERO": "若非真实零一致度，改填真实 0–1 值；单审可标 single_reviewer。",
    "META_TAGS": "tags 写成非空数组。",
    "META_JSON": "修正 meta.json 为合法 JSON 对象。",
    "META_TIME_OUTLIER": "按真实用时改 completion_time_min，或 difficulty_reason 说明极端值。",
    "BASELINE_MUST_FAIL": "加严 tests 或从 workspace 去掉答案，使未套 GT 时 test 失败。",
    "GT_MUST_PASS": "修 ground_truth/solve，使套答案后 test 全过。",
    "DOCKER_DAEMON": "安装并启动 Docker Desktop，再执行 docker version 确认 Server 可用。",
    "DOCKER_BUILD_BASELINE": "在 environment/ 本地 docker build 按日志修 Dockerfile/钉死依赖。",
    "DOCKER_BUILD_GT": "检查答案是否破坏构建；修文件后再跑。",
    "GT_APPLY": "补 ground_truth 文件树（路径对齐 workspace）或可用 solution/solve.sh。",
    "README": "在包根补 README.md（题意/环境简述）。",
    "INSTRUCTION": "补 instruction.md（三模型同一份题面）。",
    "TASK_TOML": "补 task.toml（勿写真实密钥）。",
    "DOCKERFILE": "补 environment/Dockerfile。",
    "WORKSPACE": "补 environment/workspace/ 完整 Baseline。",
    "TEST_SH": "补 tests/test.sh（须能真实判分，禁 exit 0 空壳）。",
    "TEST_SH_EMPTY": "在 test.sh 写真实 pytest/脚本断言，禁止空文件或仅注释。",
    "TEST_SH_SHELL": "删掉恒通过的 exit 0/true，改成会真实 FAIL/PASS 的验收命令。",
    "TEST_SH_THIN": "增加实质断言/用例行，避免敷衍判分。",
    "GT": "提供 ground_truth/ 文件树和/或 solution/solve.sh，使套 GT 后 test 全过。",
    "GLOBAL_RUBRIC": "补 rubrics/global_rubric.yaml。",
    "TASK_RUBRIC": "补 rubrics/task_rubric.yaml。",
    "TASK_TYPE": "task_rubric.task_type 四选一，与 meta 一致。",
    "CRITERIA": "补 task_specific_criteria，五维均非空数组。",
    "SCORES_FILE": "补 scores/rubric_scores.json：三模型 eval_pass + 五维 1–5 + agreement_score。",
    "SCORES_JSON": "修正 scores/rubric_scores.json JSON 语法。",
    "SCORES_MODELS": "scores 根下增加 models 对象，放入三模型评分。",
    "REPORTS_ROOT": "包内建 reports/<模型>/…/eval_result.json（含 eval_pass）。",
    "ALL_MODELS_PASS": "收紧测试或提高题难，使至少一模型挂；禁三模全过本题。",
    "QWEN_MUST_FAIL": "确保千问本题 eval_pass=false（调测至千问不过）。",
    "BYPASS_SESSIONS": "删除 multi-sessions 等旁路目录；正式只交 trajectories 下 1 条/模型。",
    "WS_DIRTY": "从 workspace 删除 node_modules/__pycache__/.venv/.git/ground_truth 等后重新打包。",
    "WS_THIN": "确认 workspace 是完整工程 Baseline（源码+配置+验收测），非空壳。",
    "PKG_SECRET": "删除真实密钥/token，Dockerfile/workspace 内仅用占位符。",
    "INSTRUCTION_LEAK": "题面去掉 ground_truth/参考答案/hidden test 等泄答案表述。",
    "INSTRUCTION_LEAK_SOFT": "检查题面是否泄露测试断言原文；改成任务目标与完成标准描述。",
    "INSTRUCTION_SECRET": "instruction 去掉真实 API Key/token。",
    "INSTRUCTION_SHORT": "写清目标、完成标准与约束，使 Agent 可执行。",
    "TOML_SECRET": "task.toml 禁止硬编码密钥；改用本机环境变量。",
    "TRAJ_ROOT": "建 trajectories/<claude-opus-4-8|qwen-3.7-max|glm-5.2>/。",
    "MANIFEST": "建议补 manifest.json（阶段/已采模型）；非硬失败。",
    "CORR_ALIGN": "task_rubric.correctness 要点写明与 test.sh/reward/判题的关系。",
    "LAYOUT_PACKAGE": "解压后应有 instruction.md + tests/test.sh 的任务包根。",
    "LAYOUT_SESSIONS": "不要旁路 multi-sessions；轨迹只放 trajectories/<模型>/session 与 cc-gateway-log。",
}

# code 前缀 → 建议（更具体的 code 优先精确表）
PREFIX_SUGGESTIONS: list[tuple[str, str]] = [
    ("CRIT_", "在 task_rubric.yaml 的 task_specific_criteria 下补该维度非空要点数组。"),
    ("SCORE_", "scores.models.<模型>.scores 该维分值改为 1–5 数字。"),
    ("SCORES_MODEL_", "scores.models 补全该模型条目（含 eval_pass/scores/agreement_score）。"),
    ("SCORES_EVAL_PASS_", "为该模型补 bool 类型 eval_pass（与 reports 实测一致）。"),
    ("SCORES_MAP_", "该模型下增加 scores 对象，含五维 1–5 分。"),
    ("CORR_VS_PASS_", "eval_pass=true 时 correctness 至少 4，test 全过通常改 5。"),
    ("CORR_VS_FAIL_", "eval_pass=false 时 correctness 不得为 5，按漏测严重程度改 1–3。"),
    (
        "CORR_SOFT_TENSION_",
        "挂题却 correctness=4：降到 1–3，并在 dimension_notes 写清测挂原因。",
    ),
    (
        "CORR_PASS_NOT_5_",
        "若 test 全过将 correctness 改为 5；有意扣分则在 notes 说明依据。",
    ),
    (
        "RUBRIC_AI_DRAFTED",
        "人工复核五维分后将 agreement_score_status/review_status 改为 complete，补 human_review。",
    ),
    ("AGREE_", "该模型补 agreement_score（评分一致性）。"),
    ("EVAL_MISMATCH_", "对齐 reports 与 scores 的 eval_pass，以实测 test 结果为准。"),
    ("REPORTS_EVAL_", "在 reports/<模型>/ 下落 eval_result.json，解析得 bool eval_pass。"),
    ("TURNS_", "主会话 type=assistant 去重条数须 ≥20；继续对话有效执行后再交。"),
    ("SESSION_COUNT_", "session/ 仅保留 1 条主 .jsonl；subagent 放到 session/subagents/。"),
    ("SESSION_DIR_", "建 trajectories/<模型>/session/ 并放入 session.jsonl。"),
    ("SESSION_EMPTY_", "放入主会话 session.jsonl（Claude Code 导出）。"),
    ("SESSION_", "确认模型 session 路径与主 jsonl 齐全。"),
    ("GW_EMPTY_", "把本场 cc-gateway 抓包 *.json 放进 cc-gateway-log/。"),
    ("GW_DIR_", "建 trajectories/<模型>/cc-gateway-log/ 并放入至少 1 个 *.json。"),
    ("TRAJ_", "补全 trajectories 下 opus/qwen/glm 三模型目录。"),
    ("TOML_", "修正或清理 task.toml。"),
]


def suggestion_for_code(code: str) -> str:
    c = (code or "").strip()
    if not c:
        return ""
    if c in CODE_SUGGESTIONS:
        return CODE_SUGGESTIONS[c]
    for prefix, sug in PREFIX_SUGGESTIONS:
        if c.startswith(prefix):
            return sug
    return ""


def finding_display(message: str, suggestion: str = "") -> str:
    """Align platform SoftWarningDisplay: 问题 + 建议：修改建议。"""
    msg = (message or "").strip()
    sug = (suggestion or "").strip()
    if not msg:
        return sug
    if not sug:
        return msg
    if "建议：" in msg or "建议:" in msg:
        return msg
    return f"{msg} 建议：{sug}"


@dataclass
class Finding:
    level: str  # PASS | WARN | FAIL
    code: str
    message: str
    suggestion: str = ""  # 怎么改
    explanation: str = ""  # 原因
    violation: str = ""  # 违反哪条

    def display(self) -> str:
        return finding_display(self.message, self.suggestion)

    def human_block(self) -> str:
        """四段人话：问题 / 原因 / 违反 / 建议。"""
        problem = (self.message or "").strip()
        reason = (self.explanation or "").strip()
        if not reason:
            pair = CODE_EXPLAIN.get(self.code)
            reason = pair[0] if pair else "该项未满足平台/甲方机检门槛。"
        viol = (self.violation or "").strip()
        if not viol:
            pair = CODE_EXPLAIN.get(self.code)
            viol = pair[1] if pair else DEFAULT_VIOLATION
        sug = (self.suggestion or "").strip() or suggestion_for_code(self.code) or "对照 FAIL 文案与甲方要求说明改包后重跑预检。"
        return (
            f"**问题**：{problem}\n"
            f"  **原因**：{reason}\n"
            f"  **违反**：{viol}\n"
            f"  **建议**：{sug}"
        )


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

    def add(
        self,
        level: str,
        code: str,
        message: str,
        suggestion: str = "",
        explanation: str = "",
        violation: str = "",
    ) -> None:
        sug = (suggestion or "").strip()
        if not sug and level in ("FAIL", "WARN"):
            sug = suggestion_for_code(code)
        expl = (explanation or "").strip()
        viol = (violation or "").strip()
        if level in ("FAIL", "WARN"):
            pair = CODE_EXPLAIN.get(code)
            if not expl and pair:
                expl = pair[0]
            if not viol and pair:
                viol = pair[1]
            if not viol:
                viol = DEFAULT_VIOLATION
            if not expl:
                expl = "该项未满足平台/甲方对交付或可验收性的机检要求。"
        self.findings.append(
            Finding(
                level=level,
                code=code,
                message=message,
                suggestion=sug,
                explanation=expl,
                violation=viol,
            )
        )

    def finalize(self) -> None:
        # FAIL → WARN → PASS，方便人读（对齐平台 SortFindings）
        rank = {"FAIL": 0, "WARN": 1, "PASS": 2}
        self.findings.sort(key=lambda f: rank.get(f.level, 9))
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

    def soft_warnings(self) -> list[Finding]:
        """潜在疑点：WARN 项（不单独当「硬挂」；但可导致 PRECHECK_WARN）。"""
        return [f for f in self.findings if f.level == "WARN"]


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
        ("README.md", "README"),
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
        ("tests/test_outputs.py", "TEST_OUTPUTS"),
        ("environment/workspace.tar.gz", "WORKSPACE_TAR"),
        ("scores/rubric_scores.json", "SCORES"),
        ("manifest.json", "MANIFEST"),
    ]:
        p = package / rel
        if p.exists():
            report.add("PASS", code, f"存在：{rel}")
        elif rel == "manifest.json":
            report.add(
                "WARN",
                "MANIFEST",
                "缺少 manifest.json（建议填写阶段 / 已采模型；见甲方要求说明 §5.5）",
            )
        # 其它可选：缺则不打 WARN，避免几乎无法 PRECHECK_PASS

    if (package / "reports").is_dir():
        report.add("PASS", "REPORTS", "存在 reports/")
    # 不接受包外/父目录 reports/：平台 only 看 package/reports（硬检在 check_reports_eval）

    gt = package / "ground_truth"
    solve = package / "solution" / "solve.sh"
    if gt.is_dir() or solve.is_file():
        report.add("PASS", "GT", "存在标准答案（ground_truth/ 和/或 solution/solve.sh）")
    else:
        report.add("FAIL", "GT", "缺失标准答案：需要 ground_truth/ 或 solution/solve.sh")


def _read_text_capped(path: Path, limit: int = 256_000) -> str:
    try:
        return path.read_bytes()[:limit].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _join_dockerfile_continuations(body: str) -> str:
    """Join lines ending with \\ so multi-line RUN install is one line for scanning."""
    out: list[str] = []
    buf = ""
    for line in body.splitlines():
        s = line.rstrip()
        if s.endswith("\\"):
            buf += s[:-1] + " "
        else:
            buf += s
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return "\n".join(out)


def _dockerfile_image_unpinned(image_ref: str, known_stages: set[str] | None = None) -> str | None:
    """Return fail reason if image ref is unpinned; None if OK. Align platform dockerfile_pin.go."""
    ref = image_ref.strip().strip("'\"")
    if not ref or ref.upper() == "SCRATCH":
        return None
    if "$" in ref:
        return None  # build ARG，结构阶段无法强制
    ref = re.split(r"\s+", ref, maxsplit=1)[0]
    lower = ref.lower()
    if "@sha256:" in lower:
        # digest 已固定；仍禁止 name:latest@sha256:…
        name = ref.split("@", 1)[0]
        last = name.rsplit("/", 1)[-1]
        if ":" in last and last.rsplit(":", 1)[-1].lower() == "latest":
            return f"使用 :latest：`{ref}`"
        return None
    # multi-stage：引用前面 AS 的 stage 名
    if known_stages and "/" not in ref and ":" not in ref and ref.lower() in known_stages:
        return None
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        tag = last.rsplit(":", 1)[-1]
        if tag.lower() == "latest":
            return f"使用 :latest：`{ref}`"
        if not tag:
            return f"镜像 tag 为空：`{ref}`"
        return None
    return f"base 镜像未固定 tag/digest：`{ref}`（禁止隐式 latest）"


def _pip_project_name(left: str) -> str:
    left = (left or "").strip()
    if "[" in left:
        left = left.split("[", 1)[0]
    return left.strip()


def _is_concrete_pep440_version(ver: str) -> bool:
    """True if version looks like a concrete pin (not wildcard / placeholder)."""
    ver = (ver or "").strip()
    if not ver:
        return False
    low = ver.lower()
    if "*" in ver or low in ("x", "latest") or ver.endswith(".*") or ".x" in low:
        return False
    # reject empty range leftovers like "=1.0" from bad === split
    if ver.startswith(("=", ">", "<", "~", "!")):
        return False
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9_.!+-]*$", ver))


def _pip_token_unpinned_name(tok: str) -> str | None:
    """Return package name if NOT pinned with exact pkg==x.y.z.

    甲方「固定版本 / 定死」：仅 `name==具体版本`（或 `name===…`）通过。
    裸名、>=、<=、~=、!=、>、< 一律 FAIL。
    URL/VCS/路径安装不按 PyPI 名扫。
    """
    tok = tok.strip().strip("'\"")
    if not tok or tok.startswith("-"):
        return None
    if tok.startswith(("http://", "https://", "git+", "svn+", "hg+", "file:")):
        return None
    if tok.endswith((".txt", ".in")) or "/" in tok or "\\" in tok:
        return None
    if ";" in tok:
        tok = tok.split(";", 1)[0].strip()

    # exact: === (arbitrary equality) or ==
    m = re.match(r"^(?P<left>.+?)(?P<op>===|==)(?P<ver>.+)$", tok)
    if m:
        name = _pip_project_name(m.group("left"))
        ver = m.group("ver").strip()
        if not name:
            return None
        if _is_concrete_pep440_version(ver):
            return None
        return name

    # range / direct-url ref with @  → 未定死 / 非 ==
    name = tok
    for sep in ("!=", ">=", "<=", "~=", ">", "<", " @ ", "@"):
        if sep in name:
            name = name.split(sep, 1)[0]
            break
    name = _pip_project_name(name)
    if not name or name in (".", "..") or name.startswith("."):
        return None
    return name


def _npm_token_not_exact_pin(tok: str) -> str | None:
    """Return label if npm package token is not pkg@x.y.z exact (禁 @latest)。"""
    tok = tok.strip().strip("'\"")
    if not tok or tok.startswith("-"):
        return None
    if tok.startswith(("http://", "https://", "file:", "git+")):
        return None
    if tok in (".", ".."):
        return None
    # already versioned: name@1.2.3 or @scope/pkg@1.2.3
    if tok.startswith("@"):
        # scoped: @scope/name@version needs 2 @
        if tok.count("@") >= 2:
            ver = tok.rsplit("@", 1)[-1]
            if ver.lower() == "latest" or not ver or ver == "*":
                return tok
            if re.match(r"^[\w.*+-]+$", ver) and "*" not in ver:
                return None
            return tok
        return tok  # @scope/pkg without version
    if "@" in tok:
        ver = tok.rsplit("@", 1)[-1]
        if ver.lower() == "latest" or not ver or "*" in ver:
            return tok.split("@", 1)[0] or tok
        if re.match(r"^[\w.+-]+$", ver):
            return None
        return tok.split("@", 1)[0] or tok
    return tok  # bare


def _pip_req_file_refs(body: str) -> list[str]:
    """Collect -r / --requirement paths from pip install lines."""
    refs: list[str] = []
    flat = _join_dockerfile_continuations(body)
    for m in re.finditer(r"\bpip(?:3)?\s+install\b([^\n]*)", flat, re.IGNORECASE):
        tokens = m.group(1).split()
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t in ("-r", "--requirement") and i + 1 < len(tokens):
                refs.append(tokens[i + 1].strip("'\""))
                i += 2
                continue
            if t.startswith("-r=") or t.startswith("--requirement="):
                refs.append(t.split("=", 1)[1].strip("'\""))
            i += 1
    return refs


def _resolve_req_file(dockerfile: Path, package: Path, ref: str) -> Path | None:
    """Resolve -r path relative to Dockerfile dir, then package/environment, then basename search."""
    ref = (ref or "").strip().strip("'\"")
    if not ref or ref.startswith("http://") or ref.startswith("https://"):
        return None
    # container absolute → use basename under docker build context candidates
    pure = Path(ref)
    name = pure.name
    candidates: list[Path] = []
    base = dockerfile.parent
    if not pure.is_absolute() and not ref.startswith("/"):
        candidates.append((base / pure).resolve())
        candidates.append((base / name).resolve())
    else:
        # /app/requirements.txt → try sibling paths
        candidates.append((base / name).resolve())
        # strip common container prefixes: /app, /workspace, /src
        parts = [p for p in pure.parts if p not in ("/", "app", "workspace", "src", "code")]
        if parts:
            candidates.append((base / Path(*parts)).resolve())
            if len(parts) >= 2:
                candidates.append((package / "environment" / Path(*parts[-2:])).resolve())
    candidates.append((package / "environment" / name).resolve())
    candidates.append((package / "environment" / "workspace" / name).resolve())
    # under environment/ (shallow)
    env = package / "environment"
    if env.is_dir():
        for p in env.rglob(name):
            if p.is_file() and p.name == name:
                candidates.append(p.resolve())
                if len(candidates) > 40:
                    break
    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        try:
            if c.is_file():
                # must stay inside package (read-only scan of user package)
                c.relative_to(package.resolve())
                return c
        except (OSError, ValueError):
            continue
    return None


def _requirements_file_unpinned(
    req_path: Path, *, depth: int = 0, max_depth: int = 4
) -> list[str]:
    """Parse pip requirements file; return labels 'file:pkg' for unpinned names."""
    if depth > max_depth or not req_path.is_file():
        return []
    hits: list[str] = []
    try:
        text = req_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [f"{req_path.name}:<unreadable>"]
    try:
        rel_hint = req_path.name
    except Exception:
        rel_hint = str(req_path)
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # nested -r
        nested_ref: str | None = None
        if line.startswith("-r ") or line.startswith("--requirement "):
            nested_ref = line.split(None, 1)[1].strip().strip("'\"")
        elif line.startswith("-r=") or line.startswith("--requirement="):
            nested_ref = line.split("=", 1)[1].strip().strip("'\"")
        if nested_ref:
            nested = req_path.parent / nested_ref
            if nested.is_file():
                hits.extend(_requirements_file_unpinned(nested, depth=depth + 1, max_depth=max_depth))
            else:
                hits.append(f"{rel_hint}:-r {nested_ref}(missing)")
            continue
        if line.startswith("-"):
            continue  # other pip flags / options
        # VCS / URL / local path
        if line.startswith(("http://", "https://", "git+", "svn+", "hg+", "file:")):
            continue
        # strip env markers: pkg==1.0 ; python_version>="3"
        if ";" in line:
            line = line.split(";", 1)[0].strip()
        name = _pip_token_unpinned_name(line)
        if name:
            hits.append(f"{rel_hint}:{name}")
    return hits


def _pip_install_unpinned(body: str) -> list[str]:
    """Bare pip package names on install CLI without ==/@/version pin."""
    hits: list[str] = []
    seen: set[str] = set()
    flat = _join_dockerfile_continuations(body)
    for m in re.finditer(r"\bpip(?:3)?\s+install\b([^\n]*)", flat, re.IGNORECASE):
        rest = m.group(1)
        # still walk tokens; -r file handled separately with path resolution
        tokens = rest.split()
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t in ("-r", "--requirement"):
                i += 2  # skip file arg
                continue
            if t.startswith("-r=") or t.startswith("--requirement="):
                i += 1
                continue
            if t.startswith("-"):
                i += 1
                continue
            name = _pip_token_unpinned_name(t)
            if name and name not in seen:
                seen.add(name)
                hits.append(name)
            i += 1
    return hits


def _pip_pin_failures(dockerfile: Path, package: Path, body: str) -> list[str]:
    """CLI bare packages + requirements.txt contents referenced by -r."""
    hits = list(_pip_install_unpinned(body))
    seen = set(hits)
    for ref in _pip_req_file_refs(body):
        resolved = _resolve_req_file(dockerfile, package, ref)
        if resolved is None:
            label = f"-r {ref}(文件未找到)"
            if label not in seen:
                seen.add(label)
                hits.append(label)
            continue
        for h in _requirements_file_unpinned(resolved):
            if h not in seen:
                seen.add(h)
                hits.append(h)
    return hits


def _npm_install_unpinned(body: str) -> list[str]:
    """npm install/i/add without exact pkg@x.y.z (禁 @latest / 裸名)。"""
    hits: list[str] = []
    seen: set[str] = set()
    flat = _join_dockerfile_continuations(body)
    for m in re.finditer(r"\bnpm\s+(?:install|i|add)\b([^\n]*)", flat, re.IGNORECASE):
        rest = m.group(1)
        if re.search(r"(^|\s)-g\s*$", rest) or rest.strip() in ("", "-g"):
            continue
        for tok in rest.split():
            if tok.startswith("-"):
                continue
            bad = _npm_token_not_exact_pin(tok)
            if bad and bad not in seen:
                seen.add(bad)
                hits.append(bad)
    return hits


def _check_one_dockerfile(path: Path, package: Path, report: Report) -> None:
    """检查单个 Dockerfile：FROM 钉 tag；pip/npm 须固定版本；禁止 latest。"""
    try:
        rel = path.relative_to(package).as_posix()
    except ValueError:
        rel = str(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines_no_comment: list[str] = []
    for line in text.splitlines():
        lines_no_comment.append(line.split("#", 1)[0])
    body = "\n".join(lines_no_comment)
    flat = _join_dockerfile_continuations(body)

    fail_hits: list[str] = []
    known_stages: set[str] = set()
    from_full = re.compile(
        r"^\s*FROM\s+(?:--\S+\s+)*(?P<img>\S+)(?P<rest>.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    has_from = False
    for m in from_full.finditer(flat):
        has_from = True
        rest = m.group("rest") or ""
        as_m = re.search(r"(?i)\bAS\s+(\S+)", rest)
        if as_m:
            known_stages.add(as_m.group(1).lower())
        reason = _dockerfile_image_unpinned(m.group("img"), known_stages)
        if reason:
            fail_hits.append(f"FROM：{reason}")
    if not has_from:
        fail_hits.append("未找到 FROM 行")

    for i, raw in enumerate(text.splitlines(), start=1):
        code = raw.split("#", 1)[0]
        if not EXPLICIT_LATEST_RE.search(code):
            continue
        if re.match(r"^\s*FROM\b", code, re.IGNORECASE):
            continue
        fail_hits.append(f"L{i}: 禁止使用 latest（`{raw.strip()[:80]}`）")

    seen: set[str] = set()
    uniq: list[str] = []
    for h in fail_hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)

    if uniq:
        for h in uniq[:8]:
            report.add(
                "FAIL",
                "DOCKER_IMAGE_PIN",
                f"{rel}：依赖未钉死版本：{h}。须固定 tag/digest（如 ubuntu:24.04），禁止 latest"
                f"（甲方：Dockerfile 依赖固定版本；对齐平台）",
            )
        if len(uniq) > 8:
            report.add("FAIL", "DOCKER_IMAGE_PIN", f"{rel}：另有 {len(uniq) - 8} 处镜像未钉版本")
    else:
        report.add(
            "PASS",
            "DOCKER_IMAGE_PIN",
            f"{rel}：FROM 镜像已固定 tag/digest（禁止 latest）",
        )

    pip_bad = _pip_pin_failures(path, package, body)
    if pip_bad:
        shown = ", ".join(pip_bad[:8])
        more = f" 等共 {len(pip_bad)} 项" if len(pip_bad) > 8 else ""
        report.add(
            "FAIL",
            "DOCKER_PIP_PIN",
            f"{rel}：pip 未钉死版本：{shown}{more}"
            f"（甲方须 pkg==x.y.z 定死；禁止裸名/>=/~=/区间；-r 文件内同样）",
        )
    else:
        report.add(
            "PASS",
            "DOCKER_PIP_PIN",
            f"{rel}：pip install / -r requirements 均为 pkg==x.y.z 定死版本",
        )

    npm_bad = _npm_install_unpinned(body)
    if npm_bad:
        shown = ", ".join(npm_bad[:6])
        more = f" 等共 {len(npm_bad)} 项" if len(npm_bad) > 6 else ""
        report.add(
            "FAIL",
            "DOCKER_NPM_PIN",
            f"{rel}：npm 未钉死版本：{shown}{more}（须 pkg@x.y.z 定死；禁裸名/@latest）",
        )
    else:
        # 多数包无 npm，静默 PASS 过噪；仅有 npm 装包行才 PASS
        if re.search(r"\bnpm\s+(?:install|i|add)\b", body, re.I):
            report.add("PASS", "DOCKER_NPM_PIN", f"{rel}：npm 均为 pkg@x.y.z 定死版本")


def check_dockerfile_pins(package: Path, report: Report) -> None:
    """甲方：依赖须固定版本；禁止 Docker 镜像/包用 latest。对齐平台 dockerfile_pin.go。"""
    paths = [
        package / "environment" / "Dockerfile",
        package / "environment" / "workspace" / "Dockerfile",
    ]
    any_checked = False
    for path in paths:
        if path.is_file():
            any_checked = True
            _check_one_dockerfile(path, package, report)
    if not any_checked:
        return  # 缺失路径由 check_core_files 报 DOCKERFILE


def check_test_sh(package: Path, report: Report) -> None:
    """禁止空壳 test.sh（如仅 exit 0）。"""
    path = package / "tests" / "test.sh"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    solid: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("#!"):
            continue
        # set -e 等不算“测试体”
        if re.match(r"^set\s+-", s):
            continue
        solid.append(s)
    if not solid:
        report.add("FAIL", "TEST_SH_EMPTY", "tests/test.sh 无有效命令，疑似空壳")
        return
    trivial = True
    for s in solid:
        if re.fullmatch(r"exit\s+0;?", s, re.IGNORECASE):
            continue
        if s in (":", "true"):
            continue
        trivial = False
        break
    if trivial:
        report.add(
            "FAIL",
            "TEST_SH_SHELL",
            "tests/test.sh 疑似空壳（实质仅 exit 0 / true），禁止恒通过测试",
        )
        return
    if len(solid) < 3:
        report.add(
            "WARN",
            "TEST_SH_THIN",
            f"tests/test.sh 有效命令很少（{len(solid)} 行），请确认非敷衍判分",
        )
    else:
        report.add("PASS", "TEST_SH_BODY", f"tests/test.sh 有实质内容（约 {len(solid)} 条有效命令）")


def check_package_secrets(package: Path, report: Report) -> None:
    """Dockerfile / workspace 常见密钥落点粗扫（不扫 trajectories / 大体积源码全量）。"""
    candidates: list[Path] = []
    df = package / "environment" / "Dockerfile"
    if df.is_file():
        candidates.append(df)
    ws = package / "environment" / "workspace"
    if ws.is_dir():
        for p in ws.rglob("*"):
            if not p.is_file():
                continue
            name = p.name.lower()
            if (
                name.startswith(".env")
                or name in (".npmrc", "credentials.json", "secrets.yaml", "secrets.yml", "id_rsa")
                or name.endswith(".pem")
            ):
                candidates.append(p)
            if len(candidates) >= 40:
                break

    hits: list[str] = []
    for p in candidates:
        text = _read_text_capped(p)
        if not text:
            continue
        if SECRET_RE.search(text) or SECRET_EXTRA_RE.search(text):
            try:
                rel = str(p.relative_to(package))
            except ValueError:
                rel = str(p)
            hits.append(rel)

    if hits:
        report.add(
            "FAIL",
            "PKG_SECRET",
            "疑似真实密钥/token：" + "; ".join(hits[:8]) + "（须移出包，换占位）",
        )
    else:
        report.add(
            "PASS",
            "PKG_SECRET",
            "Dockerfile / workspace 常见密钥文件未见明显硬编码密钥",
        )


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
    hard_hit = next((t for t in INSTRUCTION_LEAK_HARD if t.lower() in low), None)
    if hard_hit:
        report.add(
            "FAIL",
            "INSTRUCTION_LEAK",
            f"instruction.md 不得提及「{hard_hit}」（平台/甲方：泄答案路径或隐藏测）",
        )
    else:
        soft_hit = next((t for t in INSTRUCTION_LEAK_SOFT if t.lower() in low), None)
        if soft_hit:
            report.add(
                "WARN",
                "INSTRUCTION_LEAK_SOFT",
                f"instruction.md 提及「{soft_hit}」，请确认未泄测试断言原文",
            )
        else:
            report.add("PASS", "INSTRUCTION_LEAK", "instruction.md 未见明显泄题关键词")

    # 软：目标/完成可执行性（启发式；深审见 SKILL §E）
    has_goalish = any(
        k in text for k in ("目标", "完成", "要求", "Implement", "implement", "需", "验收", "约束")
    )
    if len(text.strip()) >= 40 and not has_goalish:
        report.add(
            "WARN",
            "INSTRUCTION_GOAL_SOFT",
            "instruction.md 未见明显「目标/完成标准/约束」类表述，平台语义审可能判题面不充分",
            suggestion="补清：任务目标、完成标准、禁止项；勿写答题步骤泄测。深审见 SEMANTIC_REVIEW.md §E2。",
            explanation="平台 Claude 会看 instruction 是否可执行；仅机检长度不够。",
            violation="平台 instruction_tests_audit 软项 / 甲方题面可执行",
        )

    if SECRET_RE.search(text) or SECRET_EXTRA_RE.search(text):
        report.add("FAIL", "INSTRUCTION_SECRET", "instruction.md 疑似含密钥/token")


def check_task_toml(package: Path, report: Report) -> None:
    path = package / "task.toml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if SECRET_RE.search(text) or SECRET_EXTRA_RE.search(text):
        report.add("FAIL", "TOML_SECRET", "task.toml 疑似含真实密钥")
    else:
        report.add("PASS", "TOML_SECRET", "task.toml 未见明显硬编码密钥")


def _as_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _meta_one_liner_thin(s: str) -> bool:
    runes = list((s or "").strip())
    if len(runes) < 20:
        return True
    low = s.strip().lower()
    for p in ("demo", "test", "todo", "placeholder", "简述本题", "一句话介绍", "tbd", "xxx"):
        if low == p or low.startswith(p + " "):
            return True
    return False


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
        if str(tid) != package.name:
            report.add(
                "FAIL",
                "META_TASK_ID_MISMATCH",
                f"task_id「{tid}」须与任务目录名「{package.name}」一致（平台 packagecheck / 甲方 §5）",
            )
        else:
            report.add("PASS", "META_TASK_ID_MATCH", f"task_id 与目录名一致：{tid}")
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
        if _meta_one_liner_thin(str(one)):
            report.add(
                "WARN",
                "META_ONELINER_THIN",
                "one_liner 过短或像占位文，未讲清测什么/为何是好题",
            )
    else:
        report.add("FAIL", "META_ONELINER", "缺少 one_liner / one_sentence_summary")

    diff_ok = False
    if str(meta.get("difficulty") or "").strip():
        diff_ok = True
        report.add("PASS", "META_DIFF", f"difficulty = {meta.get('difficulty')}")
    else:
        da = meta.get("difficulty_assessment")
        if isinstance(da, str) and da.strip():
            diff_ok = True
            report.add("PASS", "META_DIFF", "有 difficulty_assessment 文本")
        elif isinstance(da, dict):
            if str(da.get("level") or da.get("difficulty") or "").strip():
                diff_ok = True
                report.add("PASS", "META_DIFF", "有 difficulty_assessment 档位")
    if not diff_ok:
        report.add(
            "FAIL",
            "META_DIFF",
            "缺少非空 difficulty（或 difficulty_assessment 文本/档位）",
        )

    ab = meta.get("annotator_background")
    if ab is None:
        report.add(
            "FAIL",
            "META_ANNOTATOR",
            "缺少 annotator_background（须含 industry / years_experience / role）",
        )
    elif not isinstance(ab, dict):
        report.add(
            "FAIL",
            "META_ANNOTATOR",
            "annotator_background 须为对象 {industry, years_experience, role}",
        )
    else:
        miss: list[str] = []
        industry = str(ab.get("industry") or "").strip()
        role = str(ab.get("role") or "").strip()
        years = _as_float(ab.get("years_experience"))
        if years is None:
            years = _as_float(ab.get("years"))
        if not industry:
            miss.append("industry")
        if ab.get("years_experience") is None and ab.get("years") is None:
            miss.append("years_experience")
        elif years is None or years < 0:
            miss.append("years_experience(须为≥0数字)")
        if not role:
            miss.append("role")
        if miss:
            report.add(
                "FAIL",
                "META_ANNOTATOR",
                "annotator_background 不完整，缺/非法: " + ", ".join(miss),
            )
        else:
            report.add(
                "PASS",
                "META_ANNOTATOR",
                f"annotator_background: {industry} / {years:g} 年 / {role}",
            )

    ct = _as_float(meta.get("completion_time_min"))
    if meta.get("completion_time_min") is None or ct is None:
        report.add(
            "FAIL",
            "META_COMPLETION_TIME",
            "缺少 completion_time_min（预估完成本题/标注用时，分钟，须为数字）",
        )
    elif ct <= 0 or ct > 10080:
        report.add(
            "FAIL",
            "META_COMPLETION_TIME",
            f"completion_time_min 须在 (0, 10080] 分钟内，当前={meta.get('completion_time_min')}",
        )
    else:
        report.add("PASS", "META_COMPLETION_TIME", f"completion_time_min = {ct:g}")
        if ct < 30 or ct > 720:
            report.add(
                "WARN",
                "META_TIME_OUTLIER",
                f"completion_time_min={ct:g} 偏离常见出题/标注区间（建议约 30–720 分钟）",
            )
        hda = meta.get("human_difficulty_assessment")
        if isinstance(hda, dict):
            est = _as_float(hda.get("estimated_minutes"))
            if est is not None and est > 0 and (ct / est < 0.5 or ct / est > 2):
                report.add(
                    "WARN",
                    "META_TIME_INCONSISTENT",
                    f"completion_time_min={ct:g} 与 human_difficulty_assessment.estimated_minutes={est:g} 相差超过 2 倍",
                    suggestion=(
                        "统一两处用时口径（completion_time_min 通常为出题+标注总用时）"
                    ),
                )

    af = _as_float(meta.get("agreement_score"))
    if meta.get("agreement_score") is None or af is None:
        report.add(
            "FAIL",
            "META_AGREE",
            "agreement_score 须为 [0,1] 数字（禁止 null/缺省/非数字）",
        )
    elif af < 0 or af > 1:
        report.add(
            "FAIL",
            "META_AGREE",
            f"agreement_score 须在 [0,1]，当前={meta.get('agreement_score')}",
        )
    else:
        report.add("PASS", "META_AGREE", f"agreement_score = {af:g}")
        if af == 0:
            report.add(
                "WARN",
                "META_AGREE_ZERO",
                "agreement_score=0，可能是未填或占位",
            )

    status_blob = (
        str(meta.get("agreement_score_status") or "")
        + " "
        + str(meta.get("review_status") or "")
    ).lower()
    if "single_reviewer" in status_blob:
        report.add(
            "WARN",
            "META_SINGLE_REVIEWER",
            "meta 标注 agreement 为 single_reviewer_only（单审、无交叉验证）",
            suggestion=(
                "建议增加第二 reviewer 交叉评分，或在 meta 注明单审原因"
            ),
        )

    tags = meta.get("tags")
    if isinstance(tags, list) and tags:
        report.add("PASS", "META_TAGS", f"tags 共 {len(tags)} 项")
    else:
        report.add("FAIL", "META_TAGS", "缺少 tags（数组）")



def _load_yaml_soft(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def check_rubrics(package: Path, report: Report) -> None:
    """对齐平台 checkRubric：维度要点 + scores 正式文件。"""
    global_p = package / "rubrics" / "global_rubric.yaml"
    task_p = package / "rubrics" / "task_rubric.yaml"
    if global_p.is_file():
        report.add("PASS", "GLOBAL_RUBRIC_BODY", "存在 rubrics/global_rubric.yaml")
    # 存在性已在 core_files 查
    if not task_p.is_file():
        return

    doc = _load_yaml_soft(task_p)
    text = task_p.read_text(encoding="utf-8", errors="replace")
    if doc is None:
        # 无 PyYAML 时用文本启发
        if "task_type" not in text:
            report.add("FAIL", "TASK_TYPE", "task_rubric 缺少 task_type")
        else:
            report.add("PASS", "TASK_RUBRIC_PARSE", "task_rubric.yaml 可读取（未装 PyYAML，维度细则请自查）")
        for d in RUBRIC_DIMS:
            if d not in text:
                report.add("FAIL", f"CRIT_{d}", f"task_rubric 文本未见维度 {d}")
    else:
        tt = str(doc.get("task_type") or "").strip()
        if tt in RUBRIC_TYPES:
            report.add("PASS", "TASK_TYPE", f"task_type={tt}")
            # 与 meta.rubric_task_type 一致
            mp = package / "meta.json"
            if mp.is_file():
                try:
                    meta = json.loads(mp.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    meta = None
                if isinstance(meta, dict):
                    mtt = meta.get("rubric_task_type") or meta.get("task_type")
                    if mtt and str(mtt).strip() != tt:
                        report.add(
                            "FAIL",
                            "TASK_TYPE_META_MISMATCH",
                            f"task_rubric.task_type={tt!r} 与 meta={mtt!r} 不一致",
                            suggestion="统一 meta.rubric_task_type 与 rubrics/task_rubric.yaml 的 task_type",
                        )
        else:
            report.add("FAIL", "TASK_TYPE", f"task_rubric.task_type 须为四选一，当前={tt!r}")
        criteria = doc.get("task_specific_criteria")
        if not isinstance(criteria, dict):
            report.add("FAIL", "CRITERIA", "缺少 task_specific_criteria")
        else:
            for d in RUBRIC_DIMS:
                v = criteria.get(d)
                ok = isinstance(v, list) and len(v) > 0
                if ok:
                    report.add("PASS", f"CRIT_{d}", f"{d} 有 {len(v)} 条要点")
                else:
                    report.add(
                        "FAIL",
                        f"CRIT_{d}",
                        f"{d} 的 task_specific_criteria 须为非空数组（平台 rubric FAIL）",
                    )
            corr = " ".join(str(x) for x in (criteria.get("correctness") or []))
            low = corr.lower()
            if any(k in low for k in ("test", "reward", "判题", "pytest", "通过")):
                report.add("PASS", "CORR_ALIGN", "correctness 提及判题相关表述")
            else:
                report.add(
                    "WARN",
                    "CORR_ALIGN",
                    "correctness 要点建议明确对齐 test.sh / reward / 判题通过",
                )

    check_rubric_scores(package, report)


def check_rubric_scores(package: Path, report: Report) -> None:
    """scores/rubric_scores.json：三模型 eval_pass + 五维 1–5 + agreement（平台硬）。"""
    path = package / "scores" / "rubric_scores.json"
    if not path.is_file():
        report.add(
            "FAIL",
            "SCORES_FILE",
            "缺少 scores/rubric_scores.json（平台 rubric 硬门槛；须交付正式评分结果）",
        )
        return
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.add("FAIL", "SCORES_JSON", f"scores/rubric_scores.json 非法 JSON：{e}")
        return
    if not isinstance(root, dict):
        report.add("FAIL", "SCORES_JSON", "scores 根须为对象")
        return
    models_block = root.get("models")
    if not isinstance(models_block, dict):
        report.add("FAIL", "SCORES_MODELS", "scores 须含 models 对象")
        return

    need = [
        ("claude-opus-4.8", ("claude-opus-4-8", "claude-opus-4.8")),
        ("qwen-3.7-max", ("qwen-3.7-max",)),
        ("glm-5.2", ("glm-5.2",)),
    ]
    eval_map: dict[str, bool | None] = {}
    scores_ok = True
    for label, keys in need:
        mm = None
        key_hit = ""
        for k in keys:
            if isinstance(models_block.get(k), dict):
                mm = models_block[k]
                key_hit = k
                break
        if mm is None:
            scores_ok = False
            report.add("FAIL", f"SCORES_MODEL_{label}", f"scores.models 缺少 {label}")
            eval_map[label] = None
            continue
        ep = mm.get("eval_pass")
        if not isinstance(ep, bool):
            scores_ok = False
            report.add("FAIL", f"SCORES_EVAL_PASS_{label}", f"{key_hit} 须含 bool eval_pass")
            eval_map[label] = None
        else:
            eval_map[label] = ep
        scores = mm.get("scores")
        if not isinstance(scores, dict):
            scores_ok = False
            report.add("FAIL", f"SCORES_MAP_{label}", f"{key_hit} 须含 scores 对象")
        else:
            for d in RUBRIC_DIMS:
                sv = scores.get(d)
                try:
                    f = float(sv)
                except (TypeError, ValueError):
                    f = -1
                if f < 1 or f > 5:
                    scores_ok = False
                    report.add(
                        "FAIL",
                        f"SCORE_{key_hit}_{d}",
                        f"分值须在 1–5: {key_hit}.{d}={sv!r}",
                    )
            # correctness vs eval_pass
            try:
                cf = float(scores.get("correctness"))
            except (TypeError, ValueError):
                cf = None
            if isinstance(ep, bool) and cf is not None:
                if ep and cf < 4:
                    scores_ok = False
                    report.add(
                        "FAIL",
                        f"CORR_VS_PASS_{key_hit}",
                        f"{key_hit}：eval_pass=true 时 correctness 应 ≥4",
                        suggestion=(
                            "将 scores.models 与 reports/**/rubric_scores.json 中该模型 "
                            "scores.correctness 改为 ≥4（test 全过通常为 5）。"
                        ),
                    )
                if not ep and cf >= 5:
                    scores_ok = False
                    report.add(
                        "FAIL",
                        f"CORR_VS_FAIL_{key_hit}",
                        f"{key_hit}：eval_pass=false 时 correctness 不得为 5",
                        suggestion=(
                            "挂题不得 correctness=5：按漏测严重程度改为 1–3，"
                            "并在 dimension_notes.correctness 说明测挂点。"
                        ),
                    )
                # Soft WARN（对齐平台 rubric soft）：不硬失败
                if not ep and 4 <= cf < 5:
                    report.add(
                        "WARN",
                        f"CORR_SOFT_TENSION_{key_hit}",
                        f"{key_hit}：eval_pass=false（机测未过）但 correctness={cf:g}，"
                        f"分偏高（挂题 correctness 通常 1–3；=5 才硬失败）",
                        suggestion=(
                            "改 scores/rubric_scores.json 与 reports/**/rubric_scores.json 中该模型 "
                            "scores.correctness，按漏测严重程度降到 1–3，并在 dimension_notes.correctness "
                            "写清：哪些 acceptance 通过、哪些 hidden/test.sh 挂、reward=0。"
                        ),
                    )
                if ep and 4 <= cf < 5:
                    report.add(
                        "WARN",
                        f"CORR_PASS_NOT_5_{key_hit}",
                        f"{key_hit}：eval_pass=true 但 correctness={cf:g}"
                        f"（test 全过时甲方通常要求 correctness=5）",
                        suggestion=(
                            "若 test.sh 确实全过，将 correctness 改为 5；若有意扣分，"
                            "在 notes 说明「exec 过但 rubric 另有缺口」及依据。"
                        ),
                    )
        ag = _as_float(mm.get("agreement_score"))
        if mm.get("agreement_score") is None or ag is None:
            scores_ok = False
            report.add(
                "FAIL",
                f"AGREE_{key_hit}",
                f"{key_hit} 须含 agreement_score 数字 ∈ [0,1]（禁止 null/缺省）",
            )
        elif ag < 0 or ag > 1:
            scores_ok = False
            report.add(
                "FAIL",
                f"AGREE_{key_hit}",
                f"{key_hit}：agreement_score 须在 [0,1]，当前={mm.get('agreement_score')}",
            )
        # notes：过题时鼓励写点评
        notes = mm.get("notes") or mm.get("dimension_notes")
        if isinstance(ep, bool) and ep and not notes:
            report.add(
                "WARN",
                f"SCORES_NOTES_{key_hit}",
                f"{key_hit}：eval_pass=true 但缺少 notes/dimension_notes（建议人工点评）",
                suggestion="在 scores.models 下补 notes 或 dimension_notes，说明通过依据与扣分点。",
            )
        # Soft：AI 草拟分
        if _model_ai_drafted(mm):
            report.add(
                "WARN",
                f"RUBRIC_AI_DRAFTED_{key_hit}",
                f"{key_hit}：评分仍为 AI 草拟（agreement_score_status/review_status=ai_drafted），"
                f"尚未按人审终稿落盘",
                suggestion=(
                    "人工对照轨迹与 eval_result 复核五维分后：将 models 内及根级 "
                    "agreement_score_status、review_status 改为 complete；补 human_review / "
                    "reviewed_at；并同步 reports/**/rubric_scores.json。"
                ),
            )
    if _root_ai_drafted(root) and not any(
        f.code.startswith("RUBRIC_AI_DRAFTED_") for f in report.findings
    ):
        report.add(
            "WARN",
            "RUBRIC_AI_DRAFTED",
            "scores/rubric_scores.json 根级 agreement_score_status/review_status=ai_drafted："
            "当前为 AI 草拟分，不是人工终审完成态",
            suggestion=(
                "人工复核后改为 complete，补 human_review 说明与 reviewed_at；"
                "确认 correctness 与各模型 eval_pass 一致后提交。"
            ),
        )
    if scores_ok:
        report.add(
            "PASS",
            "SCORES_FILE",
            "scores/rubric_scores.json 三模型 eval_pass/五维分/agreement 可解析",
        )

    # 众包单题硬门槛（与平台 models_summary 对齐）
    known = [v for v in eval_map.values() if isinstance(v, bool)]
    if len(known) == 3 and all(known):
        report.add(
            "FAIL",
            "ALL_MODELS_PASS",
            "禁止三模型都测通（平台/甲方众包单题硬门槛；见 scores.eval_pass）",
        )
    if eval_map.get("qwen-3.7-max") is True:
        report.add(
            "FAIL",
            "QWEN_MUST_FAIL",
            "千问须在本题测不过（平台：每题千问过题率=0；scores 中 qwen eval_pass 须为 false）",
        )


def _status_looks_ai_drafted(v: Any) -> bool:
    s = str(v or "").strip().lower()
    if not s or s == "none":
        return False
    return s in ("ai_drafted", "ai-drafted", "draft", "drafted")


def _model_ai_drafted(mm: dict[str, Any] | None) -> bool:
    if not isinstance(mm, dict):
        return False
    return _status_looks_ai_drafted(mm.get("agreement_score_status")) or _status_looks_ai_drafted(
        mm.get("review_status")
    )


def _root_ai_drafted(root: dict[str, Any] | None) -> bool:
    if not isinstance(root, dict):
        return False
    return _status_looks_ai_drafted(root.get("agreement_score_status")) or _status_looks_ai_drafted(
        root.get("review_status")
    )


def check_reports_eval(package: Path, report: Report) -> None:
    """平台：三模型均须有 reports/<model>/**/eval_result.json 含 eval_pass。"""
    traj_need = [
        ("claude-opus-4.8", ("claude-opus-4-8", "claude-opus-4.8")),
        ("qwen-3.7-max", ("qwen-3.7-max",)),
        ("glm-5.2", ("glm-5.2",)),
    ]
    reports = package / "reports"
    if not reports.is_dir():
        report.add(
            "FAIL",
            "REPORTS_ROOT",
            "缺少 reports/（平台须交付各模型 eval_result.json）",
        )
        return
    report.add("PASS", "REPORTS_ROOT", "存在 reports/")

    score_pass: dict[str, bool | None] = {}
    sp = package / "scores" / "rubric_scores.json"
    if sp.is_file():
        try:
            root = json.loads(sp.read_text(encoding="utf-8"))
            mb = root.get("models") if isinstance(root, dict) else None
            if isinstance(mb, dict):
                for label, keys in traj_need:
                    for k in keys:
                        m = mb.get(k)
                        if isinstance(m, dict) and isinstance(m.get("eval_pass"), bool):
                            score_pass[label] = m["eval_pass"]
                            break
        except json.JSONDecodeError:
            pass

    for label, keys in traj_need:
        hit_dir = None
        for k in keys:
            p = reports / k
            if p.is_dir():
                hit_dir = p
                break
        if hit_dir is None:
            report.add(
                "FAIL",
                f"REPORTS_EVAL_{label}",
                f"{label}：缺少 reports/<model>/（须含 eval_result.json）",
            )
            continue
        eval_files = list(hit_dir.rglob("eval_result.json"))
        if not eval_files:
            report.add(
                "FAIL",
                f"REPORTS_EVAL_{label}",
                f"{label}：reports 下未找到 eval_result.json（平台 hard）",
            )
            continue
        ep = None
        for ef in eval_files:
            try:
                data = json.loads(ef.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and isinstance(data.get("eval_pass"), bool):
                ep = data["eval_pass"]
                break
            # reward 1/0 兼容
            if isinstance(data, dict) and "reward" in data:
                try:
                    ep = float(data["reward"]) >= 1.0
                except (TypeError, ValueError):
                    pass
                if ep is not None:
                    break
        if ep is None:
            report.add(
                "FAIL",
                f"REPORTS_EVAL_{label}",
                f"{label}：eval_result.json 无法解析 bool eval_pass",
            )
            continue
        report.add(
            "PASS",
            f"REPORTS_EVAL_{label}",
            f"{hit_dir.name}: reports.eval_pass={ep}",
        )
        if label in score_pass and score_pass[label] is not None and score_pass[label] != ep:
            report.add(
                "FAIL",
                f"EVAL_MISMATCH_{label}",
                f"{label} reports.eval_pass={ep} 与 scores.eval_pass={score_pass[label]} 不一致",
            )
        # 深检：session_id / 是否空壳 report
        chosen = None
        for ef in eval_files:
            try:
                data = json.loads(ef.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and (
                isinstance(data.get("eval_pass"), bool) or "reward" in data
            ):
                chosen = data
                break
        if isinstance(chosen, dict):
            sid = chosen.get("session_id") or chosen.get("sessionId")
            if not sid:
                report.add(
                    "WARN",
                    f"REPORTS_SESSION_ID_{label}",
                    f"{label}：eval_result 未带 session_id（建议与轨迹主会话对应，便于溯源）",
                    suggestion="在 reports/.../eval_result.json 写入 session_id（与 session 文件名 UUID 一致）。",
                )
            # 对应用 reports 下 rubric_scores.json 若存在且 eval 不一致
            for rs in hit_dir.rglob("rubric_scores.json"):
                try:
                    rdoc = json.loads(rs.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    report.add(
                        "WARN",
                        f"REPORTS_RUBRIC_JSON_{label}",
                        f"{label}：reports 内 rubric_scores.json 非法 JSON：{rs.name}",
                    )
                    continue
                if not isinstance(rdoc, dict):
                    continue
                # 若嵌套 models[key]
                r_ep = None
                if isinstance(rdoc.get("eval_pass"), bool):
                    r_ep = rdoc["eval_pass"]
                mb = rdoc.get("models")
                if isinstance(mb, dict):
                    for k in keys:
                        m = mb.get(k)
                        if isinstance(m, dict) and isinstance(m.get("eval_pass"), bool):
                            r_ep = m["eval_pass"]
                            break
                if r_ep is not None and r_ep != ep:
                    report.add(
                        "FAIL",
                        f"REPORTS_SCORES_MISMATCH_{label}",
                        f"{label}：reports 内 rubric_scores.eval_pass={r_ep} 与 eval_result={ep} 不一致",
                        suggestion="以实测 eval_result 为准，同步改 rubric_scores.json（包内 scores/ 与 reports/）。",
                    )


def check_bypass_sessions(package: Path, report: Report) -> None:
    for name in SESSIONS_DIR_NAMES:
        if (package / name).is_dir():
            report.add(
                "FAIL",
                "BYPASS_SESSIONS",
                f"禁止提交旁路目录 {name}/：每模型正式只交 1 条轨迹（trajectories/）",
            )
            return
    report.add("PASS", "BYPASS_SESSIONS", "未见 multi-sessions 等旁路 session 目录")


def check_workspace_clean(package: Path, report: Report) -> None:
    ws = package / "environment" / "workspace"
    if not ws.is_dir():
        return
    bad: list[str] = []
    # 嵌套也查（如 src/__pycache__）；找到即跳过该子树继续
    for dirpath, dirnames, _filenames in os.walk(ws):
        drop: list[str] = []
        for name in list(dirnames):
            if name in WS_FORBIDDEN_DIR_NAMES:
                rel = str(Path(dirpath, name).relative_to(ws))
                bad.append(rel)
                drop.append(name)
        for name in drop:
            dirnames.remove(name)
        if len(bad) >= 12:
            break
    if bad:
        shown = ", ".join(bad[:8])
        more = f" 等共 {len(bad)} 处" if len(bad) > 8 else ""
        report.add(
            "FAIL",
            "WS_DIRTY",
            f"workspace 不应包含：{shown}{more}（禁止 node_modules/.venv/__pycache__/.git/ground_truth 等）",
        )
    else:
        report.add("PASS", "WS_DIRTY", "workspace 未见常见污染目录（含嵌套 __pycache__/.git 等）")
    files = [p for p in ws.rglob("*") if p.is_file()]
    if len(files) < 3:
        report.add("WARN", "WS_THIN", f"workspace 文件很少（{len(files)}），请确认是完整 Baseline")
    else:
        report.add("PASS", "WS_SIZE", f"workspace 文件数约 {len(files)}")


# Generated call-level / derived JSONL are not “主会话”
_AUX_TRAJ_JSONL = frozenset({"call_level.jsonl", "calls.jsonl"})

SESSION_DIR_NAME = "session"
GATEWAY_LOG_DIR_NAME = "cc-gateway-log"


def count_assistant_turns(path: Path) -> int:
    """Align platform quality.go: type=assistant, dedupe message.id / uuid."""
    seen: set[str] = set()
    count = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("type") != "assistant":
            continue
        msg = row.get("message")
        mid = ""
        if isinstance(msg, dict):
            mid = str(msg.get("id") or "").strip()
        if not mid:
            mid = str(row.get("uuid") or "").strip()
        if mid:
            if mid in seen:
                continue
            seen.add(mid)
        count += 1
    return count


def _find_sessions_in_dir(search_dir: Path) -> list[Path]:
    """Main Claude session .jsonl under a directory (exclude call_level)."""
    found: list[Path] = []
    if not search_dir.is_dir():
        return found
    for p in sorted(search_dir.glob("*.jsonl")):
        if p.name in _AUX_TRAJ_JSONL:
            continue
        found.append(p)
    found.sort(key=lambda p: (0 if p.name == "session.jsonl" else 1, p.name))
    return found


def _find_sessions(model_dir: Path) -> tuple[list[Path], Path | None, bool]:
    """Return (sessions, session_root_used, used_session_subdir).

    Preferred layout: trajectories/<model>/session/*.jsonl
    Legacy (warn path): trajectories/<model>/*.jsonl at model root.
    """
    preferred = model_dir / SESSION_DIR_NAME
    if preferred.is_dir():
        return _find_sessions_in_dir(preferred), preferred, True
    legacy = _find_sessions_in_dir(model_dir)
    return legacy, (model_dir if legacy else None), False


def check_model_sessions(sessions_root: Path, report: Report) -> None:
    """检查 trajectories/ 下每模型：session/ + cc-gateway-log/ 各一份正式轨迹。"""
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

        session_dir = hit / SESSION_DIR_NAME
        gw_dir = hit / GATEWAY_LOG_DIR_NAME
        if not session_dir.is_dir():
            report.add(
                "FAIL",
                f"SESSION_DIR_{model}",
                f"{hit.name}/ 缺少 {SESSION_DIR_NAME}/（须放 Claude Code 主会话 .jsonl）",
            )
        else:
            report.add(
                "PASS",
                f"SESSION_DIR_{model}",
                f"存在 {hit.name}/{SESSION_DIR_NAME}/",
            )
        if not gw_dir.is_dir():
            report.add(
                "FAIL",
                f"GW_DIR_{model}",
                f"{hit.name}/ 缺少 {GATEWAY_LOG_DIR_NAME}/（须放本场 cc-gateway 抓包 *.json）",
            )
        else:
            gw_files = list(gw_dir.glob("*.json")) + list(gw_dir.rglob("*.json"))
            # de-dup if both top and nested
            gw_files = sorted({p.resolve() for p in gw_files}, key=lambda p: str(p))
            if not gw_files:
                report.add(
                    "FAIL",
                    f"GW_EMPTY_{model}",
                    f"{hit.name}/{GATEWAY_LOG_DIR_NAME}/ 下未找到 *.json 抓包",
                )
            else:
                report.add(
                    "PASS",
                    f"GW_DIR_{model}",
                    f"{hit.name}/{GATEWAY_LOG_DIR_NAME}/ 含 {len(gw_files)} 个 json 抓包",
                )

        sessions, sroot, used_subdir = _find_sessions(hit)
        if not used_subdir and sessions:
            report.add(
                "WARN",
                f"SESSION_LAYOUT_{model}",
                f"{hit.name}/ 主会话仍在模型根目录；请改放到 {SESSION_DIR_NAME}/session.jsonl",
            )
        if not sessions:
            report.add(
                "FAIL",
                f"SESSION_{model}",
                f"{hit.name}/{SESSION_DIR_NAME}/ 下未找到主 session .jsonl",
            )
            continue
        if len(sessions) == 1:
            report.add(
                "PASS",
                f"SESSION_COUNT_{model}",
                f"{hit.name}/{SESSION_DIR_NAME}/ 含 1 条主轨迹（符合每模型只交 1 条）",
            )
        else:
            report.add(
                "FAIL",
                f"SESSION_COUNT_{model}",
                f"{hit.name}/{SESSION_DIR_NAME}/ 含 {len(sessions)} 条顶层 .jsonl；"
                f"正式须仅 1 条主会话（subagent 请放 {SESSION_DIR_NAME}/subagents/）",
            )
        main = sessions[0]
        rel_main = f"{sessions_root.name}/{hit.name}/{SESSION_DIR_NAME if used_subdir else ''}/{main.name}".replace(
            "//", "/"
        )
        report.add("PASS", f"SESSION_{model}", f"主 session：{rel_main}")
        assistant = count_assistant_turns(main)
        if assistant >= MIN_ASSISTANT_TURNS:
            report.add(
                "PASS",
                f"TURNS_{model}",
                f"{hit.name}: assistant 轮次={assistant} ≥ {MIN_ASSISTANT_TURNS}"
                f"（type=assistant 去重，对齐平台）",
            )
        else:
            report.add(
                "FAIL",
                f"TURNS_{model}",
                f"{hit.name}: assistant 轮次={assistant}，须 ≥{MIN_ASSISTANT_TURNS}"
                f"（平台：每个模型各自达标，非三模型平均）",
            )
        call_level = hit / "call_level.jsonl"
        if not call_level.is_file() and sroot is not None:
            call_level = sroot / "call_level.jsonl"
        if call_level.is_file():
            report.add(
                "PASS",
                f"CALL_LEVEL_{model}",
                f"{hit.name} 存在 call_level.jsonl（可选/历史产物；正式§B 默认不写回包，字段以临时合并校验为准）",
            )
        sub_a = (sroot or hit) / "subagents"
        if sub_a.is_dir():
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



def _read_model_eval_passes(package: Path) -> dict[str, bool | None]:
    """Prefer reports eval_pass, fill gaps from scores (platform models summary style)."""
    labels_keys = [
        ("claude-opus-4.8", ("claude-opus-4-8", "claude-opus-4.8")),
        ("qwen-3.7-max", ("qwen-3.7-max",)),
        ("glm-5.2", ("glm-5.2",)),
    ]
    out: dict[str, bool | None] = {lab: None for lab, _ in labels_keys}
    reports = package / "reports"
    if reports.is_dir():
        for lab, keys in labels_keys:
            for k in keys:
                d = reports / k
                if not d.is_dir():
                    continue
                for ef in d.rglob("eval_result.json"):
                    try:
                        data = json.loads(ef.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    if isinstance(data.get("eval_pass"), bool):
                        out[lab] = data["eval_pass"]
                        break
                    if "reward" in data:
                        try:
                            out[lab] = float(data["reward"]) >= 1.0
                            break
                        except (TypeError, ValueError):
                            pass
                if out[lab] is not None:
                    break
    sp = package / "scores" / "rubric_scores.json"
    if sp.is_file():
        try:
            root = json.loads(sp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            root = None
        mb = root.get("models") if isinstance(root, dict) else None
        if isinstance(mb, dict):
            for lab, keys in labels_keys:
                if out[lab] is not None:
                    continue
                for k in keys:
                    m = mb.get(k)
                    if isinstance(m, dict) and isinstance(m.get("eval_pass"), bool):
                        out[lab] = m["eval_pass"]
                        break
    return out


def check_agent_semantic_gates(package: Path, report: Report) -> None:
    """Force visibility of §E (platform reports_review / instruction_tests_audit). Agent must still execute."""
    ep = _read_model_eval_passes(package)
    known = [v for v in ep.values() if isinstance(v, bool)]
    all_failed = len(known) == 3 and all(v is False for v in known)
    any_pass = any(v is True for v in known)

    report.add(
        "WARN",
        "SEMANTIC_REPORTS_REVIEW_REQUIRED",
        f"{package.name}：Agent **必须**完成 §E reports_review（人填 scores/reports 语义、叙事是否甩锅、"
        f"session 是否对齐）。脚本无法代做 Claude 语义；详见 SEMANTIC_REVIEW.md。",
        suggestion=(
            "只读 reports/** 与 scores/rubric_scores.json、session；"
            "输出 reports_review: PASS|WARN|FAIL + conclusion + 四段条目。见 SEMANTIC_REVIEW.md E1。"
        ),
        explanation=(
            "平台 precheck-judgment 无论硬项是否通过都跑 reports_review；"
            "不做则上传后可能被 Claude 语义分项挡住。"
        ),
        violation="平台 judgment.reports_review（恒 RUN）",
    )

    if all_failed:
        report.add(
            "WARN",
            "SEMANTIC_INSTRUCTION_AUDIT_REQUIRED",
            f"{package.name}：三模型 eval_pass 均为 false → Agent **必须**深入 instruction_tests_audit"
            f"（题面+Baseline+tests 是否不公）。",
            suggestion=(
                "对照 instruction / 未套 GT 的 workspace / tests；"
                "不公则 FAIL，合理难题 PASS，仅偏薄 WARN。模板见 SEMANTIC_REVIEW.md E2。"
            ),
            explanation="平台在 all_models_failed 时强制 instruction+tests 公平性审查，FAIL 会挡 PASSED。",
            violation="平台 judgment.instruction_tests_audit（三模全挂）",
        )
    else:
        skip_reason = (
            "非三模型全挂"
            if any_pass or len(known) < 3
            else "无法完整解析三模型 eval_pass"
        )
        report.add(
            "PASS",
            "SEMANTIC_INSTRUCTION_AUDIT_SKIP_HINT",
            f"{package.name}：instruction_tests_audit 可写 SKIP（{skip_reason}）；"
            f"仍建议软读 instruction/tests 偏薄项 → WARN。reports_review 仍必做。",
            suggestion="汇报写 instruction_tests_audit: SKIP 与简短 conclusion；薄题进软 WARN。",
            explanation="平台非全挂时该分项 SKIP，但软不足进 warnings。",
            violation="平台 judgment.instruction_tests_audit SKIP 规则",
        )

    report.add(
        "PASS",
        "SEMANTIC_PLATFORM_GOAL",
        f"{package.name}：目标=§A+§B+§D+§E 全过后尽量 platform 预审直过（终审另计）",
    )


def check_one_package(package: Path, root: Path, report: Report) -> None:
    report.add("PASS", "PKG_BEGIN", f"—— 检查数据包：{package.name}/ ——")
    check_dirname(package, report)
    check_core_files(package, report)
    check_dockerfile_pins(package, report)
    check_test_sh(package, report)
    check_package_secrets(package, report)
    check_instruction(package, report)
    check_task_toml(package, report)
    check_meta(root, package, report)
    check_rubrics(package, report)
    check_reports_eval(package, report)
    check_bypass_sessions(package, report)
    check_workspace_clean(package, report)
    traj = package / "trajectories"
    if traj.is_dir():
        if not report.sessions_dir:
            report.sessions_dir = str(traj)
        check_model_sessions(traj, report)
    else:
        report.add("FAIL", "TRAJ_ROOT", f"{package.name}/ 缺失 trajectories/（每模型须含 session/ + cc-gateway-log/）")
    check_no_agents_required(package, report)
    check_agent_semantic_gates(package, report)


def run_check(root: Path) -> Report:
    """全量静态审核：单项 FAIL 不阻断其余检测。Docker 见 SKILL §D（Agent 执行）。"""
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
            f"检测到旁路 {sess.name}/：正式勿交；每模型轨迹放 trajectories/<模型>/session/ 与 cc-gateway-log/",
        )

    scan_root = root if not _looks_like_package(root) else root.parent
    for package in packages:
        check_one_package(package, scan_root, report)

    report.add(
        "PASS",
        "DOCKER_AGENT_REMINDER",
        "Docker Baseline/GT 须由 Agent 按 SKILL §D 在临时深拷贝上执行（脚本不替代）",
    )
    report.add(
        "PASS",
        "FULL_PLATFORM_PATH",
        "可上传声明条件：§A 无 FAIL + §B call-level 过 + §D Docker 过 + §E 语义非 FAIL + §C 集合自检；见 SKILL",
    )

    report.finalize()
    return report


def _next_steps(report: Report) -> list[str]:
    fails = [f for f in report.findings if f.level == "FAIL"]
    warns = [f for f in report.findings if f.level == "WARN"]
    steps: list[str] = []
    if fails:
        steps.append(
            "按上方 **全部 FAIL**（一次列出、勿只改第一项）逐项改包内对应文件；"
            "改完后在同一路径重跑本预检，确认 FAIL=0。"
        )
        # bucket hints
        codes = {f.code for f in fails}
        if any(c.startswith("META_") for c in codes):
            steps.append(
                "补齐/修正 meta.json：annotator_background、completion_time_min、"
                "agreement_score，以及与目录同名的 task_id。"
            )
        if any(c in ("DOCKER_PIP_PIN", "DOCKER_NPM_PIN", "DOCKER_IMAGE_PIN") for c in codes):
            steps.append("钉死 Dockerfile 依赖：pip 仅 pkg==x.y.z；FROM 固定 tag；禁止 latest。")
        if any(
            c.startswith("SCORE")
            or c.startswith("CORR")
            or c.startswith("REPORT")
            or c.startswith("EVAL_")
            or c.startswith("AGREE_")
            or c in ("ALL_MODELS_PASS", "QWEN_MUST_FAIL")
            for c in codes
        ):
            steps.append("对齐 scores/rubric_scores.json 与 reports 的 eval_pass/五维分；收紧题难度以满足众包过题规则。")
        if any(c.startswith("TURNS") or c.startswith("SESSION") or c.startswith("TRAJ") or c.startswith("GW") for c in codes):
            steps.append("补 trajectories 下 session/ 与 cc-gateway-log；每模型仅 1 条主会话且 assistant≥20。")
    else:
        steps.append("结构静态项未出 FAIL：继续 §B merge_call_level 与 §D Docker（临时深拷贝）。")
    steps.append(
        "§B：merge_call_level.py --package … --check（临时目录，不写回包）。"
    )
    steps.append(
        "§D Docker：深拷贝到临时目录 → build → Baseline 须挂 → 套 GT 须过 → 清理。"
        "详见 SKILL §D（禁止改用户包）。"
    )
    steps.append(
        "§E 语义（对齐平台 Claude）：必做 reports_review；若 SEMANTIC_INSTRUCTION_AUDIT_REQUIRED "
        "则深入 instruction_tests_audit。清单 SEMANTIC_REVIEW.md；结论写入总汇报。"
    )
    if warns:
        steps.append(
            f"处理 {len(warns)} 条 WARN（含 SEMANTIC_* 待办；上传前建议 WARN→0 以贴近平台通过）。"
        )
    steps.append(
        "§C 集合：题量≥3、千问全挂、Opus≤60%、Opus−千问>20%、GLM≥1（脚本不查，须表格式自检）。"
    )
    steps.append(
        "全部完成后上传 https://www.shixianw.com/3bench/upload ；"
        "目标 platform 预审直过；甲方终审另计。"
    )
    return steps


def format_markdown(report: Report) -> str:
    fails = [f for f in report.findings if f.level == "FAIL"]
    warns = [f for f in report.findings if f.level == "WARN"]
    passes = [f for f in report.findings if f.level == "PASS"]
    lines = [
        "# 上传前预检报告",
        "",
        f"- 提交根目录：`{report.task_dir}`",
        f"- 甲方数据包：`{report.package_dir or '（未解析）'}`",
        f"- 轨迹目录：`{report.sessions_dir or '（未解析）'}`",
        f"- **结论**：`{report.verdict}`",
        f"- 统计：FAIL={report.summary.get('FAIL', 0)} / WARN={report.summary.get('WARN', 0)} / PASS={report.summary.get('PASS', 0)}",
        f"- 策略：**全量检测后一次汇报**（单项失败不中断其余审核点）",
        f"- 用户包：**只读**；Docker 仅在系统临时目录深拷贝执行",
        "",
        f"> {report.disclaimer}",
        "",
    ]
    if fails:
        lines.extend(["## 须修复（FAIL · 问题 / 原因 / 违反 / 建议）", ""])
        for i, f in enumerate(fails, 1):
            lines.append(f"### {i}. FAIL `{f.code}`")
            lines.append(f.human_block())
            lines.append("")
    else:
        lines.extend(["## 须修复（FAIL）", "", "无。", ""])

    if warns:
        lines.extend(["## 潜在疑点（WARN · 全量列出，不单独当硬挂）", ""])
        for i, f in enumerate(warns, 1):
            lines.append(f"### {i}. WARN `{f.code}`")
            lines.append(f.human_block())
            lines.append("")
    else:
        lines.extend(["## 潜在疑点（WARN）", "", "无。", ""])

    lines.extend(["## 下一步计划（不阻断 · 按序执行）", ""])
    for i, s in enumerate(_next_steps(report), 1):
        lines.append(f"{i}. {s}")
    lines.append("")

    lines.extend(
        [
            "## 通过项（PASS，摘要）",
            "",
        ]
    )
    if not passes:
        lines.append("- （无）")
    else:
        for f in passes:
            lines.append(f"- **PASS** `{f.code}` — {f.message}")
    lines.extend(
        [
            "",
            "## Agent 必做（脚本不替代 · 对齐 platform 全路径）",
            "",
            "- **§B** call-level 合并校验",
            "- **§D** 临时深拷贝 Docker：Baseline 挂 + GT 过",
            "- **§E** `reports_review`（恒做）+ 条件 `instruction_tests_audit` → `SEMANTIC_REVIEW.md`",
            "- **§C** 集合过题比例（见甲方要求说明）",
            "- 总报告**必须**含 §D/§E 分项 status + conclusion 后才能声称「可尽量 platform 预审过」",
            "",
            "## Agent 汇报约定",
            "",
            "- 复述 **全部** FAIL 与 WARN（四段），含 SEMANTIC_* 待办落地后的真实语义结论",
            "- 不因单项失败截断；**禁止修改用户数据包**",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="众包任务包上传前结构/人写交付预检（Docker 由 Agent 按 SKILL §D 执行）"
    )
    parser.add_argument(
        "--task-dir",
        type=Path,
        required=True,
        help="待提交根目录（内含甲方原格式数据包），或直接指向数据包目录",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="可选：写出 JSON 报告（须在数据包目录外；禁止写回用户包）",
    )
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
        "next_steps": _next_steps(report),
        "findings": [asdict(f) for f in report.findings],
        "failures": [
            {
                "code": f.code,
                "message": f.message,
                "explanation": f.explanation,
                "violation": f.violation,
                "suggestion": f.suggestion,
                "display": f.display(),
                "human": f.human_block(),
            }
            for f in report.findings
            if f.level == "FAIL"
        ],
        "warnings": [
            {
                "code": f.code,
                "message": f.message,
                "explanation": f.explanation,
                "violation": f.violation,
                "suggestion": f.suggestion,
                "display": f.display(),
                "human": f.human_block(),
            }
            for f in report.soft_warnings()
        ],
    }
    if args.json:
        json_path = args.json.expanduser().resolve()
        package_root = Path(report.package_dir).resolve() if report.package_dir else task_dir
        for root, label in ((task_dir, "task-dir"), (package_root, "package")):
            try:
                json_path.relative_to(root)
            except ValueError:
                continue
            print(
                f"ERROR: 预检 skill 禁止对用户数据包写入报告（--json={json_path} 落在 {label}={root} 内）。"
                f"请写到包外临时路径，或仅用 --markdown 打 stdout。",
                file=sys.stderr,
            )
            return 2
        try:
            pd = Path(report.package_dir)
            if pd.is_dir() and json_path.is_relative_to(pd.resolve()):
                print(
                    "ERROR: 预检 skill 禁止对用户数据包写入报告（--json 落在 package 内）。",
                    file=sys.stderr,
                )
                return 2
        except (ValueError, OSError, TypeError):
            pass
        packages = discover_packages(task_dir)
        for p in packages:
            try:
                if json_path.is_relative_to(p.resolve()):
                    print(
                        "ERROR: 预检 skill 禁止对用户数据包写入报告（--json 落在 package 内）。",
                        file=sys.stderr,
                    )
                    return 2
            except (ValueError, OSError):
                pass
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.markdown or not args.json:
        print(format_markdown(report))
    else:
        print(
            json.dumps(
                {
                    "verdict": report.verdict,
                    "summary": report.summary,
                    "next_steps": payload["next_steps"],
                    "fail_preview": [
                        {"code": f.code, "message": f.message, "suggestion": f.suggestion}
                        for f in report.findings
                        if f.level == "FAIL"
                    ],
                    "warnings": [
                        {"code": w["code"], "message": w["message"]}
                        for w in payload["warnings"]
                    ][:20],
                },
                ensure_ascii=False,
            )
        )

    return 0 if report.verdict != "PRECHECK_FAIL" else 1



if __name__ == "__main__":
    raise SystemExit(main())
