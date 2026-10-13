# R2 · Chief 任务文档入口 · Cursor Executor 唯一任务书

你是 Control Plane Cursor Executor。目标：让 Chief 只写结构化任务文档，系统就能安全登记、判定并交给现有 Cursor Runner；Chief 不调用 CLI、不直接写 SQLite。中断先读 `PROGRESS.md/BLOCKED.md`。冲突时：审批与幂等 > 可追溯 > 自动化 > 速度。

## 我替领导拍的板

- R1 Runner 已由 Chief 判 `PASS_R1_RUNNER_WITH_CLOSEOUT`，当前仅允许 `control-panel`。
- R2 只建文件入口和结果回执，复用 `TaskRegistry`、`DecisionPolicyEngine`、`LeaseDispatcher`；禁止第二队列。
- 知识库/数据库写入、方向、验收标准变更仍须 `approvalClass + ownerApprovalRef`；缺失必 BLOCKED。
- 不接 Julius、Director、Eval，不处理飞书凭据，不 merge/push/deploy。

## 界限

先在 R1 worktree 只修 5 处行尾空格并提交激活证据，形成纯文档 closeout commit。随后从该 HEAD 创建独立 R2 分支/worktree；R2 允许修改 Control Plane `src/`、`scripts/`、`tests/`、`config/`、`docs/`、`reports/`、`PROGRESS.md/BLOCKED.md`。禁止改 DB schema、R1 安全门禁、LaunchAgent allowlist、其他仓或生产。R1 常驻服务保持 idle，不得让开发 worktree 被它执行。

## 现状与任务 0

记录 R1 HEAD、dirty 文件、实时 launchd/idle 状态、测试基线 110/0/0、READY=0、Cursor 调用累计=1。完成证据 closeout commit 后验证 R1 worktree clean；再建 R2 worktree。把路径、分支、基线和最大风险写入 R2 `PROGRESS.md`。

## 任务 1—3

1. **文件合同**：定义 gitignored 的本机 `chief-task-outbox/` 与 `chief-task-inbox/`。Chief 只原子写入一个严格 JSON task envelope；字段复用现有 task schema，必须含稳定 id、版本/source hash、project、workspace、acceptance、approvalClass/ref。拒绝 symlink、非普通文件、越界路径、未知字段、重复 id 不同内容、部分写入和超大文件。示例只含假数据。
2. **单向摄取**：实现独立 importer/daemon，观察完整文件后经 `TaskRegistry` 登记 DRAFT，再调用现有确定性 policy；只有证据齐全、低风险、审批满足才进 READY。不得直接 SQL、不得绕租约。完全相同文件重复投递必须幂等；冲突、缺审批、高风险或非法输入写结构化 BLOCKED 回执，绝不启动 Cursor。处理结果原子写 inbox，保留 source hash、task version、state、matched rules、时间和脱敏错误。
3. **审查回执**：为 Runner 周期增加只读状态回执或独立 reporter，把 CLAIMED/RUNNING/REVIEW/BLOCKED 的最新事实写入 inbox；不得自动把 REVIEW 变 DONE。Chief 能仅读单个短 JSON 判断是否需下钻。Importer 与 Runner 各自单一职责，崩溃重启不重复登记或重复执行。

先用 fake executor 做端到端：Chief 文件→DRAFT/policy→READY→唯一 lease→REVIEW→inbox。反向验证：缺 Owner approval、越界 workspace、同 id 改内容、symlink、截断 JSON，均 0 executor calls。R2 真实 Cursor 调用为 0。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉文件边界/Registry/Policy/Lease、shell 拼接、轮询无限刷错或记录 secrets。不得让 R1 现有数据库接收 R2 开发测试数据；测试用临时目录/DB。连续三次同一失败即停。完成后一个 R2 原子本地 commit，不 merge/push；不得启用 R2 常驻，停在 Chief REVIEW。

## 完成条件

1. R1 证据 closeout 独立 commit，worktree clean；R1 Runner持续 idle、调用累计仍为1。
2. 全套测试≥110、0 fail、0 skip；端到端 fake 流程一次进 REVIEW，五个反向输入均 0 calls；重启/重复投递幂等。
3. `git diff --check`、配置示例、权限/原子写测试通过；无 schema 变更、无仓外修改、无真实 Cursor/飞书调用。
4. `PROGRESS/BLOCKED` 给出测试数、红→绿、task/hash/state/lease/review 回执、两个 commit、worktree 状态与调用数，停在 Chief REVIEW。
