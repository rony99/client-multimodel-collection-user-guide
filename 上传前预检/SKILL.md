---
name: client-harbor-presubmit
description: >-
  上传前预检众包任务包。对齐 3bench 平台 packagecheck 可静态硬门槛 + §B call-level +
  对照 甲方要求说明.md double check。轮次每模型≥20、scores/reports、禁三模全过/千问须挂等
  与网站预审一致；仍不跑 Docker。绿 ≠ 终审。未给路径先询问。
---

# 上传前预检（众包自包含包）

对用户**已整理好的甲方数据包**做检查，**尽量与平台网站 `packagecheck` 同严**：

1. **§A 脚本**：结构 + **平台静态硬门槛**（见下表）  
2. **§B 合并 call-level**（effort / Opus signature 等）  
3. **§C** 对照 **[`../甲方要求说明.md`](../甲方要求说明.md)** 全面复核 + double check  
4. 仍**不**在本地替代 Docker/GT 真跑——网站会跑；用户须自测 Baseline FAIL、GT PASS  

## 硬规则：只读用户包（禁止任何写入）

- **一律只读**用户提供的数据包：`session/`、`cc-gateway-log/`、workspace 等  
- **禁止**写回 `call_level.jsonl`、`agents/`、修改 tests/Dockerfile/scores，或任何就地「整理」  
- §B 合并产物**仅**落系统临时目录（或显式 `--scratch-dir` 且须在包外）  
- `--json` / `--report` 等报告路径也**不得**落在数据包内；默认 stdout  
- Agent **不得**为「修好预检」去改用户包内容；只汇报 FAIL/WARN  

用户交卷只有 **session + Gateway**；call-level 须 §B 在**临时目录**合并校验。

---

## 与平台预审（3bench）对齐的 §A 硬项

| 项 | 级别 | 说明 |
| --- | --- | --- |
| 必备路径 + README、空壳 test.sh、脏 workspace、密钥 | **FAIL** | 与 platform structure/content_rules |
| **Dockerfile：FROM 禁 latest/无 tag**；**pip 须 `pkg==x.y.z` 定死**（裸名/`>=`/`~=` 等 FAIL，含 `-r` 文件）；npm 未钉版本 FAIL | **FAIL** | 甲方「依赖固定版本」；对齐 `dockerfile_pin.go`（主 Dockerfile + workspace/Dockerfile） |
| `meta.task_id` **=** 任务目录名 | **FAIL** | 平台 `META_TASK_ID_MISMATCH` |
| 每模型主会话 **仅 1 条** `.jsonl` | **FAIL** | |
| 每模型 assistant 轮次 **各自 ≥ 20**（`type=assistant` 去重） | **FAIL** | **非**三模型平均；平台 quality |
| `scores/rubric_scores.json`：三模型 `eval_pass` + 五维 1–5 + `agreement_score` | **FAIL** | 平台 rubric |
| correctness 与 `eval_pass` 不得冲突 | **FAIL** | 过题 corr≥4；挂题 corr≠5 |
| `reports/<model>/**/eval_result.json` 可解析 `eval_pass` | **FAIL** | 平台 models（须在包内 `reports/`，勿放包外） |
| reports 与 scores 的 `eval_pass` 一致 | **FAIL** | |
| 三模型都过 / 千问本题过 | **FAIL** | 众包单题硬门槛 |
| instruction 强泄题词（ground_truth 等） | **FAIL** | 软词 WARN |
| 旁路 `multi-sessions` | **FAIL** | |
| task_rubric 五维 `task_specific_criteria` | **FAIL** | |
| session/ + 非空 cc-gateway-log/ | **FAIL** | |
| **Docker Baseline/GT 真跑** | 本 Skill **不跑** | 平台会跑；§C 提醒用户已自测 |

Dockerfile 细则（脚本硬 FAIL，**版本须定死**，与甲方「固定版本」一致）：

- **镜像**：`FROM ubuntu:24.04` / `name@sha256:…` 合法；`FROM ubuntu`、`:latest` 不合法  
- **pip**：**仅** `pkg==x.y.z`（具体版本）合法；**禁止**裸名、`>=`/`~=`/`!=`/`>`/`<`、`==*` 通配  
  - `pip install -r requirements.txt` **会打开文件扫每一行**，同样只认 `pkg==x.y.z`；文件缺失 FAIL  
- **npm**：**仅** `pkg@x.y.z`；禁止裸名与 `@latest`

脚本 PASS **不保证**网站通过：网站还有 Docker/GT、可能有 Claude 语义分项、超时 30 分钟等。

---

## Agent 入口硬规则（必先执行）

### 用户只需提供一件事

**唯一必要输入：数据包目录路径**（绝对路径优先）。

| 检查 | 是否另要路径 |
| --- | --- |
| §A 结构 | 否，`--task-dir PACK` |
| §B 合并校验 | 否，同一 `PACK` 的 `--package` |
| 对照甲方要求全文 | 否；**Agent 必须读取** [`../甲方要求说明.md`](../甲方要求说明.md) |
| 本机 `~/.claude` / `~/.claude_lproxy` | **不要索要** |
| Session ID | **不要索要**（从包内 session 自读） |

### 若用户未提供数据包路径

立刻停住，先要路径，再执行。禁止猜路径。

### 禁止

