你是运维执行者，这是 R7 激活的最终续跑，也是唯一任务来源；不写代码、不运行 Cursor。中途没人可问，拿不准写 evidence 后停。前次只因把 Chief 在开工前新增的正式报告/队列误判成执行期漂移而停止；这些文件现已属于合法基线。目标是从开工瞬间重新冻结当前 Owner 主仓，此后零漂移地完成 clean target 与 R7→R1→R7。冲突时：Owner 资产守恒 > R6 clean 契约 > 可回滚 > 速度。只有“只允许/不许”是硬边界。

## 我替领导拍的板

- 禁止再与旧 `activation-evidence*.json` 的文件数或 SHA 比较；它们只证明历史，不定义本轮基线。
- 本轮任务启动后立即采集 fresh snapshot；该瞬间已有的全部 Chief/Owner 文件均合法，此后才冻结。
- runtime=`/Users/pojian/chief-runtime/director-control-plane-r7`；新 clean target=`/Users/pojian/chief-runtime/director-control-plane-target`。
- 自动任务只在 clean target 到 REVIEW；Owner main 以后由独立 merger 保全导入。
- 最终必须是 R7 idle；ingress关闭，print=0。

## 界限

只允许新建 clean target 和 `/Users/pojian/chief-state/control-plane-production/live-v3/`；替换同一 LaunchAgent plist并用 launchctl切换；写 `/Users/pojian/chief-state/control-plane-production/activation-evidence-v3.json`；更新 R7 `PROGRESS.md/BLOCKED.md` 不提交。Owner main、runtime、R1 worktree、Keychain值、飞书、四项目、remote只读。禁止 commit/merge/reset/clean/stash/push、任务注册/READY、模型调用、删除旧state/日志/备份。

## 现状与任务 0｜重新冻结现在

只核对不变事实：main/runtime=`140b993`且runtime clean；当前 LaunchAgent plist/argv仍指R1；rollback plist SHA匹配当前R1；历史任务/lease/print=0。不要把旧资产总数当判据。

然后现场重新枚举 Owner main：每个 tracked dirty 与每个 untracked 文件记录相对路径、类型、SHA256，不记录内容；目录项必须展开到文件。将此 fresh snapshot 写入 v3 evidence，完成后立即再扫一次必须相等。此后所有守恒只与该 fresh snapshot 比较。写≤10行回执；不符即停。

## 任务 1｜clean target 与 live-v3

从 main committed `140b993` 建独立 clean target；若目标目录已存在但不是本轮创建且非预期空状态，停止，不覆盖。要求 target/runtime/main commit tree相同、target status clean、三者git-common-dir不同，target `var/` ignored。

在 live-v3 创建无凭证 projects/runner/lifecycle：runtimeRoot=clean runtime；projectRoot=clean target；poolRoot=target内 `var/task-worktrees`；DB/state/report/inbox/receipt/occupancy/log/halt全在live-v3。注册baseline=`140b993`，task/lease=0。CLI使用已验收绝对路径；Key只通过service/account名称由可信父进程读取。配置/plist不得含Key/token。

## 任务 2｜红→绿空队列预检

先用临时配置将projectRoot指Owner main，运行max-cycles=1，必须以 `project root must be a clean git checkout` 拒绝，executor/print=0。再用live-v3正式配置运行max-cycles=1，必须exit=0且只idle；runtime/target clean，task/lease/print/authJson/halt=0，stderr=0。失败不切LaunchAgent。

## 任务 3｜实际R7→R1→R7

生成R7 plist：WorkingDirectory/PYTHONPATH/scripts指clean runtime；参数含live-v3所有配置、logs/halt/inbox、Keychain service/account；KeepAlive=`SuccessfulExit=false`，静态扫描无凭证。

1. bootout R1，原子换R7并bootstrap；等至少2个idle周期，证明R7 PID/argv、零task/lease/print/error。
2. bootout R7，原字节恢复R1 backup并bootstrap；证明plist SHA/argv回R1且idle。
3. bootout R1，再恢复已验证R7并bootstrap；最终等2个idle周期，证明R7 running/idle。

任一步失败立即恢复R1；恢复失败即停，不扩大删除/权限。

## 规矩

执行期间每个阶段后将Owner main与fresh snapshot比较，必须零新增/删除/SHA变化。不启用ingress、不复用旧DB、不搬旧任务、不清日志掩盖错误。任何Cursor调用、凭证命中或资产漂移均回滚R1。不得 `|| true`。

## 完成条件

1. 最终LaunchAgent=R7；runtime+target=`140b993` clean；实际回滚R1并再次激活R7，连续2周期idle。
2. 相对fresh snapshot资产漂移=0；task/lease/print/authJson/secret hit=0；R1 backup可用；ingress/push=0。

写脱敏 v3 evidence并贴实际输出；只说完成不算。`BLOCKED.md` 空也写“无”。
