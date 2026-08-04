# 采集答疑口径库（v1.1）

Agent 回答用户问题以本文件为准。每题格式：**结论** → **要点** → **文档**。

相关路径均相对 `采集用户说明_final/`。

---

## A. 模型与连接

### A1. 平台会提供模型 API 吗？可以用自己的账号吗？

**结论：仓库内提供预编译本地 Gateway（`cc-gateway/`）；不提供模型 API。用你自己的账号经 Gateway 生成。**

- 正式对比模型仍为三套：`claude-opus-4.8` / `glm-5.2` / `qwen-3.7-max`  
- 配置 `providers.yaml` 的 `active`：`A` GLM / `B` 千问 / `C` 官方 Opus 订阅  
- **正式采题前必须做 §0 接通自检**（三套都能通 + 抓包目录名=Session ID=Claude Code 会话 ID）  
- **须先启动 Gateway 并全程保持**，再用 `claude --settings …/providers.claude.settings.json`  
- Gateway 日志：本机 `<root_dir>/<sessionId>/*.json` → 交卷 `trajectories/<模型>/cc-gateway-log/`  
- 交卷：数据包 + 每模型 **`session/` + `cc-gateway-log/`，缺一不可**

**文档**：`cc-gateway/README.md`；`Gateway采集说明.md`（§0 自检 + 教程）；`用户操作步骤.md` 第 0、1 步；`参与方式.md`。

### A2. 采数前要确认什么？

**结论：先通 §0 自检；采题时 Gateway 在跑、用了正确 settings、active 对口、抓包已写入；交卷 session 与 Gateway 日志成对。**

- 采千问时不要误开成 Opus；换模型 = 改 `active` → 重启网关 → 新目录新 session。  
- 核对 `~/.claude_lproxy/projects/<sessionId>/` 有文件，且目录名 = Claude Code 默认 Session ID。  
- 账号 / 令牌不要写进题目仓库。  
- **禁止只交 session 或只交 Gateway 日志。**

**文档**：`Gateway采集说明.md` §0、§4–§7；`用户操作步骤.md` 第 0、1、6、8 步。

### A3. Gateway 日志路径？Session ID 是什么？

**结论：默认根目录 `~/.claude_lproxy/projects`（或 YAML `root_dir` / 环境 `CCG_DATA_DIR`）；其下每个子目录名即 Session ID。**

- Claude Code 通常通过请求头 `x-claude-code-session-id` 带 UUID，网关用它做目录名。  
- 一会话多文件正常；整目录保留。  
- 与包内 `trajectories/<模型>/session/` 的 session **同一 ID**。

**文档**：`Gateway采集说明.md` §7–§8。

---

## B. 基本概念

### B1. 「一条数据」是一个模型跑一次的结果吗？

**结论：不是。一条交卷数据 = 一道完整题。**

| 内容 | 说明 |
| --- | --- |
| 甲方数据包 `<task_id>/` | 题面、环境、测试、GT、rubric、meta、`trajectories/` 等 |
| `trajectories/<模型>/session/` | Claude Code 主会话 1 条（有则 subagents） |
| `trajectories/<模型>/cc-gateway-log/` | 该 Session 的 cc-gateway 抓包 |

细分：

- **一道题** → 一个 `<task_id>/`
- **一次 session** → 某模型从干净起点做一整题留下的一份 `.jsonl`
- **不再要求 pass@4** → 不要同题连跑 4 次再交；比例按你交的多道题统计

**文档**：`README.md` FAQ；`甲方要求说明.md` §4。

### B2. 用户交的 session 是什么格式？

**结论：Claude Code 主会话 `.jsonl`（及有则 subagent `.jsonl`）。**

- 放在 `trajectories/<模型>/session/`。
- Gateway 抓包放在同模型 `cc-gateway-log/`。
- 需要甲方 call-level 时：整理进包后用  
  `merge_call_level.py --package <任务包> --check`  
  **只读包内** `session/` + `cc-gateway-log/`（见 [上传前预检/SKILL.md](../上传前预检/SKILL.md) §B）。
- **禁止**编造 system/tools；request 取 Gateway，response 必要时用 session 补。
- 用户侧**不要求**手工写 call-level；合并可写 `agents/main_agent.json`。
- **最终以甲方实际审核为准**。

**文档**：`用户操作步骤.md` 第 6 / 8 步；`上传前预检/SKILL.md` §B。

### B3. Baseline 和 Ground Truth 是什么？

**结论：Baseline = 未完成的初始工程；GT = 标准答案，必须与做题目录分开。**

