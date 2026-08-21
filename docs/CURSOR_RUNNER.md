# Cursor Runner

R1 reuses the R0 injected-command adapter. The official Cursor CLI is started only by an
explicit local wrapper whose `cliPath` comes from a gitignored config file.

## Contract

- `CursorRunner` still requires `--executor-command` as a **JSON array of argv**. There is no
  PATH lookup, no default binary, and wrapper flags cannot be parsed as daemon flags.
- The production entry `scripts/run_cursor_runner.py` requires `--lifecycle-config`. It loads
  absolute runtime/project/pool/state/report roots, constructs `TaskWorktreePool`, and injects
  the pool plus execution report directory. Missing config, overlapping roots, a mismatched
  project root, or unavailable `/usr/bin/sandbox-exec` fail before claim or Executor. There is
  no unsandboxed resident switch. `--cursor-keychain-service` and `--cursor-keychain-account`
  are required; the parent loads the key from `/usr/bin/security` into child `CURSOR_API_KEY`
  only and never writes it to argv, plist, JSON, or logs.
- The wrapper reads R0 JSON from stdin, requires `verification` 1:1 with `acceptance`, and
  tells Cursor to change only `scope` and create exactly one commit, with no push/merge/deploy.
  Final assistant text is not identity, commit proof, or acceptance. Task text is never concatenated into a shell.
- Cursor `--output-format json` stdout must be a single `{ "type": "result", ... }` object with a
  field allowlist, `type=result`, and no error subtype. Extra text, a second JSON value, or an
  error envelope fail closed. The inner `result` (text or JSON) is discarded and never copied to
  wrapper stdout, logs, or reports. `CursorRunner` takes task/lease identity from the registry and
  active lease, `commitRef` from `inspect_execution`, and acceptance from `run_chief_verification`.
- CLI `status` and `--print` receive a filtered environment allowlist only (runtime/locale/tmpdir
  plus `CURSOR_API_KEY` / `CURSOR_API_ENDPOINT`). Other secrets are not inherited.
  Production supplies `CURSOR_API_KEY` from Keychain; HOME/TMP/XDG remain inside the clone.
  The sandbox always sets `AGENT_CLI_CREDENTIAL_STORE=file` so Cursor CLI uses an
  isolated file store under clone HOME (`.sandbox-home/.cursor/auth.json`) instead of
  Darwin login keychain. Host `memory`/`default` values are overwritten. The trusted
  parent deletes that `auth.json` in `finally` after success, non-zero exit, exception,
  or timeout. The file is visible to the child only while it runs.
- Missing authentication, timeout, or a non-zero CLI exit fail closed. Suspected secrets are redacted.
- Success still stops at `REVIEW`. Julius remains isolated. One active execution per project.
- `cursor-daemon` claims at most one task per cycle and stays idle when the queue is empty.
- Identical permanent rejections trip a circuit breaker, write a halt file, exit 0, and wait for Chief.
  LaunchAgent `KeepAlive` is `SuccessfulExit=false`, so a halt does not restart the job.

## Local config

Copy `config/cursor-runner.example.json` to `config/cursor-runner.local.json` (gitignored).
Set `cliPath` to the absolute `cursor-agent` executable. Do not store API keys in that file.
Copy `config/execution-lifecycle.example.json` to an absolute gitignored lifecycle file and pass
it as `--lifecycle-config`. Do not enable the LaunchAgent in R7.

```bash
PYTHONPATH=src python3 -m control_plane.main --config /absolute/config/projects.cursor-r1.local.json cursor-run \
  --executor-id cursor-r1 \
  --executor-command '["/usr/bin/python3","/absolute/scripts/cursor_cli_wrapper.py","--runner-config","/absolute/config/cursor-runner.local.json"]' \
  --project control-panel
```

The resident daemon is `scripts/run_cursor_runner.py` and always requires `--lifecycle-config`.

## Daemon

The user-level LaunchAgent template is `scripts/com.pojian.chief-cursor-runner.plist.example`.
`parse_runner_argv(None)` must read process arguments (LaunchAgent calls `main()` with no argv list).
R7 does not enable or replace the running R1 LaunchAgent. The example plist now includes
`--lifecycle-config` so a future activation cannot start without R6 isolation.
The plist must contain PYTHONPATH and explicit program arguments only — never credentials.
A halt file at `--halt-file` means the runner is waiting for Chief; delete it only after the
permanent rejection has been corrected.

## Not authorized in R7

Julius, Director, Eval, KESU, knowledge-base writes, business database changes, push, merge,
deploy, LaunchAgent replacement, and more than two real Cursor `--print` canary invocations.
