# Chief Review · Cursor Runner R1 Bootstrap

- Review date：2026-08-20（Asia/Shanghai）
- Reviewed commit：`549cce7ed04f6daff6a82f2d6782a1e4d338cb91`
- Baseline：`fe5062fa75691ba366d209aac1f927f0e29ad643`
- Owner approval：`OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
- Verdict：`CHANGES_REQUESTED_R1`（实现阶段部分通过；启动验收未通过）

## 已确认

- 专用 worktree/分支与一个原子本地 commit 存在，主工作树原有改动未被纳入。
- Executor 报告任务 0 为 91 tests、最终为 103 tests，均 0 fail / 0 skip。
- 三个反向门禁记录了越界 workspace、baseline 漂移、缺 Owner approval 的拒绝结果。
- 官方 CLI 已安装；在未认证状态下真实 `--print` 调用保持 0，LaunchAgent 未启用，符合 fail-closed。

## 阻断项

1. **R1 核心完成条件未达成**：真实 pilot=0、飞书测试卡=0、LaunchAgent 未启用；因此当前仍不能由 Chief 自动派单给 Cursor。
2. **环境变量边界过宽**：`cursor_cli_wrapper.py` 将完整宿主环境 `env=dict(environment)` 传给 CLI，可能把与任务无关的凭据暴露给 Executor。必须改为经过测试的最小 allowlist。
3. **常驻命令参数合同未被证明可启动**：`run_cursor_runner.py` 使用 `--executor-command nargs="+"`，而模板在该参数内部嵌入 `--runner-config`；没有覆盖“按 plist 原样解析并成功启动”的测试。必须消除歧义并用模板等价 argv 验证。
4. **重启没有上限**：plist 使用无条件 `KeepAlive=true`；daemon 对 rejected 状态继续循环。遇到永久拒绝或启动错误时会无限重试，不符合受限重启与异常升级原则。

## Chief 决定

- 不合并、不 push、不启用 LaunchAgent。
- 原 R1 Owner approval 继续覆盖同范围内补正，不新增方向或验收变更。
- 由同一 Cursor Executor 执行 `CURSOR_RUNNER_R1_1_FIX_EXECUTOR_BRIEF_2026-08-20.md`。
- 补正后仍必须完成一次真实 pilot 和一次飞书出站，才能重新提交 Chief REVIEW。

## 外部前置

- 当前 `agent status` 未证明已认证；真实 pilot 前需要 Owner 在本机完成 Cursor CLI 登录，或由既有安全凭据机制向 Runner 提供 `CURSOR_API_KEY`，不得通过聊天传递。
- 当前执行环境未取得 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`；飞书本身尚不可用于报告这个启动阻塞，因此本次只能在 Chief 会话说明。
