# 甲方数据包参考样例说明

本目录仅保留**一道正式样例数据包** + 可抄模板。  
**每模型正式 1 份轨迹**，且必须包含两个子目录：

| 子目录 | 内容 |
| --- | --- |
| `session/` | Claude Code 主会话 `.jsonl`（有则 `subagents/`） |
| `cc-gateway-log/` | 该 Session 对应的 **cc-gateway 抓包** `*.json`（从 `<root_dir>/<sessionId>/` 拷入） |

| 路径 | 是什么 | 是否必交 |
| --- | --- | --- |
| [20260617_gateway-raw-http/](./20260617_gateway-raw-http/) | **甲方原格式数据包**示意 | <span style="color:#d93025">**交卷形态必仿**</span> |
| [模板/](./模板/) | 可抄的 meta / rubric | 参考用 |

## 正式交卷怎么摆

```text
<submit_root>/
  <task_id>/
    trajectories/
      claude-opus-4-8/
        session/
          session.jsonl
        cc-gateway-log/
          *.json
      glm-5.2/
        session/
          session.jsonl
        cc-gateway-log/
          *.json
      qwen-3.7-max/
        session/
          session.jsonl
        cc-gateway-log/
          *.json
```

- **不要**再交同题多次 run 的平级目录（旧称 `multi-sessions/`）。  
- Gateway 不再单独「题包外另交」；正式写入包内 `cc-gateway-log/`。  
- 集合比例见 [用户操作步骤.md](../用户操作步骤.md) 第 7 步。  
- 字段：[甲方要求说明.md](../甲方要求说明.md)。  
- 采集：[Gateway采集说明.md](../Gateway采集说明.md)。
