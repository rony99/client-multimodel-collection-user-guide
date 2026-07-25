---
name: client-harbor-presubmit
description: >-
  上传前预检众包 Harbor 任务包：检查是否含平级甲方原格式数据包与 multi-sessions/
  （多次 session + 通过情况 manifest），以及 meta/rubric 是否齐全。
  用户提供提交根路径后由 Agent 执行；预审≠实现网/甲方后期审核通过。
---

# 上传前预检（众包自包含包）

对本目录上级手册约定的**待上传提交根目录**做结构与完整性预审。

## 开场必须告诉用户（原文级要点）

> **预审不代表审核通过。** 本检查只看文件是否存在、字段是否齐全、结构是否合理。  
> **需要你自行验证通过率及区分度**（Opus pass@4≤60%、三模型偏序、平台分差等）。  
> **最终以实现网和甲方的后期审核为准。**

## 用户需要提供什么

| 输入 | 说明 |
| --- | --- |
| **提交根目录** `--task-dir` | 内含**平级**的甲方原格式数据包 + `multi-sessions/`；也可直接指向数据包（旁边须有 `multi-sessions/`） |

## 最新交卷结构（预检强制）

```text
<submit_root>/
  <task_id>/                   # ① 甲方原格式数据包
  multi-sessions/              # ② 附加：多模型多次 session
    claude-opus-4-8/           # Opus ≥2，建议 4
    glm-5.2/
    qwen-3.7-max/
    manifest.json              # session_id ↔ 模型 ↔ eval_pass
```

示意：[../甲方数据包参考样例/](../甲方数据包参考样例/)

## Agent 必须执行

```bash
python3 上传前预检/scripts/presubmit_check.py \
  --task-dir <用户提交根目录绝对路径> \
  --markdown
```

工作目录应为：`采集用户说明_final/`。

## 预检覆盖什么

1. **布局**：甲方原格式数据包与 `multi-sessions/` 是否平级；`multi-sessions/manifest.json`  
2. **数据包**：instruction、workspace、Dockerfile、test.sh、rubrics、meta、GT 等  
3. **`multi-sessions/`**：三模型目录；**Opus ≥2** 份独立 `.jsonl`  
4. manifest 是否含 `session_id` / `model_id` / `eval_pass`  
5. **不强制** `agents/`  
6. 轨迹口径：检查 Claude Code session `.jsonl`（非 call-level schema）  

## 预检明确不覆盖

| 项目 | 说明 |
| --- | --- |
| Opus pass@4 ≤ 60% 等实测门槛 | 须用户自测 |
| 后期审核 | **以实现网和甲方的后期审核为准** |

## 报告怎么跟用户说

1. 贴出脚本 Markdown 报告全文。  
2. 总结：`PRECHECK_PASS` / `PRECHECK_WARN` / `PRECHECK_FAIL`。  
3. 再次复述：预审 ≠ 审核通过。  

## 权威口径

- [../甲方要求说明.md](../甲方要求说明.md)  
- [../用户操作步骤.md](../用户操作步骤.md)  
- [../甲方数据包参考样例/](../甲方数据包参考样例/)  
