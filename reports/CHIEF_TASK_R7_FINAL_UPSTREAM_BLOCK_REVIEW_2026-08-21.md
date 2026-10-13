# R7 最终验收 · 上游阻断 · 2026-08-21

## 结论

`BLOCKED_UPSTREAM / DO_NOT_MERGE / DO_NOT_ACTIVATE / R7_STOPPED`

R7 的 Control Plane 代码与隔离测试通过，但真实 Cursor Agent CLI 无法在当前安全模型下运行。最新版在显式 API-key、clone HOME 环境中仍访问 macOS login keychain，并在 30 秒后超时。生产自动执行不得启用。

## 最终证据

- 官方 update：exit 0，`Already up to date`
- CLI：`2026.08.11-e8db854`
- SHA-256：`eed61c5224668c9236334c4c68936a16aecc37374b592f59e31eb50433817831`
- focused tests：56/0/0
- full tests：171/0/0
- `git diff --check`：通过；src/tests/docs 无 diff
- 真实 `--print`：1；结果：Keychain operation timeout 30000ms
- clone 新 commit：0；official report：无；REVIEW：否
- R7 HEAD：`0bf2e89`；相对 main：1 commit
- main、目标 main、LaunchAgent、Julius、Director、Eval、R4/R6：未改
- merge / promote / push / deploy：0

## Chief 决策

1. 不批准 R7 commit 合并或生产激活。
2. 不再要求 Owner 更换、重存或披露 API key。
3. 不执行 `agent logout/login`、Keychain 解锁、宿主 HOME 写权限放宽。
4. 不为绕过此问题引入容器、专用系统用户、远程 CI 或新的执行系统。
5. live R1 Runner 保持 `SAFE_IDLE`；现有生产服务与四项目不变。

## 恢复条件

仅在以下任一条件成立后重开 R7：

- Cursor 发布新稳定 CLI，明确修复 API-key 无头模式的 macOS Keychain 依赖，并在相同隔离 canary 中验证；或
- Owner 明确批准新的执行架构与新的安全验收标准。

在此之前不创建 R7.1、R8 或更多认证轮次。
