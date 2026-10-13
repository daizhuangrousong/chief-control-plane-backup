# CURSOR-RUNNER R0 · Cursor Executor 任务书

你是 Control Plane Cursor Executor；本任务书是唯一任务来源。中途无人可问，拿不准写 `BLOCKED.md` 后继续不受影响部分。断线后先读 `PROGRESS.md` 接着做。此任务要证明 Chief 能安全派单给 Cursor，而不是让 Chief 自己执行。冲突时：安全隔离 > 审计完整 > 功能完整 > 速度。“只允许/禁止”违反即失败。

## 我替领导拍的板

- Owner 已解冻受限本机 Cursor Runner，但仅到 R0；真实 Cursor、launchd 和业务仓试跑均未授权。
- Chief 只写 Goal / Task Brief / Review / Decision；Runner 与 Cursor Executor 承担实际执行。
- 知识库写入、数据库写入、方向变更、验收标准变更必须有 Owner approval ref。
- 复用现有 `TaskRegistry`、`DecisionPolicy`、`LeaseDispatcher`；禁止另造队列或绕过 SQLite 租约。

## 界限

只允许修改：`src/control_plane/`、`tests/`、`config/`、`docs/`、`README.md`、`CHANGELOG.md`，以及新建 `PROGRESS.md`、`BLOCKED.md`。其余只读。禁止修改 Julius、Director、KESU、数据库、chief-clock；禁止安装 Cursor CLI、真实调用 Cursor、启动 launchd、push、merge、deploy。禁止移除 `ISOLATED_PROJECT_IDS` 或降低现有 dispatcher 门禁。

## 现状与任务 0

实测基线：`LeaseDispatcher` 已有 executor/project/risk allowlist、唯一 lease、baseline 检查、幂等 request ID、过期恢复和连续两次失败禁用；`docs/LEASE_DISPATCHER.md` 明确 Cursor wrapper 不得绕过这些门。先运行：

```bash
git status --short --branch
command -v cursor-agent || command -v agent
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

CLI 只探测，不安装、不调用。记录测试数、失败数、skip 数。与现状不符写 `BLOCKED.md`；再把目标、顺序、最大风险用不超过 10 行写进 `PROGRESS.md`。

## 任务 1 · 冻结执行合同

为 task schema/domain 增加可机器判定的审批分类：`none | knowledge_write | database_write | direction | acceptance_change`；非 `none` 必须带非空 `ownerApprovalRef` 才可能 READY。兼容旧任务，默认 `none`。补 schema/domain/policy 测试，证明缺引用必阻断、伪字段不能绕过。

## 任务 2 · R0 Cursor 适配器

实现一个本地适配器，但只接受注入的 executor command；生产默认不得找到或启动真实 Cursor。适配器必须：从 LeaseDispatcher 领取单任务；校验 project、workspace root、baseline、task version；把任务正文作为数据传入，禁止 shell 拼接；超时/非零退出写 fail；成功只进 REVIEW；日志去除疑似 secret/token；同一项目最多一个活动执行。用临时目录和 fake executable 覆盖成功、失败、超时、越界、baseline 漂移、重复 claim、审批缺失。

反向验证：故意提交一次越界 workspace 和一次缺 Owner approval 的数据库任务，贴出被拒输出；再恢复并贴全绿。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉被测适配器、改测试发现方式、`|| true`。测试数不得低于任务 0；skip 必须为 0。不得把真实 CLI 路径写死为默认启用。连续三次同一验收失败即停；结果比基线差则回滚本任务代码并如实报告。完成后只做一个原子本地 commit，不 push。

## 完成条件

1. 全套测试零失败零 skip，且反向验证证明越界与缺审批都会被拒；真实 Cursor 调用次数为 0。
2. 仓外零修改、零安装、零业务仓写入、零远程写入；本地 commit 仅含白名单文件。

最终回复贴任务 0 与最终测试、反向红→绿、`git diff --check`、`git status --short --branch`、`git show --stat --oneline HEAD` 的实际输出。`BLOCKED.md` 必须提交，空则写“无”。
