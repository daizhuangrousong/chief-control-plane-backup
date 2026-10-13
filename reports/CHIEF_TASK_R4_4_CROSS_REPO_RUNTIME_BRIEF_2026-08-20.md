# R4.4 · Control Plane 跨仓执行 · Cursor Executor 任务书

你是执行者，本文件是唯一任务来源；拿不准写 `BLOCKED.md`，继续不受影响项。断线后先读 `PROGRESS.md` 接着做，每完成一项立即更新。此任务让 Control Plane 的不可变运行时管理另一个独立 Git 仓，R5 才能以 Eval 为真实目标。让步顺序：运行时与目标仓真实分离 > 状态可追溯 > 无重复副作用 > 速度。“只允许/禁止”是硬约束。

## 我替领导拍的板

- `runtimeRoot` 是加载 Control Plane 代码的干净 Git 根；`projectRoot` 是独立目标仓；两者不得同仓、相等或嵌套。
- `stateRoot` 保存 DB、review inbox、execution reports、receipts、occupancy；必须在两个 Git 仓和 task pool 之外。
- task pool 由目标仓创建 worktree；只与 `projectRoot` 共用 git-common-dir，不与 runtime 共仓。
- verification 每任务只执行一次。Merger 复核持久报告与 Git，不二次运行命令。

## 界限

只允许改 `src/control_plane/services/{task_worktree,cursor_runner,execution_contract,chief_review_decision,task_merger,baseline_promoter}.py`、确有必要的 `src/control_plane/{config.py,services/__init__.py}`、对应 `tests/`、生命周期示例 `config/`、`docs/EXECUTION_LIFECYCLE.md`、`docs/OPERATIONS.md`、`CHANGELOG.md`、`PROGRESS.md`、`BLOCKED.md`。其余只读。禁止权限/依赖/LaunchAgent、R1/R3/主仓/业务仓、merge/push/deploy/真实 Cursor/飞书。

## 现状与任务 0

HEAD 应为 `0d6695d`，自报 148/0/0；Chief Review：`reports/CHIEF_TASK_R4_3_CHIEF_REVIEW_2026-08-20.md`。核对 HEAD、clean、测试命令及 `TaskWorktreePool` 的 same-common-dir 限制；核对 R1 idle、R3 importer 不存在。结果写 `PROGRESS.md` ≤10 行，不符写 `BLOCKED.md`。

## 任务 1｜四个根各司其职

重构配置与路径校验：runtimeRoot 必须是当前 Control Plane 代码所在的干净、固定 HEAD Git 根；projectRoot 必须是另一个干净 Git 根；poolRoot 受 projectRoot 管辖但不得等于项目根；stateRoot 是普通独立目录，拒绝 symlink、嵌套任一 Git 根或 pool。review/report/receipt/occupancy 全进 stateRoot；不得为了状态文件修改/忽略 runtime 仓。

新增反向测试：runtime=project、同 git-common-dir、任意嵌套、stateRoot 在任一仓内、运行模块不来自 runtimeRoot，均 fail closed。

## 任务 2｜真正的跨仓 A/B 生命周期

测试必须创建两个完全独立的临时 Git 仓：control-runtime repo 与 target repo，断言 git-common-dir 不同。Runner 从 runtime repo 加载，Task A/B 的 branch/worktree/commit/merge/baseline 只发生在 target repo；每阶段断言 runtime HEAD/porcelain 恒定。Task A promotion 后 Task B 从新 target baseline 开始。

## 任务 3｜验收只跑一次且不逃逸

任务注册拒绝 argv 中任何 `..` 路径段。Runner 执行一次 Chief verification 后复核 runtime、target 和 task tree；Merger 只验证持久 evidence、decision hash、commit/scope/diff，不再执行命令。测试记录 invocation count：每任务从 execute 到 merge 总计恰好 1；路径逃逸调用次数 0。

## 任务 4｜R5 就绪证据

用第三个空 target repo 模拟 Eval，完成一条仅新增 Markdown 的 fake 任务并停在 REVIEW；不得建真实 Eval 仓。输出可直接供 R5 使用的配置示例，明确四根、refs、state 目录与清理/回滚计划。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉真实 Git/worktree/subprocess/持久化边界、`|| true`。测试数不得低于 148，skip=0；同一验收连败 3 次即停。完成后一个 R4.4 本地原子 commit，停在 Chief REVIEW。

## 完成条件

1. 独立 Control Plane repo 能连续管理不同 git-common-dir 的目标仓 A/B，runtime 始终不变；verification 总调用每任务恰好 1，逃逸为 0。
2. 全套测试 ≥148、0 fail、0 skip，`git diff --check` 通过；R1/R3/主仓不变，真实外部调用增量 0。交付贴实际输出与红→绿证据；`BLOCKED.md` 无阻塞也写“无”。

