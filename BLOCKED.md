# BLOCKED · R3 Chief 文档自动派单激活

## Feishu outbound

BLOCKED: `FEISHU_APP_ID` and `FEISHU_APP_SECRET` are unset. R3 did not send cards or request credentials.

## Real Cursor `--print`

未激活前增量为 0。累计仍为 1 次。激活时最多再调用 1 次；失败不重试。

## LaunchAgent

激活前 R1 `com.pojian.chief-cursor-runner` 保持 idle，作为回滚基线。R3 代码提交后才允许启用 `com.pojian.chief-task-ingress` 并把 Runner 切到已提交 R3 worktree。
