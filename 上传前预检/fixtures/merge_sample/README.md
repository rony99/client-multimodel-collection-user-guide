# merge_sample fixture

合成微缩数据：session 根 + Gateway 根 + Session ID → call-level。

Session ID：`11111111-aaaa-bbbb-cccc-222222222222`

```text
session_root/
  <sid>.jsonl
  <sid>/subagents/explorer-001.jsonl   # 可选 subagent
gateway/
  <sid>/*.json                         # local-cc call 抓包
```

## 推荐（用户 / Skill 口径）

```bash
python3 ../../scripts/merge_call_level.py \
  --session-root session_root \
  --gateway-root gateway \
  --session-id 11111111-aaaa-bbbb-cccc-222222222222 \
  --out /tmp/call_level.jsonl \
  --agents-out /tmp/agents \
  --check
```

## 兼容直路径

```bash
python3 ../../scripts/merge_call_level.py \
  --session session.jsonl \
  --gateway-dir gateway/11111111-aaaa-bbbb-cccc-222222222222 \
  --out /tmp/call_level.jsonl \
  --check
```

`expected/call_level.jsonl` 为主链金标参考。