- Baseline → `environment/workspace/`（**不含**标准答案）。
- GT → `ground_truth/`；套上后 `test.sh` 必须全过。
- 做题目录里**禁止**夹带答案。

**文档**：`用户操作步骤.md`「强烈建议」、第 2 / 5 步。

### B4. 还要不要算 pass@4？

**结论：众包日常不要求。**

- 甲方原文可能仍写同题 4 次；本包操作改为**集合过题比例**（见 C 节）。
- 每模型每题正式只交 **1** 条轨迹。
- 最终仍以甲方实际审核为准。

**文档**：`用户操作步骤.md` §7；`甲方要求说明.md` §4、附录 Z。

### B5. 本机做完题，session 文件在哪里找？（交卷前）

**类型：B 类（非业务辅助）；交卷放哪见 D 节**

```text
~/.claude/projects/<工作目录编码>/
  <session_id>.jsonl
  <session_id>/subagents/*.jsonl
```

- 找最新 `.jsonl`，拷到 `<task_id>/trajectories/<模型>/session/`。  
- 对应 Gateway 目录拷到 `trajectories/<模型>/cc-gateway-log/`。

**说明：以上为非业务类型问题，由 Agent 根据通用信息辅助回复，不代表本平台采集规范或最终审核口径。**

---

## C. 通过与合格

### C1. 怎么才算单次「通过」？

**结论：只看自动测试，不看人眼。**

1. 在 Docker 内对当次做题结果跑 `tests/test.sh`
2. 退出码 `0` → 通过；非 `0` → 未通过
3. 自行记下该题该模型过/不过，用于集合比例自检

**文档**：`用户操作步骤.md` §3.1。

### C2. 怎样才算集合比例合格（自行核，结构脚本不查）？

**结论：单题材料齐全 + 集合比例达标。结构预检绿 ≠ 本条合格。**

| 类型 | 要求 |
| --- | --- |
| 单题 | 三模型各 `session/`+`cc-gateway-log/`；turns 平均 ≥20；Baseline 挂 / GT 过；同一 instruction |
| 集合 | <span style="color:#d93025">禁「三模型都测通」</span> |
| 集合 | <span style="color:#d93025">所交**每道题千问均须测不过**</span>（过题率 = 0） |
| 集合 | <span style="color:#d93025">Opus 过题率 ≤ 60%</span> |
| 集合 | <span style="color:#d93025">Opus − 千问过题率差 > 20%</span>（千问全挂时 ≈ Opus 率，Opus 宜在 (20%,60%]） |
| 集合 | <span style="color:#d93025">GLM ≥ 1 道测通</span> |
| 题量 | <span style="color:#d93025">要求 ≥3</span>；少于 3 可交，是否采纳看整体分布 |

出题须先保证千问不过再采。n=3 时 Opus 通常只能过 **1** 道才不超 60%。

**文档**：`用户操作步骤.md` §7；`甲方要求说明.md` §4.2。

### C3. 少于 3 道可以交吗？

**结论：可以交；是否采纳由平台按当期整体数据分布决定。**

不保证**采纳 / 送审**（结构预检仍可能 PASS）。

### C4. 结构预检通过 = 结算 / 终审通过吗？

**结论：不等于。**

- 上传前预检：只查文件结构与完整性。
- 集合比例须用户自核。
- **最终以甲方实际审核为准。**

### C5. 「单次通过」和「集合比例合格」有什么区别？

**结论：单次通过只是一次 `test.sh==0`；集合合格看整批过题比例。**

- 某题 Opus 测过了，不代表整批 Opus 过题率已 ≤60%。
- 结构预检绿了，不代表比例合格或甲方终审通过。

---

## D. 交卷结构

### D1. 最终要交什么？

**结论：一道题一个甲方原格式数据包；每模型同时交 `session/` + `cc-gateway-log/`。**

```text
<submit_root>/
  <task_id>/
    trajectories/
      claude-opus-4-8/
        session/session.jsonl
        cc-gateway-log/*.json
      glm-5.2/
        session/session.jsonl
        cc-gateway-log/*.json
      qwen-3.7-max/
        session/session.jsonl
        cc-gateway-log/*.json
```

- 目录名仅允许字母、数字、`._-`。
- `task_id` 须与数据包目录名一致。

**文档**：`用户操作步骤.md` §8.1。

### D2. 还要不要交 multi-sessions？

**结论：不要交。**

- 样例包已**不再包含** `multi-sessions/`。
- 正式只交包内 `session/` + `cc-gateway-log/`。

### D3. 每个模型交几次 session？

**结论：正式交卷每模型每题恰好 1 条主会话（在 `session/`）。**

