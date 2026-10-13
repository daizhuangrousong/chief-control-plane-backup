# Owner Approval · Cursor Runner R1 Bootstrap

- Approval ref：`OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
- 日期：2026-08-20（Asia/Shanghai）
- 来源：Owner 在 Chief 会话中先明确“可以解冻”，并在 Chief 提出一次性 R1 Bootstrap 后回复“好的”。

## 批准范围

仅批准 Control Plane 的一次性 R1 启动桥接：

1. 由 Cursor Executor 接入 Cursor 官方 CLI；
2. 完成一次低风险、文档型真实 Cursor pilot；
3. 验证一次飞书真实出站；
4. 验收通过后建立仅面向 Control Plane、显式配置、单任务的用户级常驻 Runner；
5. 在专用 worktree 做代码、测试和一个本地原子 commit，交 Chief REVIEW。

## 未批准范围

- 不批准 Julius、Director、Eval/KESU 的执行或接线；
- 不批准知识库写入、业务数据库/schema 修改、产品方向或验收标准变更；
- 不批准生产变更、push、merge、deploy、发布或新增第三方 Agent/调度系统；
- 不批准读取、展示、迁移或提交任何 secret。

本授权不替代后续高风险任务的独立 Owner approval。
