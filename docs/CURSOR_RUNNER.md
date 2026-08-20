# Cursor Runner R1

R1 reuses the R0 injected-command adapter. The official Cursor CLI is started only by an
explicit local wrapper whose `cliPath` comes from a gitignored config file.

## Contract

- `CursorRunner` still requires `--executor-command`. There is no PATH lookup and no default binary.
- The wrapper reads R0 JSON from stdin, validates task/project/workspace/baseline/version/approval,
  and passes the payload as a single argv JSON prompt. Task text is never concatenated into a shell.
- Missing authentication, timeout, or a non-zero CLI exit fail closed. Suspected secrets are redacted.
- Success still stops at `REVIEW`. Julius remains isolated. One active execution per project.
- `cursor-daemon` claims at most one task per cycle and stays idle when the queue is empty.

## Local config

Copy `config/cursor-runner.example.json` to `config/cursor-runner.local.json` (gitignored).
Set `cliPath` to the absolute `cursor-agent` executable. Do not store API keys in that file.

```bash
PYTHONPATH=src python3 -m control_plane.main --config config/projects.cursor-r1.local.json cursor-run \
  --executor-id cursor-r1 \
  --executor-command /usr/bin/python3 scripts/cursor_cli_wrapper.py --runner-config /absolute/config/cursor-runner.local.json \
  --project control-panel
```

## Daemon

The user-level LaunchAgent template is `scripts/com.pojian.chief-cursor-runner.plist.example`.
It may be enabled only after the R1 reverse gates and the single real pilot have passed.
The plist must contain PYTHONPATH and explicit program arguments only — never credentials.

## Not authorized in R1

Julius, Director, KESU, knowledge-base writes, business database changes, push, merge, deploy,
and a second real Cursor `--print` invocation.