- 试难度时可多跑，但交卷只保留 1 条主 `.jsonl`。
- 不要为 pass@4 刻意交多条；多条会被上传前预检判 FAIL。
- **必须同时**有非空 `cc-gateway-log/`。

### D4. 包内 `trajectories/` 放什么？

**结论：三模型各：`session/`（Claude Code）+ `cc-gateway-log/`（cc-gateway 抓包）。**

### D5. 用户需要交 `agents/` 吗？

**结论：不强制手写。** 可用合并脚本生成；已交两目录即可让 Agent 代跑。

---

## E. 采集铁律

### E1. 每次做题怎么开？

**结论：新目录副本 + 新 session。**

推荐：Baseline 母版 → 每次 `cp` 到 `runs/<模型>/` → 确认无 GT → **新开** Claude Code session → 发同一份 `instruction.md`。

禁止：

- 多个模型 / 多次尝试共用同一份改过的代码
- 在唯一母版上直接让 AI 改
- 做题目录带着答案
- 换模型却沿用旧 session

**文档**：`用户操作步骤.md` 文首「强烈建议」、第 6 步。

### E2. 三模型可以用不同题面吗？

**结论：不可以。**

- 必须同一份 `instruction.md`（同一内容发给三个模型）。
- 不能给 Opus「更细」、给千问「更粗」。
- Baseline、测试、Docker、判分口径也不得因模型而异或中途改完再比通过率。

**文档**：`README.md` FAQ #5；`用户操作步骤.md` 第 6 步铁律。

### E3. 同一模型同一题能不能拆成两个 session 拼？

**结论：不要。** 同一模型、同一题只用一个完整 session，不要拆成两个拼。

### E4. 多个任务（多道题）能不能放在一个 session 里？

**结论：不可以。**

- **一道题 ↔ 一个干净 session**（同一模型、同一题只用这一份完整对话）。
- 多道题 → 每道题各自：**新目录副本 + 新开 session**。
- 与 E3 对称：既不能一 session 多题，也不能一题拆两 session 拼。

**文档**：`用户操作步骤.md` 第 6 步铁律。

---

## F. 材料与字段

### F1. instruction 怎么写才好？

**结论：三模型共用一份；写清要做什么与约束，不要写出答案。**

高优方向（不能替代难度硬门槛；长程 100+ 为建议）：

- 长程任务（执行轮次尽量高；底线仍 ≥20）
- 需遵守项目内 `CLAUDE.md` 等约束
- 多文件 / 长链路
- 多轮用户需求（同一 session 内递进改需求）
- 需查文档等（最终测试仍须 Docker 内可复现）

**文档**：`用户操作步骤.md` §2.1；`甲方要求说明.md` 高优方向；`参考/Taxonomy标签.md`。

### F2. `solve.sh` 必须交吗？

**结论：已有可用的 `ground_truth/` 文件树时非必须；有则可方便验收复现。**

- 路径惯例：`solution/solve.sh`（一键把 workspace 套成答案态再跑测试）。

**文档**：`甲方要求说明.md` §3.4。

### F3. meta / rubric 怎么填？

**结论：对照 `甲方要求说明.md` 第 5 节 + 附录 Checklist；标签枚举用 `参考/Taxonomy标签.md`。**

- 可抄 `甲方数据包参考样例/模板/`。
- 样例只作结构与写法参考；字段以要求说明为准。

### F4. 测试有什么禁忌？

**结论：`test.sh` 不能永远 `exit 0`（空壳）；须 Baseline 失败、套 GT 成功。**

- 通过 = 退出码 0；依赖应钉死；密钥不进仓库明文。

**文档**：`用户操作步骤.md` 第 3–4 步。

---

## G. 预检、审核与文档导航

### G1. 上传前预检做什么？要我提供什么？

**结论：你只要提供「数据包目录路径」这一个地址。**

| 段 | 用不用别的路径 |
| --- | --- |
| §A 结构 | 否，就是这个包 |
| §B 合并校验 | 否，仍是这个包里的 `session/` + `cc-gateway-log/` |

- **没给路径**：Agent / 支持方会先问你，再跑检查。  
- 不需要本机 `~/.claude` 或 Session ID 列表（ID 从包内读）。  
- 加载 `上传前预检/SKILL.md` 执行；绿 ≠ 结算。

### G1b. call-level 合并用什么路径？

**结论：同一数据包路径。**

```bash
python3 上传前预检/scripts/merge_call_level.py --package <任务包> --check
```

详见 `上传前预检/SKILL.md`。

### G2. 文档应该先看哪个？

**结论：以 `用户操作步骤.md` 为主；`甲方要求说明.md` 含门槛与文末甲方要求一览。**

