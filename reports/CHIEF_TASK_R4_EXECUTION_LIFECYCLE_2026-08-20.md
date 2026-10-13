# R4 · 可持续执行生命周期 · Cursor Executor 任务书

状态：`CREATED_NOT_DISPATCHED`。原因：R3 文件入口已回滚，当前 R1 Runner 只能轮询 SQLite，Chief 无权直接写队列。本文件先作为唯一任务源；在安全入口恢复前不得声称已执行。

## 我替领导拍的板

- 目标不是再做一次 pilot，而是让连续任务可持续通过：任务文档→独立 worktree→执行与测试→原子 commit→Chief REVIEW→Executor 合并/部署/回滚→baseline 晋升。
- Chief 只读事实、写 Task/Review/Decision 文档；不运行代码、测试、git、部署或直接写 SQLite。
- 常驻运行时代码必须不可被任务污染；每个任务使用独立 worktree/branch，禁止在 daemon 自身 worktree 执行。
- 知识库、数据库、方向、验收标准仍需 Owner approval；其余低风险工程执行由 Chief 决策。

## 界限

只允许修改 Control Plane 的执行生命周期、文件合同、测试、配置示例与文档；开发必须在独立 R4 worktree。禁止启用服务、调用真实 Cursor/飞书、连接 Julius/Director/Eval、修改业务数据库/schema、merge/push/deploy。R1 safe-idle 必须保持不变；R2/R3 DB、outbox/inbox、日志和证据只读。

## 现状与任务 0

实测事实：R1 Runner safe-idle；R3 已回滚。R3 失败原因包括：运行 worktree 与任务 workspace 相同、证据 commit 后 HEAD 与 Dispatcher baseline 漂移、Importer 重复处理旧 outbox、缺少 review→merge→baseline promotion 协议。先记录各 worktree/commit、R1 label、R3 baseline/HEAD、现有 schema/API 与测试基线，写入 `PROGRESS.md`。若事实不符，写 `BLOCKED.md`。

## 任务 1—4

1. **不可变运行时与任务隔离**：设计并实现 runtime root 与 task worktree pool 分离。任务 worktree 必须从已注册 baseline 创建、路径受项目 root/allowlist 约束、一个任务一个 branch；拒绝 symlink、复用脏 worktree、未知 HEAD 与并发占用。常驻服务不得从任务 worktree加载代码。
2. **执行与提交合同**：Cursor 只能在租约 worktree 内改白名单文件、运行验收并做一个本地原子 commit；报告必须含 before/after ref、changed paths、tests、diff-check、lease/task version。越界、空提交冒充完成、多个提交、基线漂移和未提交改动均 fail closed，停在 REVIEW。
3. **Review/merge/baseline 晋升**：Chief 只写结构化 Review Decision。独立 merger Executor 验证 commit、scope、测试证据、任务版本和审批后才可本地合并；baseline promoter 仅在目标分支 clean、merge commit 可验证、无活动 lease、运行健康时原子更新 Dispatcher baseline。失败保持旧 baseline并输出 rollback plan；不得由任务执行器自批自合。
4. **一次消费与状态回执**：文件入口按完整 hash 一次消费，已完成 outbox 不重复运行 Git/写 receipt；回执分离 `taskState` 与 `runnerStatus`，明确 READY/CLAIMED/RUNNING/REVIEW/BLOCKED/HALTED。崩溃重启不重复执行、合并或晋升。

用临时仓、临时 DB 和 fake executor 完成两条连续任务：Task A 执行/commit/review/merge/baseline 晋升后，Task B 必须从新 baseline 正常完成。反向覆盖：脏 worktree、越界路径、未授权审批、冲突 commit、重复 review、merge 后健康失败、旧 outbox；Executor calls/merge/promotion 均符合预期。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉 git/worktree/lease/review/merge/promotion 边界、直接 SQL、shell 拼接或真实外部调用。失败路径必须先证明旧 baseline 与 R1 runtime 不变。连续三次同一验收失败即停。完成后一个 R4 本地 commit，不启用、不合并、不 push。

## 完成条件

1. 两个连续 fake 任务跨一次 baseline 晋升成功；运行时 worktree 始终 clean/不变。
2. 所有反向场景 fail closed；失败后旧 baseline、分支、服务与证据可恢复，重复输入不产生第二次副作用。
3. 全套测试 0 fail/0 skip，数量不低于 R3 的 131；`git diff --check` 通过，无仓外/R1/R3状态修改。
4. `PROGRESS/BLOCKED` 给出 worktree/refs/leases/reviews/merge/promotion、红→绿、测试与调用计数，停在 Chief REVIEW。
