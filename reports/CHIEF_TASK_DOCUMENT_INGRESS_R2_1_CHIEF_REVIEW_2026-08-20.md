# Chief Review · R2.1 Chief Task Ingress Fix

- Reviewed commit：`c957083`
- Verdict：`PASS_R2_1_FIX_HOLD_ACTIVATION`

## PASS

- Executor 报告 126 tests / 0 fail / 0 skip，R2 真实 Cursor/飞书调用均为 0。
- 完整 envelope identity 已冻结；facts-only drift 与同 id 冲突只写 attempted/original hash，不改变既有 state/version。
- workspace HEAD 与 Dispatcher baseline 不一致时 BLOCKED、0 calls。
- `run_cursor_runner.py --inbox-dir` 已有真实脚本入口 fake 测试，最终 REVIEW 可写 inbox。
- ingress config、目录重叠/symlink、sidecar 损坏和读取换文件窗口均 fail closed。

## 激活前保留项

- Reporter 当前只在 `CursorRunner.run_next()` 同步返回后收到结果；执行期间不会发布 CLAIMED/RUNNING，Chief 会继续看到旧 READY。
- 第三次相同拒绝触发 halted 时在 reporter 调用前 return；最终熔断状态不会进入 task inbox。
- R2 importer/reporter 尚无受限常驻配置，现有 R1 LaunchAgent 也未切换到带 `--inbox-dir` 的 R2 版本。

## Chief 决定

- R2.1 代码修复通过，但不直接启用。
- 下一阶段 R3 同时完成持续状态发布、受限常驻、可回滚切换和一次低风险完整自动派单证明。
- 不扩 Julius、Director、Eval；不处理飞书凭据；不改数据库 schema。
