# 上传前预检

用户**只需一个**已整理好的**甲方数据包路径**。未提供路径：Agent 先问，勿猜。

**目标：** 按 [SKILL.md](./SKILL.md) **完整**跑完后，尽量在 3bench platform 预审直过。  
**只读用户包**；call-level / Docker 只在临时深拷贝上动。

```bash
# §A 静态（结构/meta/轮次/scores/reports …）
python3 scripts/presubmit_check.py --task-dir <数据包> --markdown

# §B call-level（临时合并，不写回包）
python3 scripts/merge_call_level.py --package <数据包> --check
```

| 段 | 内容 |
| --- | --- |
| §A | 脚本硬检 |
| §B | call-level |
| §D | Agent：临时拷贝 + Docker Baseline 挂 / GT 过 |
| §E | Agent：`reports_review` + 条件 `instruction_tests_audit` → [SEMANTIC_REVIEW.md](./SEMANTIC_REVIEW.md) |
| §C | 集合比例、私有题意等（甲方要求说明） |

**仅跑 §A 绿不够。** 须含 §B§D§E 结论才可称「对齐平台预审路径」。

反馈：全量 FAIL/WARN（问题/原因/违反/建议）+ 下一步，不中途截断。
