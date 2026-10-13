# Chief Review · R2 Chief Task Document Ingress

- Reviewed commit：`68b58cb`
- Baseline：`b7e17bf`
- Verdict：`CHANGES_REQUESTED_R2`

## 已通过

- R1 evidence closeout commit `b7e17bf` 已独立完成；R1 Runner 持续 idle。
- R2 在独立 clean worktree；Executor 报告 120 tests / 0 fail / 0 skip，真实 Cursor 增量 0，R2 未启用。
- 文件边界、TaskRegistry、DecisionPolicy、LeaseDispatcher 的正向 fake 流程和五类反向输入已有覆盖。

## 阻断项

1. `_conflict_existing` 会把同 id 不同内容的既有任务转为 BLOCKED；这可由一个冲突文件改写 RUNNING/REVIEW 状态。冲突入口只能写拒绝回执，不能改变已登记任务。
2. 幂等只比较 `source_fingerprint(task)`，不比较完整 envelope hash。只修改 `facts` 会被视为相同任务，同时回执被写成新 `sourceHash`，来源与真实决策不再一致。
3. `CursorDaemon` 虽增加 reporter hook，但实际 `scripts/run_cursor_runner.py` 没有配置或实例化 Reporter；生产 Runner 不会把 REVIEW/BLOCKED 更新到 Chief inbox。
4. `baseline_known` 只检查 workspace 有 Git HEAD，没有确认它等于 Dispatcher 注册 baseline；会把注定被 Runner 拒绝的任务提前判 READY。
5. ingress config 未严格验证必填字段、类型、正数上限与 outbox/inbox 路径关系，真实服务错误会以 KeyError/异常退出而非结构化 fail-closed。

## Chief 决定

- 不启用、不合并、不 push R2。
- 由同一 Cursor Executor 在原 R2 分支做一个 R2.1 原子补正 commit；真实 Cursor 调用必须为 0。
- 补正后仍停在 Chief REVIEW，不连接 Julius、Director、Eval。
