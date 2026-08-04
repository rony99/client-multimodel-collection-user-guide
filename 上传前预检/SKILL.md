---
name: client-harbor-presubmit
description: >-
  上传前预检众包任务包。用户只需提供一个「甲方数据包」目录路径。
  有路径后：§A 结构 + §B 包内 session/cc-gateway-log 合并校验。
  用户未给路径时必须先询问，禁止猜测本机 projects 或自行扩路径。
  不查集合过题比例；结构/合并绿 ≠ 终审。
---

# 上传前预检（众包自包含包）

对用户**已整理好的甲方数据包**做 §A 结构 + §B 包内 call-level 合并校验。

---

## Agent 入口硬规则（必先执行）

### 用户只需提供一件事

**唯一必要输入：数据包目录路径**（绝对路径优先），例如：

- `/Users/me/submit/20260617_gateway-raw-http`
- 或用户工作区中指向该目录的路径

| 检查 | 是否另要路径 |
| --- | --- |
| §A 结构 | 否，用该路径 `--task-dir` |
| §B 合并校验 | 否，用**同一路径** `--package` |
| 本机 `~/.claude` / `~/.claude_lproxy` | **不要索要**（正式流程不用） |
| Session ID 列表 | **不要索要**（从包内 session 自读） |

### 若用户未提供数据包路径

1. **立刻停住**，不要跑预检脚本、不要猜路径、不要去扫 `~/.claude`。  
2. **先用一句话向用户要路径**，例如：

> 请提供已整理好的**甲方数据包目录**的完整路径（需含 `instruction.md`、`tests/`、`trajectories/` 等）。  
> 示例：`/path/to/your-task-id`。拿到路径后我会做结构预检和包内日志合并校验。

3. 用户给出有效路径后，再执行下文 §A → §B。  
4. 路径无效（不存在 / 不是目录）→ 说明问题并**再要一次**。

### 禁止

- 在未拿到用户路径时声称「已完成预检」  
- 默认改用本机原始 session 根 / Gateway 根  
- 向用户索要 Session ID、session-root、gateway-root（正式流程）

---

## 开场可告知用户（拿到路径之后）

> 我将用您提供的**这一个数据包路径**做：  
> 1）结构是否齐全；2）包内 `session/` + `cc-gateway-log/` 合并 call-level。  
> 不到您机器上的 Claude/Gateway 原始目录另找文件。  
> 不查集合过题比例；**绿 ≠ 结算；最终以甲方审核为准。**

---

## 标准流程（路径已具备时）

```text
用户给出 PACK = 数据包目录
    → §A：presubmit_check.py --task-dir PACK
    → §B：merge_call_level.py --package PACK --check
    → 汇报两段结果
```

默认**两段都跑**（用户明确只要「看文件齐不齐」时可只跑 §A）。

### §A 结构预检

```bash
python3 上传前预检/scripts/presubmit_check.py \
  --task-dir <用户给的数据包绝对路径> \
  --markdown
```

### §B 包内合并校验

```bash
python3 上传前预检/scripts/merge_call_level.py \
  --package <同一数据包绝对路径> \
  --check
```

单模型（用户点名时）：

```bash
python3 上传前预检/scripts/merge_call_level.py \
  --package <同一数据包绝对路径> \
  --model claude-opus-4-8 \
  --check
```

脚本从包内读取：

```text
trajectories/<模型>/
  session/session.jsonl     # Session ID 从文件内容解析
  session/subagents/        # 有则
  cc-gateway-log/*.json
```

写出（§B）：`trajectories/<模型>/call_level.jsonl`。

合并策略：`request.*` ← 包内 Gateway 抓包；`response` 必要时用 session；禁止编造 system/tools。

兼容 CLI（`--session-root` / `--gateway-root` / `--session-id`）**仅调试**；Agent **正式不得引导用户使用**。

---

## 覆盖 / 不覆盖

| 覆盖 | 不覆盖 |
| --- | --- |
| 包布局、三模型 `session/`+`cc-gateway-log/` | 集合过题比例 |
| 包内 Session ID 对齐与合并 | Docker Baseline/GT 实测 |
| call-level 字段检测 | 甲方终审 |

---

## 报告怎么说

1. 确认使用的路径：`PACK=…`  
2. 贴 §A markdown 全文  
3. 贴 §B 每模型：包内路径、session-id、records、FAIL/WARN、字段 PASS/FAIL  
4. 结构/合并绿 ≠ 比例合格 ≠ 结算  

工作目录：包内文档所在的 `采集用户说明_final/`（或用户仓库中等价根）。

## 权威口径

- [../用户操作步骤.md](../用户操作步骤.md)  
- [../Gateway采集说明.md](../Gateway采集说明.md)  
- [../甲方要求说明.md](../甲方要求说明.md)  
- [../甲方数据包参考样例/](../甲方数据包参考样例/)  
