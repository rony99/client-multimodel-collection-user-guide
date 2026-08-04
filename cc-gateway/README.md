# cc-gateway 使用手册（从零到验证通过）

本目录是**已经编译好**的本地 Gateway，装在你电脑上运行。  
作用只有一件事：让 **Claude Code → 本机网关 → 模型服务**；并把每次请求按 **Session ID** 记成日志。

正式出题 / 采集**之前**，请按本文做完**一遍验证**。验证不过，不要进入正式采集。

相关文档：

| 文档 | 看什么 |
| --- | --- |
| **本文** | 配置怎么写、怎么启动、怎么一步步验收 |
| [../Gateway采集说明.md](../Gateway采集说明.md) | 众包硬规矩、交卷、`session/` + `cc-gateway-log/` |
| [../用户操作步骤.md](../用户操作步骤.md) | 出题、调难度、交卷主线 |
| 各系统子目录里的 `使用说明.md` | 与本文等价的包内副本（偏技术备忘） |

---

## 0. 先搞懂三个名词

| 名词 | 含义 | 你在硬盘上看到什么 |
| --- | --- | --- |
| **Session ID** | Claude Code **每一次**新建对话会话的唯一 ID（通常是一串带横杠的 UUID） | 文件名、文件夹名里的那串 UUID |
| **Claude Code 会话文件** | Claude 把对话写在本地的日志 | 例如 `~/.claude/projects/某项目目录名/XXXXXXXX-....jsonl`，**文件名（去掉 .jsonl）= Session ID** |
| **Gateway 抓包目录** | 网关为**同一次对话**保存的 API 请求/响应 | 例如 `~/.claude_lproxy/projects/XXXXXXXX-..../`，**文件夹名 = Session ID** |

### 「Session ID 一样」到底指什么？

一次合格的对话，下面三处必须是**同一个 UUID**（字符完全相同，含横杠）：

```text
示例（假数据）：sessionId = a1b2c3d4-e5f6-7890-abcd-ef1234567890

1) Claude Code 会话文件：
   ~/.claude/projects/-tmp-ccgw-smoke/a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl
                                    └──────────── 这一段 ────────────┘

2) Gateway 抓包文件夹：
   ~/.claude_lproxy/projects/a1b2c3d4-e5f6-7890-abcd-ef1234567890/
                              └──────────── 这一段 ────────────┘

3) 文件夹里面应有 call 的 .json 文件（至少 1 个），例如：
   ~/.claude_lproxy/projects/a1b2c3d4-.../xxxx.json
```

- **对了**：说明 Claude Code 的请求确实打进了本机 Gateway，Gateway 按官方 Session 落盘。  
- **不对 / 没有 Gateway 文件夹**：说明没用 settings 走网关、网关没开、或看错了目录——**这次不能当正式轨迹**。

交卷时也一样：

```text
trajectories/<模型>/session/          ← 来自 Claude Code 的 .jsonl
trajectories/<模型>/cc-gateway-log/   ← 来自 Gateway 该 sessionId 目录下的 *.json
```

两边对应**同一次** Session ID。**缺一不可。**

---

## 1. 你需要准备什么

1. 已安装 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)，在终端执行 `claude --version` 有输出。  
2. 本仓库已 clone 到本机（本 `cc-gateway` 文件夹在仓库里）。  
3. 至少准备好你接下来要用的账号（自检时 **A、B、C 各测一轮**）：  
   - **A GLM**：厂商提供的 **Anthropic 兼容**地址 + API Key  
   - **B 千问**：同上  
   - **C 官方 Opus**：本机 Claude Code **已经登录** Pro / Max 等订阅（网关不替你填官方 token）  
4. 若本机访问模型 API 需要代理：请开 VPN，并尽量用 **Tun / 增强 / 全局虚拟网卡**（不要只开「仅浏览器代理」）。

**不要**把含真实 Key 的 `providers.yaml`、网关自动生成的 `providers.claude.settings.json` 提交到 Git 或塞进交卷题目包。

---

## 2. 选择正确的程序目录和二进制

在仓库根目录下进入对应系统文件夹：

