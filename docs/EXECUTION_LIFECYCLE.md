# Execution lifecycle (R4 / R4.3)

Resident runtime code stays on a dedicated Control Plane worktree. Each task gets its own
`git worktree` and `task/<taskId>` branch created from the Dispatcher-registered
baseline. The daemon never uses its own checkout as the executor cwd, and never
puts the live project path in the executor payload.

R4.3 is Owner Tier 1: same macOS user, prevent mistakes and false greens, not a
malicious-process sandbox. The next allowed attach is a new Eval repository in R5.
Do not connect Julius, Director, databases, secrets, or deploy from this lifecycle.

## Isolation

`TaskWorktreePool` refuses `runtime_root == project_root`, runtime/pool nesting,
symlinks, dirty reuse, unknown HEAD, unexpected Git toplevels, and a second
allocate of the same task. Runtime and project must be distinct git worktrees of
the same repository (`git-common-dir` match, resolved paths). The pool sits
inside the project root and is gitignored.

When the pool is enabled, `workspaceRoots` sent to the executor is only the leased
worktree. After the process exits, the runner proves the runtime HEAD, target
checkout, and registered baseline were not modified.

## Chief-authored verification

Every READY task must declare `verificationCommands`: one `{id, criterion, argv}`
object per acceptance criterion, in the same order. `argv` is a non-empty string
array, not a shell string. Registration rejects `sh|bash|zsh`, `-c`, redirects,
pipes, empty arguments, and absolute paths. Unstructured legacy acceptance cannot
become READY.

The executor result may only cite `commandId`, `criterion`, `status`, and
`evidence`. Executor-supplied `argv` or `exitCode` is rejected and those argv are
never executed. The runner reads Chief argv from the registered task, runs them
with `shell=False` in the leased worktree, and treats a non-zero exit as FAILED.
It then re-checks worktree cleanliness, single-commit, scope, diff-check, and
runtime/target snapshots. Verification that dirties the tree, changes the commit,
or changes a host cannot enter REVIEW. The durable report records Chief argv, the
real exit code, and a truncated output summary.

## Execution contract

After the injected executor exits 0, the runner requires exactly one commit on the
leased worktree, a clean tree, `git diff --check` pass, and changed paths inside
`task.scope`. It then parses a strict `executor-result/1.0.0` envelope from
stdout: bound to task/version/lease/commit, with acceptance checks in task order.
The runner never invents `pass` and never replays Executor argv. Missing,
ordered-wrong, empty, failed, plain-text, or commit-mismatched results fail the
lease.

Only after that envelope, Chief verification, and Git contract succeed does the
runner atomically persist `execution-report/1.0.0` under the runtime control
directory, reload it, and then `complete` into REVIEW. A persist/reload/complete
failure fails the lease; leftover temp files are not mergeable evidence.

## Chief review, merger, promoter

Chief drops `chief-review-decision/1.0.0` into a runtime-side inbox. Caller
strings such as `actor=chief` or `caller_executor_id=merge-r4` are not identity.
`TaskMerger.merge(task_id, request_id)` re-runs the Git contract and Chief argv,
fast-forwards locally, writes the receipt, then consumes the decision.
If merge fails, the decision stays usable and HEAD/baseline are unchanged. If
HEAD already equals the approved commit, retry only fills receipt/consume and
does not merge again.

Merger identity comes from instance config and must not appear in
`allowedExecutors`. `BaselinePromoter` updates Dispatcher baseline only when the
target is clean, the merge commit is HEAD, there is no active lease, and runtime
health passes. Failure keeps the old baseline and returns a rollback plan; it
does not run the restore command.

## Once-consume receipts

A `{taskId}.consumed.json` sidecar seals the original envelope hash. Repeating the
same outbox bytes does not re-run Git or rewrite the receipt. Receipts expose both
`taskState` and `runnerStatus` (including `HALTED` on the circuit breaker).

R4 does not enable LaunchAgents, call the real Cursor CLI, merge this branch, or push.
