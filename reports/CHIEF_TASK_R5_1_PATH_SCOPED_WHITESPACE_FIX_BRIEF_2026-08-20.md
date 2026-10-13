# R5.1 · 冻结原稿逐路径例外 · Cursor Executor 任务书

你是执行者，本文件是唯一任务来源；拿不准写 stateRoot 的 `BLOCKED.md`，继续不受影响项。断线先读 `PROGRESS.md`。这次只修 R5 的空白检查策略：冻结原稿保持原字节，Executor 新写文件继续受默认检查。让步顺序：判据不放宽 > 原稿不改字节 > 证据可审计 > 速度。“只允许/禁止”违反即失败。

## 我替领导拍的板

- `TASK-R5A-CANARY` Chief Review 已拒绝；不得 merge/promote，也不得改写其证据。
- 允许用 tracked `.gitattributes` 对六份冻结导入资产做逐路径例外；禁止 glob、目录级或全仓例外。
- 本轮最多两次执行尝试；失败即停，不创建 R5.2。

## 界限

只允许修改 Eval 仓本地 `core.whitespace` 配置，并从 main=`da82152a90869b955ed4c738e5f288b12eaac61c` 新建任务 worktree。新 task commit 只允许 `.gitattributes` 与 R5 既定 7 个资产路径。只读 Downloads 四原稿、Control Plane handoff/两份 Owner 决议、R4.4 runtime 与 Eval stateRoot。禁止删旧任务/worktree/branch/证据，禁止改 runtime、DB schema、验收代码、依赖、网络、API、push、merge、promotion。

## 现状与任务 0

证明 runtime=`b9c344a` clean、149/0/0；Eval main 和 registered baseline 均为 `da82152`、main clean、无 remote；DB 中 `TASK-R5A-ASSETS=FAILED`、`TASK-R5A-CANARY=REVIEW` 且无 active lease。记录当前 local `core.whitespace=-blank-at-eol,-blank-at-eof,space-before-tab`。任一事实不符即停。把目标/顺序/最大风险≤10行写入 `PROGRESS.md`。

## 任务 1｜撤销全仓放宽

只移除 Eval local `core.whitespace` 键；不得改 global/system config。记录移除前后 `git config --show-origin --get-all core.whitespace` 的输出与退出码。

## 任务 2｜逐路径、可审计例外

新建 `TASK-R5A-CANARY-V2`，从 main/baseline 起步。`.gitattributes` 只能有六条精确路径：两份 docs、报告骨架、handoff、两份 Owner 决议；每条仅设置 `whitespace=-blank-at-eol,-blank-at-eof,space-before-tab`。不得豁免 `README.md`、`reports/R5_CANARY.md`、通配符或目录。复制六份冻结资产并保持 R5 已冻结 SHA；生成干净的 `R5_CANARY.md`。一次提交。

## 任务 3｜红→绿与生命周期

先在 stateRoot 临时 Git 小样中证明：同样的逐路径属性允许一份冻结副本通过，但未列名的带尾随空格文件必须被默认 `git diff --check` 报红；还原后全绿。再通过 R4.4 文件入口与 fake executor 跑 V2。Chief verification 必须包含强制默认规则的只读 argv：`git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab diff --check da82152a90869b955ed4c738e5f288b12eaac61c..HEAD`，以及文件存在/来源哈希检查。成功停在 REVIEW。

## 任务 4｜交付证据

记录 task/lease/commit/changed paths、`.gitattributes` 全文、红→绿原始输出、7 个资产 SHA、verification 调用数、DB 状态和回滚计划。证明 main/baseline 不变，API/网络/候选仓/merge/promotion=0；`BLOCKED.md` 无也写“无”。

## 规矩

不得 skip/todo、放宽断言、mock 判卷、修改测试/验收脚本、`|| true` 或再次设置 local/global `core.whitespace`。同一验收失败两次立即停；不得删除重来。

## 完成条件

1. V2 单 commit 停在 REVIEW；六份冻结资产原字节一致，逐路径属性可审计，未列名坏文件红、还原后默认检查绿。
2. local `core.whitespace` 不存在；R4.4 ≥149/0/0；main/baseline、外部调用、费用、merge、promotion 均不变。必须贴实际输出，只说完成不算。
