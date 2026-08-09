---
name: client-harbor-presubmit
description: >-
  众包上传前全量预检：§A 静态机检 + §B call-level + §D 临时拷贝 Docker + §E
  reports_review / instruction_tests_audit（对齐平台 Claude 语义）+ §C 甲方集合项。
  目标：本 skill 过完后尽量在 3bench platform 预审直接通过。只读包；全量汇报。未给路径先问。
---

# 上传前预检（对齐 Platform · 尽量预审直过）

**产品目标：** 按本 Skill **完整跑完且 FAIL=0、WARN 清完或可控** 后，再上传  
https://www.shixianw.com/3bench/upload ，**尽量**让 `packagecheck` 硬项 + Claude 语义审一次过。  
机检绿 + 你按 §E 做过人填/题测审查 ≠ 甲方终审结算，但应覆盖平台预审主路径。

对用户**已整理**的甲方数据包：

| 段 | 谁执行 | 对应 Platform |
| --- | --- | --- |
| **§A** | `presubmit_check.py` | structure + quality + rubric/scores/models 硬项 |
| **§B** | `merge_call_level.py --check` | merge call-level |
| **§D** | **Agent** 临时深拷贝 + Docker | docker_eval Baseline/GT |
| **§E** | **Agent** 只读语义审查 | Claude `reports_review` + `instruction_tests_audit` |
| **§C** | **Agent** | 集合比例 / 私有题意等（平台单题管线不算，甲方会看） |

**硬规则：禁止修改用户数据包。**  
§B/§D 写操作只在**系统临时目录**；§E 只读。报告 stdout 或不落用户包。

用户未给 **数据包路径** → 先问，禁止猜。

---

## 标准流程（必须按序做完再声称「可上传」）

```text
PACK = 用户数据包
  1 §A  scripts/presubmit_check.py --task-dir PACK --markdown   → 机检 FAIL/WARN 全量
  2 §B  scripts/merge_call_level.py --package PACK --check        → 临时合并
  3 §D  临时深拷贝 + Docker Baseline 挂 / 套 GT 过               → 见下 §D
  4 §E  reports_review（必做）+ instruction_tests_audit（条件） → 见下 §E
  5 §C  对照 ../甲方要求说明.md（集合比例等）
  6 一次汇报：硬 FAIL + 软 WARN + §D/§E 结论 + 下一步
     勿因单项停检；勿改用户包「修绿」
```

开场可告知用户：

> 我会按 3bench 平台预审项做完整自检（结构、轨迹、Docker 临时拷贝、人填 reports、题测公平性等），**不改你的包**；一次给全量问题与改法。目标是上传后尽量平台直过；终审仍以甲方为准。

---

## §A 静态机检（脚本 · 硬门槛）

```bash
python3 scripts/presubmit_check.py --task-dir <PACK> --markdown
```

覆盖平台 structure/quality/rubric 主硬项：必备路径、Dockerfile pin、`pkg==x.y.z`、meta 人写字段、轮次≥20/模型、scores/reports、`eval_pass` 一致、禁三模全过、千问须挂、空壳 test、脏 workspace、instruction 强泄题等。

脚本同时输出 **§D/§E 待办**（不能代替你执行语义与 Docker）。  
**仅 §A 脚本绿 → 不够上传。** 必须继续 §B§D§E§C。

---

## §B call-level

```bash
python3 scripts/merge_call_level.py --package <PACK> --check
```

合并产物**仅**临时目录；与平台 merge 同目标。FAIL 并入总汇报。

---

## §D Docker（Agent · 临时深拷贝）

与平台 docker_eval **同判定**，步骤可简化；**禁止**在 `PACK` 上 build/改 workspace。

```bash
EVAL=$(mktemp -d "${TMPDIR:-/tmp}/cc-docker-eval.XXXXXX")
# 确保 $EVAL 不是 $PACK 子路径
cp -a "$PACK"/. "$EVAL"/
cd "$EVAL/environment" && docker build -t cc-presubmit-baseline .
docker run --rm --network=none -v "$EVAL/tests:/tests:ro" cc-presubmit-baseline \
  bash -lc 'bash /tests/test.sh; echo EXIT:$?'
# Baseline 须失败。通过 → FAIL 空壳/答案泄漏

# 仅在 $EVAL 套 GT：ground_truth 覆盖 workspace → patch → 或 solution/solve.sh
cd "$EVAL/environment" && docker build -t cc-presubmit-gt .
docker run --rm --network=none -v "$EVAL/tests:/tests:ro" cc-presubmit-gt \
  bash -lc 'bash /tests/test.sh; echo EXIT:$?'
# GT 后须通过

docker rmi -f cc-presubmit-baseline cc-presubmit-gt 2>/dev/null || true
rm -rf "$EVAL"
```

