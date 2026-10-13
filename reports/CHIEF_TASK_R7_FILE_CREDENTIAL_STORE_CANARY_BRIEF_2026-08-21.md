你是执行者，这份文档是 R7 隔离 file 凭证续跑的唯一任务来源；中途没人可问，拿不准写 `BLOCKED.md`，跳过不受影响项。断线先读 `PROGRESS.md` 接着做，每项完成即更新。这活要绕过已证实失效的 memory 路径，同时保证凭证只在隔离 clone 内短暂存在并必定清除。冲突时：凭证不残留 > R6 隔离不退 > 可判 canary > 速度。只有“只允许/不许”是硬边界。

## 我替领导拍的板

- Owner 已批准 `AGENT_CLI_CREDENTIAL_STORE=file`；它是当前固定 CLI 的兼容方案，不是放宽宿主 HOME。
- `auth.json` 仅可在 Cursor 子进程存活期间位于当前 clone 的 `.sandbox-home/.cursor/auth.json`；成功、非零退出、异常和超时都由可信父进程清理。
- 真实 `--print` 最多一次；成功也只到 REVIEW，不合并、不激活。

## 界限

只允许改 `src/control_plane/services/cursor_launch.py`、`executor_sandbox.py`；对应 `tests/test_cursor_cli_wrapper.py`、`test_executor_sandbox.py`、`test_execution_lifecycle.py`；`docs/CURSOR_RUNNER.md`、`SECURITY.md`、`OPERATIONS.md`；`PROGRESS.md/BLOCKED.md`。允许写全新短路径 `/Users/pojian/chief-state/r7k7/` 和一次性 canary clone。其他路径只读。判卷测试、CLI 二进制、Keychain 值、宿主 HOME、sandbox 写白名单、main、LaunchAgent、Julius/Director/Eval、生产 DB/remote 不许改；禁止 merge/push/deploy/promote。不得输出、复制、哈希或记录 Key/token/auth.json 内容。

## 现状与任务 0

HEAD=`0bf2e8981acab9b7854a3d82bbfce13169b4c962`，相对 main 恰好 1 commit；当前 3 个代码、3 个测试、3 个 docs 文件是未提交 memory 修复，另有 `PROGRESS.md/BLOCKED.md`。focused 自报 59/0/0。`r7auth` 已证明 exchange=2xx、tokenSchemaValid=true、print=0。先逐项核对并记录初始 diff SHA、测试数、顺序和最大泄露风险（≤10行）；任一不符停并写 BLOCKED。

## 任务 1｜固定 file 并保证清理

将生产 sandbox 无条件固定为精确小写 `file`，宿主传入 memory/default/恶意值均不得覆盖。保持 HOME/TMP/XDG 在 clone、write allow 恰好 2。可信父进程包住 sandboxed executor：只针对解析并验证位于当前 clone HOME 下的 `.cursor/auth.json` 做清理；成功、非零退出、异常、超时四条路径都必须最终不存在。路径逃逸、父目录/文件为异常类型时 fail closed，不递归删除、不跟随链接、不扩大清理范围。

增加 fake CLI 红→绿：旧 memory 行为导致 file-store 断言红；修复后证明子进程看到 file、可创建 auth.json，父进程返回前已清除。另覆盖非零退出和超时清理、宿主 store 被覆盖、宿主 HOME 写仍 EPERM、`.sandbox-home` 不进入 commit/import、日志/stdout/stderr 无 canary secret。不得 mock 被测清理函数。

验收：
`PYTHONPATH=src .venv/bin/python -m unittest tests.test_cursor_cli_wrapper tests.test_executor_sandbox tests.test_execution_lifecycle -v`
要求 failure/error/skip=0、测试数≥59；贴旧行为红与修复后绿。

## 任务 2｜全量回归

更新三份文档，明确短暂落盘位置、同进程可见风险、finally 清理与失败即停。运行：
`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`
`git diff --check`
要求全测数≥171，failure/error/skip=0；不得 skip/todo、放宽断言、删测试、改阈值、mock 被测对象或 `|| true`。

## 任务 3｜唯一真实 canary

仅前两项全绿后，在 r7k7 经生产入口、Keychain 内存注入、file store、短 clone HOME、R6 sandbox 运行一次真实 Cursor。任务只新增 `reports/R7_REAL_CURSOR_CANARY.md`，要求 `--print=1`、独立 clone 单 commit、父进程 exact import、固定 verification、official report、状态 REVIEW；merge/promote=0，目标 main/宿主/四项目不变。无论结果如何，检查所有 clone、state、日志、证据中 `auth.json=0` 且无 key/token。若认证、清理、契约或超时失败，立即停，不重试、不 amend。

canary 全部成立后才 amend 原 R7 commit，最终相对 main 恰好 1 commit；`PROGRESS.md/BLOCKED.md` 不进 commit。

## 规矩

同一验收失败 3 次即停；结果比开工差则恢复本轮改动并如实报告。不新增依赖、权限、流程或执行系统。

## 完成条件

1. 唯一真实 canary 到 REVIEW，`--print=1`、单 commit/import/official report 全成立；或按止损带证据停。
2. `auth.json=0`、secret/token 泄露=0、write allow=2、宿主/main/LaunchAgent/四项目变化=0。

每条贴脱敏实际输出；只说完成不算。`BLOCKED.md` 空也写“无”。
