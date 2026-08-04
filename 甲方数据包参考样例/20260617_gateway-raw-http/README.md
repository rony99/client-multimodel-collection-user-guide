# 20260617_gateway-raw-http（甲方原格式数据包样例）

Labels: `python` / `feature` / `Backend_Infrastructure`  
Rubric task type: `code_generation`

本目录保持 **Harbor 甲方原格式**。每模型轨迹须同时提交：

1. **`session/`** — Claude Code 主会话（及有则 subagents）  
2. **`cc-gateway-log/`** — 本场 cc-gateway 抓包目录内容  

```text
trajectories/
  claude-opus-4-8/
    session/
      session.jsonl              # Claude Code 主会话
      subagents/                 # 有委派时交齐
    cc-gateway-log/              # 该 Session 的 Gateway 抓包（整夹内 *.json）
      *.json
  glm-5.2/
    session/
      session.jsonl
    cc-gateway-log/
      *.json
  qwen-3.7-max/
    session/
      session.jsonl              # 本例另有 subagents/
      subagents/
    cc-gateway-log/
      *.json
```

正式交卷仿本结构；**不要**再交同题多 run 的 `multi-sessions/`。

| 内容 | 路径 |
| --- | --- |
| 题面 | `instruction.md` |
| 环境 | `environment/` |
| 测试 | `tests/` |
| 标准答案 | `ground_truth/`（`solution/solve.sh` 可选） |
| Rubrics / meta | `rubrics/`、`meta.json`、`task.toml`、`manifest.json` |
| 正式轨迹 | `trajectories/<model>/session/` + `trajectories/<model>/cc-gateway-log/` |

字段以 [甲方要求说明.md](../../甲方要求说明.md) 为准。采集见 [Gateway采集说明.md](../../Gateway采集说明.md)。
