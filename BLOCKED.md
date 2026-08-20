# BLOCKED · R3 Chief 文档自动派单激活

## Feishu outbound

BLOCKED: `FEISHU_APP_ID` and `FEISHU_APP_SECRET` are unset. R3 did not send cards or request credentials.

## Real Cursor `--print`

本任务增量 1。累计 2。失败不重试。不得再调用。

## LaunchAgent

`com.pojian.chief-task-ingress` 与 R3 `com.pojian.chief-cursor-runner` 均 running/idle。R1 plist 备份仍在 `var/rollback/com.pojian.chief-cursor-runner.plist.r1`。等待 Chief REVIEW，不得扩到其他项目。
