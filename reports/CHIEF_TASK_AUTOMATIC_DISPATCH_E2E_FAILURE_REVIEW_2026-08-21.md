# Chief Review · 自动派发最终 E2E

结论：`FAIL / SHORT-PATH RECOVERY REQUIRED`。

- ingress 与 R7 runner 均已上线并保持运行；单个原子任务已自动入队并启动 Executor。
- `TASK-AUTO-DISPATCH-001` 只调用一次 Cursor `--print`，随后因 `mkdir /tmp/.cursor/...` 被 R6 沙盒拒绝，状态为 `FAILED`，没有 official report、task branch 或 REVIEW。
- Owner main、runtime、target main 均保持 `140b993`；active lease/READY/auth.json/Key hit/merge/promote/push 均为 0；两个 halt 与 stderr 均为 0。
- 失败生产工作路径长 99 字符；已通过的 r7k9 路径长 49 字符。队列历史已明确记录“生产 pool 必须使用短路径”，但最终生产配置仍采用长 target/pool。这是 Chief 配置遗漏。
- 不允许把 `/tmp/.cursor` 加入写白名单，也不重试旧任务。恢复方案只创建短 clean target `/Users/pojian/chief-runtime/cpt`、短 pool `.../var/w` 与全新 live-v4，使用新任务 `TASK-A2` 做一次 canary。

原始证据：`/Users/pojian/chief-state/control-plane-production/live-v3/automatic-dispatch-evidence.json`。
