---
name: client-harbor-presubmit
description: >-
  上传前预检众包任务包。用户只需提供一个「甲方数据包」目录路径。
  有路径后：§A 结构脚本；§B call-level 合并校验；再**对照
  甲方要求说明.md 做全面人工复核与 double check**（脚本未覆盖项必查）。
  脚本绿 ≠ 终审。未给路径时必须先询问。
---

# 上传前预检（众包自包含包）

对用户**已整理好的甲方数据包**做检查：

1. **§A 结构脚本**：布局、固定版本镜像、空壳测试、脏 workspace、密钥粗扫等  
2. **§B 合并 + call-level 字段**：包内 session + Gateway log → 临时 call-level 再校验  
3. **对照权威要求全文再查一遍（double check）** — 以  
   **[`../甲方要求说明.md`](../甲方要求说明.md)** 为准做**全面核对**  
   （含脚本未覆盖项：集合比例、Baseline/GT 真跑、私有题意、依赖是否真正钉版本等）

用户交卷材料只有 **Claude Code session** 与 **本 Gateway 抓包**；**甲方 call-level 形态必须合并后才能得到**。正式预检**不得**把合并产物写进用户数据包。

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
- 正式流程把 `call_level.jsonl` / `agents/` **写回用户数据包**（污染包）  
- 要求用户事先手写 call-level  
- 索要本机 session-root / gateway-root（调试除外）

---

## 开场可告知用户（拿到路径之后）

> 将用这一路径：  
> 1）脚本查包结构与 call-level；2）再按 **甲方要求说明.md** 做**全面复核 / double check**（含脚本覆盖不到的门槛）。  
> **绿 ≠ 结算；最终以甲方审核为准。**

---

## 标准流程

```text
PACK = 用户数据包目录
    → §A：presubmit_check.py --task-dir PACK
    → §B：merge_call_level.py --package PACK --check
         · 只读 trajectories/<模型>/session/ 与 cc-gateway-log/
         · 合并到系统临时目录（scratch）
         · 校验合并后 JSONL：effort high+；有 thinking 时 Opus 强制 **signature 非空**
    → §C double check（Agent 必做，不可跳过）：
         · 打开并对照 ../甲方要求说明.md（全文 + 附录 Checklist）
         · 按该文件逐项核对包与用户声明：
           必备材料、禁止事项、单题硬门槛、集合比例、采集纪律、
           交付结构、题意私有、Docker 依赖钉版本（不止 latest）、
           Baseline FAIL / GT PASS（脚本不做 Docker 时须询问用户是否已自测）等
         · 特别复查：脚本「未覆盖」清单 vs 甲方要求说明中的红色硬门槛
         · 脚本 FAIL 与全文复核差异一并汇报
    → 汇报：§A / §B 结论 + §C 对照「甲方要求说明」的遗漏/风险项
```

### §C · 对照「甲方要求说明」全面复核（double check）

**权威文件（必读）：** [`../甲方要求说明.md`](../甲方要求说明.md)

Agent **不得**把 §A/§B 脚本 PASS 当作「已满足甲方全部要求」。在脚本跑完后必须：

1. **通读 / 检索**该文件的合格门槛、交付结构、附录 Checklist（至少 C1～C7、§4、§5）。  
2. **按该文件做全面检查**，把每一条要求映射到当前 `PACK`（能打开的文件就打开核对；需真跑 Docker / 集合过题率的，标注「须用户确认」或「结构无法自动判定」）。  
3. **再做 second pass**：对照脚本报告中的「结构预检未覆盖」与甲方红色硬门槛，确认没有漏报。  
4. 汇报时分开写：  
   - 机器预检（§A/§B）  
   - 对照《甲方要求说明》的人工/Agent 复核结论（问题列表 + 通过项摘要）  

若与脚本冲突：以 **[甲方要求说明.md](../甲方要求说明.md)** 与用户最终声明为准，并写明依据章节。

### §A 结构

```bash
python3 上传前预检/scripts/presubmit_check.py \
  --task-dir <PACK> \
  --markdown
```

