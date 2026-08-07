# 上传前预检

用户**只需提供一个**已整理好的**甲方数据包目录路径**。  
未提供路径时：Agent 先询问，勿开跑、勿猜路径。

```bash
# §A 结构（含 Dockerfile 固定版本 / 禁止 latest）
python3 scripts/presubmit_check.py --task-dir <数据包> --markdown

# §B 包内 session + cc-gateway-log 合并到临时目录，再校验甲方 call-level（同一 PACK）
# 默认不写回数据包
python3 scripts/merge_call_level.py --package <数据包> --check
```

§A：布局 + 轨迹 + **Dockerfile 钉 tag（禁 latest）** + **README 必填** + **禁空壳 test.sh** + workspace 脏目录/密钥粗扫 等。  
§B：只读包内两路日志 → 临时 `call_level.jsonl` → 字段校验（**effort high+**；有 thinking 时 Opus 强制 signature 非空；GLM/千问不硬检；无 thinking 不查）。  
结构/合并绿 ≠ 结算；**最终以甲方实际审核为准。**  
完整规则：[SKILL.md](./SKILL.md)（含 **§C：对照 [甲方要求说明.md](../甲方要求说明.md) 全面复核 + double check**）。
