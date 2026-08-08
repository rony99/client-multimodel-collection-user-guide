# 上传前预检

用户**只需提供一个**已整理好的**甲方数据包目录路径**。  
未提供路径时：Agent 先询问，勿开跑、勿猜路径。

**只读原则：脚本与 Agent 均不得对用户数据包做任何写入**（合并与报告仅写包外临时目录 / stdout）。

```bash
# §A 结构（含 Dockerfile 固定版本 / 禁止 latest）— 只读
python3 scripts/presubmit_check.py --task-dir <数据包> --markdown

# §B 包内 session + cc-gateway-log 合并到**临时目录**，再校验甲方 call-level
# 严禁写回数据包（--write-into-package 已禁用）
python3 scripts/merge_call_level.py --package <数据包> --check
```

§A：对齐 **3bench 平台** 可静态机检（布局、Dockerfile、轮次≥20/模型、scores/reports、禁三模全过/千问挂、空壳 test 等）。  
§B：call-level 合并校验。§C：对照 [甲方要求说明.md](../甲方要求说明.md) double check。  
**仍不代替** 平台 Docker/GT 真跑。详见 [SKILL.md](./SKILL.md)。
