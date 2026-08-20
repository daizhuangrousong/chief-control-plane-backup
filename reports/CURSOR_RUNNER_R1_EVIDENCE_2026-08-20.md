# CURSOR-RUNNER R1 EVIDENCE · 2026-08-20

Owner approval: `OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
Worktree: `/Users/pojian/repos/director-control-plane-r1-bootstrap`
Branch: `cursor-runner-r1-bootstrap`
R0 baseline: `fe5062fa75691ba366d209aac1f927f0e29ad643`

## Task 0

- Main tree HEAD matched R0. Dirty Chief files were left untouched.
- Tests: 91 / 0 fail / 0 skip
- `agent` / `cursor-agent` were missing; official CLI `2026.08.11-e8db854` was installed to `~/.local/bin/agent`
- Headless invocation: `agent --print --force --trust --sandbox enabled --output-format json --workspace <root> <prompt>`
- `agent status --format json` → `isAuthenticated=false`; `CURSOR_API_KEY` unset
- No cursor-runner LaunchAgent was present

## Reverse gates (executor never started)

Fake executor marker stayed absent.

```json
{"status": "rejected", "error": "workspace is outside the authorized project root: /private/tmp"}
```

```json
{"status": "rejected", "error": "baseline drift: workspace HEAD fe5062fa75691ba366d209aac1f927f0e29ad643 != registered deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"}
```

```json
{"status": "rejected", "error": "ownerApprovalRef is required for database_write tasks"}
```

After those three tasks were moved to BLOCKED, `cursor-daemon --max-cycles 1` returned idle and still did not create the marker.

## Real Cursor `--print` call

Count: **0**. See `BLOCKED.md`. The wrapper fail-closes on missing authentication and does not start `--print`.

## Feishu outbound

Independent BLOCKED. Private `config/feishu-control.local.json` exists; `FEISHU_APP_ID` and `FEISHU_APP_SECRET` are unset. No test card was sent.

## LaunchAgent

Not enabled. Label would be `com.pojian.chief-cursor-runner`. Logs would be `/Users/pojian/repos/director-control-plane-r1-bootstrap/var/logs/chief-cursor-runner.log`.

## Final tests

103 / 0 fail / 0 skip. `git diff --check` passed.
