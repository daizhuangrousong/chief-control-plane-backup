# R7 真实 Key Canary · Chief Review · 2026-08-21

## 结论

`BLOCKED / CURSOR_CLI_KEYCHAIN_ERROR / OWNER_DECISION_REQUIRED`

完整 User API Key 的唯一一次真实 canary 未进入 REVIEW。Cursor CLI 没有返回 invalid key，而是在 API-key 模式中仍尝试访问 macOS login keychain，并以 `security` exit 154 退出。

## 事实

- CLI：`2026.08.11-e8db854`；本机无其他已安装版本
- `--print`：1；任务：FAILED
- clone 新 commit：0；official report：无；REVIEW：否
- HOME：短独立 clone；sandbox write allow：2
- R7 HEAD：`0bf2e89`；相对 main：1 commit
- 错误 status 前置改动已全部恢复；工作树仅 `PROGRESS.md/BLOCKED.md`
- main、目标 main、LaunchAgent、Julius、Director、Eval、R4/R6：未改
- merge / promote / push / deploy：0
- 凭证：无落盘、无日志、无证据泄露

## 判断

Cursor 官方文档规定 `CURSOR_API_KEY` 用于无头自动化；官方社区答复也说明 API-key 路径应绕过 macOS Keychain。当前固定 CLI 的行为与该契约不一致。继续修改 Key、放宽宿主 Keychain 写权限或执行 `agent logout/login` 都不是可接受修复。

## 建议决策

批准由 Executor 将 Cursor Agent CLI 升级到最新稳定版，记录旧/新版本与二进制哈希，更新 R7 的显式 `cliPath`，复跑认证、沙盒、完整测试；全部通过后最多再做一次真实 canary。若不批准升级，R7 保持 BLOCKED，生产自动执行不启用。
