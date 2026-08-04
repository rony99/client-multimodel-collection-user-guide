cc-gateway v0.1.0 — linux 发行包
========================================

完整中文说明请打开同目录下的：  使用说明.md

【网络前置】
  使用 GLM / 千问 / 官方 Anthropic 时，请先开启 VPN，并建议使用 Tun 模式
  （全局虚拟网卡），不要仅开「系统代理」，否则 CLI/网关可能无法访问上游。

【快速开始】
  1. 复制配置：
       mac/linux:  cp providers.example.yaml providers.yaml
       windows:    Copy-Item providers.example.yaml providers.yaml
  2. 编辑 providers.yaml：设置 active 为 A/B/C，A/B 填 url 与 key
  3. 选择本机架构并启动网关：
       Apple Silicon / ARM64:  ./cc-gateway-arm64 -config ./providers.yaml
       Intel / AMD x86_64:     ./cc-gateway-amd64 -config ./providers.yaml
  4. 保持网关运行，另开终端，使用启动日志打印的命令启动 Claude Code：
       claude --settings <绝对路径>/providers.claude.settings.json

【方案说明】
  active: A  → GLM（glm-5.2）
  active: B  → 千问（qwen-3.7-max）
  active: C  → 官方 Claude 订阅透传（需本机已登录）

【抓包目录】
  默认：~/.claude_lproxy/projects/<sessionId>/<callId>.json
  sessionId 与 Claude Code 会话 UUID 一致（X-Claude-Code-Session-Id）。
  认证头不会落盘明文（显示 [redacted]）。

不需要安装 Go。详情见 使用说明.md
