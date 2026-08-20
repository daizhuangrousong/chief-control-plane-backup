# Cursor Runner R0

R0 is an isolated, injected-command adapter. It lets Chief hand a READY task to a Cursor executor
without Chief executing the work, and without discovering or starting a real Cursor binary.

## Contract

- The executor command must be injected. There is no default PATH lookup and no `cursor-agent` fallback.
- The adapter claims exactly one task through `LeaseDispatcher`. It does not create a parallel queue
  and does not write SQLite except through the existing lease operations.
- Before claim it checks project isolation, `workspaceRoots` against the registered project root,
  task version, git HEAD vs the registered baseline, and owner approval.
- The task body is passed as JSON on stdin. The command list is never shell-concatenated with task text.
- Timeout or a non-zero exit calls `fail`. Success calls `complete` and stops at `REVIEW`.
- Logs and failure reasons redact `token`/`secret`/`password`/`api key`/`bearer`/`sk-` values.
- A project may have at most one active execution.

## Not authorized in R0

Real Cursor, launchd, Julius, Director, KESU, database writes, and remote push/merge/deploy.

## Command

```bash
PYTHONPATH=src python3 -m control_plane.main --config config/projects.local.json cursor-run \
  --executor-id cursor-r0 \
  --executor-command /path/to/injected/executor
```

Omitting `--executor-command` is a usage error. Do not add a default Cursor path.
