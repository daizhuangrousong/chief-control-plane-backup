你是运维验收执行者，这是自动派发上线的最后一轮，也是唯一任务来源；不改代码。中途没人可问，拿不准写 evidence 后停。目标是让 Chief 以后只需原子写任务文档，ingress 自动入队，R7 自动隔离执行并回传 REVIEW。冲突时：Owner资产与凭证安全 > REVIEW停点 > 端到端自动化 > 速度。只有“只允许/不许”是硬边界。

## 我替领导拍的板

- 启用已提交的 `com.pojian.chief-task-ingress`，与当前 R7 runner 共用 live-v3 DB/inbox；没有第二队列。
- 只投递 `TASK-AUTO-DISPATCH-001`，真实 Cursor `--print` 最多1次。
- canary只在clean target任务分支新增 `reports/AUTO_DISPATCH_CANARY.md` 并停REVIEW；不合并、不提升baseline、不写Owner main。
- 通过后 ingress 与 runner 都保持常驻 idle；这是最后一次手动粘贴任务。

## 界限

只允许在 `/Users/pojian/chief-state/control-plane-production/live-v3/` 新增 ingress config/outbox/inbox/log/evidence；安装/切换唯一 label `com.pojian.chief-task-ingress` 的 plist；系统自动在 clean target pool、task branch、live-v3 DB/report/receipt 中写 canary 状态。允许更新R7 `PROGRESS.md/BLOCKED.md`不提交。Owner main/runtime/target main、R7 runner plist、R1 backup、Keychain值、飞书、四项目、remote只读。禁止代码改动、commit到现有main、merge/promote/push/deploy、第二个task或第二次print。

## 现状与任务0

核对当前 R7 runner running，runtime/target=`140b993` clean；live-v3 task/lease=0、runner连续idle、stderr/halt/authJson=0；ingress label和plist均不存在。开工瞬间fresh-snapshot Owner main并立即复扫相等，此后只与本轮snapshot比较。确认target main与baseline=`140b993`。写≤10行回执；不符即停。

## 任务1｜ingress红→绿与常驻

创建无凭证 ingress config：outbox=`live-v3/outbox`，inbox=`live-v3/inbox`，allowedProjects仅`control-panel`，maxBytes=262144。先用隔离precheck目录放一个截断JSON，`max-cycles=1`必须拒绝且task/lease/print=0、无halt；不得把坏文件放生产outbox。

再对空生产outbox运行`max-cycles=1`，必须exit=0且只idle。生成plist：WorkingDirectory/PYTHONPATH/script指clean runtime；projects config与live-v3 runner相同；参数含ingress config、5秒idle、log/halt；KeepAlive=`SuccessfulExit=false`，无凭证。若旧label/plist意外存在，停止不覆盖。

bootstrap ingress，等2个idle周期；证明两个LaunchAgent均running，DB相同、task/lease/print=0、两边stderr/halt=0。失败bootout ingress并把plist移入live-v3 rollback，R7 runner保持运行。

## 任务2｜唯一自动派发canary

构造一个严格 envelope：id=`TASK-AUTO-DISPATCH-001`，project=`control-panel`，risk=low，approval=none，executor仅`cursor-r1`，workspaceRoot指clean target；scope仅`reports/AUTO_DISPATCH_CANARY.md`；objective仅创建该短报告和1 commit；唯一Chief verification为 `test -f reports/AUTO_DISPATCH_CANARY.md`；所有变更/付费/发布/权限facts=false，safety/baseline/workspace/acceptance facts=true。

先在outbox外校验JSON/schema/大小；再同目录临时文件写入、fsync并原子rename为`TASK-AUTO-DISPATCH-001.json`。rename后禁止手动调用importer、runner或Cursor，只观察。

在5分钟止损内记录自动状态链：ingress consumed/READY receipt → runner CLAIMED/RUNNING → official execution report → REVIEW receipt。要求print=1、Cursor单提交、Git scope/clean/single-commit通过、Chief命令exit0、exact import task branch、model内层输出未进日志/report。target main和baseline仍`140b993`，Owner main零变化，merge/promote=0。

## 任务3｜收尾运行态

确认auth.json文件/链接/异常类型=0、exact Key hit=0、两个stderr/halt=0、active lease=0、eligible READY=0。保留REVIEW任务、official report和原子文档证据，不标DONE、不合并。等待两个服务各再出现2个idle周期；ingress与R7 runner保持loaded/running。

## 规矩

任何第二次print、非白名单路径、Owner漂移、secret命中、REVIEW后继续动作立即停止；不重试、不清日志、不人工改状态。不得skip、`|| true`或伪造状态链。

## 完成条件

1. 单个原子任务文档无人干预自动到REVIEW，print=1，official report/receipt/task branch完整，两个服务回idle。
2. Owner/runtime/target main漂移=0，authJson/Key hit/active lease/READY=0，merge/promote/push=0，R1 rollback仍可用。

写脱敏 `automatic-dispatch-evidence.json` 并贴实际输出；只说完成不算。`BLOCKED.md`空也写“无”。
