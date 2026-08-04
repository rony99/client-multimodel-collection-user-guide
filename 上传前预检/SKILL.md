---
name: client-harbor-presubmit
description: >-
  上传前结构预检众包 Harbor 任务包：检查甲方原格式数据包与 trajectories/
  （每模型 1 条 session），可选将 session-root+Gateway-root+SessionID 合并为甲方 call-level。
  不查集合过题比例。用户提供路径后由 Agent 执行；结构绿 ≠ 甲方终审。
---

# 上传前结构预检（众包自包含包）

对本目录上级手册约定的**待上传提交根目录**做**结构与完整性**检查；需要交付甲方 call-level 时，先跑 **session + Gateway 合并**。

## 开场必须告诉用户（原文级要点）

> **结构预检**只查文件是否存在、字段是否齐全、结构是否合理。  
> **不查集合过题比例**（须你自行核：≥3 题；**每题千问均挂**；禁三模型全过；Opus≤60%；Opus−千问>20%；GLM≥1 道过）。  
> **结构绿 ≠ 比例合格 ≠ 结算**；**最终以甲方实际审核为准。**  
> 平台**不**代提供模型 API；用户自备账号经 Gateway。  
> 若需要 call-level：用原生 session + Gateway 抓包**合并**，不可编造 system/tools。

## 用户需要提供什么

### 结构预检（§A）

| 输入 | 说明 |
| --- | --- |
| **提交根目录** `--task-dir` | 内含一个或多个甲方原格式数据包 |

### 合并 call-level（§B）——优先只要这三项

两边都用 **同一个 Session ID** 命名：

| 输入 | 典型路径 | 脚本如何解析 |
| --- | --- | --- |
| **session 根目录** | `~/.claude/projects/<工作目录编码>/` | 主会话：`<sessionId>.jsonl`；若有 subagent：同名文件夹 `<sessionId>/`（常含 `subagents/*.jsonl`） |
| **Gateway 根目录** | `~/.claude_lproxy/projects/` | 会话抓包：`<sessionId>/*.json`（该 session 下全部 call） |
| **Session ID** | 与上述文件/文件夹同名 | 必须两边一致 |

```text
# Claude 原生（session 根目录）
session_root/
  <sessionId>.jsonl              # 主 Agent（必有）
  <sessionId>/                   # 可选：有 subagent 时
    subagents/
      explorer-001.jsonl
      ...

# Gateway（gateway 根目录）
gateway_root/
  <sessionId>/
    call-aaa.json
    call-bbb.json
    ...
```

一题三模型时：对**每个 Session ID** 各跑一次合并（每个模型正式 1 条轨迹对应 1 个 Session ID）。

## 最新交卷结构（预检强制）

```text
<submit_root>/
  <task_a>/
    trajectories/
      claude-opus-4-8/
        session.jsonl          # 主会话（可从原生 <sid>.jsonl 拷入）
        call_level.jsonl       # 可选：合并产物
        subagents/             # 有则交齐 / 合并也可写出 sub call_level
      glm-5.2/
      qwen-3.7-max/
    agents/                    # 可选：合并写出 main_agent.json
```

<span style="color:#d93025">不要交同题多 run 旁路目录</span>；正式只认每模型 **1 条**主会话（`call_level.jsonl` 不计入第二条主 session）。

示意：[../甲方数据包参考样例/](../甲方数据包参考样例/)

## Agent 何时跑哪一段

| 用户意图 | 跑什么 | 向用户索取 |
| --- | --- | --- |
| 文件齐不齐 / 交卷结构 | 仅 **§A** | 提交根或数据包路径 |
| 合并 / 校验甲方 call-level | **§B**（可再跑 §A） | session 根 + Gateway 根 + 每个正式 Session ID；若要写入包内再要任务包路径 |
| 全部上传前检查 | **§B（各模型 sid）→ §A** | 上两项都要 |

**禁止**：用户只给了任务包、却声称已做 call-level 校验（除非包内已有通过校验的 `call_level.jsonl` 且仍建议重跑 §B）。

## Agent 工作流

工作目录：`采集用户说明_final/`。

