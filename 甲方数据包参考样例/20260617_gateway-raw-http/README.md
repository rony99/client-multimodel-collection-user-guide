# 20260617_gateway-raw-http（甲方原格式数据包样例）

Labels: `python` / `feature` / `Backend_Infrastructure`  
Rubric task type: `code_generation`

本目录保持**甲方 Harbor 原格式**（题面 / 环境 / 测试 / GT / rubric / meta / `trajectories/` 等）。

正式交卷时，在本包**旁边**再交平级目录 [`../multi-sessions/`](../multi-sessions/)：三模型多次独立 session + 通过情况 `manifest.json`。

| 内容 | 路径 |
| --- | --- |
| 题面 | `instruction.md` |
| 环境 | `environment/` |
| 测试 | `tests/` |
| 标准答案 | `ground_truth/`（`solution/solve.sh` 可选） |
| Rubrics / meta | `rubrics/`、`meta.json`、`task.toml`、`manifest.json` |
| 包内轨迹（甲方结构） | `trajectories/<model>/` |

字段以 [甲方要求说明.md](../../甲方要求说明.md) 为准。
