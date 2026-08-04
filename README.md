# 采集用户说明（v1.1）

本文件夹可独立使用。

请按 **[用户操作步骤.md](./用户操作步骤.md)** 完成配连接、出题、调难度与交卷。

**本地 Gateway 预编译包已放在仓库内：[cc-gateway/](./cc-gateway/)**（mac / linux / win）。  
专章：**[Gateway采集说明.md](./Gateway采集说明.md)**。

<span style="color:#d93025">
<strong>开跑前必做：</strong>先按 Gateway 说明「§0 接通自检」验证——三套模型配置（A GLM / B 千问 / C Opus）
都能经由本机 Gateway 对话，且抓包目录名 = Session ID 并与 Claude Code 默认会话 ID 一致。
自检通过后才能进正式采集。采题期间<strong>保持 Gateway 开启</strong>。
交卷每个模型必须<strong>同时</strong>交 <code>session/</code>（Claude Code）与 <code>cc-gateway-log/</code>（Gateway），<strong>缺一不可</strong>。
</span>

[甲方要求说明.md](./甲方要求说明.md) 含门槛细则与文末「甲方要求一览」；日常以操作步骤为主。

交卷前可用 **[上传前预检/](./上传前预检/)**：用户**只提供数据包目录路径**即可  
（§A 结构 + §B 包内 `session/`/`cc-gateway-log` 合并校验；未给路径时先询问）。  

结构绿 / call-level 绿 ≠ 比例合格 ≠ 结算。**最终以甲方实际审核为准。**

有疑问时，可先让 Agent 加载 **[qa_skill/](./qa_skill/)**（读 `SKILL.md`）按口径交流答疑。

想参与采集？见 **[参与方式.md](./参与方式.md)**。

| 文档 / 资源 | 用途 |
| --- | --- |
| [用户操作步骤.md](./用户操作步骤.md) | 主线：怎么做 |
| [cc-gateway/README.md](./cc-gateway/README.md) | **Gateway 从零手册**：yaml 怎么写、逐步验证、Session ID 怎么对 |
| [Gateway采集说明.md](./Gateway采集说明.md) | 自检清单、启动、切换模型、双目录交卷、Session ID |
| [甲方要求说明.md](./甲方要求说明.md) | 门槛、字段、Checklist、甲方要求一览 |
| [参与方式.md](./参与方式.md) | 谁可参与、如何报名进群 |
| [甲方数据包参考样例/](./甲方数据包参考样例/) | 交卷结构样例 |
| [qa_skill/](./qa_skill/) | 答疑 |
| [上传前预检/](./上传前预检/) | 结构预检（§A）+ 可选 call-level 合并检测（§B） |

## 参与方式（摘要）

- **对象**：理工类程序员相关从业者（前后端、数据分析、测试、DevOps 等）  
- **门槛**：Claude Code 完成过 ≥2 个项目；有 Docker 与单元测试经验  
- **报名**：微信发给 **栗子** 进群  
- **开跑前**：用仓库内 [cc-gateway/](./cc-gateway/) 做 **§0 接通自检**（通三模型 + Session ID 对齐）  
- **开跑后**：保持 Gateway 开启，用**自己的账号**采千问 / GLM / Opus；每模型**同时**交 **`session/` + `cc-gateway-log/`**（**缺一不可**）

## 提交量与分布（摘要）

- **不再要求**同题连跑多次（pass@4）；**每模型每题 1 份轨迹**：`session/` + `cc-gateway-log/`。  
- **要求每人至少交 ≥ 3 道题**，并在交题集合上满足模型过题比例：禁三模型全过；**Opus 过题率 ≤60%**；**Opus−千问 >20%**；**GLM ≥1 道过**。少于 3 道也可交，**是否采纳看当期整体分布**。  
- **所交每道题均须千问测不过**（千问过题率 = 0，便于拉开与 Opus 的差距）。  
- **平台不提供模型 API**；用自己的 Key / 订阅经本机 Gateway。  
- **结算与最终是否合格：以甲方实际审核为准。**

## FAQ

**Q：平台会提供模型 API / 密钥吗？**  
A：**不会。** 使用本地 **Gateway（cc-gateway）**；你用自己的 Key / Claude 订阅。用法见 [Gateway采集说明.md](./Gateway采集说明.md)。

**Q：可以绕过 Gateway、直连厂商 API 吗？**  
A：正式采集须走 Gateway，否则没有 Session 目录抓包。不要用未接入 Gateway 的直连冒充正式轨迹。

**Q：Gateway 装在哪？先测什么？**  
A：仓库 [cc-gateway/](./cc-gateway/)。**正式采题前必须做 Gateway 说明 §0**：三套 active 都能对话、抓包目录名 = Session ID 且与 Claude Code 一致。通过后再采集。

**Q：Gateway 日志在哪？和 Session 什么关系？**  
A：本机默认 `~/.claude_lproxy/projects/<sessionId>/*.json`，**文件夹名 = Session ID**。交卷拷入 `trajectories/<模型>/cc-gateway-log/`，与 `session/` 同一 ID。**session + Gateway 日志都要交，缺一不可。**

**Q：怎么才算「通过」？**  
A：单题单次看 Docker 里 `tests/test.sh` 退出码是否为 `0`。个人提交还要看**整体过/不过比例**；最终以甲方审核为准。

**Q：「一条数据」是某一个模型跑一次吗？**  
A：不是。一条 = **一道完整题**（数据包 + 三模型各 1 份 `session/` + `cc-gateway-log/`）+ 约定其它日志。

**Q：还要不要同题跑 4 次（pass@4）？**  
A：**众包日常不要求。** 每模型每题 1 条轨迹即可；看你交的多道题上的整体比例。

**Q：预审核 / 结构预检通过了就算过关吗？**  
A：不算。结构预检只做文件检查；call-level 合并仅验轨迹字段；集合比例须自核；**最终以甲方实际审核为准。**

**Q：要不要自己做 call-level？**  
A：不必手写。整理好数据包后：  
`python3 上传前预检/scripts/merge_call_level.py --package <任务包> --check`  
只用包内 `session/` + `cc-gateway-log/`。详见 [上传前预检/SKILL.md](./上传前预检/SKILL.md)。
