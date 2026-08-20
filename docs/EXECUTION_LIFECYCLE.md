# Execution lifecycle (R4)

Resident runtime code stays on the Control Plane worktree. Each task gets its own
`git worktree` and `task/<taskId>` branch created from the Dispatcher-registered
baseline. The daemon never uses its own checkout as the executor cwd.

## Isolation

`TaskWorktreePool` refuses symlinks, dirty reuse, unknown HEAD, and a second
allocate of the same task (crash restart does not re-execute). The pool path must
sit inside the authorized project root and must not be the runtime root.

## Execution contract

After the injected executor exits 0, the runner requires exactly one commit on the
leased worktree, a clean tree, `git diff --check` pass, and changed paths inside
`task.scope`. Failures call `dispatcher.fail` and never merge or promote. Success
stops at REVIEW with `beforeRef`, `afterRef`, changed paths, tests, and lease/task
version. The task executor cannot mark DONE, merge, or update baseline.

## Chief review, merger, promoter

Chief writes `chief-review-decision/1.0.0`. Only actor `chief` is valid.
`TaskMerger` (`merge-r4`) verifies REVIEW, task version, completed lease, matching
commit, and then fast-forwards the target branch locally. `BaselinePromoter`
updates Dispatcher baseline only when the target is clean, the merge commit is
HEAD, there is no active lease, and runtime health passes. Failure keeps the old
baseline and returns a rollback plan; it does not run the restore command.

## Once-consume receipts

A `{taskId}.consumed.json` sidecar seals the original envelope hash. Repeating the
same outbox bytes does not re-run Git or rewrite the receipt. Receipts expose both
`taskState` and `runnerStatus` (including `HALTED` on the circuit breaker).

R4 does not enable LaunchAgents, call the real Cursor CLI, merge this branch, or push.
