# 甲方数据包参考样例说明

本目录有两块，<span style="color:#d93025">**正式交卷时两块都要提交**</span>（平级放置）：

| 路径 | 是什么 | 是否必交 |
| --- | --- | --- |
| [20260617_gateway-raw-http/](./20260617_gateway-raw-http/) | **甲方要求的最终数据包**（题面 / 环境 / 测试 / GT / rubric / meta / `trajectories/` 等） | <span style="color:#d93025">**必交**</span> |
| [multi-sessions/](./multi-sessions/) | **多次执行 session 校验**（三模型多次独立 session + `manifest.json` 标明每次是否通过测试） | <span style="color:#d93025">**必交**</span> |
| [模板/](./模板/) | 可抄的 meta / rubric | 参考用 |

## 正式交卷怎么摆

```text
<submit_root>/
  <task_id>/                 # 甲方数据包（结构对照本目录样例包）
  multi-sessions/            # 额外再交：多模型多次 session
    claude-opus-4-8/
      <session_id>.jsonl     # Opus 至少 ≥2 次，建议 4 次
    glm-5.2/
    qwen-3.7-max/
    manifest.json            # 每个 session_id ↔ 模型 ↔ eval_pass
```

- 甲方包保持**原有 Harbor 格式**（见样例包内树）。  
- `multi-sessions/` 用于核验通过率 / 区分度；其中 Opus **≥ 2 次**独立轨迹（建议 4 次对齐 pass@4）。  
- `multi-sessions/manifest.json` 与甲方包内 `manifest.json` 可并存：前者专记多次 run 的通过情况。

字段与门槛见 [甲方要求说明.md](../甲方要求说明.md)；操作见 [用户操作步骤.md](../用户操作步骤.md)。
