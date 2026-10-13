# R4.2 · 真实验收与可恢复合并 · Cursor Executor 任务书

你是执行者，本文件是唯一任务来源；拿不准的写 `BLOCKED.md`，继续不受影响项。断线后先读 `PROGRESS.md` 接着做，每完成一项立即更新。此任务让可信但可能出错的本机 Executor 不能靠假绿灯进入合并，并让写报告或 merge 失败后可恢复。让步顺序：证据真实 > 状态可恢复 > 不重复副作用 > 速度。“只允许/禁止”是硬约束；建议可调整但须记理由。

## 我替领导拍的板

- Owner 已批准 Tier 1：同一 macOS 用户，防误操作与错误，不宣称防恶意进程；R5 只允许新 Eval 仓库。
- R6 才解决系统权限隔离；本任务禁止顺手加用户、沙箱、容器或新服务。
- Executor 验收证据必须来自实际返回结果，Runner 不得把任务 criterion 自动标为 pass。
- Git merge 失败不能消费 Chief decision；崩溃重试不得产生第二次 merge。

## 界限

只允许改 `src/control_plane/services/{cursor_runner,execution_contract,chief_review_decision,task_merger}.py`、确有必要的 `src/control_plane/services/__init__.py`、`tests/test_execution_lifecycle.py`、`config/*execution-lifecycle*`、`config/*chief-review*`、`docs/EXECUTION_LIFECYCLE.md`、`docs/OPERATIONS.md`、`CHANGELOG.md`、`PROGRESS.md`、`BLOCKED.md`。其余只读。禁止改任务方向/审批分类、旧测试判据、依赖、权限、LaunchAgent、R1/R3/主仓/业务仓；禁止 merge/push/deploy/真实 Cursor/飞书。

## 现状与任务 0

HEAD 应为 `5701a4e`，自报基线 137/0/0；Chief Review：`reports/CHIEF_TASK_R4_1_CHIEF_REVIEW_2026-08-20.md`。先核对 HEAD、clean、测试命令、R1 label/pid、R3 importer 不存在；不符写 `BLOCKED.md`。再在 `PROGRESS.md` 用 ≤10 行记录目标、顺序、最大风险。

## 任务 1｜验收不能自动写绿

定义严格 Executor result envelope：必须绑定 task/version/lease/commit，并逐条返回与 task acceptance 同序的实际检查结果；每项包含 criterion、明确的执行/人工检查类型、状态、非空证据，命令型还须有 argv 与真实 exit code。Runner 只解析和验证，禁止自己生成 pass。缺项、错序、空证据、非零退出、畸形 JSON、普通文本或 commit 不匹配均进入 FAILED，不能 REVIEW。先用旧实现证明“失败验收仍被写绿”，再修到红→绿。

## 任务 2｜证据先落盘，再进入 REVIEW

顺序固定为：Executor 成功 → 主机/提交/范围复核 → 严格解析验收 → 原子持久化报告 → 回读并校验 → Dispatcher complete 到 REVIEW。任一报告写入/回读失败必须 fail lease，任务不得留在 REVIEW；残留临时文件不得被 merger 接受。故障注入覆盖写失败、截断、替换和 complete 冲突。

## 任务 3｜merge 失败与崩溃可恢复

Chief decision 只在 fast-forward 已确认成功后消费。实现幂等恢复：若目标 HEAD 已等于已批准 commit，但 receipt/consume 未完成，重试只补齐状态，不再 merge；若 merge 失败，decision 保持可用、HEAD/baseline 不变；receipt、decision hash、task/version/lease/commit 必须一致。故障注入覆盖 merge 前、merge 后/receipt 前、receipt 后/consume 前；每种恢复后 merge 副作用最多 1 次。

## 任务 4｜Tier 1 回归

真实临时 Git worktree 跑 A→review→merge→promotion→B；再跑失败验收、报告写失败、merge 冲突和三处崩溃点。A/B 各 1 次 execute/merge/promotion；失败路径不晋升 baseline，runtime 与目标树保持预期状态。文档明确：R4.2 仅允许 Eval R5，不得连接 Julius/Director/DB/密钥/部署。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉 Git/持久化/merge 边界、`|| true`。测试数不得低于 137，skip=0；同一验收连败 3 次即停该项。完成后一个 R4.2 本地原子 commit，停在 Chief REVIEW。

## 完成条件

1. 失败/缺失/伪造验收不能进入 REVIEW；报告故障不孤立 REVIEW；merge 任一失败/崩溃点可重试且副作用最多 1 次。
2. 全套测试 ≥137、0 fail、0 skip，`git diff --check` 通过；R1/R3/主仓不变，真实外部调用增量 0。交付必须贴实际输出与红→绿证据；`BLOCKED.md` 无阻塞也写“无”。

