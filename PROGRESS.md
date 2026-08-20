# PROGRESS · R2 Chief 任务文档入口 · Chief REVIEW

- 目标：R1 证据 closeout 后，在独立 R2 worktree 建立 Chief 任务文档入口。不得调用真实 Cursor，不启用 R2 常驻。停在 Chief REVIEW。
- Owner approval：`OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
- 阶段：**Chief REVIEW**。未 merge、未 push、未启用 R2 LaunchAgent、未再调用 Cursor。

## 两个 commit / 两个 worktree

- R1 closeout：`b7e17bf` Record R1.2 LaunchAgent idle evidence after Chief PASS.
  - 工作树 `/Users/pojian/repos/director-control-plane-r1-bootstrap` 分支 `cursor-runner-r1-bootstrap`，closeout 后 clean
- R2：`chief-task-ingress-r2` @ `/Users/pojian/repos/director-control-plane-r2-ingress`，基线同一 SHA `b7e17bf`

## 任务 0（closeout 时）

- 测试基线 110 / 0 fail / 0 skip
- READY=0；Cursor `--print` 累计=1
- LaunchAgent `gui/501/com.pojian.chief-cursor-runner` state=`running` pid=`9214` runs=2，持续 idle

## 红 → 绿

- 文件合同：symlink / 截断 JSON / 未知字段 / 超大文件 / 越界 workspace 先失败后进 BLOCKED 回执
- 缺 Owner approval 与同 id 改内容：0 executor calls
- 端到端 fake：outbox → DRAFT/policy → READY → 唯一 lease → REVIEW → inbox；重复投递幂等；reporter 不把 REVIEW 变 DONE

## 测试

- 120 / 0 fail / 0 skip（原 110 + 10）
- `git diff --check` 通过
- 测试只用临时目录/DB，未写入 R1 `var/cursor-r1.sqlite3`

## LaunchAgent / 调用计数（完成后复核）

- R1 仍 idle：pid=`9214` runs=2；日志持续 `idle: no eligible READY task`（至 2026-08-20 15:12:40）
- R1 READY=0
- 真实 Cursor `--print` 累计：1；本任务增量：0
- R2 常驻：未启用
- 飞书：独立 BLOCKED

## 端到端回执形状（测试）

- taskId / sourceHash / taskVersion / state / matchedRules / leaseId / observedAt / error
- 正向：READY 后 REVIEW，lease 非空
- 反向五类：BLOCKED 或非法输入回执，executor marker=0
