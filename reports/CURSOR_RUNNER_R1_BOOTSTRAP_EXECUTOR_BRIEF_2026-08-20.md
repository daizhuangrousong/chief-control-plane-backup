# CURSOR-RUNNER R1 BOOTSTRAP · Cursor Executor 唯一任务书

Owner approval ref：`OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`。你是本次唯一 Cursor Executor；本任务书是唯一任务来源。中途无人可问，拿不准就写 `BLOCKED.md`，继续不受影响部分。断线先读 `PROGRESS.md`。目标是让 Chief 今后只写任务与审查文档，由本机 Cursor Runner 执行；不是让 Chief 或 Codex 代做工程。冲突时：安全与可恢复 > 证据 > 自动化 > 速度。

## 我替领导拍的板

- 只为 Control Plane 解冻 R1：接入官方 Cursor CLI、完成一次低风险真实试跑、验证飞书真实出站、通过后建立本机常驻 Runner。
- Chief 只中控、读事实、写 Goal / Task Brief / Review / Decision；代码、测试、提交、合并、部署、回滚全部由 Cursor Executor 执行。
- 本次不改变产品方向或验收标准，不改知识库/业务数据库；不授权 push、merge、deploy。
- R0 commit 为 `fe5062fa75691ba366d209aac1f927f0e29ad643`，已由 Chief 判定 `PASS_R0`；R1 必须复用 `CursorRunner`、`LeaseDispatcher` 和现有飞书通道，禁止另造队列。

## 界限

允许改 Control Plane 仓内 `src/control_plane/`、`scripts/`、`tests/`、`config/`、`docs/`、`reports/`、`README.md`、`CHANGELOG.md`、`PROGRESS.md`、`BLOCKED.md`，以及创建专用 git worktree、用户级 LaunchAgent 和被 git 忽略的本机私有配置。只可安装 Cursor 官方 CLI；不得安装其他 Agent/调度系统。禁止触碰 Julius、Director、Eval/KESU、知识库、业务数据库、生产服务、chief-clock；禁止读取、打印、提交或把凭据写进 plist/任务报告。现有主工作树全部用户改动必须原样保留，不得 stash、清理、覆盖或纳入提交。

## 现状与任务 0

先记录：主仓 `git status --short --branch`、HEAD、`command -v agent`/`cursor-agent`、CLI 版本/帮助、相关 launchd label、全套测试数/失败/skip。核对 `docs/CURSOR_RUNNER.md`、`docs/FEISHU_CONTROL_CHANNEL.md`、`docs/OPERATIONS.md` 与 R0 review。随后从 R0 HEAD 创建独立分支及专用 worktree；所有工程修改只在该 worktree。把目标、阶段、基线、最大风险写入 `PROGRESS.md`。若 R0 基线不符、无法安全隔离主工作树，立即 `BLOCKED`。

## 任务 1—3

1. **CLI 接线**：没有 CLI 时仅按 Cursor 官方文档安装；不得用来路不明脚本或要求 Owner 在聊天中给密钥。验证当前版本的 headless 非交互调用方式。实现显式本机 wrapper：从 stdin 读取 R0 JSON，严格校验 task/project/workspace/baseline/version/approval，任务内容作为数据传递，禁止 shell 拼接；CLI 路径必须由本机忽略配置显式提供，仍不得在生产代码中默认发现。超时、非零退出、缺认证均 fail closed 并脱敏。
2. **单次真实试跑**：在专用 worktree 注册一个低风险、`approvalClass=none`、仅新增一份固定文案报告的 pilot；先证明越界 workspace、baseline 漂移、缺 Owner approval 各自被拒。随后真实 Cursor 调用最多 **1 次**，不得访问网络资料、不得改代码、不得提交；成功必须留下目标文件与执行证据，并只进入 `REVIEW`。失败不得自动重试。
3. **飞书与常驻**：复用现有 Feishu SDK 通道。若本机已有私有配置和环境凭据，只验证存在/权限，不显示值；发送 1 张明确标注“R1 启动验证、无需决策”的测试卡，记录 message id 与送达状态。缺配置/权限则只将飞书项写 `BLOCKED`，不得索取或伪造凭据。仅在全套测试、反向门禁和真实 pilot 全部通过后，建立用户级常驻 Runner：显式命令、Control Plane 项目 allowlist、单任务、空队列 idle、受限重启、日志轮转；启动前确认无其他 READY 任务，启动后证明 idle 不调用 Cursor。飞书 worker 可仅在凭据已安全存在且送达验证成功后常驻。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉真实边界、`|| true`、静默重试或把 task 文本拼入 shell。真实 Cursor 总调用数≤1，测试卡≤1；费用异常即停。不得把 secrets、完整环境、聊天记录写进证据。连续三次同一验收失败即停。完成后只做一个原子本地 commit，范围仅含 R1 白名单；不合并、不 push。LaunchAgent 若阶段失败不得启用；若启用后验收失败，立即 unload，保留日志并写 `BLOCKED.md`。

## 完成条件

1. 全套测试零失败零 skip，测试数不低于任务 0；`git diff --check` 通过。
2. 三个反向门禁都有真实拒绝证据；真实 pilot 恰好一次，产物存在，状态为 `REVIEW`，主工作树零变化。
3. Runner 常驻后空队列保持 idle、无 Cursor 调用；重启后恢复；配置显式且权限最小。飞书项必须如实为 PASS 或独立 BLOCKED，不得伪造成功。
4. `PROGRESS.md` 给出阶段状态、调用次数、测试数、commit、LaunchAgent label、日志路径、pilot task/lease/review id；`BLOCKED.md` 无阻塞则写“无”。最终贴任务 0/最终测试、红→绿、真实调用证据、飞书出站结果、`git status`、`git show --stat`。停在 Chief `REVIEW`，不得自行合并或扩到其他项目。
