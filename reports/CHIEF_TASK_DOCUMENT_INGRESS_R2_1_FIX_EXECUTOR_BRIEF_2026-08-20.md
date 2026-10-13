# R2.1 · Chief 任务文档入口补正 · Cursor Executor 唯一任务书

你是同一 Control Plane Cursor Executor；只处理 Chief 对 `68b58cb` 的 `CHANGES_REQUESTED_R2`。断线先读 R2 `PROGRESS/BLOCKED` 与 Chief Review。真实 Cursor/飞书调用均为 0；不得启用 R2 常驻。

## 我替领导拍的板

- 保留 R1 与 R2 commit，不改写历史；在 `chief-task-ingress-r2` 新增一个原子补正 commit。
- 冲突输入永远不能改写既有 task state；完整 envelope 才是幂等身份。
- 生产 Runner 必须实际写回执；baseline 必须与 Dispatcher 注册值相等。
- 不改 DB schema、不扩项目 allowlist、不 merge/push/deploy。

## 界限

只允许修改 R2 worktree 中 ingress/reporter/runner 接线、相关配置示例、测试、文档和 `PROGRESS/BLOCKED`。禁止触碰 R1 运行数据库、LaunchAgent、其他仓、知识库、业务数据库、方向、验收标准和飞书凭据。测试只用临时目录/DB/fake executor。

## 现状与任务 0

确认 HEAD=`68b58cb`、worktree clean、测试基线 120/0/0、R1 READY=0 且持续 idle、真实 Cursor累计=1/R2增量=0。先为五个阻断项各写一个会失败的测试，记录红测。

## 任务 1—3

1. **不可变身份**：第一次成功登记后固定完整 envelope sourceHash。重复相同 bytes 幂等；同 id 但 task 或 facts 任一字节/规范内容变化都写 conflict 回执，回执同时保留 originalHash 与 attemptedHash，既有 DRAFT/READY/RUNNING/REVIEW/BLOCKED 状态和版本均不变。不得用冲突 hash 覆盖原决策来源。若不改 schema，使用受保护的原子 receipt/sidecar 合同并测试丢失/损坏时 fail closed。
2. **真实接线与 baseline**：Importer 用 Dispatcher 注册 baseline 做机器核验，workspace HEAD 不等时直接 BLOCKED、0 calls。为 `run_cursor_runner.py` 增加显式、可选的 inbox/reporter 配置；真实脚本等价 argv 启动后，fake READY task 经现有 Runner 到 REVIEW，并由实际运行入口写短回执。未配置 reporter 时保持 R1 行为，不降低门禁。
3. **配置与文件安全**：严格验证 config 必填字段/未知字段/类型、`allowedProjects` 非空字符串列表、`maxBytes` 与 idle 值范围、outbox≠inbox、两者为绝对本地目录且不能互相包含或是 symlink。打开 outbox 文件后 `fstat` 再确认 regular/size 与读取前身份，避免换文件窗口；异常必须脱敏、fail closed，不能 crash-loop。

反向验证至少包括：facts-only drift、冲突 REVIEW、baseline mismatch、损坏 sidecar、symlink/root overlap、缺配置；全部 0 executor calls。正向用真实 `run_cursor_runner.py` 入口 + fake executor 一次到 REVIEW/inbox，重启和重复投递不重复执行。

## 规矩

不得 skip/todo、删测试、放宽断言、mock 掉生产脚本入口/Registry/Policy/Dispatcher、直接 SQL、shell 拼接或记录 secrets。不得修改已有 R1 task/state。连续三次同一失败即停。只做一个本地 commit；不启用 importer、不调用真实 Cursor/飞书。

## 完成条件

1. 全套测试≥120、0 fail、0 skip；五项阻断均有红→绿，`git diff --check` 通过。
2. 冲突 envelope 不改变既有任何状态/版本；原始与尝试 hash 可追溯；baseline mismatch 0 calls。
3. 实际 runner 脚本入口把 fake task 唯一执行到 REVIEW 并写 inbox；重复/重启仍只执行一次。
4. 配置和 TOCTOU 反向测试 fail closed；仓外/R1 DB/真实调用均为 0。更新 `PROGRESS/BLOCKED` 与证据，贴 commit、测试、hash/state/lease/receipt，停在 Chief REVIEW。
