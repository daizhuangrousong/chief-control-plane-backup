# CHIEF TASK PIPELINE R3 ROLLBACK EVIDENCE · 2026-08-20

Owner approval: `OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
Chief verdict: `CHANGES_REQUESTED_R3_ROLLBACK`
Worktree: `/Users/pojian/repos/director-control-plane-r2-ingress`
Branch: `chief-task-ingress-r2`
Waiting: Chief REVIEW. No R3 re-enable. No code change. No baseline update. No Cursor call.

## Task 0 (before rollback)

| item | value |
| --- | --- |
| HEAD | `39b2e206156e94750fd6d8119c1c995594207438` |
| R3 baseline | `f56f896d6ebdd030343a74f1a7651d3a6840abef` (unchanged; not updated) |
| READY | 0 (R3 and R1) |
| Cursor `--print` cumulative | **2** |
| Feishu | unset / 0 cards |

| label | pid | runs | forks | state |
| --- | --- | --- | --- | --- |
| `gui/501/com.pojian.chief-task-ingress` | 22766 | 1 | 468 | running |
| `gui/501/com.pojian.chief-cursor-runner` (R3) | 22924 | 1 | 3 | running |

Backup plist `var/rollback/com.pojian.chief-cursor-runner.plist.r1` sha256=`1f5270208c68c41b84dbae11f24bbf955067e7ae4fd432a9cbca1b05485a8c1a` **matched** the recorded hash. No `--inbox-dir`. No R2 worktree path.

Receipts before rollback (left intact):

| file | state | originalHash | mtime local | sha256 |
| --- | --- | --- | --- | --- |
| inbox `TASK-R3-PILOT.json` | REVIEW v5 | `347e343b…86408548` | 2026-08-20T15:51:55+0800 | `111aec61fc0257c0b80353db716ad1845db251586c2c4d3707eb6cc0a9f4cbee` |
| inbox `TASK-R3-REVERSE.json` | BLOCKED v2 | `6a8e2eba…232f0aa4` | 2026-08-20T15:49:53+0800 | `d03ae70663b90bd47e25f760278b94b9d27bd70ef988fde11a2a218ac4be4a67` |

Importer log still showed `cycle ingested=2 published=0` every 5s (unsustainable). Last ingress line before stop: `2026-08-20 16:01:51,379`.

## Rollback actions (each once)

1. `launchctl bootout gui/501/com.pojian.chief-task-ingress` — service gone; pid 22766 exited.
2. `launchctl bootout gui/501/com.pojian.chief-cursor-runner` — service gone; pid 22924 exited.
3. Atomic restore of the backup onto `~/Library/LaunchAgents/com.pojian.chief-cursor-runner.plist`; `plutil -lint` OK.
4. Restored live plist sha256=`1f5270208c68c41b84dbae11f24bbf955067e7ae4fd432a9cbca1b05485a8c1a` **byte-identical** to backup. No `--inbox-dir`. Paths are only `director-control-plane-r1-bootstrap`.
5. `launchctl bootstrap` once. R1 runner: state=`running` pid=`26003` runs=1 forks=0.
6. Live ingress LaunchAgent file was moved to gitignored `var/rollback/` so login will not reload R3 importer. R3 DB/logs/outbox/inbox/plist backup were not deleted or truncated.

## R1 idle proof

Log `/Users/pojian/repos/director-control-plane-r1-bootstrap/var/logs/chief-cursor-runner.log`

| when | event |
| --- | --- |
| 2026-08-20 16:01:56,275 | idle after restore |
| 2026-08-20 16:02:26,378 | idle cycle 2 |
| 2026-08-20 16:02:56,459 | idle cycle 3 |
| 2026-08-20T16:03:xx | `launchctl kickstart` once; pid stayed `26003` runs=1 |
| 2026-08-20 16:03:26,543 | idle after reload |
| 2026-08-20 16:03:56,645 | idle |

New log lines are only `idle: no eligible READY task`. No `rejected`, `halted`, `starting injected`, or `--print`. Launchd stderr still size **568** (old R1.1 TypeError; not appended). Halt file absent. This-task Cursor increment **0**. Feishu increment **0**.

## After checks

- `com.pojian.chief-task-ingress` not found in `gui/501`
- R3 outbox/inbox hashes and `mtime_ns` unchanged versus pre-bootout snapshot
- R3 sqlite: `TASK-R3-PILOT` REVIEW v5; `TASK-R3-REVERSE` BLOCKED v2; READY=0
- R3 baseline still `f56f896d6ebdd030343a74f1a7651d3a6840abef`
- HEAD before this evidence commit: `39b2e206156e94750fd6d8119c1c995594207438`

## Stop

Chief REVIEW of R3 rollback. Do not re-enable R3. Do not merge, push, or deploy.
