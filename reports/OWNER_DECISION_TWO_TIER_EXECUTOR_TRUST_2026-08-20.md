# Owner Decision · Two-tier Executor Trust · 2026-08-20

状态：`APPROVED`

## Tier 1 · 可信但可能出错

- R4.2 修复真实验收证据、REVIEW 顺序与 merge 重试恢复。
- 允许 R4.2 PASS 后以全新 Eval 仓库执行 R5。
- 同一 macOS 用户下的路径隔离只防误操作、漂移和错误，不宣称能抵御恶意进程。

## Tier 2 · 权限隔离

- 在自动化连接 Julius、Director、生产数据库、密钥、部署或回滚前，必须完成 R6。
- R6 必须提供真实的进程/系统权限边界，使任务 Executor 不能写 Chief decision、可信证据、生产 checkout 或运行时。
- R6 未通过时，任何生产项目不得复用 Eval 的 Tier 1 放行结论。

