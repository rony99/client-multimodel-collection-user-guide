# Gateway 采集说明（本地 cc-gateway）

正式采集须经 **本地 Gateway（cc-gateway）** 中转 Claude Code 请求：平台**不**代发模型 API。你用**自己的账号 / Key / Claude 订阅**，Gateway 负责转发并**按 Session ID 落盘**请求响应。

本仓库已附带预编译包：

```text
cc-gateway/
  cc-gateway-mac/
  cc-gateway-linux/
  cc-gateway-win/
```

> **从零配置 / 逐步验收 / Session ID 怎么对**：请先完整看 [cc-gateway/README.md](./cc-gateway/README.md)（字段说明、yaml 示例、成功判定）。  
> 下文 §0 是验收清单摘要；包内另有各系统 `使用说明.md`。操作主线见 [用户操作步骤.md](./用户操作步骤.md)。

<span style="color:#d93025">
<strong>硬要求（务必记住）：</strong><br/>
1. 正式采题<strong>之前</strong>，必须先完成下文「§0 接通自检」；未自检通过不要进入正式轨迹采集。<br/>
2. 采题全过程<strong>保持 Gateway 进程开启</strong>；换模型改 active 后须重启网关并新开 session。<br/>
3. 交卷每个模型必须<strong>同时</strong>提交 Claude Code 会话目录与 Gateway 抓包目录：<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<code>trajectories/&lt;模型&gt;/session/</code> + <code>trajectories/&lt;模型&gt;/cc-gateway-log/</code>，<strong>缺一不可</strong>。<br/>
4. Gateway 落盘文件夹名 = <strong>Session ID</strong>，须与 Claude Code 默认会话 ID 一致。
</span>

---

## 0. 接通自检（采题前必做）

目的：确认「能通三套模型配置」+「Session ID 与落盘一致」。**全部通过后**再做出题与正式三模型轨迹。

**逐步操作（推荐照抄）：** [cc-gateway/README.md](./cc-gateway/README.md) 第 3–5 节  
（含「`providers.yaml` 每个字段怎么写」「Session ID 一样」示意图与命令）。

### 0.1 选对二进制

| 系统 | 目录 | 示例命令 |
| --- | --- | --- |
| macOS Apple Silicon | `cc-gateway/cc-gateway-mac/` | `./cc-gateway-arm64 -config ./providers.yaml` |
| macOS Intel | 同上 | `./cc-gateway-amd64 -config ./providers.yaml` |
| Linux x86_64 | `cc-gateway/cc-gateway-linux/` | `./cc-gateway-amd64 -config ./providers.yaml` |
| Linux arm64 | 同上 | `./cc-gateway-arm64 -config ./providers.yaml` |
| Windows x64 | `cc-gateway/cc-gateway-win/` | `.\cc-gateway-amd64.exe -config .\providers.yaml` |

若需代理才能访问上游，建议 VPN + **Tun 模式**（CLI 往往不走「仅浏览器代理」）。

### 0.2 配置

```bash
cd cc-gateway/cc-gateway-mac   # 按你的系统改路径
cp providers.example.yaml providers.yaml
# 编辑 A/B 的 url+key；C 需本机已登录 Claude 订阅
```

```yaml
active: A   # 自检时依次改为 A → B → C

root_dir:   # 建议先留空，用默认 ~/.claude_lproxy/projects

A:
  url: https://your-glm-provider.example/api/anthropic
  key: your-glm-key
B:
  url: https://your-qwen-provider.example/apps/anthropic
  key: your-qwen-key
C: {}
```

### 0.3 对 A / B / C 各跑一遍「通模型 + 对 ID」

每个 `active` 重复：

1. 启动 Gateway，**保持该终端在跑**。  
2. 确认打印类似：

   ```text
   cc-gateway ready (...)
     active:       A (GLM)
     listen:        :3001
     data dir:      /Users/<你>/.claude_lproxy/projects
   Start Claude Code with:
     claude --settings <绝对路径>/providers.claude.settings.json
   ```

3. 健康检查：

   ```bash
   curl -s http://127.0.0.1:3001/health
   ```