| 你的系统 | 进入目录 | 选哪个程序 |
| --- | --- | --- |
| macOS（M 系列芯片） | `cc-gateway/cc-gateway-mac/` | `cc-gateway-arm64` |
| macOS（Intel） | `cc-gateway/cc-gateway-mac/` | `cc-gateway-amd64` |
| Linux x86_64 | `cc-gateway/cc-gateway-linux/` | `cc-gateway-amd64` |
| Linux arm64 | `cc-gateway/cc-gateway-linux/` | `cc-gateway-arm64` |
| Windows x64 | `cc-gateway/cc-gateway-win/` | `cc-gateway-amd64.exe` |
| Windows ARM | `cc-gateway/cc-gateway-win/` | `cc-gateway-arm64.exe` |

不确定 Mac 芯片时：

```bash
uname -m
# arm64 → 用 cc-gateway-arm64
# x86_64 → 用 cc-gateway-amd64
```

---

## 3. 如何写配置文件 `providers.yaml`（逐步）

### 3.1 从模板复制一份

在**所选系统目录**下操作（下面以 Mac 为例；Linux/Windows 换路径即可）：

```bash
# 先进入本仓库
cd /你的路径/client-multimodel-collection-user-guide/cc-gateway/cc-gateway-mac

cp providers.example.yaml providers.yaml
```

Windows PowerShell：

```powershell
cd C:\你的路径\client-multimodel-collection-user-guide\cc-gateway\cc-gateway-win
Copy-Item providers.example.yaml providers.yaml
```

之后**只改** `providers.yaml`，不要改坏 `providers.example.yaml`（模板留给别人对照）。

### 3.2 字段说明（每一项是什么）

| 字段 | 必填？ | 含义 | 怎么写 |
| --- | --- | --- | --- |
| `active` | 是 | **当前**走哪一套模型 | 只能是 `A`、`B` 或 `C`（大写） |
| `root_dir` | 否 | Gateway 把日志存在哪 | **建议先留空**，自动用 `~/.claude_lproxy/projects` |
| `A.url` | 用 A 时必填 | GLM 的 Anthropic 兼容 API 根地址 | 以你购买的服务文档为准（一般带 `/anthropic` 一类路径） |
| `A.key` | 用 A 时必填 | GLM 的 API Key | 厂商控制台复制，**不要加引号外的空格** |
| `B.url` / `B.key` | 用 B 时必填 | 千问侧同理 | 同上 |
| `C` | 用 C 时 | 官方订阅透传 | 写成 `C: {}` 即可，**不要**在这里填 Anthropic key |

`active` 与模型对应关系：

| `active` 的值 | 实际用的侧 | 你需要 |
| --- | --- | --- |
| `A` | GLM（网关会映射到 `glm-5.2`） | 填好 `A.url` + `A.key` |
| `B` | 千问（映射 `qwen-3.7-max`） | 填好 `B.url` + `B.key` |
| `C` | 官方 Claude / Opus 订阅 | 本机已 `claude` 登录成功；`C: {}` |

### 3.3 完整示例（请换成你自己的真实值）

```yaml
# 当前启用哪套：验证时你会依次改成 A、再 B、再 C
active: A

# 抓包根目录：留空 = 默认
# macOS/Linux: /Users或home/<用户名>/.claude_lproxy/projects
# Windows:     C:\Users\<用户名>\.claude_lproxy\projects
root_dir:

A:  # GLM
  # 把下面换成你真实的 Anthropic 兼容 endpoint（示例为占位）
  url: https://your-glm-provider.example/api/anthropic
  key: sk-替换成你的GLM密钥

B:  # 千问
  url: https://your-qwen-provider.example/apps/anthropic
  key: sk-替换成你的千问密钥

C: {}  # 官方 Opus：无需 url / key
```

注意：

- YAML 缩进用**空格**，不要用 Tab。  
- `key:` 后面空一格再写密钥。  
- `url` 必须以你服务商文档为准；错一个字母就会连不上。  
- 改完 `active` 或密钥后，必须 **关掉网关再重新启动**，旧进程不会读新配置。

### 3.4 第一次建议怎么填

1. 先把 `A`、`B` 的 `url`/`key` 都写好（真密钥）。  
2. `active` **先写 `A`**（先测 GLM）。  
3. `C` 保持 `{}`；测 C 时仅靠本机 Claude 登录。  
4. `root_dir` 留空，方便和本文命令一致。

---

## 4. 启动 Gateway（终端 ①，全程不要关）

### macOS / Linux