- 未给路径声称预检完成  
- **只跑 §A/§B 脚本、不读「甲方要求说明」就声称全面合格**  
- **对用户数据包做任何创建/修改/删除**（含写回 call_level、agents、改 instruction/tests/Dockerfile/scores、就地「修包」）  
- 要求用户事先手写 call-level  
- 索要本机 session-root / gateway-root（调试除外）
- 使用已禁用的 `--write-into-package` 或把 `--scratch-dir`/`--json` 指进用户包

---

## 开场可告知用户（拿到路径之后）

> 将用这一路径：  
> 1）脚本按**与 3bench 平台对齐的硬门槛**查包结构 / scores / reports / 轮次；2）call-level 合并校验；3）再按 **甲方要求说明.md** double check。  
> **仍不替代网站 Docker 预审与甲方终审。**

---

## 标准流程

```text
PACK = 用户数据包目录
    → §A：presubmit_check.py --task-dir PACK
    → §B：merge_call_level.py --package PACK --check
    → §C：对照 ../甲方要求说明.md + 平台未跑项（尤其 Docker Baseline/GT）
    → 汇报（分：脚本硬 FAIL / WARN / 须用户自测 Docker / 集合比例）
```

### §C · 对照「甲方要求说明」全面复核（double check）

**权威文件（必读）：** [`../甲方要求说明.md`](../甲方要求说明.md)（**甲方公布的主要验收标准**）

1. 通读合格门槛、交付结构、附录 Checklist（C1～C7、§4、§5）。  
2. 映射到 `PACK`；下列**脚本未覆盖**项 → 标「须用户确认」：
   - **Docker 真构建**（建议 ≤30 min）+ Baseline `test.sh` FAIL + 套 GT 后 PASS  
   - **集合级比例**（题量≥3、千问全挂、Opus≤60%、Opus−千问>20%、GLM≥1 道过）  
   - 私有题意 / 未抄公开 Issue·DeepSWE；无外部登录·强时效网页  
   - 三模型**同一份** instruction + 同一 Baseline/测试/Docker（过程一致性）  
   - Opus 失败归因于题难而非环境；未伪造 session；未中途改测试凑分  
3. Second pass：对照脚本「未覆盖」与甲方红色硬门槛。  
4. 分条汇报机器预检 vs 全文复核。

### §A 结构

```bash
python3 上传前预检/scripts/presubmit_check.py \
  --task-dir <PACK> \
  --markdown
```

### §B 合并到临时文件 + 甲方字段校验

```bash
python3 上传前预检/scripts/merge_call_level.py \
  --package <PACK> \
  --check
```

单模型：

```bash
python3 上传前预检/scripts/merge_call_level.py \
  --package <PACK> \
  --model claude-opus-4-8 \
  --check
```

合并策略：

- `request.*` ← Gateway；response 可补 session  
- **effort** high|xhigh|max 且来自 `output_config.effort`  
- **thinking/sig**：有 thinking 时 Opus 强制 signature；无 thinking 不查；GLM/千问不硬检 sig  

---

## 覆盖 / 不覆盖

| 覆盖（尽量=平台静态机检） | 不覆盖（§C 须人工/用户自测） |
| --- | --- |
| 布局、GT 路径、README、密钥、脏 workspace | **Docker build / Baseline FAIL / GT PASS 真跑** |
| **Dockerfile FROM pin + pip CLI/`-r requirements` 内固定版本 + npm** | `apt`/`yarn` 等其它包管理钉版（无硬检） |
| scores/reports、轮次≥20/模型、众单题门槛 | **集合过题比例**（题量≥3、Opus/GLM/千问集合率） |
| 1 条主 session + 非空 gateway；禁 multi-sessions | 私有题意/撞题/语义质量（Claude 末级 judgment） |
| call-level 字段（§B，临时目录合并） | 平台 30min 墙钟；甲方终审/结算 |
| 只读用户包（禁止写回） | 兼容模式 `--session`/`--out` 可写任意路径（**正式流程只用 `--package`**） |

---

## 报告怎么说

1. `PACK=…`  
2. §A（标明是否含平台对齐 FAIL）  
3. §B  
4. §C  
5. 明确：**本地绿 ≠ 3bench PASSED ≠ 结算**

### 问题 + 修改建议（对齐平台预审反馈）

与网站 `Finding.message` + `Finding.suggestion` / `warnings[]` 同形：

| 层 | 写法 |
| --- | --- |
| 脚本 stdout / markdown | **FAIL**/**WARN** 行：`问题描述 建议：具体改法` |
| JSON | `findings[].message` + `findings[].suggestion`；`warnings[]` 仅 WARN |
| Agent 对用户口述 | **必须带建议**：勿只报 code 或「有问题」；勿写黑话 |
| 硬 FAIL vs 潜在疑点 | FAIL 须修才能谈过预检；WARN（如 AI 草拟分、挂题 correctness=4）不硬挡但建议改 |

脚本内已对常见 code 带默认建议（Dockerfile pin、task_id、轮次、scores/reports、AI 草拟等）；平台 soft 的 `CORR_SOFT_TENSION` / `CORR_PASS_NOT_5` / `RUBRIC_AI_DRAFTED` 本 skill 同步。

工作目录：`采集用户说明_final/`。

## 权威口径

- **[../甲方要求说明.md](../甲方要求说明.md)** — 甲方主要验收标准  
- 平台实现参考：`甲方要求/platform/api/internal/packagecheck/`（structure / quality / rubric soft+suggestion / content_rules）  
- [../用户操作步骤.md](../用户操作步骤.md) · [../Gateway采集说明.md](../Gateway采集说明.md)  
