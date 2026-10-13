# 独立钟（2026-08-19 登记）

目标：系统永远知道三个 agent 是否活着。不是三个窗口永远开着。

```
launchd（钟，自持）
    → status probe → HOURLY_STATUS 落盘
    → Chief 判断（WARNING，不修复）
```

## 角色（2026-08-19 12:04 锁定）

| 层 | 承担 | 不承担 |
|---|---|---|
| **钟** | launchd 自持；每小时观察、落盘 | 执行产品工作 |
| **手** | 优先 Cursor 本机 agent（非交互拉起，Clock Proof **之后**才验） | 聊天窗口当 daemon |
| **WB** | 人工审批 / 临时发射 / 产品运营入口（看稿、专项评审、人工介入） | 每小时检查、每天巡检、持续治理；不进控制链 |

Agent Runner 原冻结已由 Owner 于 2026-08-20 部分解冻：允许设计和实现受限本机 Cursor Runner。当前仍 **未验、未启用、未接管任何仓**；R0 只做 fake executor 安全验证。

```
launchd → cursor-agent --cwd <repo> --prompt HOURLY_LOOP.md
```

真实非交互拉起、launchd 接线与仓库试跑均不属于 R0；须在安全适配器验收后另行授权。WB 不进入持续控制链。

Julius 仓内 `julius-workbuddy` 仍可当 **J3 产品执行器**（draft_build），那是运营入口，不是小时巡检 daemon。hy3 / `dispatch next` 仍冻。

## Clock Proof Phase（今日里程碑：完成）

P0 2026-08-19：11:40–13:10 连续 7 拍 `on_time=True`、exit 0、无 log 缺口。  
P1：手过期时钟打 WARNING（Julius / Control Plane），未修复。  
P2：Chief 未接管。

钟继续跑（launchd）。本窗不再当观察循环。

## 下一阶段：Status Contract v1（先于换手）

协议：`STATUS_CONTRACT.md`。各仓无论换哪个 agent 都只遵守该字段。Runner R0 可开发，但真实换手仍须先采纳协议并单独过启用门。

长期治理（QUEUED）：`CHIEF_GOVERNANCE.md` → D-EVOL、J-POS。

指针：`/Users/pojian/chief-clock/`  
LaunchAgent：`gui/501/com.pojian.chief-clock`