4. 新建一个空目录做探针（不要用正式题仓）：

   ```bash
   mkdir -p /tmp/ccgw-smoke && cd /tmp/ccgw-smoke
   claude --settings <网关打印的 providers.claude.settings.json 绝对路径>
   ```

5. 在 Claude 里发一条**带独特探针码**的短指令（如含 `CCGW-SMOKE-88421`），等模型有回复。  
6. **记下 Session ID 三处一致**：

   | 位置 | 应看到同一 UUID |
   | --- | --- |
   | Claude Code 会话文件 | `~/.claude/projects/<项目 slug>/<sessionId>.jsonl` |
   | Gateway 抓包目录 | `~/.claude_lproxy/projects/<sessionId>/`（**文件夹名就是 Session ID**） |
   | 抓包 JSON 内字段 | 如带 `sessionId` 或请求头 `X-Claude-Code-Session-Id` |

   ```bash
   ls -lt ~/.claude_lproxy/projects | head
   ls ~/.claude_lproxy/projects/<sessionId>/
   ```

7. **在 Gateway log 中确认「测过的内容」真的写进去了**（不要只看文件夹在）：

   ```bash
   # 搜索步骤 5 里你发的探针码 / 测试原文
   rg -n 'CCGW-SMOKE-88421' ~/.claude_lproxy/projects/<sessionId>/
   # 或: grep -R -n 'CCGW-SMOKE-88421' ~/.claude_lproxy/projects/<sessionId>/
   ```

   至少一个 `*.json` 命中 → 内容落盘成功。搜不到 → **不算自检通过**（可能是旧目录或未走网关）。逐步说明见 [cc-gateway/README.md](./cc-gateway/README.md) 步骤 6。

8. 换下一个 `active`：改 yaml → **重启 Gateway** → 新开 Claude（新 settings / 新 session / **新探针码**）→ 再测一遍。

### 0.4 自检通过标准（打勾再进正式采集）

- [ ] `A`（GLM）：能对话，Gateway 有对应 `<sessionId>/*.json`，**log 能搜到本轮测试原文**  
- [ ] `B`（千问）：同上  
- [ ] `C`（Opus 订阅）：同上（本机订阅已登录）  
- [ ] **每一轮** Gateway 目录名 = Claude Code 主会话文件名（同一 Session ID，与默认行为一致）  
- [ ] 抓包非空；认证字段已脱敏（明文 key 不应出现在 json 里）

<span style="color:#d93025">上述未全部通过 → Gateway 视为不可用，不要开始正式采集轨迹。</span>

---

## 1. 你在做什么

```text
Claude Code  ──HTTP──►  本机 cc-gateway (:3001)  ──►  上游模型
                              │
                              ▼
              ~/.claude_lproxy/projects/<sessionId>/*.json
                         （Gateway 抓包；文件夹名 = Session ID）
```

| 日志类型 | 是什么 | 交卷位置 |
| --- | --- | --- |
| **Claude Code session** | 做题主会话（及 subagent） | `trajectories/<模型>/session/` |
| **Gateway 日志** | 每次模型 API 调用的请求/响应抓包 | 本机 `~/.claude_lproxy/projects/<sessionId>/` → 包内 `trajectories/<模型>/cc-gateway-log/` |
| **赛讯日志** | 若平台另有定义 | 按群内说明 |

<span style="color:#d93025">
<strong>交卷缺一不可：</strong>同一模型下必须同时有<br/>
<code>session/</code>（Claude Code 默认轨迹）与 <code>cc-gateway-log/</code>（Gateway 日志）。
只交其中一种视为不合格。
</span>

---

## 2. 前置条件

1. 已安装 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)，终端能运行 `claude`。  
2. 本仓库 `cc-gateway/` 预编译包（或后续群里发放的同版本包）。  
3. 三套账号可配：`A` GLM、`B` 千问、`C` 本机 Claude 订阅。  
4. **§0 接通自检已通过。**  
5. 换模型 = 改 `active` → **重启 Gateway** → **新开** Claude session。

---

## 3. 配置 `providers.yaml`

见 §0.2 与 [cc-gateway/\*/使用说明.md](./cc-gateway/cc-gateway-mac/使用说明.md)。  
**勿**把真实 key 写进会公开的仓库或题目包。

