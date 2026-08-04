# Gateway 采集说明（本地 cc-gateway）

正式采集须经 **本地 Gateway（cc-gateway）** 中转 Claude Code 请求：平台**不**代发模型 API。你用**自己的账号 / Key / Claude 订阅**，Gateway 负责转发并**按 Session ID 落盘**请求响应。

> 本说明可独立阅读；操作主线仍见 [用户操作步骤.md](./用户操作步骤.md)。  
> 技术实现对齐本组织的 `local-cc-gateway`（cc-gateway）项目；你实际拿到的可能是预编译包，命令以包内 README 为准。

---

## 1. 你在做什么

```text
Claude Code  ──HTTP──►  本机 cc-gateway (:3001)  ──►  上游模型
                              │
                              ▼
                    <root_dir>/<sessionId>/*.json
                         （Gateway 抓包日志）
```

同时请保留 Claude Code 自己的 **会话轨迹**（主会话 `.jsonl`，交卷进 `trajectories/`；若群里还要求「赛讯日志」，按其定义一并交）。

| 日志类型 | 是什么 | 典型位置 |
| --- | --- | --- |
| **Gateway 日志** | 每次模型 API 调用的请求/响应抓包 | 见下文「抓包目录」 |
| **Claude Code session** | 做题对话主会话（及 subagent） | 本机 `~/.claude/projects/...`；交卷拷到 `trajectories/<模型>/` |
| **赛讯日志** | 若平台另有定义，以群内 / 平台说明为准 | 按说明打包发送 |

<span style="color:#d93025">正式跑题时必须先启动 Gateway，并用其生成的 settings 启动 Claude Code；否则没有 Gateway 日志，正式轨迹不齐。</span>

---

## 2. 前置条件

1. 已安装 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)，终端能运行 `claude`。  
2. 已拿到 **cc-gateway** 程序（预编译文件夹或源码编译产物；路径以发放为准）。  
3. 三套模型账号至少能配齐后续要用的：  
   - **A GLM**：厂商 Anthropic 兼容 URL + 你自己的 Key  
   - **B 千问**：同上  
   - **C 官方 Opus**：本机 Claude Code **已登录**官方订阅（Pro / Max 等）；Gateway **不**替你填 token  
4. 换模型 = 改配置后**重启 Gateway**，再开新 Claude Code session（不要混在同一脏 session 里换）。

---

## 3. 配置 `providers.yaml`

在 Gateway 所在目录：

```bash
cp providers.example.yaml providers.yaml
```

示例（勿把真实 key 提交进 git 或写进题目仓库）：

```yaml
# 当前启用：A=GLM | B=千问 | C=官方 Opus（订阅透传）
active: B

# 抓包根目录；留空则默认 ~/.claude_lproxy/projects
root_dir:

A:  # GLM
  # 填你可用的 Anthropic 兼容 endpoint（以厂商/聚合文档为准）
  url: https://your-glm-provider.example/api/anthropic
  key: your-glm-key

B:  # 千问（qwen-3.7-max）
  # 填你可用的 Anthropic 兼容 endpoint（以厂商/聚合文档为准）
  url: https://your-qwen-provider.example/apps/anthropic
  key: your-qwen-key

C: {}  # 官方 Opus：无需 url / key
```

| `active` | 对应模型（生成侧） | 你需要提供 |
| --- | --- | --- |
| `A` | GLM（配置里会钉 `glm-5.2`） | Anthropic 兼容 `url` + 自己的 `key` |
| `B` | 千问（`qwen-3.7-max`） | Anthropic 兼容 `url` + 自己的 `key` |
| `C` | 官方 Opus 订阅透传 | 本机已登录 Claude 订阅 |

可选：

```yaml
root_dir: ~/.claude_lproxy/projects   # 或绝对路径；便于你固定打包位置
```

