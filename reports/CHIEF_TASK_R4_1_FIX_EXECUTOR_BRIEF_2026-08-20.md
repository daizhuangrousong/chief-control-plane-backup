# R4.1 · 封死隔离与自批绕过 · Cursor Executor 任务书

你是执行者，本文件是唯一任务来源；拿不准的写 `BLOCKED.md`，继续不受影响的项。断线后先读 `PROGRESS.md` 接着做，每完成一项立即更新。此任务要让 R4 的隔离、审查与合并边界在恶意输入下也成立。让步顺序：不污染运行时/生产树 > 不可自批自合 > 功能完整 > 速度。“只允许/禁止”是硬约束，“建议”可调整但要记理由。

## 我替领导拍的板

- R4 结论为 REJECT；只修 Chief Review 的 4 个阻断点，不扩架构。
- 审查决定必须来自任务工作树之外的 Chief review inbox；调用方传入的 `actor/caller_executor_id` 不算身份。
- 合并前必须读取持久化执行证据并独立重验 Git 范围；不能相信 Executor 返回的内存字典。
- R1 safe-idle、R3 状态、生产仓和真实 Cursor 都不动。

## 界限

只允许改 `src/control_plane/services/{cursor_runner,task_worktree,execution_contract,chief_review_decision,task_merger}.py`、确有必要的 `src/control_plane/services/__init__.py`、`tests/test_execution_lifecycle.py`、`config/*execution-lifecycle*`、`config/*chief-review*`、`docs/EXECUTION_LIFECYCLE.md`、`docs/OPERATIONS.md`、`CHANGELOG.md`、`PROGRESS.md`、`BLOCKED.md`。其余只读。禁止改旧测试判据、直接 SQL、依赖、权限、LaunchAgent、R1/R3 文件、主仓、业务仓；禁止 merge/push/deploy/真实 Cursor/飞书。

## 现状与任务 0

基线提交 `6d29059`，Executor 自报 134/0/0；Chief Review 位于 `reports/CHIEF_TASK_R4_CHIEF_REVIEW_2026-08-20.md`。先核对分支、HEAD、工作树、R1 pid/label 和测试命令；数字不符即写 `BLOCKED.md`。随后在 `PROGRESS.md` 用不超过 10 行写目标、顺序、最大风险。

## 任务 1｜任务树成为唯一可写工作区

启用 pool 时，传给 Executor 的 `workspaceRoots` 只能是租约 worktree，不能泄露原项目路径；执行后同时证明 runtime root、目标 checkout 与 baseline 未被修改。拒绝 `runtime_root == project_root`、runtime 位于 pool 内、pool 位于 runtime 内及非预期 Git 顶层。新增恶意 fake：读取 payload 中全部路径并尝试写入，必须只能影响租约树；旧实现先红，修复后绿。

## 任务 2｜真实分离审查与合并身份

删除由调用者字符串证明身份的接口。Review Decision 必须从配置的 Chief-only inbox 读取，路径不得位于任务 worktree、pool 或任务 scope；绑定 task/version/lease/commit，并一次消费。Merger 身份来自实例配置且不得出现在任务 allowedExecutors。新增反向测试：任务 Executor 伪造 `actor=chief`、`caller=merge-r4` 或直接传 dict 均不能合并；旧实现先红，修复后绿。

## 任务 3｜合并前独立重验执行证据

Runner 将 execution report 原子持久化到运行时控制目录，绑定 before/after、task/version/lease、changed paths、commit count、diff-check 和验收测试结果。Merger 从该目录读取，核对 Chief decision 后重新计算 branch commit、单提交、clean、scope 和 diff-check；报告缺失、篡改、测试失败/缺失、scope 漂移都 fail closed。不得由任务 Executor 写或替换证据。补齐红→绿测试。

## 任务 4｜回归生命周期

用真实临时 Git worktree 拓扑跑 Task A→review→merge→promotion→Task B；再覆盖恶意路径、伪造审批、证据篡改、runtime=project、旧 outbox。两任务各仅 1 次 execute/merge/promotion；失败路径均为 0 次副作用，旧 baseline 与 runtime HEAD 不变。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉 Git/worktree/review/merge/promotion 边界、用 `|| true`。测试数不得低于 134，skip=0；同一验收失败 3 次即停该项。完成后只做一个 R4.1 本地原子 commit，停在 Chief REVIEW。

## 完成条件

1. 恶意 Executor 无法获知或改写原项目/运行时，也无法用字符串伪造 Chief/merger；合并前持久证据被独立重验，篡改必红。
2. 全套测试 ≥134、0 fail、0 skip，`git diff --check` 通过；R1/R3/主仓不变，真实外部调用增量 0。每条须在交付贴实际输出和红→绿证据；`BLOCKED.md` 无阻塞也写“无”。

