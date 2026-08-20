# PROGRESS · R4.1 封死隔离与自批绕过

- 目标：修 Chief REJECT 的 4 个阻断点。不扩架构、不启用、不 merge/push。停在 Chief REVIEW。
- 工作树：`/Users/pojian/repos/director-control-plane-r4-lifecycle` 分支 `chief-task-lifecycle-r4` 基于 `6d29059`
- 验收：`PYTHONPATH=src python3 -m unittest discover -s tests` → 137 / 0 fail / 0 skip；`git diff --check` 通过
- R1：`gui/501/com.pojian.chief-cursor-runner` pid=`26003` running；ingress 不存在
- 完成项：租约树唯一可写、Chief inbox 身份、持久证据独立重验、真实 git worktree A/B 回归
- 状态：停在 Chief REVIEW。未启用、未 merge、未 push、未调用真实 Cursor