环境变量（可选）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CCG_LISTEN_ADDR` | `:3001` | 监听地址 |
| `CCG_DATA_DIR` | — | 覆盖 `root_dir` / 默认抓包目录 |

---

## 4. 启动 Gateway

校验失败时进程**不会监听**，直接报错退出。

**macOS / Linux（预编译示例）**

```bash
cd /path/to/cc-gateway-mac    # 或 linux 包；选对应架构二进制
# 已写好 providers.yaml 后：
./cc-gateway-arm64 -config ./providers.yaml   # Apple Silicon
# ./cc-gateway-amd64 -config ./providers.yaml
```

**本机有 Go 时**

```bash
go run ./cmd/gateway -config ./providers.yaml
# 或
./cc-gateway -config ./providers.yaml
```

**Windows（PowerShell）**

```powershell
cd C:\path\to\cc-gateway-win
.\cc-gateway-amd64.exe -config .\providers.yaml
```

成功时终端类似：

```text
cc-gateway ready
   active:       B (...)
   listen:       :3001
...
Start Claude Code with:
  claude --settings /绝对路径/providers.claude.settings.json
```

网关会在 YAML **同目录**生成 `providers.claude.settings.json`（只含指向本机 Gateway 的 `ANTHROPIC_BASE_URL` 等；**A/B 的 key 会进 settings 的 ENV，注意勿外传、勿提交仓库**）。

<span style="color:#d93025">网关进程保持运行</span>，不要关掉再去开 Claude Code。

探活：

```bash
curl -s http://127.0.0.1:3001/health
```

---

## 5. 启动 Claude Code（必须走 settings）

**另开一个终端**，在**做题工作目录**（`runs/某模型/` 副本）下：

```bash
claude --settings /绝对路径/providers.claude.settings.json
```

Windows：

```powershell
claude --settings C:\path\to\providers.claude.settings.json
```

说明：

- `--settings` 覆盖本次会话的 `ANTHROPIC_BASE_URL` → 本机 Gateway，**不必**改全局 `~/.claude/settings.json`。  
- 务必在目标做题目录启动，避免 session 与工程路径对不上。  
- 新开做题：**新副本 + 新 session**（见操作步骤）。

---

## 6. 切换模型（千问 / GLM / Opus）

正式三模型各采一条时：

1. 编辑 `providers.yaml` 的 `active`（`A` / `B` / `C`），A/B 填好自己的 url/key。  
2. **Ctrl+C 停掉网关 → 再启动**（运行中不热加载配置）。  
3. 从干净 baseline **再 copy 一份**做题目录。  
4. 用**网关重新打印**的（或同一路径的）`claude --settings ...` **新开** Claude Code session。  
5. 发同一份 `instruction.md`；做完跑 `test.sh`、保存 session。

不要在同一 session / 脏目录里切换 `active` 当正式成绩。

---

## 7. 抓包目录与 Session ID（必须会验）

### 路径规则

```text
<root_dir>/<sessionId>/<callId>.json
```

- 默认 `<root_dir>` = `~/.claude_lproxy/projects`  
  - macOS：`/Users/<你>/.claude_lproxy/projects`  
  - Linux：`/home/<你>/.claude_lproxy/projects`  
  - Windows：`C:\Users\<你>\.claude_lproxy\projects`  
- **文件夹名 = Session ID**（与每条 JSON 内字段 `sessionId` 一致）。  
- 一次可见对话可能产生**多个** `*.json`（标题、探针、多次 `/v1/messages`）；不要当成「一个文件 = 一轮用户消息」。

Session ID 优先取 Claude Code 请求头 **`x-claude-code-session-id`**（一般即本机 session UUID）；无头时再退回 metadata / 消息哈希等。目录名会做安全化（非安全字符变 `_`）。

### 自检清单（每跑完一模型做一遍）

1. 网关进程仍在；`curl` `/health` 正常。  
2. 打开抓包根目录，确认**新出现**（或刚更新）了名为某 `<sessionId>` 的文件夹。  
3. 打开其中任一 `*.json`：  
   - `"sessionId"` **等于**父文件夹名  
   - 有 `request` / `response`（流式时 `response.bodyText` 可能是合并后的 assistant 文本）  
4. 对照本机 Claude Code 主会话：session 文件 id 应与该 `<sessionId>` **一致**（正式整理时轨迹放 `trajectories/<模型>/`，Gateway 目录整夹保留备交）。  
5. 鉴权头在抓包中为哈希，**不应**出现明文 API Key。  
6. （可选）用 [上传前预检 §B](./上传前预检/SKILL.md) 指定 session 根 + Gateway 根 + 该 Session ID，确认 **甲方 call-level 字段检测 PASS**（无 tools 的探针 call 会被跳过；须有真实主对话 + Gateway 落盘）。

若不出现新目录：多半是 Claude Code **没**使用 `--settings` 指向本机 Gateway，或请求未走到该网关端口。

> **流式说明**：local-cc 抓包对流式响应可能只保留部分 `bodyText`；正式 call-level 依赖 **Gateway request（system/tools）+ session assistant（完整 content）** 双源合并，勿只靠抓包当完整 reply。

---

## 8. 交卷时怎么交日志

| 交什么 | 建议 |
| --- | --- |
| 甲方数据包 + `trajectories/<模型>/` session | 见 [用户操作步骤.md](./用户操作步骤.md) 第 8 步 |
| **Gateway 日志** | 该题各模型对应的 `<root_dir>/<sessionId>/` 整目录（至少正式三条 session 的三个文件夹）；按群内要求打包 zip 上传 / 发送 |
| **赛讯日志** | 以平台 / 群内定义为准；若未另行定义，以「Claude Code 主会话 jsonl 已放 trajectories」为准，并确认 Gateway 目录齐 |
| call-level（可选） | [上传前预检 §B](./上传前预检/SKILL.md)：session 根 + Gateway 根 + Session ID → 校验后的 `call_level.jsonl` |

<span style="color:#d93025">只交题目、不交 Gateway 日志 = 正式链路不齐。</span>

---

## 9. 常见问题

| 现象 | 处理 |
| --- | --- |
| 启动立刻退出 | 检查 `providers.yaml` 是否存在；`active` 是否为 A/B/C；A/B 的 url（`http(s)` 绝对地址）与 key 是否非空 |
| 方案 C 认证失败 | 先用官方方式登录 Claude 订阅；Gateway 不代填 token |
| 方案 A/B 连不上 | 核对厂商兼容 URL 与 Key；看网关终端日志与抓包 `response.statusCode` |
| 改 YAML 不生效 | **必须重启** Gateway |
| 端口占用 | `CCG_LISTEN_ADDR=:3002 ./cc-gateway -config ./providers.yaml`，再用新 settings 启 Claude Code |
| 抓包目录为空 | 确认 `claude --settings` 指向本网关生成的 settings；确认在发请求时 Gateway 在运行 |
| 一次对话文件很多 | 正常；按 **sessionId 目录** 整夹保留，不要只挑一个 json 当全量 |

---

## 10. 推荐采一次「最小自测」

换正式出题前，建议先做 5 分钟冒烟：

1. `active: C`（或你已有 Key 的 A/B）配置并启动 Gateway。  
2. 任意空目录：`claude --settings ...`，发一句「ping」。  
3. 确认 `~/.claude_lproxy/projects/<sessionId>/` 下出现 `.json`，且 `sessionId` 与文件夹名一致。  
4. 再开始正式 baseline / 三模型流程。

---

相关：主线 [用户操作步骤.md](./用户操作步骤.md) · 报名 [参与方式.md](./参与方式.md) · 答疑 [qa_skill/faq.md](./qa_skill/faq.md) A 节 · call-level 合并 [上传前预检/SKILL.md](./上传前预检/SKILL.md) §B。
