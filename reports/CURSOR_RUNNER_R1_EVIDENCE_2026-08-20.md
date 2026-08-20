# CURSOR-RUNNER R1 EVIDENCE · 2026-08-20

Owner approval: `OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
Worktree: `/Users/pojian/repos/director-control-plane-r1-bootstrap`
Branch: `cursor-runner-r1-bootstrap`
R0 baseline: `fe5062fa75691ba366d209aac1f927f0e29ad643`
R1 commit: `549cce7ed04f6daff6a82f2d6782a1e4d338cb91`
R1.1 commit: `86ad00a9f0d326ab91369e2f1fc82cde8ff4444b`
R1.2 commit: `659422e`
Chief verdict on R1: `CHANGES_REQUESTED_R1`
Waiting: Chief REVIEW of R1.2

## Task 0 (R1.2)

- Pre-fix HEAD=`86ad00a9f0d326ab91369e2f1fc82cde8ff4444b`; worktree was clean
- Tests before fix: 108 / 0 fail / 0 skip
- Crash log retained: `var/logs/chief-cursor-runner.launchd.err.log`
  - mtime=`2026-08-20T14:09:29+0800` size=568
  - sha256=`47fab84c69ad466d61fb54246be4cd91bb7b220887512944bdfc10df1bbbb767`
  - root cause: `parse_runner_argv(None)` → `list(None)` TypeError
- READY count: 0; `TASK-R1-PILOT` = REVIEW v5
- LaunchAgent was not running and was disabled

## R1.2 code contract

- `parse_runner_argv(None)` uses argparse process args (`parse_args(None)`), not `list(None)`
- Explicit argv lists still parse as before
- Red tests: `test_parse_runner_argv_none_reads_process_args` and real script entry `test_real_script_entry_with_none_argv_idles_empty_queue` reproduced the TypeError, then went green
- Plist-equivalent `--max-cycles 1` on an empty queue exits 0, writes idle, executor marker = 0

## Reverse gates (from R1, executor never started)

```json
{"status": "rejected", "error": "workspace is outside the authorized project root: /private/tmp"}
```

```json
{"status": "rejected", "error": "baseline drift: workspace HEAD fe5062fa75691ba366d209aac1f927f0e29ad643 != registered deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"}
```

```json
{"status": "rejected", "error": "ownerApprovalRef is required for database_write tasks"}
```

## Real Cursor `--print` call

Count: **1** (authorized maximum). This task increment: **0**.

- task: `TASK-R1-PILOT`
- lease: `6ac024e6-1ee4-4f7f-928c-a2d45d46b8af`
- state: `REVIEW` version 5
- artifact: `reports/CURSOR_RUNNER_R1_PILOT_2026-08-20.md`

## Feishu outbound

Independent BLOCKED. No test card. message id: none.

## LaunchAgent idle proof (R1.2)

Label: `com.pojian.chief-cursor-runner`
Domain: `gui/501`
Plist: `/Users/pojian/Library/LaunchAgents/com.pojian.chief-cursor-runner.plist`
Log: `/Users/pojian/repos/director-control-plane-r1-bootstrap/var/logs/chief-cursor-runner.log`
Halt file: `/Users/pojian/repos/director-control-plane-r1-bootstrap/var/cursor-runner.halt.json` (absent)
Stderr: `/Users/pojian/repos/director-control-plane-r1-bootstrap/var/logs/chief-cursor-runner.launchd.err.log` (old TypeError only; size still 568)

| when | event |
| --- | --- |
| 2026-08-20T14:31:52+0800 | `launchctl enable` then `bootstrap`; exit 0 |
| 2026-08-20T14:31:56+0800 | `launchctl print`: state=`running` pid=`9004` runs=1 |
| 2026-08-20 14:31:53,164 | idle |
| 2026-08-20 14:32:23,267 | idle |
| 2026-08-20 14:32:53,361 | idle |
| 2026-08-20T14:33:00+0800 | `launchctl kickstart -k`; exit 0 |
| 2026-08-20T14:33:04+0800 | `launchctl print`: state=`running` pid=`9214` runs=2 |
| 2026-08-20 14:33:01,059 | idle after reload |
| 2026-08-20 14:33:31,172 | idle second cycle after reload |

Log contains only `idle: no eligible READY task`. No `rejected`, `halted`, or new traceback. No `cursor-agent` process during observation.

## Final tests

110 / 0 fail / 0 skip. `git diff --check` passed. `plutil -lint` passed on the example plist and the user LaunchAgent.

## git

```
659422e Fix Cursor runner argv=None so LaunchAgent can idle.
 PROGRESS.md                                 | 21 ++++---
 src/control_plane/services/cursor_launch.py |  4 +-
 tests/test_cursor_cli_wrapper.py            | 85 +++++++++++++++++++++++++++++
 3 files changed, 97 insertions(+), 13 deletions(-)
```

Activation evidence in this file / `PROGRESS.md` / `BLOCKED.md` is after that commit and is not a second commit.
