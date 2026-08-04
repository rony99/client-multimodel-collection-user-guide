# 上传前预检

用户**只需提供一个**已整理好的**甲方数据包目录路径**。  
未提供路径时：Agent 先询问，勿开跑、勿猜路径。

```bash
# §A 结构
python3 scripts/presubmit_check.py --task-dir <数据包> --markdown

# §B 包内 session + cc-gateway-log 合并校验（同一路径）
python3 scripts/merge_call_level.py --package <数据包> --check
```

两段都只读该数据包；**不**回源本机 Claude / Gateway 原始目录。  
结构/合并绿 ≠ 结算；**最终以甲方实际审核为准。**  
完整 Agent 规则：[SKILL.md](./SKILL.md)。