```bash
cd /你的路径/.../cc-gateway/cc-gateway-mac   # 或 linux 目录

chmod +x ./cc-gateway-arm64 ./cc-gateway-amd64   # 首次需要
./cc-gateway-arm64 -config ./providers.yaml      # 按 §2 换成 amd64 如需要
```

### Windows（PowerShell）

```powershell
cd C:\你的路径\...\cc-gateway\cc-gateway-win
.\cc-gateway-amd64.exe -config .\providers.yaml
```

### 启动成功时，终端应出现类似内容

```text
cc-gateway ready (...)
  active:       A (GLM)
  listen:        :3001
  data dir:      /Users/你的用户名/.claude_lproxy/projects
  upstream:      https://...
  ...

Start Claude Code with:
  claude --settings /绝对路径/providers.claude.settings.json
```

请**原样复制**最后一行的路径（每个机器绝对路径不同）。  
同目录下会生成：`providers.claude.settings.json`（含指向本机网关的设置；A/B 时还会写入 token，勿外传）。

**这个跑着 Gateway 的窗口在验证 / 采集期间都不要关。**  
关掉 = 不再抓包；关掉后的对话不能当正式数据。

若启动失败（进程直接退出）：

- 看终端报错：常见是 `providers.yaml` 缩进错误、缺 key、端口占用。  
- 端口被占时可：`CCG_LISTEN_ADDR=:3002 ./cc-gateway-arm64 -config ./providers.yaml`（再按新路径用 settings）。

---

## 5. 验证是否成功（照着做，建议约 10–15 分钟）

目标（全部打勾才算 Gateway **可用**）：

1. 网关在本机监听；  
2. Claude Code 能经网关拿到模型回复；  
3. 硬盘上**出现与 Session ID 同名的 Gateway 文件夹**，且与 Claude 会话文件同名；  
4. 对 `active=A`、`B`、`C` **各成功至少一轮**。

下面以 **`active: A`（GLM）** 写完整步骤；B、C 只是改配置重做一遍。

### 步骤 1：确认网关活着

**另开一个终端**（不要停 Gateway 那个）：

```bash
curl -s http://127.0.0.1:3001/health
```

- 有正常响应（非「连接被拒绝」）→ 继续。  
- `Connection refused` → Gateway 没在跑或端口不对。

### 步骤 2：在干净目录用网关启动 Claude Code

```bash
mkdir -p /tmp/ccgw-smoke
cd /tmp/ccgw-smoke

# 把下面换成 Gateway 终端里打印的那一整行（路径要对）
claude --settings /绝对路径/providers.claude.settings.json
```

**必须**带 `--settings ...providers.claude.settings.json`。  
若直接敲 `claude` 不带 settings，往往**不走 Gateway**，后面就没有合法抓包。

### 步骤 3：在 Claude 里发一句短话

例如：

```text
只用一个词回复：pong
```

等到界面上出现模型回复（不是一直报错、不是空白失败）。

### 步骤 4：找出本次的 Session ID（Claude Code 侧）

再开一个终端：

```bash
# 看本项目相关会话目录（/tmp/ccgw-smoke 会被编码进项目路径名，名称因版本而异）
ls -lt ~/.claude/projects | head

# 进入最近修改较多的、与 smoke 相关的目录后：
ls -lt ~/.claude/projects/<刚才看到的项目目录名>/ | head
```

你应看到类似：

```text
a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl
```

**没有 `.jsonl` 扩展名的整段 UUID = Session ID。**  
先复制保存，例如：

```text
SESSION_ID=a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

若一次有多个 `.jsonl`，选**刚刚创建 / 时间最新**的那个。

### 步骤 5：核对 Gateway 侧有没有「同名文件夹」

```bash
# 列出抓包根目录（data dir 以 Gateway 启动打印为准，默认如下）
ls -lt ~/.claude_lproxy/projects | head

