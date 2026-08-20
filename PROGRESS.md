# PROGRESS · R3 回滚到 R1 safe-idle

- 目标：停止不可持续的 R3 激活，恢复已验证 R1 idle。真实 Cursor/飞书增量必须为 0。停在 Chief REVIEW。
- 工作树：`/Users/pojian/repos/director-control-plane-r2-ingress` 分支 `chief-task-ingress-r2`
- 回滚前：HEAD=`39b2e20`；R3 baseline=`f56f896`（未更新）；READY=0；Cursor 累计=2
- 回滚前 labels：ingress pid=`22766` runs=1 forks=468；R3 runner pid=`22924` runs=1 forks=3
- 备份 plist hash 核验通过：`1f5270208c68c41b84dbae11f24bbf955067e7ae4fd432a9cbca1b05485a8c1a`
- 回滚后：仅 R1 `com.pojian.chief-cursor-runner` pid=`26003` runs=1 idle；`com.pojian.chief-task-ingress` 不存在
- 恢复后 live plist 与备份字节一致；无 `--inbox-dir`、无 R2 worktree 路径
- R3 证据保留：PILOT=REVIEW v5，REVERSE=BLOCKED v2；outbox/inbox mtime 已停止变化
- 本任务 Cursor `--print`=0，飞书=0；未改代码、未改 baseline、未跑新任务
- 等待：Chief REVIEW。不得重新启用 R3。
