# CHIEF TASK PIPELINE R3 EVIDENCE · 2026-08-20

Owner approval: `OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
Worktree: `/Users/pojian/repos/director-control-plane-r2-ingress`
Branch: `chief-task-ingress-r2`
R2.1 HEAD before this task: `c9570830590e33da18d2de4aa590b9420ba29a7b`
R3 code commit: `f56f896d6ebdd030343a74f1a7651d3a6840abef`
Waiting: Chief REVIEW. Do not expand projects.

## Task 0

- Pre-activation HEAD=`c957083`; tests 126 / 0 fail / 0 skip; worktree clean
- R1 label=`gui/501/com.pojian.chief-cursor-runner` pid=`9214` runs=2 state=`running` idle; READY=0
- Real Cursor `--print` cumulative before this task: **1**
- R1 plist sha256=`1f5270208c68c41b84dbae11f24bbf955067e7ae4fd432a9cbca1b05485a8c1a`
- Rollback copy: `var/rollback/com.pojian.chief-cursor-runner.plist.r1` (no secrets)
- CLI authenticated; official binary `2026.08.11-e8db854`

Rollback (no secrets in plist):

```
launchctl bootout gui/$(id -u)/com.pojian.chief-task-ingress
launchctl bootout gui/$(id -u)/com.pojian.chief-cursor-runner
cp var/rollback/com.pojian.chief-cursor-runner.plist.r1 ~/Library/LaunchAgents/com.pojian.chief-cursor-runner.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pojian.chief-cursor-runner.plist
```

## Tests before service cutover

131 / 0 fail / 0 skip. `git diff --check` passed. Both example plists `plutil -lint` OK.

- Long fake executor: inbox observed `RUNNING` then `REVIEW`
- Halt published a final READY receipt; task version unchanged; executor marker 0
- Empty queue / leftover outbox did not rewrite unrelated inbox files

## LaunchAgent cutover

Isolated R3 sqlite `var/cursor-r3.sqlite3`. Baseline `f56f896d6ebdd030343a74f1a7651d3a6840abef`. Executor `cursor-r1` / `control-panel` / max-risk `low`.

| label | pid | runs | state after 30s |
| --- | --- | --- | --- |
| `gui/501/com.pojian.chief-task-ingress` | 22766 | 1 | running, idle every 5s |
| `gui/501/com.pojian.chief-cursor-runner` | 22924 | 1 | running, idle every 30s |

Kickstart once each: both remained running and idle. Launchd stderr empty. No `rejected`, `halted`, traceback, or Cursor `--print` during the idle window. Activation failures: **0**. R1 rollback copy left untouched.

Live R3 runner plist sha256=`5ae68b2d9a628887fb4ebff7095164217678869a9df1d33b2ca320d2c54a9c41`

## Reverse gate

Envelope `TASK-R3-REVERSE` (`database_write`, no `ownerApprovalRef`) ingested automatically.

- state `BLOCKED` version 2
- matchedRules `block.owner_approval_missing`
- leaseId null
- Cursor calls **0**
- runner continued `idle: no eligible READY task`
- artifact `reports/CHIEF_PIPELINE_R3_REVERSE_SHOULD_NOT_EXIST.md` absent

## Real Cursor `--print`

This task increment: **1**. Cumulative: **2**. No retry.

- task: `TASK-R3-PILOT`
- lease: `12b65b8e-f0a2-4593-8f9d-f782f686b7fe`
- states observed: READY → RUNNING → REVIEW
- taskVersion: 5
- originalHash = sourceHash = `347e343bc085f19f599980134e8dd1cd49bb60a057462b230c00a07386408548`
- matchedRules: `auto.low_risk_all_clear`
- log: `starting injected executor for TASK-R3-PILOT` then `completed TASK-R3-PILOT into REVIEW`
- artifact: `reports/CHIEF_PIPELINE_R3_PILOT_2026-08-20.md` is the only new git path versus HEAD
- runner returned to idle at `2026-08-20 15:52:25,840`

No register / decide / cursor-run CLI was used for the pilot path.

## Feishu outbound

Independent BLOCKED. `FEISHU_APP_ID` / `FEISHU_APP_SECRET` unset. No cards.

## Stop

Chief REVIEW of R3 activation. Do not connect Julius, Director, or Eval. Do not merge, push, or deploy.
