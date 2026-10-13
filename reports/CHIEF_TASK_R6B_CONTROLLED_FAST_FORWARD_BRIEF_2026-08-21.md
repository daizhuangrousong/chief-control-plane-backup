# R6B · Control Plane 受控快进 · Independent Merge Executor 任务书

你是独立合并执行器，本文件是唯一任务来源；不是 R6 的开发 Executor。目标只有一个：把 Chief 已批准的 R6 commit 安全快进到 Control Plane `main`，逐字节保住现有脏文件和未跟踪记录，回归后停止。不要启动真实 Cursor、不要接生产任务。拿不准写新证据并停，不 reset、不清理现场。

## 已冻结事实

- 目标仓：`/Users/pojian/repos/director-control-plane`
- `main` 当前 HEAD：`fe5062fa75691ba366d209aac1f927f0e29ad643`
- R4 基线：`b9c344a1ad400fd502bffcb7ef05c8ee00590680`
- 唯一批准 commit：`13127b9c26e8a0252d78282f32e165a28aa848b2`
- 批准分支：`chief-task-permission-r6`
- Chief 实测：160 tests / 0 fail / 0 skip；`fe5062f` 是批准 commit 的祖先。
- `main` 当前有 2 个 tracked 脏文件和多份未跟踪 Owner/Chief 记录；都是真实资产，禁止舍弃。

## 白名单地界

只允许：只读预检；在 `/Users/pojian/chief-state/control-plane-r6b/` 写快照/证据；对目标 `main` 执行一次 `git merge --ff-only 13127b9...`；运行测试。禁止改 R6 commit/分支/worktree，禁止 `reset/clean/stash/checkout --/rebase/cherry-pick`，禁止删除或提交既有脏文件，禁止 remote/push/deploy/LaunchAgent/真实 Cursor/网络/API，禁止写 Julius/Director/Eval/知识库/数据库。不得把 `PROGRESS.md`、`BLOCKED.md` 的 R6 未提交记录带入批准 commit。

## 任务 0｜不可丢失快照

确认目标路径、分支、HEAD 与祖先关系完全匹配；确认批准 commit 相对 R4 只有 1 commit、范围仍为 R6 十个允许路径、`git diff --check` 通过。对 `main` 当前全部 tracked 修改与未跟踪文件建立清单：相对路径、类型、字节数、SHA-256；另记 `git status --porcelain=v1 -z` 的 SHA-256。快照写到 stateRoot，不改仓库。任一路径与 `fe5062f..13127b9` 变更集重叠即停。

## 任务 1｜单次快进

再次核对 HEAD=`fe5062f...` 后，只执行一次 fast-forward-only 到 `13127b9...`。不得创建额外 commit。失败时保留现场，记录错误并停；不得用更强命令重试。成功后必须证明 `main` HEAD 精确等于批准 commit，提交图未改写，remote 未变化、push=0。

## 任务 2｜资产守恒与回归

重算任务 0 的每个既有 dirty/untracked 文件 SHA-256、类型和大小，必须逐项相同；状态允许因基线前进而显示方式变化，但资产字节不得变化。确认 R6 worktree 仍为 `13127b9`，其 `PROGRESS.md`/`BLOCKED.md` 未提交记录仍在；R4 仍为 `b9c344a` clean。用既有固定 Python 环境执行 `PYTHONPATH=src ... -m unittest discover -s tests -v`，要求恰好或不少于 160、0 fail、0 skip，并单跑真实 `test_executor_sandbox`。

## 任务 3｜证据后停止

在 stateRoot 写一份 Markdown/JSON 回执：前后 HEAD、祖先/commit count、变更范围、资产哈希守恒、测试数、R4/R6 状态、remote/push/deploy/真实 Cursor/生产接入均为 0、失败时的可恢复现场。不要修改仓内任务文档，不做 baseline DB 写入，不启动自动化。

## 防作弊验收

- 只说“文件还在”不算，必须前后 SHA-256 全等。
- 只跑 mock 或绕过真实 `sandbox-exec` 不算。
- 测试 skip/todo、放宽断言、只跑新增测试、清理脏树后再合并均失败。
- `main` 不是 fast-forward、HEAD/批准 SHA 不一致、任一现有资产变化即停；不自行回滚。

## 完成条件

`main=13127b9...`；全部既有脏/未跟踪资产逐字节保留；R4/R6 现场保留；全测≥160/0/0；没有 push、部署、生产接入或真实 Cursor。完成后只交证据，停在 Chief Review；生产激活必须另领任务。
