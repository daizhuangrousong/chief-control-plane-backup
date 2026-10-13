你是执行者，这是同一 R7 的 memory credential-store 窄修，也是唯一任务来源；先读 `PROGRESS.md/BLOCKED.md`、最新 Chief Review 和 `/Users/pojian/.cursor/projects/Users-pojian-repos-director-control-plane-r7-production-wiring/canvases/cursor-cli-isolation-options.canvas.tsx`，接着现有 R7 做。目标是让 Cursor CLI 在 clone HOME 中使用进程内凭证库，绕过 Darwin login keychain，同时保持 R6 写边界。断线先读进度续跑；拿不准写 `BLOCKED.md` 后停。让步顺序：token 不落盘 > 宿主不可写 > 真实 REVIEW > 速度。

## 我替领导拍的板

- Chief 已实测本机 CLI 源码：`AGENT_CLI_CREDENTIAL_STORE=file|memory|default`；批准固定 `memory`，不使用 file。
- 这是 R7 窄修，不建 R7.1；最终 amend `0bf2e89`，相对 main 仍 1 commit。
- 变量由 `sandbox_environment` 固定写入，绝不从宿主继承；配置、plist、任务和 Owner 均不可选择。
- 全新短路径 `/Users/pojian/chief-state/r7k6/`；真实 `--print` 最多 1 次。

## 界限

只允许改 `src/control_plane/services/cursor_launch.py`、`executor_sandbox.py`，必要时 `cursor_keychain.py`；对应 `tests/test_cursor_cli_wrapper.py`、`test_executor_sandbox.py`、`test_execution_lifecycle.py`；以及 `docs/CURSOR_RUNNER.md`、`SECURITY.md`、`OPERATIONS.md`。`PROGRESS.md/BLOCKED.md` 保持未提交记录。允许写 r7k6 与一次性 canary 目标。其他仓库/路径只读。禁止改 CLI 二进制、Keychain 值、宿主 HOME、LaunchAgent、main、四项目、生产 DB、remote；禁止 merge/push/deploy/promote。

## 现状与任务 0

实测基线：R7 HEAD=`0bf2e8981acab9b7854a3d82bbfce13169b4c962`，相对 main=1，工作树仅进度文件；全测 171/0/0。`CLI_ENV_ALLOWLIST` 当前没有该变量；CLI 源码对 `memory` 返回内存库，`default+darwin` 走 login keychain；r7k5 因 Keychain 30s 超时。先核对这些事实、LaunchAgent/四项目 HEAD 与 Keychain 项存在（不带 `-w`）；不符即停。把顺序、最大风险写 `PROGRESS.md`，≤10 行。

## 任务 1｜固定 memory 且拒绝继承

将 `AGENT_CLI_CREDENTIAL_STORE` 纳入最小 CLI 环境契约，但只接受 `memory|file`，其他值 fail closed 或丢弃；生产 `sandbox_environment` 必须无条件覆盖为 `memory`，即使宿主传 `default`、`file`、恶意值或空值。最终 CLI child 必须看到恰好 `memory`。不得把选择权放进 config/plist/task，也不得写入父进程全局环境。

红→绿测试至少证明：旧路径/缺变量会触发 fake keychain marker；memory 不触发；宿主 `file/default/恶意值` 进入 sandbox 后均为 memory；子进程可见 memory；父环境不变。

## 任务 2｜隔离与不落盘

证明 memory 模式下：宿主 HOME、runtime/state/目标 main/目标 `.git`/child/symlink 写攻击仍 errno=1；profile write allow 恰好 2（clone + `/dev/null`）；独立 clone 可 commit。扫描 clone 与父进程 import，`.sandbox-home/.cursor/auth.json` 必须不存在，任何 auth/token 文件不得进入 task ref、official report、日志或证据。Key/API token 及派生值不得落盘、哈希或输出。

## 任务 3｜真实 canary 与收口

全新 r7k6，经生产入口、Keychain 内存注入、memory store、短 clone HOME 和 R6 sandbox，真实 Cursor 只新增 `reports/R7_REAL_CURSOR_CANARY.md`。不得先跑 status；`--print` 最多 1。必须单 commit、父进程 exact import、固定 verification、official report、REVIEW；宿主/目标 main 不变，merge/promote=0。若仍出现 keychain/认证/超时/契约错误，立即停，不重试。

成功后运行：

`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`

`git diff --check`

要求全测≥175、skip/failure/error 0；只 amend 白名单代码/测试/docs，进度文件不提交；相对 main 恰好 1 commit。

## 规矩

不许 file store、auth.json、skip/todo、删/放宽断言、mock 真实 sandbox/canary、`|| true`、第二次 `--print`。不能用环境继承偶然变绿；故意注入宿主 file/default 后仍须 memory。

## 完成条件

1. 唯一真实 canary 不访问 login keychain，生成单 commit、official report 并进入 REVIEW。
2. 全测≥175 且 0/0/0，R7 仍 1 commit，write allow=2、auth.json=0、宿主/线上/四项目零变化、凭证零泄露。

每条贴脱敏实际输出，只说完成不算。`BLOCKED.md` 空也写“无”。一次即停。
