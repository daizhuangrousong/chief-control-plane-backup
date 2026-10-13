# R4.3 · Chief 固定验收命令 · Cursor Executor 任务书

你是执行者，本文件是唯一任务来源；拿不准写 `BLOCKED.md`，继续不受影响项。断线后先读 `PROGRESS.md` 接着做，每完成一项立即更新。此任务封死 R4.2 新增的任意命令重放面，让 Runner 只执行 Chief 在任务合同中预先声明的验收命令。让步顺序：命令来源可信 > 无越界副作用 > 证据完整 > 速度。“只允许/禁止”是硬约束。

## 我替领导拍的板

- 保持 Tier 1，同一 macOS 用户；不做 R6 权限隔离。
- Executor 不能新增、替换或改写验收 argv；Chief-authored task contract 是唯一命令源。
- 建议新增严格结构化 `verificationCommands` 字段（argv 数组，不用 shell 字符串）；若现有模型有等价安全字段可复用，允许替代并在 `PROGRESS.md` 说明。
- 本轮通过后直接进入 Eval R5，不再追加同层建设轮。

## 界限

只允许改任务合同/模型/解析所必需的 `src/control_plane/domain/models.py`、`src/control_plane/services/{task_registry,chief_task_ingress,cursor_runner,execution_contract}.py`、确有必要的 `src/control_plane/services/__init__.py`、对应 `tests/`、任务/生命周期示例 `config/`、`docs/EXECUTION_LIFECYCLE.md`、`docs/OPERATIONS.md`、`CHANGELOG.md`、`PROGRESS.md`、`BLOCKED.md`。其余只读。禁止权限、依赖、LaunchAgent、R1/R3/主仓/业务仓、merge/push/deploy/真实 Cursor/飞书。

## 现状与任务 0

HEAD 应为 `8dd4b1f`，自报 143/0/0；Chief Review：`reports/CHIEF_TASK_R4_2_CHIEF_REVIEW_2026-08-20.md`。核对 HEAD、clean、测试命令、任务 schema、R1 label/pid、R3 importer；不符写 `BLOCKED.md`。再用 ≤10 行记录目标、顺序、最大风险。

## 任务 1｜命令只由 Chief 合同提供

任务合同为每条 command 型 acceptance 保存预先声明的 argv；必须是非空字符串数组，禁止 shell 字符串、`sh|bash|zsh -c`、重定向/管道语义和空参数。Task 注册时严格拒绝缺失、额外、错序或未知字段。Executor result 只能引用对应 command id/criterion 并报告首次结果，不能提供可执行 argv；旧格式中的 Executor argv 必须拒绝。

反向验证：Executor 回报 `sh -c`、绝对路径写宿主、与 Chief argv 不同的命令、额外命令，均 FAILED 且调用次数 0。

## 任务 2｜Runner 独立执行并重验

Runner 从已注册任务读取 argv，以 `shell=False`、租约 worktree cwd、明确 timeout 执行；真实 exit code 非零即 FAILED。执行后重新运行 worktree clean/单提交/scope/diff-check，以及 runtime/target snapshot 检查；验收产生 tracked/untracked 变更、宿主变化或 commit 变化均不得 REVIEW。持久报告只记录 Chief argv、实际 exit code和受限长度输出摘要。

## 任务 3｜回归与兼容边界

真实临时 Git worktree 跑 A/B 生命周期；覆盖安全命令成功、命令失败、命令漂移、shell wrapper、验收弄脏树、验收改 commit、宿主变化。旧无结构命令任务必须明确 BLOCKED/不 READY，不得静默补 pass。文档写清 Tier 1 仅放行 Eval R5。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉 subprocess/Git 边界、`|| true`。测试数不得低于 143，skip=0；同一验收连败 3 次即停。完成后一个 R4.3 本地原子 commit，停在 Chief REVIEW。

## 完成条件

1. Executor 无法引入或漂移验收命令；Runner 只执行 Chief argv，任何验收副作用在 REVIEW 前被拒绝。
2. 全套测试 ≥143、0 fail、0 skip，`git diff --check` 通过；R1/R3/主仓不变，真实外部调用增量 0。交付贴实际输出与红→绿证据；`BLOCKED.md` 无阻塞也写“无”。

