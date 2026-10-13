# R3 · Chief 文档自动派单激活 · Cursor Executor 唯一任务书

你是 Control Plane Cursor Executor。目标：把已通过审查的 R2 文件入口安全接到现有 R1 Runner，并证明“任务文档→READY→Cursor→REVIEW→短回执”无需 Chief 调 CLI。中断先读 R2.1 Chief Review。冲突时：可回滚 > 状态真实 > 自动化 > 速度。

## 我替领导拍的板

- 允许一个 Control Plane-only、固定文案、低风险真实 pilot；真实 Cursor `--print` 本任务最多 1 次，失败不重试。
- 只允许 `control-panel`；不连接 Julius、Director、Eval，不处理飞书，不 merge/push/deploy。
- R1 当前服务是回滚基线；任何激活失败立即恢复原 R1 plist/路径并证明 idle。
- 不改 DB schema、产品方向或验收标准。

## 界限

在 `chief-task-ingress-r2` 分支新增一个原子代码 commit；激活证据可再做一个纯文档 closeout commit。允许新增受限的 importer/reporter LaunchAgent、本机 gitignored ingress 配置与 outbox/inbox；允许更新 Runner plist 指向已提交 R3 worktree。禁止触碰其他仓、知识库、业务数据库、生产、chief-clock、飞书 secret。现有 R1/R2 commits 不改写。

## 现状与任务 0

记录 HEAD=`c957083`、测试基线 126/0/0、R1 label/pid/log、READY=0、真实 Cursor 累计=1、R2 未启用。备份当前 plist 的 hash 与回滚命令（不得复制 secret；plist 本身无 secret）。确认 R2 worktree clean、CLI 已认证、预算正常。

## 任务 1—3

1. **持续状态**：让独立 importer/reporter 周期扫描受保护 identity 列表并发布 DRAFT/READY/CLAIMED/RUNNING/REVIEW/BLOCKED 最新事实；不改变任务状态。长运行 fake task 必须在完成前观察到 CLAIMED/RUNNING，完成后 REVIEW。halt/rejected 必须发布最终安全状态；空队列不刷写无关文件。receipt 保留 originalHash、taskVersion、leaseId、matchedRules、时间。
2. **受限常驻与回滚**：为 ingress/reporter 建用户级 LaunchAgent，显式绝对路径、Control Plane allowlist、日志轮转、有限重启/熔断、无凭据。更新 Runner 为已提交 R3 代码并传 `--inbox-dir`。启动顺序：先 importer/reporter idle，再切 Runner；两者均须 `launchctl print` running，重载恢复，30 秒内无 traceback/rejected/halted/意外 Cursor 调用。失败最多两次，之后回滚 R1。
3. **完整 pilot**：原子写入一个新的严格 envelope，任务仅在 R3 worktree 新增 `reports/CHIEF_PIPELINE_R3_PILOT_2026-08-20.md` 固定文案，不联网、不改代码、不提交。系统必须自动登记与 policy READY，Runner 唯一调用 Cursor 一次，任务进入 REVIEW，inbox 最终回执与 task/lease/hash/version 一致。不得手工调用 register/decide/cursor-run 来补路径。

反向激活验证：先投递一份缺 ownerApprovalRef 的 `database_write` envelope，必须 BLOCKED、Cursor 0 calls；不得复用 pilot id。测试文件不得留在 READY。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉常驻入口/中间状态/真实文件路径、直接 SQL、shell 拼接或显示 secrets。真实 Cursor≤1、飞书=0。任何异常先停副作用并回滚，不得无限重试。激活前全套测试必须绿；代码提交后才可切服务。

## 完成条件

1. 全套测试≥126、0 fail、0 skip；长 fake 任务证明 CLAIMED/RUNNING→REVIEW，halt 有最终回执；`git diff --check`/两个 plist lint 通过。
2. 两个 LaunchAgent running、重载恢复、日志干净、有限重启和 R1 回滚证据齐全。
3. 反向审批任务 BLOCKED/0 calls；正向真实 pilot 恰好 1 call、自动到 REVIEW、artifact 唯一、receipt hash/state/lease/version 一致。
4. 更新 `PROGRESS/BLOCKED` 与 R3 evidence，给出 commits、labels/pids/logs、调用累计、task/lease、回滚基线和 clean status，停在 Chief REVIEW；不得自行扩项目。
