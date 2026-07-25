# Taxonomy 标签枚举（本包内嵌）

> 供填写 `meta.json` 时对照。与甲方检查清单 Taxonomy 口径一致。  
> **两套 task_type 勿混用**：Rubric 四选一 ≠ Taxonomy 意图二级标签。

集合分组：`code_lang × task_type × application`，每组题目 ≤100。标签如实即可，不必铺满笛卡尔积。

## Rubric 四选一（`rubric_task_type` / meta 的评分类型）

`code_generation` / `bug_fix` / `code_qa` / `refactor`

## `code_lang`

| 取值 | 核心 |
| --- | --- |
| `go` `c` `c++` `python` `java` `js/ts` `php` `shell` `c#` `html/css` `sql` `rust` | ⭐️ |
| `kotlin` `swift` `ruby` `lua` `other` `mixed` `unknown` |  |

## Taxonomy 意图 `task_type`（写入 `labels.task_type` / `tags`）

| 一级 | 二级取值 | 核心 |
| --- | --- | --- |
| Fix | `bug-fix` | ⭐️ |
| Fix | `performance-fix` |  |
| Fix | `compatibility-fix` | ⭐️ |
| Implementation | `feature` | ⭐️ |
| Implementation | `enhancement` `backward-compatibility` `from_scratch` |  |
| Testing & Quality | `test-add` `coverage` | ⭐️ |
| Testing & Quality | `test-fix` `debug-support` |  |
| Refactoring & Maintenance | `refactor` | ⭐️ |
| Refactoring & Maintenance | `style` `deprecation` |  |
| Build & Release | `build-fix` `ci-fix` | ⭐️ |
| Build & Release | `deployment` `packaging` `config` |  |
| Documentation & Design | `user-docs` `design-spec` `diagram` |  |
| Security & Compliance | `security-fix` `auth` `privacy` |  |
| Non Coding | `Non_Coding` |  |

## `application`（一级）

| 取值 | 核心 |
| --- | --- |
| `Client_UI` `Backend_Infrastructure` `AI_ML` `Database_Storage` `Business_Domain_Logic` | ⭐️ |
| `Graphics_Media` `Embedded_Systems` `Operating_System` `Scientific_Computing` `Other` |  |
