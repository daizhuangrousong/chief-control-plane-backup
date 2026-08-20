# Execution lifecycle (R4 / R4.4)

Resident Control Plane code lives in its own Git repository (`runtimeRoot`).
Each managed target is a different Git repository (`projectRoot`). The two roots
must not be equal, nested, or share a `git-common-dir`. Task branches and
worktrees are created only on the target. Runtime HEAD and porcelain stay
unchanged.

R4.4 is Owner Tier 1: same macOS user, prevent mistakes and false greens, not a
malicious-process sandbox. The next allowed attach is a new Eval repository in R5.
Do not connect Julius, Director, databases, secrets, or deploy from this lifecycle.

## Four roots

- `runtimeRoot`: clean Git root that contains Control Plane sources (`src/control_plane`).
- `projectRoot`: clean Git root of the target. Independent of runtime.
- `poolRoot`: directory under the target (never the target root itself) that holds
  leased task worktrees. Worktrees share `git-common-dir` only with `projectRoot`.
- `stateRoot`: ordinary directory outside both Git repos and the pool. Holds the
  SQLite DB, Chief review inbox, execution reports, receipts, and occupancy.
  Symlinks and nesting inside a Git root are refused. Do not gitignore the runtime
  repo to hide state files.

## Isolation

`TaskWorktreePool` refuses `runtime_root == project_root`, shared git-common-dir,
nesting, dirty checkouts, missing Control Plane sources on runtime, a module loaded
from the target, symlinks, dirty reuse, unknown HEAD, unexpected Git toplevels, and
a second allocate of the same task.

When the pool is enabled, `workspaceRoots` sent to the executor is only the leased
worktree. After the process exits, the runner proves the runtime HEAD, target
checkout, and registered baseline were not modified.

## Chief-authored verification

Every READY task must declare `verificationCommands`. argv is a non-empty string
array. Shell wrappers, `-c`, redirects, pipes, empty arguments, absolute paths, and
any `..` path segment are rejected before invocation. The runner executes Chief argv
once with `shell=False` in the leased worktree, then re-checks the task tree and
hosts. The merger reloads the durable report and recomputes Git commit/scope/diff; it
does not run commands again. Execute-to-merge invocation count is exactly one.

The executor result may only cite `commandId`, `criterion`, `status`, and
`evidence`. Executor-supplied `argv` or `exitCode` is rejected and those argv are
never executed.

## Execution contract

After the injected executor exits 0, the runner requires exactly one commit on the
leased worktree, a clean tree, `git diff --check` pass, and changed paths inside
`task.scope`. Missing, ordered-wrong, empty, failed, plain-text, or
commit-mismatched results fail the lease.

Only after that envelope, one Chief verification, and Git contract succeed does the
runner atomically persist `execution-report/1.0.0` under `stateRoot`, reload it,
and then `complete` into REVIEW.

## Chief review, merger, promoter

Chief drops `chief-review-decision/1.0.0` into the state-root inbox. Caller
strings such as `actor=chief` or `caller_executor_id=merge-r4` are not identity.
`TaskMerger.merge(task_id, request_id)` re-runs the Git contract against the
persisted report, fast-forwards the **target** locally, writes the receipt, then
consumes the decision. It does not re-execute verification. If merge fails, the
decision stays usable and HEAD/baseline are unchanged.

`BaselinePromoter` updates Dispatcher baseline only when the target is clean, the
merge commit is HEAD, there is no active lease, and runtime health passes. Failure
keeps the old baseline and returns a rollback plan; it does not run the restore
command or reset the runtime repo.

## Once-consume receipts

A `{taskId}.consumed.json` sidecar seals the original envelope hash. Repeating the
same outbox bytes does not re-run Git or rewrite the receipt. Receipts expose both
`taskState` and `runnerStatus` (including `HALTED` on the circuit breaker).

R4 does not enable LaunchAgents, call the real Cursor CLI, merge this branch, or push.
