# PROGRESS · R4.4 Control Plane 跨仓执行

- 目标：独立 runtime 仓管理独立 target 仓；stateRoot 在两仓与 pool 外；verification 每任务恰好 1 次。不启用/merge/push。停在 Chief REVIEW。
- 工作树：`chief-task-lifecycle-r4`；R1 保持 idle。
- 测试：149 ran, 0 fail, 0 skip。
- `..` 在 Runner/contract 执行前拒绝（task_registry 不在白名单）；逃逸调用次数 0。
- 状态：任务 1–4 完成，停在 Chief REVIEW。
