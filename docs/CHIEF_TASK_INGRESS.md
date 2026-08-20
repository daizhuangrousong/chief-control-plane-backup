# Chief Task Document Ingress (R3)

Chief writes one atomic JSON envelope into a gitignored `chief-task-outbox/`.
A limited importer/reporter LaunchAgent observes complete regular files, registers
them through `TaskRegistry`, runs `DecisionPolicyEngine`, and writes a short receipt
into `chief-task-inbox/`. Identity sidecars are scanned on every cycle so
DRAFT/READY/CLAIMED/RUNNING/REVIEW/BLOCKED facts are published without changing
task state. The existing Cursor Runner claims READY work through `LeaseDispatcher`
and is passed `--inbox-dir`. There is no second queue.

## Envelope

Copy `config/chief-task-envelope.example.json`. The example is fake data.
Required object keys are only `schemaVersion`, `task`, and `facts`.
`task` reuses `config/task.schema.json`. `facts` reuses the TASK-016 decision facts.
Unknown fields, symlinks, non-regular files, paths outside the outbox, truncated JSON
and files larger than `maxBytes` are rejected with a BLOCKED receipt. Cursor is not started.

Local directories and config (gitignored):

- `chief-task-outbox/`
- `chief-task-inbox/`
- `config/chief-task-ingress.local.json`
- `config/projects.cursor-r3.local.json`
- `var/cursor-r3.sqlite3`

Do not point R3 at the R1 `var/cursor-r1.sqlite3`.

## Importer / reporter

`scripts/run_chief_task_ingress.py` is the resident entry. It requires `--log-file`
and `--halt-file`. Identical failures write the halt file and exit 0 so LaunchAgent
`KeepAlive SuccessfulExit=false` stays stopped. Empty queues do not rewrite unchanged
receipts or unrelated inbox files.

Copy `scripts/com.pojian.chief-task-ingress.plist.example`. Enable it only after the
R3 code commit, and only for Control Plane.

Workspace HEAD must equal the Dispatcher-registered baseline or the envelope is BLOCKED
before the executor starts. `scripts/run_cursor_runner.py --inbox-dir` writes receipts;
omitting it keeps R1 runner behavior.

## Receipts

Inbox files are short JSON. Chief can decide whether to drill down from `state`, `error`,
`sourceHash`, `originalHash`, `attemptedHash`, `taskVersion`, `matchedRules` and `leaseId`.
The identity publisher updates CLAIMED/RUNNING/REVIEW/BLOCKED facts and never marks
REVIEW as DONE. Halt and rejected cycles publish a final receipt without mutating the task.

## Rollback

R1 `com.pojian.chief-cursor-runner` remains the rollback baseline. Activation failure
must restore the original R1 plist/paths and prove idle. Do not merge, push, or deploy.

## Not authorized in R3

Julius, Director, Eval, Feishu credentials, merge, push, deploy, schema changes,
a second real Cursor `--print`, and any project other than `control-panel`.
