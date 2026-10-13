# R5B · Eval 受控合并与基线提升 · Cursor Executor 任务书

你是执行者，本文件是唯一任务来源；拿不准写 Eval stateRoot 的 `BLOCKED.md`。断线先读 `PROGRESS.md`。这次只消费 Chief 已批准的 V2 decision，通过独立 merger 快进 Eval main，再提升 Eval baseline；不开发、不发布。让步顺序：决议绑定正确 > 合并可恢复 > baseline 一致 > 速度。“只允许/禁止”违反即失败。

## 我替领导拍的板

- Chief 只批准 `TASK-R5A-CANARY-V2` v5、lease=`dc1b202a-18a3-4821-8c0e-dd5cde0f9e14`、commit=`bbebcb8e65c116b05319c7f626f70740be4a17ca`。
- merger 身份固定 `merge-r5`，不得使用任务 executor `fake-r5`。
- merge 成功但 promotion 失败时保留现场和旧 baseline，不自动 reset；提交 BLOCKED 供 Chief 决定。

## 界限

只允许 R4.4 runtime 读执行报告/receipt/occupancy/Chief decision，写 merge receipt、decision consumed sidecar、occupancy phase、Eval main 快进和 project baseline。允许在 `/Users/pojian/chief-state/eval-r5/` 新建 R5B 运行脚本与证据。禁止改 task commit、旧证据、runtime、源码、测试、验收标准、依赖、remote、push、部署、Julius/Director、API/网络。

## 现状与任务 0

证明 runtime=`b9c344a` clean 且 149/0/0；Eval main/registered baseline=`da82152a90869b955ed4c738e5f288b12eaac61c`、clean、无 remote；V2 branch=`bbebcb8`、REVIEW v5、lease completed、无 active lease；decision 文件字段与上方四元组完全一致且未 consumed。六份来源 SHA、精确 `.gitattributes` 和强制默认 diff check 必须仍通过。任一不符即停，写 `PROGRESS.md` ≤10行回执。

## 任务 1｜独立合并

用 R4.4 `ChiefReviewInbox`、`TaskMerger`、Eval state DB/pool/report/receipt 路径执行一次 `merge("TASK-R5A-CANARY-V2", "merge-r5b-v2")`。只允许 `--ff-only` 结果；必须得到 `status=merged`、main HEAD=`bbebcb8`、merge receipt 与 consumed sidecar。不得直接运行手写 `git merge` 绕过服务。

## 任务 2｜基线提升

合并后先验证 main clean、8 个路径和来源 SHA、默认 diff check、runtime HEAD/clean。再用 R4.4 `BaselinePromoter` 执行 `promote("eval", "bbebcb8...", "promote-r5b-v2")`；runtime health 必须绑定 HEAD=`b9c344a`、clean、149/0/0。成功要求 registered baseline=`bbebcb8`。

## 任务 3｜交付证据

记录 decision hash、merge receipt、promotion receipt、previous/new baseline、main/branch HEAD、DB/lease/occupancy、149 测试、来源哈希、默认 diff check和回滚计划。证明 API/网络/push/部署=0；`BLOCKED.md` 无也写“无”。

## 规矩

不得伪造 decision、改 version/lease/commit，不得 `reset`、force、rebase、cherry-pick、第二个 commit、skip/todo、`|| true`。任何一步失败立即停；不得重写 decision 或重复制造新 merge。

## 完成条件

1. Chief decision 被一次消费，Eval main 以 fast-forward 到 `bbebcb8`，merge receipt 完整，registered baseline 同步为该 commit。
2. runtime 149/0/0 且 clean；Eval main clean、来源字节/默认检查不退；push、部署、外部调用均为 0。必须贴实际输出，只说完成不算。
