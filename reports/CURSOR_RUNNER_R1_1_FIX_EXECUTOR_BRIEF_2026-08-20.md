# CURSOR-RUNNER R1.1 FIX · Cursor Executor 唯一任务书

继续使用 Owner approval `OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`。你是同一 Cursor Executor；只处理 Chief 对 commit `549cce7` 的 `CHANGES_REQUESTED_R1`。中断先读 `PROGRESS.md` 与 `BLOCKED.md`，拿不准就停。目标是补正安全与常驻合同，并完成原 R1 的 pilot/飞书/常驻验收；不是扩展项目。

## 我替领导拍的板

- R1 实现部分保留，但不得合并、push 或启用当前 plist。
- 必修三项：CLI 子进程最小环境、无歧义启动参数、有限重启/永久拒绝后停机。
- 真实 Cursor 总调用上限仍为原授权 **1 次**；目前计数 0。飞书测试卡上限仍为 1；目前计数 0。
- CLI 登录和飞书凭据只能使用 Owner 本机既有安全机制；不得索取、输出或写入仓库/plist。

## 界限

只在 `/Users/pojian/repos/director-control-plane-r1-bootstrap` 和原 `cursor-runner-r1-bootstrap` 分支修改 R1 白名单文件。主仓及 Julius、Director、Eval/KESU、知识库、业务数据库、生产和 chief-clock 全部禁止。不得修改产品方向、验收标准或审批分类；不得安装新系统；不得 merge/push/deploy。现有 commit 之后再做一个原子补正 commit，不改写历史。

## 现状与任务 0

先复核 HEAD=`549cce7`、worktree clean、真实调用数=0、测试基线=103/0/0，并读取 Chief Review。把补正顺序和风险写入 `PROGRESS.md`。任何数字不符先 `BLOCKED`。

## 任务 1—3

1. **最小环境**：CLI status 与 `--print` 不得继承完整 `os.environ`。建立明确 allowlist，只传运行/locale/临时目录所需字段及 Cursor 自身认证字段；用 canary secret 测试证明 `FEISHU_APP_SECRET`、通用 token/key、无关变量不进入 status/print 子进程。日志继续脱敏。
2. **可启动合同**：消除 `--executor-command nargs="+"` 与 wrapper 自身 options 的解析歧义。配置与 argv 仍须显式、非 shell、无默认发现。新增测试，用 plist 等价的完整参数序列解析并构造 Runner；模板先做 plist 语法检查，再证明单周期空队列成功 idle，CLI 调用数为 0。
3. **有限失败**：永久拒绝不得每 30 秒重试；LaunchAgent 不得无条件无限 KeepAlive。实现并测试可审计的停止/熔断与有限重启合同：同一错误达到上限后停止，留下脱敏原因并等待 Chief；空队列可持续 idle；进程恢复不重复已完成任务。更新运维文档与模板。

完成代码红→绿后检查认证。若仍未认证，保持真实调用 0，只更新 `BLOCKED.md`，不得假装完成。若已认证，按原 R1 pilot 精确调用一次：仅固定文案报告、无网络、无代码改动、成功进 REVIEW、失败不重试。飞书凭据若已安全可用，发送一次无需决策测试卡；否则独立 BLOCKED。只有三项补正、全套测试、真实 pilot 全部通过才可启用常驻；飞书 worker 仍须自身送达通过才可常驻。

## 规矩

不得 skip/todo、删测试、放宽门禁、mock 掉参数解析/环境过滤/熔断、`|| true` 或静默重试。不得打印环境或 secret 值。真实 Cursor≤1、飞书卡≤1。任何阶段失败停止后续有副作用步骤；若已启用服务再失败，立即 unload 并保留日志。只做一个本地补正 commit。

## 完成条件

1. 全套测试≥103、0 fail、0 skip；新增测试分别证明环境 canary 不泄露、模板等价 argv 可启动、永久拒绝会熔断且不无限重试。
2. `git diff --check`、plist 语法、worktree 隔离通过；两个本地 commit 清晰可审查。
3. 原 R1 完成条件如实给出：真实 pilot 恰好 1 且 REVIEW；常驻 idle/restart/circuit-breaker 有证据；飞书 PASS 或独立 BLOCKED。未满足任一核心项不得声称 R1 PASS。
4. 更新 `PROGRESS.md`、`BLOCKED.md` 和 R1 evidence，贴基线/最终测试、红→绿、调用计数、task/lease/review id、message id、LaunchAgent label/log、`git status`、`git show --stat`，停在 Chief REVIEW。
