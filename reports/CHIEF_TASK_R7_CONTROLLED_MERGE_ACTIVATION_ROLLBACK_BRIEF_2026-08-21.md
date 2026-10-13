你是运维执行者，这是 R7 受控合并、激活和回滚演练的唯一任务来源；不写业务代码。中途没人可问，拿不准写入 activation evidence 后停。断线先读 evidence 接着做。目标是把已验收 R7 变成空队列常驻 Executor，并证明可恢复原 R1。冲突时：Owner 资产守恒 > 可回滚 > 空队列安全 > 激活速度。只有“只允许/不许”是硬边界。

## 我替领导拍的板

- 批准 main 本地 `ff-only` 到 `140b993`，不 push。
- 生产使用独立 clean runtime clone，不要求脏的主仓充当 runtime。
- 必须实际执行一次 R7→R1→R7 回滚演练；最终状态为 R7 idle。
- 自动文档 ingress 本轮保持关闭；任务数必须为 0，Cursor `--print=0`。

## 界限

只允许改变：`/Users/pojian/repos/director-control-plane` 的 main ref（仅 ff-only）；新建 `/Users/pojian/chief-runtime/director-control-plane-r7/`、`/Users/pojian/chief-state/control-plane-production/`；替换 `/Users/pojian/Library/LaunchAgents/com.pojian.chief-cursor-runner.plist`；通过 launchctl 切换该唯一 label。允许更新 R7 工作树 `PROGRESS.md/BLOCKED.md`，不提交。其他仓库、R1 worktree、Keychain 值、飞书进程、Julius/Director/Eval、remote 只读。禁止改 tracked 文件、commit、reset/clean/stash、push、任务注册/READY、模型调用、删除旧 R1 资产。

## 现状与任务 0

核对：main=`13127b9`，R7=`140b993`，parent 恰为 main，tree=`21d835b…`; r7k9 REVIEW，178/0/0。当前 LaunchAgent PID=26003，路径全指向 `director-control-plane-r1-bootstrap`，plist SHA、完整 argv、日志大小先记录。对主仓全部 tracked 修改和 untracked 文件逐路径记录类型+SHA256；不得记录文件内容。确认 Keychain service/account 存在但不带 `-w`。任一不符即停。

## 任务 1｜保全后 fast-forward

先将当前 R1 plist原字节备份到 production state 的 rollback 目录并记录 SHA。执行 main `merge --ff-only 140b993`；不得 checkout/reset/stash/clean。合并后要求 main=`140b993`、相对旧 main 1 commit，开工时所有 tracked 脏文件内容 SHA 和 untracked 路径/SHA 完全不变。

在 main 跑：
`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`
`git diff --check 13127b9..140b993`
要求≥178、failure/error/skip=0。

## 任务 2｜建立干净生产运行时

从 main 建独立 clone `/Users/pojian/chief-runtime/director-control-plane-r7/`，HEAD=`140b993`、status clean、tree 一致。生产 state 内创建无凭证的 projects、runner、lifecycle 配置：runtimeRoot=该 clean clone；projectRoot=主仓；poolRoot=主仓内 gitignored 独立 clone 池；state/report/DB/log 全在 production state，路径绝对且互不违规。runner CLI 用已验收绝对路径；Key 仅通过 plist 中 service/account 名称让可信父进程读取，plist/config 不含 Key/token。

先以前台 `max-cycles=1` 空队列预检：exit=0、idle、task/lease/print=0、无 halt/error、authJson=0。失败不切 LaunchAgent。

## 任务 3｜激活、实际回滚、再激活

生成 R7 plist：WorkingDirectory/PYTHONPATH/scripts 指向 clean runtime；参数必须含 lifecycle config、Keychain service/account、独立 production logs/halt/inbox；KeepAlive=`SuccessfulExit=false`。静态扫描无凭证。

1. bootout 原 R1，原子替换 plist，bootstrap R7；等待至少2个 idle 周期。证明新 PID/argv 指向 R7，task/lease/print=0，无错误。
2. bootout R7，原字节恢复 R1 plist并 bootstrap；证明 SHA 等于开工 R1、PID/argv 指回 R1、仍 idle，无错误。
3. 再 bootout R1，恢复已验证 R7 plist并 bootstrap；最终等待2个 idle 周期，证明 R7 running/idle。

任一步失败立即恢复 R1 备份；若恢复失败，停止且不使用更强删除/重置手段。

## 规矩

不启用 `com.pojian.chief-task-ingress`，不复用 r7k9 DB，不搬旧任务，不删除 halt/日志掩盖错误。任何非空任务、Cursor 调用、凭证命中、主仓资产漂移都算失败并回滚 R1。不得 skip、`|| true` 或伪造 idle。

## 完成条件

1. main=`140b993`，clean runtime 同 commit，最终 LaunchAgent 为 R7 running 且连续2周期 idle；实际 R1 rollback 和二次 R7 激活均有证据。
2. Owner 资产 SHA 漂移=0、task/lease/print=0、authJson/secret hit=0、R1 rollback plist 可用、push=0。

将脱敏结果写入 production state `activation-evidence.json` 并贴实际输出；只说完成不算。R7 `BLOCKED.md` 空也写“无”。
