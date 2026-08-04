# 采集用户说明（v1.1）

<span style="color:#d93025">
<strong>重要：</strong>预审 / 上传前预检 / 结构或 call-level 自检结果<strong>仅供参考</strong>，
不代表交付合格或结算结果。<strong>最终一律以甲方审核标准为准。</strong>
</span>

本文件夹可独立使用。

## 开始前请先这样走

1. **先读并照做 [cc-gateway/README.md](./cc-gateway/README.md)**（Gateway 操作主手册：配置 `providers.yaml`、启动、逐步验收）。  
2. **先验证 Gateway 采集是否正常运行**（按该 README 第 5 节）：三套模型（A/B/C）都能通、Session ID 与 Claude Code 一致、且 Gateway log 里能搜到你的测试原文。  
3. **自检全部通过后**，再按 **[用户操作步骤.md](./用户操作步骤.md)** 做出题、调难度与正式采数交卷。  

<span style="color:#d93025">
<strong>不要跳过 Gateway 验收。</strong>未按
<a href="./cc-gateway/README.md">cc-gateway/README.md</a>
完成验证、不能确认采集落盘正常，请勿开始正式轨迹采集。
采题期间<strong>保持 Gateway 开启</strong>。
交卷每个模型必须<strong>同时</strong>交 <code>session/</code>（Claude Code）与 <code>cc-gateway-log/</code>（Gateway），
<strong>缺一不可</strong>。
</span>

**本地 Gateway 预编译包：** [cc-gateway/](./cc-gateway/)（mac / linux / win）  
**众包口径与清单补充：** [Gateway采集说明.md](./Gateway采集说明.md)  
**出题与交卷主线：** [用户操作步骤.md](./用户操作步骤.md)

[甲方要求说明.md](./甲方要求说明.md) 含门槛细则与文末「甲方要求一览」。

交卷前可用 **[上传前预检/](./上传前预检/)**：用户**只提供数据包目录路径**即可  
（§A 结构 + §B 包内 session/gateway **合并到临时目录**再做 call-level 校验；未给路径时先询问）。  

结构绿 / call-level 绿 ≠ 比例合格 ≠ 结算。**最终以甲方实际审核为准。**

有疑问时，可先让 Agent 加载 **[qa_skill/](./qa_skill/)**（读 `SKILL.md`）按口径交流答疑。

想参与采集？见 **[参与方式.md](./参与方式.md)**。

| 文档 / 资源 | 用途 |
| --- | --- |
| **[cc-gateway/README.md](./cc-gateway/README.md)** | **先看这份**：Gateway 怎么配、怎么跑、怎么先验采集是否正常 |
| [用户操作步骤.md](./用户操作步骤.md) | Gateway 验证通过后的主线：出题、调难度、交卷 |
| [Gateway采集说明.md](./Gateway采集说明.md) | 众包硬规矩、交卷 checklist、与操作步骤的口径补充 |
| [甲方要求说明.md](./甲方要求说明.md) | 门槛、字段、Checklist、甲方要求一览 |
| [参与方式.md](./参与方式.md) | 谁可参与、如何报名进群 |
| [甲方数据包参考样例/](./甲方数据包参考样例/) | 交卷结构样例 |
| [qa_skill/](./qa_skill/) | 答疑 |
| [上传前预检/](./上传前预检/) | 结构预检（§A）+ 可选 call-level 合并检测（§B） |

## 参与方式（摘要）

- **对象**：理工类程序员相关从业者（前后端、数据分析、测试、DevOps 等）  
- **门槛**：Claude Code 完成过 ≥2 个项目；有 Docker 与单元测试经验  
- **报名**：微信发给 **栗子** 进群  
- **开跑前**：必读 [cc-gateway/README.md](./cc-gateway/README.md)，**先验 Gateway 采集是否正常**（通 A/B/C、Session ID 对齐、log 能搜到测试文本），再开正式采数  
- **开跑后**：保持 Gateway 开启；每模型**同时**交 **`session/` + `cc-gateway-log/`**（**缺一不可**）

## 提交量与分布（摘要）

- **不再要求**同题连跑多次（pass@4）；**每模型每题 1 份轨迹**：`session/` + `cc-gateway-log/`。  
- **要求每人至少交 ≥ 3 道题**，并在交题集合上满足模型过题比例：禁三模型全过；**Opus 过题率 ≤60%**；**Opus−千问 >20%**；**GLM ≥1 道过**。少于 3 道也可交，**是否采纳看当期整体分布**。  
- **所交每道题均须千问测不过**（千问过题率 = 0，便于拉开与 Opus 的差距）。  
- **平台不提供模型 API**；用自己的 Key / 订阅经本机 Gateway。  
- **结算与最终是否合格：以甲方实际审核为准。**

## FAQ

**Q：Gateway 装在哪？先测什么？**  
A：包在 [cc-gateway/](./cc-gateway/)。**操作与验证一律按 [cc-gateway/README.md](./cc-gateway/README.md)**：配置、启动、第 5 节验收（通模型、Session ID、log 含测试原文）。先验 Gateway 采集正常，再进 [用户操作步骤.md](./用户操作步骤.md)。  

**Q：平台会提供模型 API / 密钥吗？**  
A：**不会。** 用本地 Gateway + 自己的 Key / Claude 订阅。先读 [cc-gateway/README.md](./cc-gateway/README.md)。

**Q：可以绕过 Gateway、直连厂商 API 吗？**  
A：正式采集须走 Gateway，否则没有合规 `cc-gateway-log`。不要用未接入 Gateway 的直连冒充正式轨迹。

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
A：不必手写。交卷只需整理好 `session/` + `cc-gateway-log/`。预检会在**临时目录**合并并校验甲方字段，**不改你的包**：  
`python3 上传前预检/scripts/merge_call_level.py --package <任务包> --check`  
详见 [上传前预检/SKILL.md](./上传前预检/SKILL.md)。
