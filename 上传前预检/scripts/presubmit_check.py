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
INSTRUCTION_LEAK_TERMS = (
    "ground_truth",
    "assert ",
    "assert(",
    "pytest",
    "test.sh",
    "unittest",
    "hidden test",
    "参考答案",
)

DISCLAIMER = (
    "本检查只做**结构预检**（文件是否存在、字段是否齐全、结构是否合理），"
    "**不查集合过题比例**，**不代表结算或最终合格**。"
    "请自行核验：题量要求≥3；**每题千问均挂**；禁三模型全过、Opus≤60%、Opus−千问>20%、GLM≥1 道过等；"
    "平台不代提供模型 API；"
    "每模型轨迹须含 session/ + cc-gateway-log/；"
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

    root = package.parent
    if (package / "reports").is_dir() or (root / "reports").is_dir():
        report.add("PASS", "REPORTS", "存在 reports/（package 内或根下）")

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


def _dockerfile_image_unpinned(image_ref: str) -> str | None:
    """Return fail reason if image ref is unpinned; None if OK."""
    ref = image_ref.strip().strip("'\"")
    if not ref or ref.upper() == "SCRATCH":
        return None
    # multi-stage: "name AS alias" already stripped to img by regex; may still have AS
    ref = re.split(r"\s+", ref, maxsplit=1)[0]
    lower = ref.lower()
    if lower.endswith(":latest") or lower.endswith("@latest"):
        return f"使用 :latest：`{ref}`"
    # digest form registry/path@sha256:...
    if "@sha256:" in lower or re.search(r"@sha[0-9]+:", lower):
        return None
    # tagged: last path segment after last / must contain :tag (not only registry host:port)
    # Heuristic: has ":" after last "/" → tagged (port in host:5000/img is before last /)
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        tag = last.rsplit(":", 1)[-1]
        if tag.lower() == "latest":
            return f"使用 :latest：`{ref}`"
        return None
    return f"base 镜像未固定 tag/digest：`{ref}`（禁止隐式 latest）"


def _dockerfile_unpinned_pip_tokens(body: str) -> list[str]:
    """Heuristic: bare `pip install pkg` without version constraint → tokens to WARN."""
    warns: list[str] = []
    for m in re.finditer(r"\bpip(?:3)?\s+install\b([^\n\\]*)", body, re.IGNORECASE):
        rest = m.group(1)
        if re.search(r"(^|\s)-r\s", rest):
            continue
        if re.search(r"(^|\s)-e\s", rest) or "requirements" in rest.lower():
            continue
        for tok in rest.split():
            if tok.startswith("-") or tok.startswith("http://") or tok.startswith("https://"):
                continue
            # keep package-like names
            if re.search(r"==|>=|<=|~=|!=|@|>|<", tok):
                continue
            clean = tok.strip("'\"")
            if not clean or clean in (".", "..") or clean.startswith("."):
                continue
            # -i index URL leftover, common mirror flags already skipped via -
            if "/" in clean and not clean.startswith("git+"):
                continue
            warns.append(clean)
    return warns


def check_dockerfile_pins(package: Path, report: Report) -> None:
    """甲方：依赖须固定版本；禁止 Docker 镜像/包用 latest。"""
    path = package / "environment" / "Dockerfile"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    lines_no_comment: list[str] = []
    for line in text.splitlines():
        lines_no_comment.append(line.split("#", 1)[0])
    body = "\n".join(lines_no_comment)

    fail_hits: list[str] = []
    for m in FROM_LINE_RE.finditer(body):
        reason = _dockerfile_image_unpinned(m.group("img"))
        if reason:
            fail_hits.append(f"FROM：{reason}")

    for i, raw in enumerate(text.splitlines(), start=1):
        code = raw.split("#", 1)[0]
        if not EXPLICIT_LATEST_RE.search(code):
            continue
        # FROM 行已由 base 镜像规则覆盖
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
                "DOCKER_UNPINNED",
                f"Dockerfile 依赖未钉死版本：{h}。须固定 tag/digest（如 ubuntu:24.04），禁止 latest",
            )
        if len(uniq) > 8:
            report.add(
                "FAIL",
                "DOCKER_UNPINNED_MORE",
                f"另有 {len(uniq) - 8} 处未钉版本（略）",
            )
    else:
        report.add(
            "PASS",
            "DOCKER_PIN",
            "Dockerfile base 镜像未见 :latest / 无 tag；符合固定版本要求（静态规则）",
        )

    pip_warns = _dockerfile_unpinned_pip_tokens(body)
    if pip_warns:
        shown = ", ".join(pip_warns[:6])
        more = f" 等共 {len(pip_warns)} 项" if len(pip_warns) > 6 else ""
        report.add(
            "WARN",
            "DOCKER_PIP_UNPINNED",
            f"Dockerfile 中 pip install 疑似未钉版本：{shown}{more}（甲方要求依赖固定版本，建议 pkg==x.y.z）",
        )
    else:
        report.add("PASS", "DOCKER_PIP_PIN", "Dockerfile 未见明显未钉版本的 pip install 包名")


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
    leak_hits = [term for term in INSTRUCTION_LEAK_TERMS if term in low]
    if leak_hits:
        report.add(
            "WARN",
            "INSTRUCTION_LEAK",
            "instruction.md 可能提及敏感词「"
            + "」「".join(leak_hits[:4])
            + "」，请确认未泄测试断言 / 答案路径",
        )
    else:
        report.add("PASS", "INSTRUCTION_LEAK", "instruction.md 未见明显泄题关键词")
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
    check_workspace_clean(package, report)
    traj = package / "trajectories"
    if traj.is_dir():
        if not report.sessions_dir:
            report.sessions_dir = str(traj)
        check_model_sessions(traj, report)
    else:
        report.add("FAIL", "TRAJ_ROOT", f"{package.name}/ 缺失 trajectories/（每模型须含 session/ + cc-gateway-log/）")
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
            f"检测到旁路 {sess.name}/：正式勿交；每模型轨迹放 trajectories/<模型>/session/ 与 cc-gateway-log/",
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
            "- 严格平均 assistant 执行轮次 ≥ 20（本脚本仅粗估行数 WARN）；私有题意 / 非公开 Issue 改造",
            "- Docker 内 Baseline FAIL / GT PASS 的完整复现（本脚本默认不做 Docker 构建）",
            "- apt/npm 全量 pin、pip 全量钉版本（Dockerfile 对 bare pip 仅 WARN；不替代人工）",
            "- Rubric 人工/LLM 打分是否与测试结论一致；三模型条件完全一致的过题实测",
            "- 每模型轨迹：session/ + cc-gateway-log/；平台不代提供模型 API（用户自备经 Gateway）",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="众包任务包上传前结构预检（trajectories 须含 session/ + cc-gateway-log/）"
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
