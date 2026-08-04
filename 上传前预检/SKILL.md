---
name: client-harbor-presubmit
description: >-
  上传前预检众包任务包。用户只需提供一个「甲方数据包」目录路径。
  有路径后：§A 结构；§B 在包内定位 session/ 与 cc-gateway-log/、合并到临时目录（不写回数据包）、
  再对合并后的 call-level 做甲方日志字段校验（须有 thinking 块；**signature 非空**；thinking 正文可空）。
  未给路径时必须先询问。不查集合过题比例；绿 ≠ 终审。
---

# 上传前预检（众包自包含包）

对用户**已整理好的甲方数据包**做两段检查：

1. **§A 结构**：文件是否按甲方包布局放齐  
2. **§B 合并 + 甲方日志字段**：用包内 **session + Gateway log** 生成 call-level，校验是否满足甲方 trace 规格  

用户交卷材料只有 **Claude Code session** 与 **本 Gateway 抓包**；**甲方 call-level 形态必须合并后才能得到**。正式预检**不得**把合并产物写进用户数据包。

---

## Agent 入口硬规则（必先执行）

### 用户只需提供一件事

**唯一必要输入：数据包目录路径**（绝对路径优先）。

| 检查 | 是否另要路径 |
| --- | --- |
| §A 结构 | 否，`--task-dir PACK` |
| §B 合并校验 | 否，同一 `PACK` 的 `--package` |
| 本机 `~/.claude` / `~/.claude_lproxy` | **不要索要** |
| Session ID | **不要索要**（从包内 session 自读） |

### 若用户未提供数据包路径

立刻停住，先要路径，再执行。禁止猜路径。

### 禁止

- 未给路径声称预检完成  
- 正式流程把 `call_level.jsonl` / `agents/` **写回用户数据包**（污染包）  
- 要求用户事先手写 call-level  
- 索要本机 session-root / gateway-root（调试除外）

---

## 开场可告知用户（拿到路径之后）

> 将用这一路径：  
> 1）检查包结构；2）在包内找各模型 `session/` 与 `cc-gateway-log/` 合并成 call-level（产物在临时目录，**不改您的包**），再判断合并结果是否达到甲方日志字段要求。  
> **绿 ≠ 结算；最终以甲方审核为准。**

---

## 标准流程

```text
PACK = 用户数据包目录
    → §A：presubmit_check.py --task-dir PACK
    → §B：merge_call_level.py --package PACK --check
         · 只读 trajectories/<模型>/session/ 与 cc-gateway-log/
         · 合并到系统临时目录（scratch）
         · 校验合并后 JSONL：thinking 块 + **signature 非空**（正文可空）
    → 汇报两段结果；说明临时目录路径（可选调试）
```

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
- **硬门槛**：每条 response 须有 `type=thinking` 且 **`signature` 非空**（**thinking 正文可为空**）

---

## 覆盖 / 不覆盖

| 覆盖 | 不覆盖 |
| --- | --- |
| 包布局；session + cc-gateway-log 成对 | 集合过题比例 |
| 包内两路日志合并 → 临时 call-level | 写回用户包 |
| 合并后甲方字段（tools/system/effort/**thinking 有块 + sig 非空**；正文可空） | Docker 真跑；甲方终审 |

---

## 报告怎么说

1. `PACK=…`  
2. §A markdown  
3. §B 每模型：包内 session 路径、gateway 路径、session-id、**临时 out 路径**、records、字段 PASS/FAIL  
4. 结构/合并绿 ≠ 终审  

工作目录：`采集用户说明_final/`（或仓库中等价根）。

## 权威口径

- [../用户操作步骤.md](../用户操作步骤.md)  
- [../Gateway采集说明.md](../Gateway采集说明.md)  
- [../甲方要求说明.md](../甲方要求说明.md)  
- [../甲方数据包参考样例/](../甲方数据包参考样例/)  
