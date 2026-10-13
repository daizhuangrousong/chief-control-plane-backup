# R4.1 Chief Review · 2026-08-20

Decision: `REJECT / OWNER_DECISION_REQUIRED`

Reviewed commit: `5701a4e`

Executor evidence: reported 137 tests / 0 fail / 0 skip; one local commit; R1 safe-idle; no merge, activation, push, or real Cursor call.

## What was fixed

- Executor payload now exposes the leased worktree instead of the live project path.
- Runtime/project/pool Git topology is validated.
- Execution reports are persisted and Git facts are recomputed before merge.
- Review decisions are loaded from a runtime-side inbox rather than passed directly as a dict.

## Blocking findings

1. **Acceptance is fabricated, not executed.** `CursorRunner` creates one `acceptanceChecks` entry per task criterion with `status: pass` and uses the commit ref as evidence. No acceptance command or Executor test result is actually captured. Merger therefore verifies a self-generated green label, not task acceptance.
2. **Review consumption is not crash/failure safe.** `TaskMerger` marks the Chief decision consumed before `git merge --ff-only`. If merge then fails, the task remains in REVIEW but its decision cannot be loaded again, leaving no defined retry/recovery path.
3. **“Chief-only” is not an enforced permission boundary.** Inbox placement is outside the task worktree, but Cursor and Control Plane run as the same OS user. A malicious Executor can still locate and modify the inbox/report directory. Current tests prove path omission, not write denial.
4. **REVIEW can be orphaned.** Dispatcher transitions the task to REVIEW before the durable execution report is written. A report write failure leaves REVIEW without mergeable evidence and without a defined recovery transition.

## Disposition

- Do not merge or activate `5701a4e`.
- Keep R1 safe-idle.
- Owner must choose the threat model before R4.2: trusted-but-fallible same-user Executor, or adversarial Executor requiring a real OS/sandbox permission boundary.

