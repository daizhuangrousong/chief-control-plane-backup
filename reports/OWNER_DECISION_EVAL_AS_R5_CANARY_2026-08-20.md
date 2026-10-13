# Owner Decision · Eval 作为 R5 受控演练

日期：2026-08-20

状态：`APPROVED / GATED_BY_R4.1_PASS`

## 决定

- R4.1 通过 Chief Review 后，不另开一轮空泛演练；直接以 Eval 仓库落地作为 R5 第一个真实、低风险任务。
- Eval 正式项目：通用 AI Agent 生产验收体系；首个垂类为 Deep Research Agent。它检查单个 Agent 的交付健康，不是排行榜或横评。
- 预定本机仓库路径：`/Users/pojian/repos/ai-agent-production-acceptance`。
- 此决定批准仓库初始化、Control Plane 注册、既有 Phase 0 资产找回/重建、目录与版本固化、本地 smoke test。

## R5 边界

- 只验证：任务下发 → 独立 worktree → Executor 提交 → Chief Review → merger → baseline promotion。
- 不安装或运行 GPT Researcher、Open Deep Research、`dzhng/deep-research`。
- 不调用付费模型、不产生实验费用、不部署、不发布、不改变 Phase 0 方向或验收标准。
- R5 落盘资产必须明确：多个 Agent 只是校准同一把尺子的样本；不计算综合排名、不选冠军、不宣称认证，商业化不是 Phase 0 成功条件。
- 既有资产若无法找回，只能按已确认记录重建并明确标注来源；不得假装原文件已恢复。

## R5 预期资产

- `AI_AGENT_ACCEPTANCE_PHASE0_BRIEF_2026-08-20.md`
- `PHASE0_EXPERIMENT_DESIGN_V0_1.md`
- `BILINGUAL_REPORT_SKELETON_V0_1.md`

## 后续闸口

R5 通过后，Chief 才可下发 Eval Phase 1：固定版本、安装三个 Agent、smoke test。正式运行 Case 001 仍受 100 元总成本上限与真实账单纪律约束。

方向与验收基线以 `OWNER_DECISION_EVAL_ACCEPTANCE_NOT_RANKING_2026-08-20.md` 为准；若旧资产出现“横评、榜单、冠军或综合排名”表述，必须先纠正再进入 R5 验收。
