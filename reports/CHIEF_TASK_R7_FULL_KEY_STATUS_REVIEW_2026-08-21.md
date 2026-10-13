# R7 完整 Key status 探针 · Chief Review · 2026-08-21

## 结论

`INCONCLUSIVE_AUTH_PROBE / ZERO_PRINT / CHIEF_CRITERION_RETRACTED`

探针安全止损成立，但 `isAuthenticated=false` 不再作为 User API Key 无效的证据。Chief 撤销此前把 `agent status` 设为 API-key canary 前置闸门的判断。

## 事实

- 探针：exit=0、JSON 有效、`isAuthenticated=false`、`printCalls=0`
- HOME 位于短 clone；sandbox write allow=2
- canary、official report、REVIEW：均未发生
- R7 HEAD 仍 `0bf2e89`；相对 main 1 commit
- 5 个认证代码/测试/docs 改动仍未提交；不批准纳入 R7
- main、LaunchAgent、Julius、Director、Eval、R4/R6：未改

## 修正

Cursor 官方文档确认 API key 可通过 `CURSOR_API_KEY` 供自动化请求使用，但本机实测表明隔离 HOME 下的 `status` 不能作为该 key 的充分有效性判断。真正的服务端请求会明确接受或拒绝 key；因此恢复 HEAD 中“显式 key 直接进入请求、无 key 才查登录状态”的分支，并以一次真实 canary 作为最终认证证据。

## 下一步

精确回退 5 个未提交的 status 前置改动，不动执行记录；使用完整 User API Key、短 clone HOME 和原 R6 sandbox，最多运行一次真实 `--print`。成功则验收 REVIEW；服务端拒绝则终局 BLOCKED，不再更换 key 或窄修。
