# cc-gateway 预编译包（本仓库自带）

正式众包采集用的 **本地 Gateway** 发行包（macOS / Linux / Windows，amd64 + arm64）。

| 目录 | 系统 |
| --- | --- |
| [cc-gateway-mac/](./cc-gateway-mac/) | macOS |
| [cc-gateway-linux/](./cc-gateway-linux/) | Linux |
| [cc-gateway-win/](./cc-gateway-win/) | Windows |

**不要把** 本机改好后含密钥的 `providers.yaml`、`providers.claude.settings.json` 提交进仓库；只用 example 模板。

## 使用入口（必读顺序）

1. **本表 + 包内说明**：进入对应系统目录，读其中 `使用说明.md`。  
2. **众包流程与交卷硬规矩**：[../Gateway采集说明.md](../Gateway采集说明.md)  
   - **先完成「§0 接通自检」**：三套 `active`（A/B/C）都能通、Gateway 落盘目录名 = Session ID 且与 Claude Code 一致。  
   - **自检全绿后**再开正式出题采集。  
   - 采题全程 **保持 Gateway 开启**。  
3. 操作主线：[../用户操作步骤.md](../用户操作步骤.md)

## 启动摘录（Mac Apple Silicon）

```bash
cd cc-gateway/cc-gateway-mac
cp providers.example.yaml providers.yaml
# 编辑 url/key 与 active
chmod +x ./cc-gateway-arm64
./cc-gateway-arm64 -config ./providers.yaml
# 另开终端：按打印的命令
# claude --settings <绝对路径>/providers.claude.settings.json
```

Windows / Linux 见各子目录 `使用说明.md`。

## 交卷（缺一不可）

每个模型轨迹须同时提交：

1. **Claude Code 会话**：`trajectories/<模型>/session/`  
2. **Gateway 抓包**：`trajectories/<模型>/cc-gateway-log/`（本机源目录名 = Session ID）

二者 ID 一致；缺任一侧不合格。
