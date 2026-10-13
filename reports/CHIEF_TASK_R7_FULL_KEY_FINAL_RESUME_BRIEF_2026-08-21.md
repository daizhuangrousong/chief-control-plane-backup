你是执行者，这是同一 R7 的完整 Key 最终续跑，也是唯一任务来源；先读 `PROGRESS.md`、`BLOCKED.md` 和最新 R7 Chief Review，接着现有未提交现场做，不重做已完成修复。目标是先证明完整 Cursor User API Key 有效，再用一次真实 canary 到 REVIEW。拿不准写 `BLOCKED.md` 并停在安全状态。让步顺序：密钥不泄露 > 零误调用 > 沙盒边界 > REVIEW > 速度。“只允许/不许”违反即失败。

## 我替领导拍的板

- Owner 已确认新建的是 Cursor Dashboard → API Keys 的 User API Key，并重新保存了创建时显示的完整值。
- Chief 已在宿主仅用不带 `-w` 的查询确认 service=`com.pojian.chief-cursor-api`、account=`pojian` 存在，未读取值。
- 保留当前认证假绿修复，不再改认证策略；最终仍 amend 原 R7，不能建 R7.1 或增加第二个 commit。
- 使用全新短路径 `/Users/pojian/chief-state/r7k3/`；真实 `--print` 最多 1 次。

## 界限

沿用上一份 R7 任务白名单：只允许当前已改的 `cursor_cli_wrapper.py`、对应测试、3 份认证文档及未提交 `PROGRESS.md/BLOCKED.md`；允许写 `/Users/pojian/chief-state/r7k3/` 和一次性 canary 目标。其他仓库/路径只读。禁止 main、R4/R6、live LaunchAgent、Julius、Director、Eval、生产 DB、remote、merge/push/deploy/promote；禁止打印、保存、哈希或比较 key；禁止 `env`/`printenv`/进程转储。

## 现状与任务 0

基线：R7 HEAD=`0bf2e8981acab9b7854a3d82bbfce13169b4c962`，相对 main 1 commit；未提交现场为认证假绿修复、4 个测试、3 份文档及进度文件。上一轮 wrapper tests=28/0/0；旧探针 `isAuthenticated=false`、`printCalls=0` 已封存。核对 HEAD、工作树、LaunchAgent/四项目 HEAD 及 Keychain 项存在（仍不带 `-w`）；不符即停。将本轮顺序和最大风险写入 `PROGRESS.md`，不超过 10 行。

## 任务 1｜完整 Key 零调用预检

用全新短 clone HOME、现有 R6 sandbox、真实 Keychain loader 和与 `--print` 完全相同的过滤环境，调用真实 `cursor-agent status --format json` 一次。只记录 exit、JSON 是否有效、`isAuthenticated`、`printCalls=0`、HOME 是否在 clone、write allow 数；不得保存 stdout 原文、账号、key 或派生值。

只有 exit=0、单一 JSON、`isAuthenticated=true` 才继续。否则立即写 `BLOCKED.md` 并停止：不运行 canary、不改代码猜修、不做第二次探针。

## 任务 2｜一次真实 canary

仅任务 1 通过后，建全新一次性目标、DB/outbox/inbox/report/pool，经生产入口让真实 Cursor 只新增 `reports/R7_REAL_CURSOR_CANARY.md`。必须 `--print` 恰好 1、独立 clone 恰好 1 commit、父进程 exact import、固定 verification 通过、official report 存在、状态 REVIEW；宿主与目标 main 零变化，merge/promote=0。失败即停，不允许第二次 canary。

## 任务 3｜收口

canary 到 REVIEW 后运行：

`PYTHONPATH=src .venv/bin/python -m unittest tests.test_cursor_cli_wrapper -v`

`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`

`git diff --check`

要求 wrapper tests≥28、全测≥175、skip/failure/error 全 0。确认 key 未出现在仓库、stateRoot、日志、stdout/stderr 或证据后，更新 `PROGRESS.md/BLOCKED.md`；只提交白名单代码/测试/docs，`PROGRESS.md/BLOCKED.md` 保持未提交；`git commit --amend --no-edit`，相对 main 恰好 1 commit。

## 规矩

不许 skip/todo、删或放宽断言、mock 真实 status/canary、修改验收阈值、`|| true`。sandbox write allow 仍仅 clone + `/dev/null`。任何边界变差就回滚并如实报告；认证预检或 canary 任一失败即用尽本轮，不窄修。

## 完成条件

1. 完整 Key 预检为 true，唯一一次 `--print` 形成单 commit、official report 并进入 REVIEW；或预检失败时以 `printCalls=0` 安全止损。
2. 成功路径下 R7 相对 main 恰好 1 commit，全测≥175 且 0/0/0，主仓/线上/四项目零变化、凭证零落盘零泄露。

每条贴脱敏实际输出，只说完成不算。`BLOCKED.md` 空也写“无”。一轮即停。
