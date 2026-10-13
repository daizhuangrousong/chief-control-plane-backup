# R4 Chief Review · 2026-08-20

Decision: `REJECT / FIX_REQUIRED`

Reviewed commit: `6d29059987947b63cfc937ce09c8352b3689e940`

Executor evidence: one local commit; reported 134 tests / 0 fail / 0 skip; `git diff --check` pass; R1 safe-idle; no R4 LaunchAgent, real Cursor call, merge, push, or baseline promotion.

## Blocking findings

1. **Leased-worktree isolation can be bypassed by the task payload.** `CursorRunner` changes `cwd` to the leased worktree, but `_invoke()` still sends the task's original `workspaceRoots`. A real Executor can follow that field and write directly to the live project checkout; post-run inspection checks only the leased worktree. The current fake executor ignores this field, so the test does not expose the bypass.
2. **Self-approval separation is asserted by caller-controlled strings.** `TaskMerger.merge()` trusts `caller_executor_id == "merge-r4"`, while the decision parser trusts `actor == "chief"`. The same process can supply both strings. This does not enforce “task Executor cannot self-approve or self-merge.”
3. **Merger does not verify the execution contract it claims to verify.** It checks REVIEW/version/lease/branch commit, but does not load or validate a durable execution report, recompute scope/commit count/diff-check, or verify test evidence before fast-forwarding.
4. **Runtime/project separation is not fail-closed.** `TaskWorktreePool` rejects only `pool_root == runtime_root`; it allows `runtime_root == project_root`, which would let merge mutate the resident runtime checkout. The test runtime is a non-git sentinel directory, so it does not cover the real worktree topology.

## Disposition

- Do not merge, enable, deploy, or promote R4.
- Keep R1 safe-idle and retain R4 commit/evidence.
- Dispatch R4.1 only for the four findings above. No new architecture, external service, production action, or real Cursor call.

