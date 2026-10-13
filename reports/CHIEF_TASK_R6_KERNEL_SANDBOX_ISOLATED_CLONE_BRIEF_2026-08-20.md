# R6 · Executor 内核写隔离与独立 Git 副本 · Cursor Executor 任务书

你是执行者，本文件是唯一任务来源；拿不准写 `BLOCKED.md`，继续不受影响项。断线先读 `PROGRESS.md`。这次把 Tier 1 的“同用户防误操作”升级为内核强制写隔离：任务进程只能改自己的独立 Git 副本，不能改 Chief 状态、可信证据、runtime 或项目 main。让步顺序：真实拒写 > 可恢复 Git 交付 > 兼容性 > 速度。“只允许/禁止”违反即失败。

## 我替领导拍的板

- 采用 macOS `/usr/bin/sandbox-exec`；不可用或拒绝加载就 fail closed，不退回路径检查。
- 任务空间用 `git clone --no-hardlinks` 的独立副本，不再把共享 `.git` worktree 暴露给不可信 Executor。
- 本轮只跑 fake benign/adversarial canary，不启动真实 Cursor、不连接 Julius/Director/Eval 生产任务。

## 界限

从 `b9c344a1ad400fd502bffcb7ef05c8ee00590680` 新建 `/Users/pojian/repos/director-control-plane-r6-permission` 与分支 `chief-task-permission-r6`。只允许改 `src/control_plane/services/{executor_sandbox.py,task_clone.py,cursor_runner.py,task_worktree.py,execution_contract.py,task_merger.py,__init__.py}`、`tests/{test_executor_sandbox.py,test_execution_lifecycle.py}`、`README.md`。其余只读。禁止改既有测试断言、DB schema、任务审批规则、Eval/Julius/Director、LaunchAgent、密钥、remote、push、merge、部署。

## 现状与任务 0

证明 R4 runtime=`b9c344a` clean、149/0/0，R6 路径/分支不存在。实机预检必须证明：同一 profile 允许沙盒内独立 clone 完成一次 commit；对 clone 外 sentinel 写入返回非零且文件不存在。当前已知 macOS=`26.5.1`、`sandbox-exec` 存在；若实测不符即停。核验后在 `PROGRESS.md` 写目标/顺序/最大风险≤10行。

## 任务 1｜独立任务副本

实现任务 clone pool：可信父进程从 registered baseline 创建 `--no-hardlinks` 独立 clone，移除 remote，common-dir 必须位于 clone 内且不同于 runtime/项目；禁止 symlink、复用旧目录和 shared object store。Executor 成功后由可信父进程验证单 commit/scope/diff，再把 exact commit 导入目标 `task/<id>` ref；Executor 本身不能写目标 `.git`。

## 任务 2｜内核写沙盒

实现 fail-closed profile/launcher：默认保留系统读取与进程运行，但拒绝全部 `file-write*`；只允许任务 clone 与 `/dev/null`，把 HOME/TMPDIR/XDG 定向到 clone 内，并沿用环境变量 allowlist。profile 由可信父进程生成在 stateRoot，Executor 不可修改。沙盒启动失败、路径重叠、profile 越界或平台不支持均不得调用 Executor。

## 任务 3｜真实攻击 Canary

不得 mock `sandbox-exec`。恶意子进程及其 child 必须实际尝试写 runtime、stateRoot decision/report、目标 main 文件、目标 `.git/refs/heads/main`，并经 clone 内 symlink 再逃逸；每项都要非零、sentinel 不存在、宿主 HEAD/porcelain/关键 SHA 不变。正向 canary 必须能在 clone 内写文件并 commit，可信父进程导入 exact commit，生命周期到 REVIEW；不得 merge/promote。再证明 state/report 只能由父进程落盘。

## 任务 4｜证据与回归

新增针对 fail-open、shared objects、嵌套/符号链接、子进程继承、环境泄密、宿主 ref 写入、benign commit/import 的测试；测试数≥149、fail=0、skip=0。记录 profile、独立 common-dir/inode 证据、每个 deny errno、父进程导入 ref、REVIEW 状态和回滚计划。

## 规矩

不得 skip/todo、放宽断言、mock 权限失败、只检查路径却不实际写、chmod 假隔离、`|| true`。同一核心 canary 连败 2 次即停并交根因；不创建 R6.1。

## 完成条件

1. 真实恶意进程对 5 类保护目标全部被内核拒写且宿主零变化；benign 任务只在独立 clone 成功，可信父进程导入后停 REVIEW。
2. R4 原 worktree 保持 `b9c344a` clean；R6 单 commit、全测≥149/0/0；真实 Cursor、生产接入、merge、promotion、push、部署均为0。必须贴实际输出，只说完成不算。
