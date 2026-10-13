# R4.4 Chief Review · 2026-08-20

Decision: `PASS_TIER1 / PROCEED_TO_EVAL_R5`

Reviewed commit: `b9c344a`

Executor evidence: reported 149 tests / 0 fail / 0 skip; one local commit; R1 safe-idle; no activation, merge, push, real Cursor call, or production attachment.

## Passed

- Control Plane runtime and target project are required to be independent Git repositories with different git-common-dir values.
- State root is outside runtime, target repository and task pool; occupancy/review/reports/receipts no longer dirty runtime code.
- Target task worktrees derive only from target baseline.
- Chief verification runs once; merger validates durable evidence and Git without replay.
- A third independent Eval-like repository reached REVIEW while runtime and target baseline remained unchanged.
- `..` verification paths are rejected before invocation.

## Accepted Tier 1 residual

Internal validation proves the loaded module is not from the target repository, but does not prove it is under the declared `runtimeRoot`. R5 must therefore run a preflight that resolves `control_plane.__file__`, requires it to be inside `/Users/pojian/repos/director-control-plane-r4-lifecycle`, and requires runtime HEAD `b9c344a` with a clean tree. Failure stops R5 before repo/state mutation.

This residual is acceptable only for the new Eval canary under the Owner-approved trusted-but-fallible model. It does not relax the R6 gate for Julius, Director, databases, secrets or deployment.

