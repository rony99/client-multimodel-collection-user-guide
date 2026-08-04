# 20260617_gateway-raw-http（甲方原格式数据包样例）

Labels: `python` / `feature` / `Backend_Infrastructure`  
Rubric task type: `code_generation`

本目录保持 **Harbor 甲方原格式**。轨迹示意：**三模型各 1 条**主会话。

```text
trajectories/
  claude-opus-4-8/session.jsonl
  glm-5.2/session.jsonl
  qwen-3.7-max/session.jsonl   # 本例另有 subagents/（有委派时交齐）
```

正式交卷只需本结构；**不要**再交同题多 run 的 `multi-sessions/`。

| 内容 | 路径 |
| --- | --- |
| 题面 | `instruction.md` |
| 环境 | `environment/` |
| 测试 | `tests/` |
| 标准答案 | `ground_truth/`（`solution/solve.sh` 可选） |
| Rubrics / meta | `rubrics/`、`meta.json`、`task.toml`、`manifest.json` |
| 正式轨迹 | `trajectories/<model>/`（**每模型 1 条**主会话） |

字段以 [甲方要求说明.md](../../甲方要求说明.md) 为准。采集与 Gateway 日志见 [Gateway采集说明.md](../../Gateway采集说明.md)。
