---
name: client-harbor-presubmit
description: >-
  上传前预检众包任务包。§A 结构/meta/scores 脚本 + §B call-level + §D Agent 在临时深拷贝上
  Docker Baseline/GT + 对照甲方要求说明.md。全量汇报不阻断；不改用户包。绿≠终审。未给路径先问。
---

# 上传前预检（众包自包含包）

对用户**已整理好的甲方数据包**做检查：

1. **§A 脚本**：结构 + meta 人写交付 + scores/reports（静态机检）  
2. **§B**：临时目录合并 call-level 并校验  
3. **§D Docker（Agent 执行）**：按 platform 思路，**深拷贝后** Baseline 须挂、套 GT 后须过——**不必**做成与平台同等严格的自动化套件；步骤清晰可复现即可  
4. **§C**：对照 [`../甲方要求说明.md`](../甲方要求说明.md) double check  
5. **全量输出**：任一项问题 **不阻断** 其它项；一次列出全部 FAIL/WARN + 下一步  

## 硬规则：只读用户包

- **禁止**修改用户数据包任何内容  
- §B 合并、§D Docker 的**一切写操作**只允许在**系统临时目录的深拷贝**上  
- `--json` 不得写进用户包；默认 stdout  
- Agent 只汇报，不为「修绿」去改用户包  

---

## 标准流程

```text
PACK = 用户数据包路径（唯一必要输入）
  → §A：python3 scripts/presubmit_check.py --task-dir PACK --markdown
  → §B：python3 scripts/merge_call_level.py --package PACK --check
  → §D：Agent 按下文「深拷贝 + Docker」验收（不写 PACK）
  → §C：对照 甲方要求说明.md（含集合比例等）
  → 汇报：全部审核点 + 四段人话 + 下一步计划
```

用户未给 `PACK` → 先问路径，禁止猜。

---

## §A 静态机检（脚本）

| 项 | 说明 |
| --- | --- |
| 必备路径、空壳 test、脏 workspace、密钥 | FAIL |
| Dockerfile：`FROM` 钉 tag；pip **`pkg==x.y.z`**；npm 钉版本 | FAIL |
| meta：`task_id`=目录名；`annotator_background`；`completion_time_min`；`agreement_score`∈[0,1] | FAIL |
| 每模型 1 主 session；assistant 轮次各自 ≥20 | FAIL |
| scores/reports、禁三模全过、千问须挂、correctness↔eval_pass | FAIL |
| instruction 强泄题词 | FAIL |

脚本 **不**自动跑 Docker。PASS 项 `DOCKER_AGENT_REMINDER` 提醒你必须做 §D。

```bash
python3 scripts/presubmit_check.py --task-dir <PACK> --markdown
```

---

## §D Docker 验收（Agent 执行 · 对齐 platform 思路 · 不必过严）

与平台 `packagecheck` **同目标、可简化步骤**：证明「环境能 build」「未套答案测挂」「套答案测过」。  
可用 shell 逐步做，不必复制平台全部沙箱参数；**必须**遵守：只动临时副本、清理干净。

### 0. 前置

- `docker version` 能看到 **Server**（Docker Desktop / colima / dockerd 已启动）  
- 未启动 → 汇报「本机 Docker 未就绪」，**仍完成** §A/§B/§C 其它项后一并给用户  

### 1. 深拷贝（强制）

```bash
# 示例：绝对路径 PACK；副本不得落在 PACK 内
EVAL=$(mktemp -d "${TMPDIR:-/tmp}/cc-docker-eval.XXXXXX")
# 禁止：EVAL 是 PACK 的子目录
cp -a "$PACK"/. "$EVAL"/
# 后续所有 docker build / 改 workspace / 套答案 只对 $EVAL
```

结束后（成功或失败）：

```bash
# 删除本测镜像标签（若创建过）+ 删除副本
docker rmi -f cc-presubmit-baseline cc-presubmit-gt 2>/dev/null || true
rm -rf "$EVAL"
```

### 2. Baseline：未套标准答案，测试应失败

```bash
cd "$EVAL/environment"
docker build -t cc-presubmit-baseline .
# 跑 tests：把 tests 挂进容器只读（思路同 platform）
docker run --rm --network=none \
  -v "$EVAL/tests:/tests:ro" \
  cc-presubmit-baseline \
  bash -lc 'bash /tests/test.sh; echo EXIT:$?'
```

**判定（够用即可）：**

| 结果 | 结论 |
| --- | --- |
| test 失败 / 非 0 / reward≠1 | **通过**「初始应挂」 |
| test 成功 / 退出 0 且像全过 | **FAIL**：空壳测或答案已在 workspace |

记录：build 是否成功、测试退出码、关键日志摘要。

### 3. 在副本上套 GT，再测应通过

**仅改 `$EVAL`，永不写 `$PACK`。** 优先级与平台一致，任一条能套上即可：

1. 若有 `ground_truth/` 下非 patch 文件 → 按相对路径覆盖到 `$EVAL/environment/workspace/`（跳过 README、`*.patch`）  
2. 若有 `*.patch` → 在 workspace 内 `patch -p1`（或等价）  
3. 否则若有 `solution/solve.sh` → 在副本上于容器内执行（挂载整个 `$EVAL` 也可）

然后：

```bash
cd "$EVAL/environment"
docker build -t cc-presubmit-gt .
docker run --rm --network=none \
  -v "$EVAL/tests:/tests:ro" \
  cc-presubmit-gt \
  bash -lc 'bash /tests/test.sh; echo EXIT:$?'
```

**须通过**（退出 0 或 reward=1）。失败 → FAIL + 日志摘要 + 建议修 GT/tests（**不要改用户包**，只说明）。

### 4. 与脚本结果合并汇报

- §A 全部 FAIL/WARN  
- §D：`DOCKER_BUILD` / `BASELINE_MUST_FAIL` / `GT_MUST_PASS` 等人话条目  
- 一项失败 **不停** 其它步骤  

### 不必追求的（相对平台可省略）

- 镜像国内源 rewrite、严格 memory/cpu 限制、与平台完全一致的 reward 解析标记  
- 把 Docker 嵌进 `presubmit_check.py` 强制进程内跑  

只要说明：副本路径、build 成败、Baseline 挂/通、GT 套用方式、GT 后挂/通。

---

## §B call-level

```bash
python3 scripts/merge_call_level.py --package <PACK> --check
```

合并产物**仅**临时目录；已禁用写回包。

---

## §C 对照甲方要求（脚本未覆盖）

- 集合：题量≥3、千问全挂、Opus≤60%、Opus−千问>20%、GLM≥1  
- 私有题意、过程一致性、未伪造轨迹等  
- 权威：[`../甲方要求说明.md`](../甲方要求说明.md)

---

## 汇报格式

每条 FAIL/WARN：

1. **问题** 2. **原因** 3. **违反** 4. **建议**  

文末 **下一步计划**（不阻断、按序）。

开场可告知：

> 结构脚本 + call-level +（我这边）临时目录 Docker Baseline/GT + 对照甲方说明；一次给全量结果；不改你的包。绿 ≠ 网站终审。
