# PROGRESS · R3 Chief 文档自动派单激活

- 目标：把 R2 文件入口接到现有 Runner，证明文档→READY→Cursor→REVIEW→短回执。真实 `--print` 最多 1 次。失败立即回滚 R1。停在 Chief REVIEW。
- 工作树：`/Users/pojian/repos/director-control-plane-r2-ingress` 分支 `chief-task-ingress-r2`
- 任务 0：HEAD=`c9570830590e33da18d2de4aa590b9420ba29a7b`；126/0/0；worktree clean
- R1 label=`gui/501/com.pojian.chief-cursor-runner` pid=`9214` runs=2 state=`running` idle；READY=0
- 真实 Cursor 累计=1；CLI 已认证（Login successful）
- R1 plist sha256=`1f5270208c68c41b84dbae11f24bbf955067e7ae4fd432a9cbca1b05485a8c1a`
- 回滚副本：`var/rollback/com.pojian.chief-cursor-runner.plist.r1`（无 secret）
- 回滚命令：`launchctl bootout gui/$(id -u)/com.pojian.chief-task-ingress`；`launchctl bootout gui/$(id -u)/com.pojian.chief-cursor-runner`；恢复上述 plist 后 `launchctl bootstrap gui/$(id -u) <plist>` 并证明 idle
- 阶段：代码+测试待全绿后提交，再切服务。未启用 R3 LaunchAgent。
- 最大风险：切 Runner 后无法回滚，或真实 Cursor 超过 1 次
