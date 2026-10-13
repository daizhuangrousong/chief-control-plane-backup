你是执行者，这是同一 R7 的 Cursor CLI 升级与最终 canary，也是唯一任务来源；先读 `PROGRESS.md/BLOCKED.md` 和最新 R7 Chief Review，接着做。Owner 已批准把 Cursor Agent CLI 升级到最新稳定版，以修复 API-key 模式错误访问 login keychain；不等于批准生产启用。断线先读进度续跑，拿不准写 `BLOCKED.md` 并停。让步顺序：可回滚 > 密钥不泄露 > 隔离不退 > 真实结果 > 速度。

## 我替领导拍的板

- 只用当前官方二进制的 `agent update`，不运行安装脚本、不引入其他工具或渠道。
- 升级前记录旧版本、绝对路径、两个软链接目标和 SHA-256；不删除旧二进制。
- 更新成功后显式使用新版本绝对路径，不依赖 PATH 自动发现。
- 升级/测试失败时恢复两个软链接到旧版本并停止，`--print=0`；新版本 canary 最多 1 次。
- 成功也不激活 LaunchAgent、不合并、不部署；R7 HEAD 保持 `0bf2e89`。

## 界限

允许官方 updater 修改 `/Users/pojian/.local/share/cursor-agent/versions/` 及 `/Users/pojian/.local/bin/agent`、`cursor-agent` 两个软链接；允许写全新 `/Users/pojian/chief-state/r7k5/`、一次性 canary 目标和未提交 `PROGRESS.md/BLOCKED.md`。Control Plane 代码/docs/tests 全部只读；其他仓库、Keychain 值、live LaunchAgent、生产 DB、remote 全部禁止修改。禁止 logout/login、unlock-keychain、换 key、把 key 放 argv/文件/日志/哈希/输出。

## 现状与任务 0

实测：旧版本=`2026.08.11-e8db854`，路径=`/Users/pojian/.local/share/cursor-agent/versions/2026.08.11-e8db854/cursor-agent`，SHA-256=`eed61c5224668c9236334c4c68936a16aecc37374b592f59e31eb50433817831`；两个软链接均指向它。本机只有这一版。R7 HEAD=`0bf2e89`、相对 main=1，工作树仅进度文件。先复核这些值、LaunchAgent/四项目 HEAD 及 Keychain 项存在（不带 `-w`）；不符即停。把升级、回滚、测试、canary 顺序和最大风险写进 `PROGRESS.md`，≤10 行。

## 任务 1｜可回滚升级

清除子进程中的 `CURSOR_API_KEY` 后，直接运行旧绝对路径的 `update` 一次。完成后核对：两个软链接指向同一个 `/Users/pojian/.local/share/cursor-agent/versions/<new>/cursor-agent`；目标是普通可执行文件、不是旧路径；`--version` 非旧版本；记录新 SHA-256。不得删除旧版本。

反向验证回滚信息是否充分：仅做软链接目标的干跑核对，不实际切回；若新路径/版本/hash/链接任一不符，精确恢复两个链接到已核旧路径并停止，不运行 canary。

## 任务 2｜升级后静态闸门

使用 R7 仓 `.venv` 运行：

`PYTHONPATH=src .venv/bin/python -m unittest tests.test_cursor_cli_wrapper tests.test_executor_sandbox tests.test_execution_lifecycle -v`

`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`

`git diff --check`

要求全测≥171、skip/failure/error 全 0，R7 代码/docs/tests 无 diff。任一失败，恢复旧软链接并停止，`--print=0`。

## 任务 3｜新版本唯一 canary

仅任务 1–2 通过后，用 `/Users/pojian/chief-state/r7k5/`、新 CLI 绝对路径、现有 Keychain loader、短 clone HOME 和 R6 sandbox，经 R7 生产入口执行一次原 canary：只新增 `reports/R7_REAL_CURSOR_CANARY.md`。不先跑 status；`--print` 最多 1 次。

成功必须同时满足：独立 clone 1 commit、父进程 exact import、固定 verification、official report、REVIEW；宿主/目标 main 不变，merge/promote=0。若仍报 keychain/认证/非零/超时/契约错误，停止且不重试；保留新版本与旧版本，交 Chief 决定是否回滚软链接。

## 规矩

不许安装脚本、非官方下载、skip/todo、放宽断言、mock 真实升级/canary、第二次 `--print`、`|| true`。升级过程不得继承任何凭证环境；只有 canary 的可信父进程可读取 Keychain 并内存注入。

## 完成条件

1. 新稳定 CLI 在唯一一次 canary 中生成单 commit、official report 并进入 REVIEW；或带版本/hash/零变更证据明确失败。
2. 全测≥171 且 0/0/0，R7 仍 1 commit，主仓/线上/四项目零变化，旧版可回滚、凭证零泄露。

每条贴脱敏实际输出，只说完成不算。`BLOCKED.md` 空也写“无”。一次即停。
