# R3 回滚 · Cursor Executor 唯一任务书

你是 Control Plane Cursor Executor。Chief 已判 `CHANGES_REQUESTED_R3_ROLLBACK`。目标仅是停止不可持续的 R3 激活，恢复已验证的 R1 safe-idle。真实 Cursor/飞书调用必须为 0。

## 我替领导拍的板

- 使用既有回滚文件 `var/rollback/com.pojian.chief-cursor-runner.plist.r1`，其记录 hash 为 `1f5270208c68c41b84dbae11f24bbf955067e7ae4fd432a9cbca1b05485a8c1a`。
- 停止 `com.pojian.chief-task-ingress`；恢复 R1 `com.pojian.chief-cursor-runner`。
- 不修 R3 代码、不更新 baseline、不处理 outbox、不删除任何证据。

## 界限

只允许操作这两个用户 LaunchAgent，并在 R2 worktree 更新 `PROGRESS.md`、`BLOCKED.md`、新增回滚证据。禁止调用 Cursor、修改代码、任务 DB、知识库、其他仓、飞书、merge/push/deploy；禁止删除/截断 R3 DB、日志、outbox/inbox 或 plist 备份。

## 现状与任务 0

记录两个 label/pid/runs、R3 baseline=`f56f896`、HEAD=`39b2e20`、READY 数、Cursor 累计=2、importer forks、两份 receipt 的 hash/mtime。核对备份 plist hash完全一致；不一致立即 BLOCKED。

## 回滚任务

1. `bootout` R3 importer 和 R3 runner，各只尝试一次；确认进程退出。
2. 原子恢复备份 R1 plist，lint 后 bootstrap；不得把 R3 `--inbox-dir` 或 R2 worktree 路径留在 R1 plist。
3. 观察至少两个 R1 idle 周期并重载一次：state running、日志无新 traceback/rejected/halted、Cursor 增量 0。
4. 确认 importer label 不存在，R3 outbox/inbox mtime 不再变化，R3 DB 的 PILOT=REVIEW、REVERSE=BLOCKED 保持不变。

## 规矩

不得修复后继续启用 R3，不得反复 bootstrap，不得执行新任务。任何 bootout/restore/bootstrap 失败立即停止，不用更强命令。只做一个纯回滚证据 commit，不改代码。

## 完成条件

- 仅 R1 runner running/idle；R3 importer 不存在；Cursor/飞书增量 0。
- R3 全部证据原样保留，mtime 停止变化；备份 hash和恢复后 plist 合同一致。
- `PROGRESS/BLOCKED` 与回滚报告包含前后 labels/pids/logs、baseline/HEAD、forks、调用计数和 `git status/show --stat`，停在 Chief REVIEW。
