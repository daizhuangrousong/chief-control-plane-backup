你是执行者，这是同一 R7 的最后一次真实 Key canary，也是唯一任务来源；先读现有 `PROGRESS.md/BLOCKED.md` 和最新 Chief Review，接着做。上一轮把 `agent status` 当作 API-key 有效性校验是 Chief 的错误：隔离 HOME 下它不能证明 User API Key 无效。目标是恢复已提交的 R7 认证设计，让唯一一次真实 `--print` 在服务端验证完整 Key，并在成功时到 REVIEW。拿不准写 `BLOCKED.md` 后停。让步顺序：密钥不泄露 > 沙盒边界 > 真实结果 > REVIEW > 速度。

## 我替领导拍的板

- 不再运行 `status` 预检，不再更换或检查 key 内容。
- 回退上一轮未提交的“认证假绿修复”；有显式 `CURSOR_API_KEY` 时按 HEAD `0bf2e89` 直接进入真实请求，认证由 Cursor 服务端判定。无 API key 的浏览器登录路径仍用 status。
- 全新短路径 `/Users/pojian/chief-state/r7k4/`；真实 `--print` 恰好最多 1 次，失败即终局阻断。
- 不新增代码 commit；成功时 R7 HEAD 仍为 `0bf2e89`，相对 main 恰好 1 commit。

## 界限

只允许把 `src/control_plane/services/cursor_cli_wrapper.py`、`tests/test_cursor_cli_wrapper.py`、`docs/CURSOR_RUNNER.md`、`docs/SECURITY.md`、`docs/OPERATIONS.md` 精确恢复到当前 HEAD；只允许更新未提交的 `PROGRESS.md/BLOCKED.md`。允许写 `/Users/pojian/chief-state/r7k4/` 和一次性 canary 目标。其他全部只读。禁止 main、R4/R6、live LaunchAgent、Julius、Director、Eval、生产 DB、remote、merge/push/deploy/promote。Key 不得进入 argv、文件、JSON、日志、stdout/stderr、证据、哈希或进程转储。

## 现状与任务 0

基线：HEAD=`0bf2e8981acab9b7854a3d82bbfce13169b4c962`，相对 main 1 commit；5 个代码/测试/docs 文件是上一轮未提交的错误方向，`PROGRESS.md/BLOCKED.md` 是执行记录。先记录这 7 个路径并核对 LaunchAgent/四项目 HEAD、Keychain 项存在（不带 `-w`）；不符即停。仅恢复上述 5 个文件到 HEAD，随后 `git status --short` 必须只剩 `PROGRESS.md/BLOCKED.md`。不得删除旧证据。

## 任务 1｜唯一一次真实 canary

建全新一次性目标、DB/outbox/inbox/report/pool，经 R7 生产入口和 R6 sandbox，让真实 Cursor 只新增 `reports/R7_REAL_CURSOR_CANARY.md`。使用 Keychain loader 内存注入、短 clone HOME；不得先运行 status。`--print` 最多 1 次。

成功必须同时满足：服务端接受凭证；独立 clone 恰好 1 commit；父进程 exact import；固定 verification 通过；official report 存在；任务状态 REVIEW；宿主与目标 main 零变化；merge/promote=0。若 Cursor 返回 invalid/not authenticated、非零、超时或契约错误，立即写 `BLOCKED.md` 并停止，不再改代码或重试。

## 任务 2｜成功收口

仅 canary 成功后运行：

`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`

`git diff --check`

要求全测≥171、skip/failure/error 全 0；HEAD 仍 `0bf2e89`、相对 main 1 commit，工作树只剩 `PROGRESS.md/BLOCKED.md`。扫描仓库、r7k4 日志与证据，确认无 key 或派生值；只记录调用数、状态、commit、路径和守恒结果。

## 规矩

不许 skip/todo、放宽断言、mock 真实 canary、加 status 绕回、第二次 `--print`、`|| true`。sandbox write allow 仍仅 clone + `/dev/null`。失败如实交卷优于猜修。

## 完成条件

1. 唯一一次真实 `--print` 成功生成单 commit、official report 并进入 REVIEW；或明确服务端认证失败且宿主/目标零变化。
2. 成功路径下全测≥171 且 0/0/0，R7 仍 1 commit，主仓/线上/四项目零变化、凭证零落盘零泄露。

每条贴脱敏实际输出，只说完成不算。`BLOCKED.md` 空也写“无”。一次即停。