| `active` | 生成侧 | 你提供 |
| --- | --- | --- |
| `A` | GLM（钉 `glm-5.2`） | Anthropic 兼容 `url` + `key` |
| `B` | 千问（`qwen-3.7-max`） | 同上 |
| `C` | 官方 Opus 透传 | 本机已登录订阅 |

可选环境变量：`CCG_LISTEN_ADDR`（默认 `:3001`）、`CCG_DATA_DIR`（覆盖抓包根目录）。

---

## 4. 启动 Gateway（正式采集时保持开启）

```bash
# macOS 示例
cd /path/to/本仓库/cc-gateway/cc-gateway-mac
./cc-gateway-arm64 -config ./providers.yaml
```

成功后按打印的：

```bash
claude --settings /绝对路径/providers.claude.settings.json
```

<span style="color:#d93025">
采集期间不要关掉 Gateway 终端。网关挂掉后无新抓包，该段 session 不能当正式轨迹提交。
换模型：停网关 → 改 active → 再起网关 → 新 session。
</span>

Windows / Linux 命令见包内 `使用说明.md`。

---

## 5. 切换模型

1. 改 `providers.yaml` 的 `active`（及 A/B 的 url/key）  
2. Ctrl+C 停 Gateway → 再启动  
3. 用**新**打印的 `claude --settings …`；**不要**在旧脏 session 里硬换模型  

正式轨迹：千问 / GLM / Opus 各 **1** 次有效跑，对应 `active` = `B` / `A` / `C`。

---

## 6. 抓包目录与 Session ID

| | 路径 |
| --- | --- |
| 默认抓包根 | `~/.claude_lproxy/projects` |
| 单次会话 | `~/.claude_lproxy/projects/<sessionId>/*.json` |
| Claude Code 主会话 | `~/.claude/projects/<项目 slug>/<sessionId>.jsonl` |

**约定：`<sessionId>` 文件夹名 = Claude Code 默认 Session ID（UUID）**，来自请求头 `X-Claude-Code-Session-Id`。  
若两边对不上，不要交该次轨迹；先重复 §0。

---

## 7. 交卷如何拷文件（两个目录都要）

对每个模型（例：qwen）：

```bash
# 1) Claude Code 会话 → session/
mkdir -p trajectories/qwen/session
cp ~/.claude/projects/<slug>/<sessionId>.jsonl \
   trajectories/qwen/session/session.jsonl
# 有 subagent 则一并放进 trajectories/qwen/session/subagents/

# 2) Gateway 整夹内容 → cc-gateway-log/
mkdir -p trajectories/qwen/cc-gateway-log
cp ~/.claude_lproxy/projects/<sessionId>/*.json \
   trajectories/qwen/cc-gateway-log/
```

`<sessionId>` 必须与 `session.jsonl` 文件名（或内容里会话 id）一致。  
GLM / Opus 同样各拷一套。

<span style="color:#d93025">
<strong>再次强调：</strong>提交包内须同时包含 Claude Code 默认筛选后的会话文件（整理进 <code>session/</code>）
与 Gateway 采集日志（整理进 <code>cc-gateway-log/</code>）。两者都在任务包内；缺一不可。
</span>

交卷前结构预检：

```bash
python3 上传前预检/scripts/presubmit_check.py --task-dir <任务包>
# 可选 call-level（同样只认包路径）：
python3 上传前预检/scripts/merge_call_level.py --package <任务包> --check
```

---

## 8. 常见问题

**自检时模型不通**  
- 查 VPN/Tun、url、key、`curl` 上游是否通  
- C 方案先确认本机未走网关时也能登录 Claude 订阅  

**有 session 无 Gateway 日志**  
- Gateway 没开、或 Claude 没用 `--settings` 指到网关  
- 该次不得当正式交卷  

**有 Gateway 日志但 Session ID 对不齐**  
- 勿混用多份 settings / 多进程乱开  
- 勿错设 `CCG_DATA_DIR` / `root_dir`  

**可以只交 session、回头补 Gateway 吗？**  
- 不能当正式：正式轨迹必须**当时**经 Gateway 采到，且包内两边齐全  

更多发行细节：`cc-gateway/<系统>/使用说明.md`。