§A 除布局与轨迹目录外，还会静态检查（节选）：

| 规则 | 级别 |
| --- | --- |
| base 镜像 `:latest` / 无 tag；安装命令 `@latest` | **FAIL** |
| `README.md` 缺失 | **FAIL** |
| `tests/test.sh` 空壳（仅 `exit 0` / `true`） | **FAIL** |
| workspace 含 `node_modules` / `__pycache__` / `.git` / `ground_truth` 等（含嵌套） | **FAIL** |
| Dockerfile / workspace 常见密钥文件疑似硬编码密钥 | **FAIL** |
| `pip install` 未写版本号 | **WARN**（启发式） |
| `manifest.json` 缺失 | **WARN** |
| `instruction.md` 提及 ground_truth / assert / test.sh 等 | **WARN** |
| 不做 `docker build`、不查集合过题比例 | 人工 / 对照甲方要求说明 + 终审 |

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

脚本行为（正式预检默认）：

```text
读取（不得改写）：
  trajectories/<模型>/session/…jsonl
  trajectories/<模型>/cc-gateway-log/*.json

写出（临时目录，例如 /tmp/cc-calllevel-merge-XXXX/）：
  <模型>/call_level.jsonl

然后：
  对合并后的 records 做甲方 call-level 字段检测
```

| 选项 | 含义 |
| --- | --- |
| 默认 | scratch `mkdtemp`，**不污染包** |
| `--scratch-dir DIR` | 指定临时产物根 |
| `--write-into-package` | **显式**才写回包内 `call_level.jsonl`（调试；正式预检勿用） |
| `--write-agents` | 可选写 agents；勿与污染包默认混用 |

合并策略：

- `request.*` ← Gateway 抓包  
- `response` 必要时用 session 补齐  
- 禁止编造 system/tools  
- **effort / thinking_effort**：须为 `high` / `xhigh` / `max`，且来自 `request.output_config.effort`（禁止脚本缺省硬填）  
- **thinking / signature 硬门槛**（仅合并校验用）：
  - **仅当** `response_data.content` 中已有 `type=thinking` 块时才检查 signature  
  - **无 thinking 块 → 不查** signature（不因此 FAIL）  
  - **Opus**：有 thinking 时 **`signature` 须非空**（thinking 正文可空）  
  - **GLM / 千问**：有 thinking 也不把 signature 当作硬性要求

---

## 覆盖 / 不覆盖

| 覆盖 | 不覆盖（须靠 §C 对照《甲方要求说明》补全） |
| --- | --- |
| 包布局；session + cc-gateway-log 成对 | 集合过题比例 |
| **Dockerfile 禁 latest / 无 tag**；pip bare 包 **WARN** | apt/npm 全量 pin；**Docker 真跑** |
| **README 必填**；空壳 test.sh；workspace 脏目录；密钥粗扫 | Baseline/GT 真跑对错 |
| 包内两路日志合并 → 临时 call-level | 写回用户包 |
| 甲方字段（tools/system/**effort high+**/stop；**Opus 有 thinking 则 sig 非空**） | 私有题意语义、Rubric 与测试一致性等终审项 |

---

## 报告怎么说

1. `PACK=…`  
2. §A markdown  
3. §B 每模型：包内 session 路径、gateway 路径、session-id、**临时 out 路径**、records、字段 PASS/FAIL  
4. **§C：已对照 [甲方要求说明.md](../甲方要求说明.md) 的全面复核结论**（问题 / 待用户确认 / 无明显问题）  
5. 结构/合并/对照绿 ≠ 甲方终审  

工作目录：`采集用户说明_final/`（或仓库中等价根）。

## 权威口径

- **[../甲方要求说明.md](../甲方要求说明.md)** ← **全面检查与 double check 的主依据**  
- [../用户操作步骤.md](../用户操作步骤.md)  
- [../Gateway采集说明.md](../Gateway采集说明.md)  
- [../甲方数据包参考样例/](../甲方数据包参考样例/)  