| 文档 | 角色 |
| --- | --- |
| `用户操作步骤.md` | 主线 |
| `Gateway采集说明.md` | 本地网关与日志 |
| `甲方要求说明.md` | 门槛、字段、Checklist、附录 Z |
| `甲方数据包参考样例/` | 结构示意 + 模板 |
| `qa_skill/` | 本答疑口径 |
| `上传前预检/` | 结构预检 + call-level 合并 |

### G3. 最终以谁为准？

**结论：以甲方实际审核为准。** 实现网侧仅为预审核。

### G4. 怎么报名参与？

**结论：满足基本要求后，按模板微信发给「栗子」进群。** 详见 `参与方式.md`。

### G5. 出题能否直接改 GitHub Issue？

**结论：不可以。** 须私有仓库 / 私有题意；DeepSWE 等仅可参考难度，禁止照搬。

---

## I. 非业务 / 工具类（Agent 辅助，非采集规范）

本节问题**不在**交卷硬门槛内。Agent 可结合常识或检索回答，**每条末尾须加免责句**（见 [SKILL.md](./SKILL.md) B 类规则）：

> **说明：以上为非业务类型问题，由 Agent 根据通用信息辅助回复，不代表本平台采集规范或最终审核口径。**

### I1. Claude Code 怎么下载 / 安装？

- 一般从 Anthropic 官方渠道获取 Claude Code CLI（具体入口以官网 / 文档为准，版本可能更新）。
- 安装后终端可用 `claude` 命令；首次使用通常需登录或配置 API。
- **采集本题须经平台 Gateway，用你自己的账号调用三套指定模型**，并回传日志，见 [A1](#a1-平台会提供模型-api-吗可以用自己的账号吗)。

（回答时 Agent 可 Web 搜索「Claude Code install」获取最新链接，并加免责句。）

### I2. `cc switch` / 模型怎么切换？

- 指 Claude Code 侧切换当前使用的模型或配置 profile 的方式（命令名、子命令以你安装的 Claude Code 版本为准）。
- **采数前务必确认当前连的是目标模型**（千问 / GLM / Opus），见 [A2](#a2-采数前要确认什么)。
- 正式采数须走 **Gateway** + **你自己的账号**；切换方式以**平台 Gateway 说明 + 客户端当前文档**为准，Agent 可检索补充。

（回答时 Agent 可结合用户环境说明，并加免责句。）

### I3. Claude Code / API 费用、订阅、额度？

- 取决于你所用账号 / 套餐 / 厂商账单，**平台不代你出模型 API 费用**。  
- 本采集包**不规定**具体资费；账单与额度问各厂商或账号运营方。

（回答时 Agent 可概括公开定价信息，须注明可能变动，并加免责句。）

### I4. 本机 session 文件在哪？

→ 见 [B5](#b5-本机做完题session-文件在哪里找交卷前)（含免责句）。

---

## H. 快速对照（Agent 自检）

用户若问到下列关键词，优先跳到对应条目：

| 关键词 | 条目 | 类型 |
| --- | --- | --- |
| 自己的账号 / Gateway / 赛讯日志 / 是否提供 API | A1 | A 业务 |
| Gateway 路径 / sessionId 目录 | A3 | A 业务 |
| 绕过 Gateway / 直连 | A1 | A 业务 |
| 通过 / test.sh / eval_pass | C1 | A 业务 |
| 一条数据 / 一条样本 | B1 | A 业务 |
| 集合比例 / 60% / 难度 | B4, C2 | A 业务 |
| trajectories / 每模型 1 条 | D1–D4 | A 业务 |
| 不同题面 / instruction | E2 | A 业务 |
| 一 session 多题 / 多任务一个 session | E4 | A 业务 |
| 预检 / 审核 | C4, G1, G1b, G3 | A 业务 |
| call-level 包内合并 | G1b, B2, D5 | A 业务 |
| 报名 / 参与 / 栗子 / 进群 | G4 | A 业务 |
| 轮次 / turns / 20 / 100 | C2, F1 | A 业务 |
| 题量 / <3 道 / 分布 | C3 | A 业务 |
| Baseline / GT / 偷看答案 | B3, E1 | A 业务 |
| solve.sh | F2 | A 业务 |
| agents / call-level | B2, D5 | A 业务 |
| session 在哪 / .claude/projects | B5, I4 | B 辅助 |
| Claude Code 下载 / 安装 | I1 | B 辅助 |
| cc switch / 切换模型 | I2, A2 | B 辅助（切换）+ A（采哪套模型） |
| 费用 / 订阅 / 额度 | I3 | B 辅助 |
