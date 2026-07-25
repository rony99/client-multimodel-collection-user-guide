# 上传前预检

对本包约定的**提交根目录**做结构预检（Agent 执行 [SKILL.md](./SKILL.md)）。

要点：

- <span style="color:#d93025">须有**平级**的甲方原格式数据包 + `multi-sessions/`</span>
- `multi-sessions/manifest.json`：`session_id` ↔ 模型 ↔ 是否通过测试
- <span style="color:#d93025">Opus 在 `multi-sessions/` 中至少 **≥2** 份独立 session（建议 4）</span>
- 预检 ≠ 审核通过；<span style="color:#d93025">**最终以实现网和甲方的后期审核为准。**</span>
