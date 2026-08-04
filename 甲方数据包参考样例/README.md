# 甲方数据包参考样例说明

本目录仅保留**一道正式样例数据包** + 可抄模板。  
**每模型正式只交 1 条** Claude Code 轨迹（主会话 `.jsonl`；有 subagent 可同模型目录下附带）。

| 路径 | 是什么 | 是否必交 |
| --- | --- | --- |
| [20260617_gateway-raw-http/](./20260617_gateway-raw-http/) | **甲方原格式数据包**示意（题面 / 环境 / 测试 / GT / rubric / meta / `trajectories/`） | <span style="color:#d93025">**交卷形态必仿**</span> |
| [模板/](./模板/) | 可抄的 meta / rubric | 参考用 |

## 正式交卷怎么摆

```text
<submit_root>/
  <task_id>/                 # 一道题一个目录
    trajectories/
      claude-opus-4-8/
        session.jsonl        # 仅 1 条主会话（可另有 subagents/）
      glm-5.2/
        session.jsonl
      qwen-3.7-max/
        session.jsonl
```

- **不要**再交同题多次 run 的平级目录（旧称 `multi-sessions/`）。  
- 集合比例（多道题过/不过）见 [用户操作步骤.md](../用户操作步骤.md) 第 7 步。  
- 字段与门槛：[甲方要求说明.md](../甲方要求说明.md)。  
- Gateway 采集：[Gateway采集说明.md](../Gateway采集说明.md)。
