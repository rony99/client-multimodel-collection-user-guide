# 上传前预检

用户**只需提供一个**已整理好的**甲方数据包目录路径**。  
未提供路径时：Agent 先询问，勿开跑、勿猜路径。

**只读原则：不得修改用户数据包。**  
call-level 合并与 **Docker 验收** 均在**系统临时目录深拷贝**上做（见 [SKILL.md](./SKILL.md) §D）。

```bash
# §A 结构 / meta / scores / reports（静态；不含 Docker 强制跑）
python3 scripts/presubmit_check.py --task-dir <数据包> --markdown

# §B call-level（临时目录合并，不写回包）
python3 scripts/merge_call_level.py --package <数据包> --check
```

**§D Docker**：由 **Agent** 按 SKILL 步骤执行（对齐 platform 目标：临时拷贝 → build → Baseline 须挂 → 套 GT → 须过）。  
不必做成平台级自动化套件；说明白、可复现即可。脚本提醒见 PASS `DOCKER_AGENT_REMINDER`。

**反馈**：全量 FAIL/WARN（问题/原因/违反/建议）+ 下一步；一项失败不截断其它检测。

绿预检 **不等于** 甲方终审。细节见 [SKILL.md](./SKILL.md)。
