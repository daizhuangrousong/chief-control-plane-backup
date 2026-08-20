# PROGRESS · R4.3 Chief 固定验收命令

- 目标：Runner 只执行任务合同里的 Chief argv；Executor 不能引入/漂移命令。不启用、不 merge/push。停在 Chief REVIEW。
- 工作树：`chief-task-lifecycle-r4`；R1 pid 26003 idle；ingress 未安装。
- 字段：`verificationCommands` 经 `acceptance_json` 持久化为 criterion→`{id,argv}` 映射。
- 测试：148 ran, 0 fail, 0 skip；`git diff --check` 通过。
- 状态：任务 1–3 完成，停在 Chief REVIEW。
