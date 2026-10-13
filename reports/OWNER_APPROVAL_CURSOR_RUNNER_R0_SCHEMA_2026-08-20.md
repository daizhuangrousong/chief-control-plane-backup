# OWNER APPROVAL · Cursor Runner R0 Schema

- Approval ref: `OWNER-APPROVAL-20260820-CURSOR-R0-CONTROL-TASK-SCHEMA`
- Date: 2026-08-20
- Decision: **APPROVED**
- Source: Owner 在 Chief 接管会话中明确回复：“批准 Control Plane 的这两项审批字段变更”。

## 批准范围

仅批准 Control Plane 内部 SQLite `control_task` 的两项审批字段：

- `approval_class`：默认 `none`；允许 `knowledge_write | database_write | direction | acceptance_change`。
- `owner_approval_ref`：可空；当 `approval_class != none` 时，进入 READY 前必须非空。

## 未批准

- 不批准 Julius、Director、KESU 或任何业务数据库写入/迁移。
- 不批准真实 Cursor Runner、launchd 接线或业务仓试跑。
- 不批准绕过 Owner 对知识库、数据库、方向和验收标准变更的审批。

