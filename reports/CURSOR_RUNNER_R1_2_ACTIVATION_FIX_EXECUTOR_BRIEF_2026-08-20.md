# CURSOR-RUNNER R1.2 · 真实入口与激活收尾任务书

继续使用 `OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`。你是同一 Cursor Executor，只修 R1.1 真实入口崩溃并完成 idle 激活证据。真实 Cursor pilot 已用完唯一额度，本任务 **Cursor `--print` 调用必须为 0**。中断先读 `PROGRESS.md`、`BLOCKED.md` 和 R1.1 Chief Review。

## 我替领导拍的板

- 根因已确定：`parse_runner_argv(None)` 对 `None` 做 `list()`，脚本入口崩溃；不是架构问题。
- 保留 commit `549cce7`、`86ad00a`，新增一个最小原子 commit，不改写历史。
- 飞书仍独立 BLOCKED，本任务不处理凭据、不发送卡片。

## 界限

只允许修改 `src/control_plane/services/cursor_launch.py`、相关测试、`PROGRESS.md`、`BLOCKED.md`、R1 evidence/运维文档；如确有必要可最小修改 `scripts/run_cursor_runner.py`。只允许更新已授权的用户 LaunchAgent。禁止触碰其他仓、知识库、数据库 schema、方向、验收标准、生产、push/merge/deploy；禁止清理旧错误日志或任何用户文件。

## 现状与任务 0

确认 HEAD=`86ad00a`、worktree clean、测试基线 108/0/0、pilot=1、READY 队列为空、LaunchAgent 当前未运行。把旧崩溃日志时间和根因写入 `PROGRESS.md`，不要删日志。

## 任务 1—2

1. 修复 `argv=None` 时按 argparse 正常读取进程参数，显式 argv 测试能力保持不变。先加失败测试：必须通过真实脚本入口或等价 `main(None)` 重现旧 `TypeError`；再修到绿。测试还要证明完整 plist 等价命令以 `--max-cycles 1` 在空队列退出 0、写出 idle 日志、Executor marker/Cursor 调用均为 0。
2. 全套测试通过并提交后，确认数据库无 READY task，再安全 bootstrap 用户 LaunchAgent。用 `launchctl print` 证明 label 已加载；观察至少两个 idle 周期，日志只有 idle、没有 rejected/halted/traceback、没有 Cursor 调用。验证服务重载一次仍恢复 idle。任何失败立即 unload，保留日志并写 `BLOCKED.md`，不得反复 bootstrap。

## 规矩

不得新增功能、skip/todo、删测试、放宽断言、mock 掉真实入口、`|| true` 或再次调用 Cursor。不得删除/截断证据。相同激活失败最多 2 次，之后停止。只做一个本地 commit，不合并、不 push。

## 完成条件

1. 全套测试≥108、0 fail、0 skip；新增红→绿真实入口测试，`git diff --check` 与 plist lint 通过。
2. Cursor `--print` 总数仍为 1、本任务增量为 0；pilot 保持 REVIEW。
3. `launchctl print` 显示 `com.pojian.chief-cursor-runner` 已加载；两个以上 idle 周期和一次重载恢复有带时间证据，日志无新 traceback，halt file 不存在。
4. 更新 `PROGRESS.md`、`BLOCKED.md`、R1 evidence，贴 commit、测试、label/pid/state、日志路径与时间、调用计数、`git status`/`git show --stat`；停在 Chief REVIEW。飞书继续如实标独立 BLOCKED。
