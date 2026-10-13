你是运维执行者，这是 R7 激活续跑的唯一任务来源；不写代码、不运行 Cursor。中途没人可问，拿不准写 activation evidence 后停。上一轮 main 已安全合并，预检因 Owner 主仓非 clean 正确停止；本轮以第二个 clean 集成镜像作为 Executor target，Owner 主仓永不进入沙盒写边界。冲突时：Owner 资产守恒 > R6 clean 契约 > 可回滚 > 激活速度。只有“只允许/不许”是硬边界。

## 我替领导拍的板

- 生产 runtime 继续用 `/Users/pojian/chief-runtime/director-control-plane-r7`。
- 新建 `/Users/pojian/chief-runtime/director-control-plane-target` 作为 clean target；任务只在这里到 REVIEW。
- Owner main 保持 `140b993` 和现有 105 项资产；后续 reviewed commit 由独立 merger 保全导入，不让 Executor 直写主仓。
- 最终仍须实际完成 R7→R1→R7 回滚演练；ingress 关闭，print=0。

## 界限

只允许新建 clean target 与 `/Users/pojian/chief-state/control-plane-production/live-v2/`；替换同一 LaunchAgent plist并用 launchctl切换；更新 `/Users/pojian/chief-state/control-plane-production/activation-evidence-v2.json` 和 R7 `PROGRESS.md/BLOCKED.md`。Owner main、runtime clone、R1 worktree、Keychain 值、飞书、四项目、remote 全部只读。禁止 commit/merge/reset/clean/stash/push、任务注册/READY、模型调用、删除旧 state/日志/备份。

## 现状与任务 0

核对 main/runtime=`140b993`、runtime clean；Owner main 2 tracked dirty+103 untracked 与上一轮 SHA 守恒；当前 LaunchAgent 仍 R1 PID=26003、plist SHA=`1f5270…a8c1a`；rollback plist同 SHA；上轮 precheck print=0/authJson=0。若 PID自然变化可接受，但 argv/plist必须仍为R1。写≤10行回执；不符即停。

## 任务 1｜建立 clean target 与全新 live state

从 main 的 committed `140b993` 建独立 clone `/Users/pojian/chief-runtime/director-control-plane-target`；要求 HEAD/tree 与 runtime/main commit tree相同、status clean、git-common-dir与runtime/main均不同。确认 target 的 `var/` 被 ignore。

在 `live-v2` 创建无凭证 projects/runner/lifecycle：

- runtimeRoot=clean runtime；projectRoot=clean target；poolRoot=target内 `var/task-worktrees`；
- DB/state/report/inbox/receipt/occupancy/log/halt全在 live-v2；
- 注册 project baseline=`140b993`，但 task/lease 数量均0；
- CLI绝对路径为已验收版本，Key只通过 service/account 名称由可信父进程读取。

静态验证所有绝对路径、互不重叠规则、plist/config 不含 Key/token。

## 任务 2｜空队列前台预检

从 clean runtime 用新配置运行 `max-cycles=1`。要求 exit=0，日志只有 idle；project/runtime保持clean；task=0、lease=0、print=0、authJson=0、halt=0、stderr=0。故意将 projectRoot 临时指回 Owner main，必须复现 `project root must be a clean git checkout` 且 executor/print=0；恢复新配置再绿。失败不切 LaunchAgent。

## 任务 3｜R7→R1→R7

生成 R7 plist：WorkingDirectory/PYTHONPATH/scripts 指向 clean runtime；参数含 live-v2 projects、runner、lifecycle、logs/halt/inbox及Keychain service/account；KeepAlive=`SuccessfulExit=false`，无凭证。

1. bootout R1，原子换 R7 plist并 bootstrap；等至少2个 idle周期，证明新 PID/argv、task/lease/print=0、无错误。
2. bootout R7，原字节恢复 rollback R1 plist并 bootstrap；证明 plist SHA/argv回R1且 idle。
3. bootout R1，恢复验证过的R7 plist并 bootstrap；最终再等2个 idle周期，证明R7 running/idle。

任一步失败立即恢复R1；恢复失败即停，不扩大删除或权限。

## 规矩

不启用 task ingress，不复用旧 DB，不搬旧任务，不删除 halt/日志掩盖错误。任何非空任务、Cursor调用、凭证命中、Owner资产漂移均失败并回滚R1。不得 `|| true` 或伪造 idle。

## 完成条件

1. final LaunchAgent=R7，clean runtime+clean target均 `140b993`，连续2周期 idle；实际R1回滚和R7再激活有证据。
2. Owner资产漂移=0，task/lease/print/authJson/secret hit=0，R1 rollback可用，ingress/push=0。

写入脱敏 `activation-evidence-v2.json` 并贴实际输出；只说完成不算。`BLOCKED.md` 空也写“无”。
