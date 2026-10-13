# R5 · Eval 仓库落地与跨仓 Canary · Cursor Executor 任务书

你是执行者，本文件是唯一任务来源；拿不准写 `BLOCKED.md`，继续不受影响项。断线后先读现有 R4 `PROGRESS.md`，但本任务进度写入 Eval stateRoot。此任务建立真实 Eval 仓，并让首批治理资产通过 R4.4 跨仓生命周期到 REVIEW。让步顺序：方向不漂移 > 证据诚实 > 仓库可恢复 > 速度。“只允许/禁止”是硬约束。

## 我替领导拍的板

- Eval 是 Agent 交付健康验收体系，不是横评、榜单、认证或代运营；多个 Agent 只是校准样本。
- 本轮不克隆/安装/运行三个 Agent，不调用 API，不产生费用，不发布。
- 原 `/workspace/...` Git 仓历史仍不可访问，但四份原始资产已从 ChatGPT 下载到本机；必须按冻结 SHA-256 原字节导入，不得重写、补全或标为重建。
- R5A 只到 REVIEW。不得由本 Executor 写 Chief decision、merge 或 baseline promotion。

## 界限

允许创建 `/Users/pojian/repos/ai-agent-production-acceptance/`、`/Users/pojian/chief-state/eval-r5/`；只读 R4.4 runtime、Control Plane 三份 handoff/Owner 决议及 `/Users/pojian/Downloads/{README.md,PHASE0_EXPERIMENT_DESIGN_V0_1.md,PUBLIC_EXPERIMENT_CHARTER_V0_1.md,BILINGUAL_REPORT_SKELETON_V0_1.md}`。Eval 仓只允许 `.gitignore`、`README.md`、`docs/{PHASE0_EXPERIMENT_DESIGN_V0_1.md,PUBLIC_EXPERIMENT_CHARTER_V0_1.md}`、`reports/{CHIEF_HANDOFF_2026-08-20.md,BILINGUAL_REPORT_SKELETON_V0_1.md,R5_CANARY.md}`、`governance/*.md`。禁止候选仓、依赖、密钥、网络下载、push、部署和生产项目。

## 现状与任务 0

先证明 runtime HEAD=`b9c344a`、clean，且用该 runtime 的 `PYTHONPATH=src` 导入后 `control_plane.__file__` 位于 runtimeRoot；R1 仍 idle、R3 importer 不存在。证明 Eval repo 与 stateRoot 均不存在或为空；若已有内容，不覆盖，写 stateRoot 外的 `BLOCKED.md` 后停。核验四份下载原稿 SHA-256 依次为 `331e75529ce5096425d845f3b28be3779d8fad4afbd19547753fa7469966308d`、`3489d33fb5642506ecd2072174287edd97482b21bb61f41d0531a93eef482307`、`4c621fa1502ea768f547877ddf7e03476ad99b6ad1cdfffa7a52e3cdd618f17e`、`b6f00974a9ae980bd106c1dbac4f4fc103ea94dfe24078b6ec687383630c969e`；任一不符即停。把输出和理解≤10行写入 stateRoot 的 `PROGRESS.md`。

## 任务 1｜最小可恢复基线

创建 Eval `main` 仓，只提交 `.gitignore` 与原字节 `README.md` 作为 bootstrap baseline；复制后 SHA 必须仍为 `331e...6308d`。`.gitignore` 必须忽略 `var/`、本地密钥、候选仓、原始运行缓存。记录 baseline SHA；不得 remote/push。

## 任务 2｜注册独立项目

stateRoot 固定 `/Users/pojian/chief-state/eval-r5`，poolRoot 固定 Eval `var/task-worktrees`。用 R4.4 runtime 建本地 DB、注册 project `eval`、executor 与 bootstrap baseline。所有 review/report/receipt/occupancy/outbox 在 stateRoot；验证 runtime、Eval、state 三者互不嵌套且 runtime/Eval git-common-dir 不同。

## 任务 3｜资产 Canary 到 REVIEW

通过文件入口创建一个低风险任务，使用注入 fake executor 在租约 worktree 内一次提交 docs/reports/governance 文件。两份 docs 与报告骨架从 Downloads 原字节复制，目标 SHA 必须分别保持 `3489...307`、`4c62...17e`、`b6f0...69e`；handoff 与两份 Owner 决议也逐字复制并记录 SHA-256。不得增加 `RECONSTRUCTED_FROM_HANDOFF`，不得新增榜单/冠军/综合排名/Production Ready。Chief verification 只用只读 argv，执行总次数与声明数一致。成功停在 REVIEW；Eval main 仍只有 bootstrap commit，资产只在 task branch。

## 任务 4｜交付证据

记录 runtime/baseline/task commit、changed paths、任务版本、lease、report、verification、stateRoot 路径和回滚计划。证明 API 成本=0、网络调用=0、候选仓=0、merge/promotion=0；`BLOCKED.md` 无也写“无”。

## 规矩

不得 skip/todo、放宽 R4.4 判据、直接 SQL、shell 拼接、真实 Cursor/飞书。不得修改 Downloads 原稿或用复制后的近似文本替代；若任一既有路径非空、runtime preflight 失败或来源 SHA 不一致立即停，不得删除重来。完成后停在 Chief REVIEW。

## 完成条件

1. 独立 Eval 仓已建立；治理资产通过 R4.4 生命周期形成一个 task commit 并停在 REVIEW，main/baseline 未合并，方向无排行榜漂移。
2. R4.4 全测仍 ≥149/0/0，canary verification 全绿；外部调用、费用、候选仓、merge、promotion 均为 0。交付贴实际输出，只说完成不算。
