# PROGRESS · R4 可持续执行生命周期

- 目标：任务文档→独立 worktree→执行/测试→原子 commit→Chief REVIEW→独立 merger/baseline 晋升。不停在真实 Cursor，不启用服务。停在 Chief REVIEW。
- 工作树：`/Users/pojian/repos/director-control-plane-r4-lifecycle` 分支 `chief-task-lifecycle-r4` 从 `79b4557` 拉出
- 任务 0：main=`fe5062f`；R1=`b7e17bf` `cursor-runner-r1-bootstrap`；R3=`79b4557` `chief-task-ingress-r2`；R3 baseline=`f56f896` HEAD=`79b4557`
- R1 label=`gui/501/com.pojian.chief-cursor-runner` pid=`26003` idle；ingress 不存在。R3 DB/outbox/inbox 只读未改。
- 测试基线：R3 131 / 0 fail / 0 skip。本任务用临时仓+fake executor，不调用真实 Cursor/飞书。
- 红→绿：脏 worktree / 越界 / 空提交 / 多提交 / 自批 / 未授权 / 冲突 commit / 重复 merge / 健康失败 / 旧 outbox 均 fail closed，旧 baseline 保持；Task A 晋升后 Task B 从新 baseline 完成。
- 测试：134 / 0 fail / 0 skip；`git diff --check` 通过。Executor 连续任务 2 次执行 / 2 次 merge / 2 次 promotion。
- 等待：Chief REVIEW。不得启用 LaunchAgent、merge 本分支或 push。