### A. 结构预检（默认必做）

```bash
python3 上传前预检/scripts/presubmit_check.py \
  --task-dir <用户提交根目录绝对路径> \
  --markdown
```

### B. Session + Gateway → 甲方 call-level

**先向用户要齐三项：**

1. `session_root`（Claude 原生 projects 目录）  
2. `gateway_root`（默认 `~/.claude_lproxy/projects`）  
3. `session_id`（主文件 / 同名文件夹 / Gateway 子目录同名）

可选：`--out` 写入数据包某模型 `trajectories/<model>/call_level.jsonl`。

```bash
python3 上传前预检/scripts/merge_call_level.py \
  --session-root <Claude 原生 session 根目录> \
  --gateway-root <Gateway 日志根目录> \
  --session-id <SessionID> \
  --out <输出 call_level.jsonl> \
  --agents-out <package/agents 可选> \
  --snapshot-out <可选 agent_config_snapshot.json> \
  --report <可选 merge_report.json> \
  --check

python3 上传前预检/scripts/validate_call_level.py \
  --call-level <上一步 out> \
  --session <session_root>/<sessionId>.jsonl \
  --markdown
```

脚本会自动：

- 读主文件：`session_root/<sessionId>.jsonl`  
- 若存在 `session_root/<sessionId>/`：收集其中（含 `subagents/`）全部 `.jsonl`  
- 读 Gateway：`gateway_root/<sessionId>/*.json` 全部 call  
- 主链合成 `call_level.jsonl`；有 subagent 时尽量另写 `…/subagents/*_call_level.jsonl`  
- 从 Gateway 提取 `agents/main_agent.json`（能区分时再写 `subagent.json`）  

**保留**原生 session 文件，勿删。合并失败时展示 report，**不要**声称可交 call-level。合并成功后再跑 **§A**。

合并策略：

- `request.*` ← **Gateway**（system / tools / messages）  
- `response.response_data` ← Gateway 完整响应，否则用 **session assistant**  
- **禁止**编造 system/tools  
- `--check` 通过 = **甲方 call-level 字段检测 PASS**（交付规范 §7：effort/system/tools/messages/stop_reason 等）  

**检测范围边界（Agent 必须说清）：**

| 覆盖 | 不覆盖 |
| --- | --- |
| Session ID 对齐的路径解析 | 整包 Harbor 结构（用 §A） |
| 甲方 call-level JSONL 字段 | 集合过题比例 |
| 无候选 call / 无 assistant → FAIL | Docker Baseline/GT 实测 |
| | 甲方人工终审 |

回归 fixture：[fixtures/merge_sample/](./fixtures/merge_sample/)（含根目录 + session-id 模式）。

> 兼容：`--session` + `--gateway-dir` 仍可用，但**用户场景优先三项根目录 API**。

## 预检覆盖什么

1. 全部甲方原格式数据包布局  
2. instruction / workspace / Dockerfile / test.sh / rubrics / meta / GT  
3. `trajectories/` 三模型、每模型 1 条主 `.jsonl`（`call_level` 白名单）  
4. 可选 `call_level.jsonl` 存在性（字段用 `validate_call_level.py`）  
5. `agents/` 不强制手写  
6. 旁路 multi-sessions → WARN  

## 预检明确不覆盖

| 项目 | 说明 |
| --- | --- |
| 集合过题比例 | 用户自核 |
| Docker Baseline/GT | 用户自测 |
| 终审 | **以甲方实际审核为准** |
| Session ID 填错 / 两根目录不齐 | 合并 FAIL/WARN |

## 报告怎么跟用户说

1. 合并时贴：解析到的 main 路径、subagent 文件列表、Gateway 目录、records、FAIL/WARN  
2. 贴结构预检全文  
3. 结构/合并绿 ≠ 比例合格 ≠ 结算  

## 权威口径

- [../甲方要求说明.md](../甲方要求说明.md)  
- [../用户操作步骤.md](../用户操作步骤.md)  
- [../Gateway采集说明.md](../Gateway采集说明.md)  
- [../甲方数据包参考样例/](../甲方数据包参考样例/)  
