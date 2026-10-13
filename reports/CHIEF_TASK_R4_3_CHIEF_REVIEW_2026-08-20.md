# R4.3 Chief Review · 2026-08-20

Decision: `PASS_NARROW / R5_GATE_BLOCKED_BY_CROSS_REPO`

Reviewed commit: `0d6695d`

Executor evidence: reported 148 tests / 0 fail / 0 skip; one local commit; no merge, activation, push, or real Cursor call.

## Passed

- Verification argv is Chief-authored task data and is persisted in the task contract.
- Executor result cannot supply or drift argv; malformed/extra/shell/absolute command attempts are rejected before invocation.
- Runner executes with `shell=False`, rechecks host/worktree state, and blocks missing legacy verification contracts.

## R5 blocking architecture mismatch

`TaskWorktreePool` currently requires `git_common_dir(runtime_root) == git_common_dir(project_root)`. This means the Control Plane runtime and target project must be worktrees of the same repository. The production topology is the opposite: Control Plane, Eval, Julius and Director are independent repositories. Therefore the R4 lifecycle cannot create an Eval task worktree without misrepresenting an Eval checkout as the Control Plane runtime.

The test fixture hides this because `runtime` is created as a second worktree of the same temporary project repository. No test uses a Control Plane repository plus a different target repository.

## Residual Tier 1 hardening

- Chief argv validation still accepts `..` path traversal; the host-change test detects pollution after execution but does not prevent or remove the escaped file.
- Merger replays verification commands a second time without a second host snapshot, creating duplicate side-effect risk.

## Disposition

- Accept R4.3 only as completion of the command-provenance subtask.
- Do not activate or start Eval R5.
- R4.4 must prove a clean Control Plane runtime can manage a genuinely separate target Git repository with an external state root.