# 用你在步骤 4 记下的 SESSION_ID：
ls -la ~/.claude_lproxy/projects/$SESSION_ID/
```

**验证成功的标志：**

| 检查项 | 通过标准 |
| --- | --- |
| 文件夹存在 | 路径就是 `.../projects/<与步骤4完全相同的UUID>/` |
| 里面有文件 | 至少 1 个 `*.json`（有的包可能命名 call-001 等，只要是 json 落盘即可） |
| Session ID 一致 | 文件夹名 **字符串等于** Claude 的 `<uuid>.jsonl` 去掉后缀后的部分 |
| 对话有效 | Claude 侧有模型回复，不是纯本地错误信息 |

可选：打开某一个 `*.json`，用编辑器搜索该 UUID，应能在字段或请求头痕迹里看到同一 Session（有的版本字段名是 `sessionId` 等）。

### 步骤 6：用同一方法再测 B 和 C

测完 A 后：

1. 在 Claude 里退出本次会话（或关掉该 Claude 窗口）。  
2. 回到 Gateway 终端：`Ctrl+C` 停掉网关。  
3. 编辑 `providers.yaml`：把 `active: A` 改成 `active: B`（配好 B 的 url/key）。  
4. **重新启动**网关（§4）。  
5. **新开**一个终端，重新 `claude --settings <新打印的 settings 路径>`（新 session）。  
6. 再说一句话 → 重复步骤 4–5 核对 **新的** Session ID 与 Gateway 文件夹一致。  
7. 再对 `active: C` 做一轮（本机须已登录官方订阅）。

### 步骤 7：自检清单（全部 ✓ 才算「Gateway 管用」）

- [ ] `active=A`：能对话 + 两边 Session ID 一致 + 有 `*.json` 抓包  
- [ ] `active=B`：同上  
- [ ] `active=C`：同上  
- [ ] 全程用的是 Gateway 打印的 `claude --settings ...`  
- [ ] 没在「关掉网关」的情况下当正式会话  

**全部完成后，Gateway 程序可以用于正式采集。**  
再按 [../用户操作步骤.md](../用户操作步骤.md) 做出题、调难度、三模型交卷。

---

## 6. 正式采集时怎么用（验收通过之后）

1. **先开 Gateway**，保持运行。  
2. `active` 设成当前要采的模型（千问→`B`，GLM→`A`，Opus→`C`）。  
3. 在**做题工作目录**里：`claude --settings …/providers.claude.settings.json`。  
4. 做完一题/一模型：  
   - 拷 Claude 的 `<sessionId>.jsonl`（及 subagents，如有）→ 任务包  
     `trajectories/<模型>/session/`  
   - 拷 `~/.claude_lproxy/projects/<同一sessionId>/` 下全部 `*.json` →  
     `trajectories/<模型>/cc-gateway-log/`  
5. 换模型：改 `active` → **重启网关** → **全新 session** + 新工作副本（不要脏 session 里混模型）。  

<span style="color:#d93025">
<strong>交卷强调：</strong>每个模型必须同时提交 Claude Code 会话（session/）与 Gateway 日志（cc-gateway-log/），缺一不可；两侧 Session ID 必须一致。
</span>

---

## 7. 常见失败对照表

| 现象 | 常见原因 | 怎么处理 |
| --- | --- | --- |
| `curl` 连不上 3001 | 网关没起 / 改了端口 | 看 Gateway 窗口；检查 `CCG_LISTEN_ADDR` |
| Claude 一直报 API / 401 / 连不上 | key 错、url 错、订阅未登录、网络/VPN | 核对 yaml、`active`、VPN Tun；C 案先不经网关确认能登录 |
| 有 Claude 对话，**没有** `~/.claude_lproxy/projects/<id>/` | 没用 `--settings`、或 settings 不是本次网关生成的 | 只用当前 Gateway 打印的那条命令启动 |
| Gateway 有文件夹，但 UUID **对不上** Claude 的 jsonl 名 | 开了多个 session / 看了旧目录 | 用「时间最新」的 jsonl 与最新 projects 子目录对比 |
| 换了 `active` 但还是旧模型 | 没重启网关 / 没新开 Claude | 必须重启网关 + 新 session |
| 抓包 json 里看见明文 key | 异常版本或看错文件 | 正常应脱敏；勿把日志上传到公网仓库 |

---

## 8. 目录一览

```text
cc-gateway/
  README.md                 ← 你正在看的使用手册
  cc-gateway-mac/
  cc-gateway-linux/
  cc-gateway-win/
      cc-gateway-arm64[.exe]
      cc-gateway-amd64[.exe]
      providers.example.yaml   ← 模板（可进 Git）
      providers.yaml           ← 你自己的配置（勿提交）
      providers.claude.settings.json  ← 启动后生成（勿提交）
      使用说明.md
```

若只看本节仍失败：把 **Gateway 启动全文日志**、**`active` 值**、**Claude 报错原文**、**session 文件名**、**`ls ~/.claude_lproxy/projects` 结果**发给群里支持（注意打码 key）。
