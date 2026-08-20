# CURSOR-RUNNER R1 EVIDENCE · 2026-08-20

Owner approval: `OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
Worktree: `/Users/pojian/repos/director-control-plane-r1-bootstrap`
Branch: `cursor-runner-r1-bootstrap`
R0 baseline: `fe5062fa75691ba366d209aac1f927f0e29ad643`
R1 commit: `549cce7ed04f6daff6a82f2d6782a1e4d338cb91`
Chief verdict on R1: `CHANGES_REQUESTED_R1`

## Task 0 (R1.1)

- HEAD=`549cce7ed04f6daff6a82f2d6782a1e4d338cb91`; worktree was clean
- Tests: 103 / 0 fail / 0 skip
- Real `--print` count before this fix: 0

## R1.1 code contract

- CLI `status`/`--print` env is an allowlist; canary `FEISHU_APP_SECRET` / token / unrelated keys do not enter the child
- `--executor-command` is a JSON argv array; plist `plutil -lint` OK; KeepAlive is `SuccessfulExit=false`
- Identical permanent rejections halt after 3 cycles, write a halt file, and a restart stays stopped

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

Count: **1** (authorized maximum).

- task: `TASK-R1-PILOT`
- lease: `6ac024e6-1ee4-4f7f-928c-a2d45d46b8af`
- state: `REVIEW` version 5
- artifact: `reports/CURSOR_RUNNER_R1_PILOT_2026-08-20.md`
- git: only that path was newly added versus the pre-call snapshot

## Feishu outbound

Independent BLOCKED. No test card. message id: none.

## LaunchAgent

Label: `com.pojian.chief-cursor-runner`
Log: `/Users/pojian/repos/director-control-plane-r1-bootstrap/var/logs/chief-cursor-runner.log`
Halt file: `/Users/pojian/repos/director-control-plane-r1-bootstrap/var/cursor-runner.halt.json`
Enabled only after the R1.1 commit if idle proof succeeds.

## Final tests

108 / 0 fail / 0 skip. `git diff --check` passed. `plutil -lint` passed.
