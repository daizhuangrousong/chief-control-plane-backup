# PROGRESS · R2.1 Chief 任务文档入口补正 · Chief REVIEW

- 目标：按 `CHANGES_REQUESTED_R2` 补正。不启用 R2 常驻，真实 Cursor/飞书增量 0。停在 Chief REVIEW。
- 工作树：`/Users/pojian/repos/director-control-plane-r2-ingress` 分支 `chief-task-ingress-r2`
- 基线 HEAD was `68b58cb`；保留 R1 `b7e17bf` 与 R2 `68b58cb`，不改写历史。
- 阶段：**Chief REVIEW**

## 任务 0

- 测试基线 120 / 0 fail / 0 skip
- R1 READY=0；LaunchAgent pid=`9214` runs=2 持续 idle
- Cursor `--print` 累计=1；R2 增量=0

## 红 → 绿（五项阻断）

1. 冲突 REVIEW：不得改写既有 state/version；回执含 originalHash 与 attemptedHash
2. facts-only drift：完整 envelope hash 冲突，不覆盖原 sourceHash
3. 真实 `run_cursor_runner.py --inbox-dir`：fake READY → REVIEW 并写 inbox；重复启动只执行一次
4. workspace HEAD ≠ Dispatcher baseline → BLOCKED、0 calls
5. 缺配置 / outbox⊃inbox / 未知字段 fail-closed；损坏 sidecar fail-closed 且不改任务

## 测试

- 126 / 0 fail / 0 skip
- `git diff --check` 通过
- 临时 DB/fake executor；未写 R1 sqlite；未启用 R2 常驻

## 调用计数

- 真实 Cursor `--print` 累计：1；本任务增量：0
- 飞书：独立 BLOCKED
- R1 Runner：保持 idle
