# 上传前结构预检

只检查文件结构与完整性。**不查集合过题比例。**  
结构绿 ≠ 比例合格 ≠ 结算；**最终以甲方实际审核为准。**

可选：**Session + Gateway → 甲方 call-level**（见 [SKILL.md](./SKILL.md) §B）。

## 合并 call-level 用户输入（推荐）

只需 **两个根目录 + Session ID**（两边同名）：

| 输入 | 含义 |
| --- | --- |
| `--session-root` | Claude 原生 session 目录 → `<sid>.jsonl` 主会话；可选同名文件夹 `<sid>/` 下 subagent |
| `--gateway-root` | Gateway 根（如 `~/.claude_lproxy/projects`）→ `<sid>/*.json` 全部 call |
| `--session-id` | Session ID |

```bash
python3 scripts/merge_call_level.py \
  --session-root ~/.claude/projects/<encoded_cwd> \
  --gateway-root ~/.claude_lproxy/projects \
  --session-id <SessionID> \
  --out /tmp/call_level.jsonl \
  --check
```

## 交卷结构（检查什么）

- 甲方原格式数据包 + 每模型 **1** 条主 session
- 可选 `call_level.jsonl`（不算第二条主会话）
- 不要交同题多 run 旁路目录

## 脚本

| 脚本 | 用途 |
| --- | --- |
| [scripts/presubmit_check.py](./scripts/presubmit_check.py) | 结构预检 |
| [scripts/merge_call_level.py](./scripts/merge_call_level.py) | session 根 + Gateway 根 + sid → call-level |
| [scripts/validate_call_level.py](./scripts/validate_call_level.py) | call-level 字段校验 |
| [scripts/call_level_lib.py](./scripts/call_level_lib.py) | 解析 / 配对 / 校验 |

Fixture：[fixtures/merge_sample/](./fixtures/merge_sample/)
