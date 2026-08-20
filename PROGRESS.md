# PROGRESS · CURSOR-RUNNER R0

- 目标：冻结可机器判定的审批分类，并落地只接受注入命令的 R0 Cursor 适配器；证明 Chief 可安全派单。
- 任务 0：75 tests / 0 fail / 0 skip；CLI 未安装；与本任务无关的脏文件不纳入 commit。
- 任务 1：`approvalClass` + `ownerApprovalRef` 已冻结；缺引用与伪字段不能进入 READY。
- 任务 2：`CursorRunner` 只接受注入 command；成功只到 REVIEW；越界/缺审批/漂移/超时/失败/重复占用已覆盖。
- 最大风险：误启动真实 Cursor。本轮真实 Cursor 调用次数为 0。
- 验收：反向越界与缺 Owner 审批被拒后全绿；准备原子本地 commit。
