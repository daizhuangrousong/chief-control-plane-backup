# R7 Memory Credential Store · Chief Decision · 2026-08-21

## 决策

`APPROVED_NARROW_FIX / AGENT_CLI_CREDENTIAL_STORE=memory`

撤销此前 `BLOCKED_UPSTREAM` 的终局判断。已安装 Cursor CLI 自带无需 login keychain 的内存凭证库；当前阻断来自 Control Plane 环境过滤，而不是必须等待新版本。

## 独立核验

- CLI `credential-store.ts`：仅 `file` 返回 file、`memory` 返回 memory，其余 default。
- CLI 启动逻辑：Darwin、default 凭证库进入 login keychain 路径。
- CLI file store：Darwin 下落于 `$HOME/.cursor/auth.json`。
- Control Plane `CLI_ENV_ALLOWLIST`：包含 `CURSOR_API_KEY/CURSOR_API_ENDPOINT`，不含 `AGENT_CLI_CREDENTIAL_STORE`。
- R7 sandbox：HOME 已固定在独立 clone，write allow 仍为 clone + `/dev/null`。

## 冻结选择

- 仅用 `memory`；不启用 file。
- 变量由生产 sandbox 强制注入，不从宿主、config、plist 或 task 继承。
- 不修改 Cursor CLI、Keychain、宿主 HOME 或 R6 profile。
- `.sandbox-home/.cursor/auth.json` 必须不存在；token 只在 CLI 进程生命周期内。
- 通过完整测试和唯一一次真实 canary 后仍停在 Chief Review，不自动合并或激活。
