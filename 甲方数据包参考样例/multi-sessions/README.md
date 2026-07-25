# multi-sessions（附加交卷示意）

与甲方数据包**平级**提交。本目录为 **mock**：结构可照抄，内容须换成真实 Claude Code session。

```text
multi-sessions/
  claude-opus-4-8/     # 多个 <session_id>.jsonl
  glm-5.2/
  qwen-3.7-max/
  manifest.json        # 每个 session 的 model_id + eval_pass
```

`manifest.json` 字段要点：

| 字段 | 含义 |
| --- | --- |
| `session_id` | 与 `.jsonl` 文件名一致 |
| `model_id` | `claude-opus-4-8` / `glm-5.2` / `qwen-3.7-max` |
| `eval_pass` | 该次 `test.sh` 是否通过 |
| `path` | 相对本目录的路径 |

关联题目包：`../20260617_gateway-raw-http/`。