Docker 不可用：记 FAIL，**仍做** §E；不要整场停。

---

## §E 平台语义审查（Agent 必做 · 对齐 precheck-judgment）

对应平台 Claude 分项。**无论 §A/§D 是否已 FAIL，都必须做 `reports_review`**，一次暴露人写交付与语义矛盾（勿只重复机检 Docker 日志）。

细则与勾选清单见 **[SEMANTIC_REVIEW.md](./SEMANTIC_REVIEW.md)**。摘要如下。

### E1 · `reports_review`（**永远 RUN**）

只读：`reports/**`、`scores/rubric_scores.json`、`meta.json`、session 与 `session_id`。

| 判级 | 条件（对照平台） |
| --- | --- |
| **FAIL** | 明显造假/自相矛盾；session 严重错位；eval_pass 与 reward/日志明显冲突；叙述甩锅环境却有完整工具链可做；correctness 与真结果不可调和且机检未覆盖的语义谎 |
| **WARN** | AI 草拟未 complete；缺 notes 却高分；分数与轨迹观感落差大但不像硬造假；单审 |
| **PASS** | 人填与过题一致、有依据、无甩锅 |

须输出：`status` + 中文 `conclusion` + 四段问题列表（问题/原因/违反/建议）。

### E2 · `instruction_tests_audit`（**条件**）

先根据 scores/reports 判定是否 **三模型 `eval_pass` 全为 false**：

| 条件 | 动作 |
| --- | --- |
| **全挂** | **必须深入审查** instruction.md + **未套 GT 的** workspace + tests/** |
| **非全挂** | 分项写 **SKIP**；「题面/测试偏薄但不公」仍可 WARN 写入软列表 |

全挂时：

| 判级 | 条件 |
| --- | --- |
| **FAIL** | 测试要求了题面/初始代码未给出的 API、字段、路径——合理实现也必挂 → 不公 |
| **PASS** | 合理难题；失败来自模型能力而非布置坑 |
| **WARN only** | 说明不够完整 / 测试面偏窄，**但非不公** |

**非全挂也做一遍软读：** 目标是否可执行、是否同一份题面可被三模型公平跑、是否过短、是否像泄测试——问题进 WARN，**不要**因「略薄」误判为 E2 FAIL（与平台一致）。

### E3 · 固定软检清单（warnings，上限约 15）

与平台 judgment 固定项对齐（机检已硬 FAIL 的缺字段勿重复硬判）：

1. scores/status **ai_drafted** 未人审 complete  
2. **single_reviewer_only**  
3. meta.task_type 与 task_rubric / reports 不一致  
4. 顶层 scores 与 reports 内分数 / best_win 不一致  
5. instruction/tests **薄但不公**  
6. one_liner/annotator **像模板离谱**  
7. dimension_notes **甩锅环境/密钥** 但日志显示可正常用工具  
8. 过题却无任何 notes 点评  

### E4 · 汇报进总报告

用户可见总报告必须含：

```text
## 语义审查（§E · 对齐平台 Claude）
### reports_review: PASS|WARN|FAIL — <conclusion>
### instruction_tests_audit: PASS|FAIL|SKIP — <conclusion>
（及逐条四段 FAIL/WARN）
```

未写 §E 段 → **不得**声称「与平台预审同级已通过」。

---

## §C 甲方要求全文 / 集合

权威：[`../甲方要求说明.md`](../甲方要求说明.md)

- 集合：题量≥3；千问题题挂；Opus≤60%；Opus−Q>20%；GLM≥1  
- 三模型同一 instruction / Baseline / Docker；私有题意；未中途改测凑分  

平台**单题**预审不算集合 → 多题交付时 **Agent 必须人工表格式汇总**。

---

## 何为「本 Skill 通过、可上传平台」

必须**全部**满足：

1. §A 无 FAIL（WARN 已说明或用户知悉）  
2. §B call-level 校验通过  
3. §D Baseline 挂 + GT 过（或本机 Docker 明确不可用且用户接受平台再验——仍应尽量本地验）  
4. §E `reports_review` 非 FAIL；若三模全挂则 `instruction_tests_audit` 非 FAIL  
5. §C 集合与人写红线无未披露硬伤  

任一未做 → 汇报「未完成项」，**不要**说「平台侧大概没问题」。

---

## 汇报格式（FAIL/WARN 每条 · 不阻断）

1. **问题** 2. **原因** 3. **违反**（平台分项或甲方条款） 4. **建议**  

文末 **下一步计划**（按序；不中途截断其它审核点）。
