# R7 凭证替换续跑 · Chief Review · 2026-08-21

## 结论

`BLOCKED / AUTHENTICATION_FALSE / ZERO_PRINT / DO_NOT_MERGE_OR_ACTIVATE`

本轮安全止损成立，但生产目标未完成。真实 Cursor 认证预检返回 `isAuthenticated=false`；执行器没有启动 `--print`，也没有运行 canary。

## 核验事实

- R7 HEAD：`0bf2e8981acab9b7854a3d82bbfce13169b4c962`
- 相对 main：1 commit；本轮没有 amend
- 未提交现场：认证逻辑、4 个对应测试、3 份文档及 `PROGRESS.md/BLOCKED.md`
- Executor 自报 wrapper tests：28/0/0
- 真实探针：exit=0、JSON 有效、`isAuthenticated=false`、`printCalls=0`
- 短 clone HOME：是；sandbox write allow：2
- official report / REVIEW / canary：均无
- merge / deploy / push / promotion：0
- main、live LaunchAgent、Julius、Director、Eval：未改

## 代码审查

本轮删除了“环境中只要有非空 `CURSOR_API_KEY` 就直接视为已认证”的假绿路径，并改成严格解析 `status --format json`。新增测试覆盖 status=false、非零退出、坏 JSON 时 `print=0`，以及 true 时 status→print 的顺序。方向正确，但因真实认证未通过且改动未提交，不能进入合并审查。

## 根因边界

Cursor 官方认证文档说明：User API Key 可通过 `CURSOR_API_KEY` 用于自动化，`agent status` 用来检查认证。因此当前结果表示 Keychain 中的值仍未被 Cursor CLI 识别为有效凭证。Chief 不读取凭证，无法在不泄密的前提下继续区分错误 key 类型、复制字符问题或 key 已失效。

## 下一动作

Owner 确认凭证来自 **Cursor Dashboard → API Keys → User API Key**，不是 OpenAI key、Team Admin API key 或其他 Cursor token；必要时重新生成并覆盖同一 Keychain 项。覆盖后仍只准先做零 `--print` status 预检。
