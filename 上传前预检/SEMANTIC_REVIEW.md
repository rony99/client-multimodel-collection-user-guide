# §E 语义审查清单（对齐平台 precheck-judgment）

Agent **只读**用户包。与 `SKILL.md` §E 配套；目标：覆盖平台 Claude 分项后尽量预审直过。

无论机检/Docker 是否已 FAIL，**必须**完成 E1；E2 按表触发。

---

## 0. 先读（路径相对 PACK）

| 材料 | 用途 |
| --- | --- |
| `instruction.md` | 题面目标、约束、是否泄测 |
| `environment/workspace/**`（**勿套 GT**）| Baseline 有什么、缺什么 |
| `tests/**`、`tests/test.sh` | 判分实际要求什么 |
| `scores/rubric_scores.json` | eval_pass、五维、agreement、notes、status |
| `reports/<model>/**/eval_result.json` 及其中的 rubric 副本 | 过题与 reward、session_id |
| `meta.json` | task_type、背景、用时 |
| `trajectories/<model>/session/*.jsonl` | 轨迹是否支撑分数叙述 |

判定 **all_models_failed**：三模型 `eval_pass` 均 `false`（以 reports 优先，与 scores 冲突时以 §A 机检 FAIL 为准且语义只补矛盾）。

---

## E1 · reports_review（永远 RUN）

### 必答题（逐模型扫）

1. `eval_pass` / reward / 叙事是否一致？  
2. correctness 与五维分是否与过题/挂题故事一致？（机检冲突已 FAIL；此处看 notes 是否在**圆谎**）  
3. `session_id` 是否大致对应本包轨迹？严重错位 → **FAIL**  
4. notes / dimension_notes 是否像人写终稿？是否 **甩锅**（环境坏、无 key、docker 挂）而 session 显示正常读写工具？→ **FAIL 或 WARN**  
5. 是否 `ai_drafted` / 未 complete？→ **WARN**（与机检叠加时不重复硬造同码可并一句）  
6. 与 meta 难度/用时是否离谱矛盾？→ **WARN**

### 输出模板

```markdown
### reports_review: PASS|WARN|FAIL
conclusion: <一句中文>
all_models_failed: true|false

#### 条目（有则列）
- code: ...
  问题：...
  原因：...
  违反：平台 reports_review / 甲方评分诚实
  建议：...
  严重度：非常严重|比较严重|严重|有影响
```

---

## E2 · instruction_tests_audit

### 何时深入

| all_models_failed | 动作 |
| --- | --- |
| **true** | **必须**按「不公」标准深入判 FAIL/PASS；软不足用 WARN |
| **false** | 状态写 **SKIP**；仍可软读 instruction/tests → 仅 WARN |

### 全挂时「不公」FAIL 标准（与平台一致）

- 测试断言了 **题面 + Baseline workspace 均未给出** 的 API / CLI 标志 / 文件路径 / 数据结构  
- 无解题说明的隐藏契约导致 **合理实现也必挂**  
- 依赖不可复现的外部登录、强时效网页（对照甲方红线）作为必过条件  

### 不要 FAIL（用 WARN）

- 说明偏短、边界用例偏少、难但公  
- 模型笨导致三挂  

### 非全挂软读（WARN 清单）

- 目标/完成标准是否可执行  
- 是否与 test.sh 主路径大体对齐（非逐字泄露 assert）  
- 是否只写「做完即可」无验收口径  

### 输出模板

```markdown
### instruction_tests_audit: PASS|FAIL|SKIP
conclusion: <一句中文>
（FAIL/WARN 条目用同上四段 + 严重度）
```

---

## E3 · 固定 soft warnings（合并进总报告，≤15）

机检已对「缺字段」硬 FAIL 的，勿重复同一 code 硬结论；可补语义。

1. AI 草拟分未 complete  
2. single_reviewer  
3. task_type 多处不一致  
4. scores 与 reports 分数不一致  
5. instruction/tests 薄但不公  
6. one_liner / annotator 模板感  
7. 叙事甩锅  
8. 过题无点评 notes  

---

## E4 · 自检及格门槛（语义侧）

- reports_review ≠ FAIL  
- 若 all_models_failed：instruction_tests_audit ≠ FAIL  
- 若非全挂：instruction_tests_audit = SKIP（conclusion 写明），薄题 WARN 可选  

未做本节 → 整体预检 **未完成**，勿报「可上 platform」。
