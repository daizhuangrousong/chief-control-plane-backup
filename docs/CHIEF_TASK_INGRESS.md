# Chief Task Document Ingress (R2)

Chief writes one atomic JSON envelope into a gitignored `chief-task-outbox/`.
Control Plane observes complete regular files, registers them through `TaskRegistry`,
runs `DecisionPolicyEngine`, and writes a short receipt into `chief-task-inbox/`.
The existing Cursor Runner still claims READY work through `LeaseDispatcher`.
There is no second queue and no LaunchAgent for this importer in R2.

## Envelope

Copy `config/chief-task-envelope.example.json`. The example is fake data.
Required object keys are only `schemaVersion`, `task`, and `facts`.
`task` reuses `config/task.schema.json`. `facts` reuses the TASK-016 decision facts.
Unknown fields, symlinks, non-regular files, paths outside the outbox, truncated JSON
and files larger than `maxBytes` are rejected with a BLOCKED receipt. Cursor is not started.

Local directories (gitignored):

- `chief-task-outbox/`
- `chief-task-inbox/`

## Importer

```bash
PYTHONPATH=src python3 scripts/run_chief_task_ingress.py \
  --config /absolute/config/projects.local.json \
  --ingress-config /absolute/config/chief-task-ingress.local.json \
  --max-cycles 1
```

Do not enable a LaunchAgent for this script in R2. Use a temporary database for development.
Do not point the importer at the R1 `var/cursor-r1.sqlite3`.

Identical bytes are idempotent. The same task id with different task or facts bytes is a
conflict receipt: `originalHash` and `attemptedHash` are both recorded, and the existing
DRAFT/READY/RUNNING/REVIEW/BLOCKED state and version are left unchanged.
The first successful register seals the envelope hash in an inbox identity sidecar.
A missing or corrupt sidecar fails closed.

Workspace HEAD must equal the Dispatcher-registered baseline or the envelope is BLOCKED
before the executor starts. `scripts/run_cursor_runner.py` accepts optional `--inbox-dir`
and writes short receipts; omitting it keeps the R1 runner behavior.

## Receipts

Inbox files are short JSON. Chief can decide whether to drill down from `state`, `error`,
`sourceHash`, `originalHash`, `attemptedHash`, `taskVersion`, `matchedRules` and `leaseId`.
The runner reporter updates CLAIMED/RUNNING/REVIEW/BLOCKED facts and never marks REVIEW as DONE.

## Not authorized in R2

Julius, Director, Eval, Feishu credentials, merge, push, deploy, schema changes,
a second real Cursor `--print`, and a resident R2 importer/runner.
