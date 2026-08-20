# PROGRESS · CURSOR-RUNNER R1.2 ACTIVATION FIX

- 目标：修真实入口 `parse_runner_argv(None)`，完成 LaunchAgent idle 激活证明。Cursor `--print` 本任务增量必须为 0。停在 Chief REVIEW。
- Owner approval：`OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
- 工作树：`/Users/pojian/repos/director-control-plane-r1-bootstrap` 分支 `cursor-runner-r1-bootstrap`
- 任务 0：HEAD was `86ad00a9f0d326ab91369e2f1fc82cde8ff4444b`；crash log `var/logs/chief-cursor-runner.launchd.err.log` mtime=`2026-08-20T14:09:29+0800` size=568；根因 `parse_runner_argv(None)` → `list(None)` TypeError。日志未删。
- 红测：`test_parse_runner_argv_none_reads_process_args` 与真实脚本入口 `test_real_script_entry_with_none_argv_idles_empty_queue` 均复现 TypeError / exit 1。
- 修复：`parse_args(None)` 读取进程参数；显式 argv 测试保持不变。
- 测试：110 / 0 fail / 0 skip；`git diff --check` 通过；`plutil -lint` 通过。
- 真实 Cursor `--print` 累计：1；本任务增量：0
- 飞书：独立 BLOCKED，本任务不处理
- 阶段：代码已绿，提交后做一次 LaunchAgent idle 激活
- 最大风险：激活时再次调用 Cursor，或反复 bootstrap LaunchAgent
