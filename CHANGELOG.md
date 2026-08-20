# Changelog

## Unreleased

### R4 — Sustainable execution lifecycle

- Task execution uses an isolated git worktree/branch created from the registered baseline, never the resident runtime checkout.
- A single-commit contract, independent merger, and baseline promoter keep review/merge/promotion off the task executor. Same-hash outbox files are consumed once.
- R4.1: executor `workspaceRoots` is only the leased worktree; `TaskWorktreePool` rejects `runtime == project` and nested runtime/pool; review identity comes from a runtime Chief inbox, not caller strings; the merger reloads and recomputes durable execution evidence before fast-forward.
- R4.2: executor stdout must be a real `executor-result/1.0.0` envelope; reports persist before REVIEW; Chief decisions are consumed only after a confirmed fast-forward, with idempotent crash recovery. Tier 1 same-user only; R5 Eval repo is the next allowed attach.
- R4.3: `verificationCommands` are Chief-authored argv on the task contract. The runner executes those argv only, re-checks the leased tree and hosts, and rejects Executor-supplied argv. Unstructured tasks cannot become READY.

### R3 — Chief document dispatch activation

- The importer/reporter scans identity sidecars and publishes DRAFT/READY/CLAIMED/RUNNING/REVIEW/BLOCKED receipts without changing task state.
- Halt/rejected cycles write a final receipt before the daemon returns. Unchanged receipts are not rewritten.
- Added a limited `com.pojian.chief-task-ingress` LaunchAgent example and wired the runner example to `--inbox-dir` on the R3 worktree.

### R2 — Chief task document ingress

- Added a gitignored outbox/inbox file contract so Chief can drop one strict JSON task envelope without using the CLI or SQLite.
- The importer registers DRAFT through TaskRegistry, runs the existing decision policy, and writes a short receipt. Identical files are idempotent; illegal or conflicting drops never start Cursor.
- The runner may publish read-only CLAIMED/RUNNING/REVIEW/BLOCKED receipts. REVIEW is never auto-completed. No R2 LaunchAgent is enabled.
- R2.1: envelope identity is sealed in an inbox sidecar; conflicts never mutate existing task state; workspace HEAD must match the Dispatcher baseline; `run_cursor_runner.py --inbox-dir` writes receipts.

### R1 — Official Cursor CLI bootstrap

- Added an explicit stdin wrapper that validates the R0 JSON payload and invokes the official Cursor CLI from an injected absolute `cliPath`.
- Added `cursor-daemon`: one Control Plane project, one task at a time, idle when the queue is empty, rotating logs, no credential files.
- CLI subprocesses receive a filtered env allowlist; `--executor-command` is a JSON argv array; identical permanent rejections halt for Chief.
- Missing CLI authentication, timeout and non-zero exits fail closed. LaunchAgent remains disabled until the authorized real pilot passes.
- R1.2: `parse_runner_argv(None)` reads process args so the user LaunchAgent can idle on an empty queue.

### R0 — Isolated Cursor Adapter

- Added machine-checked `approvalClass` (`none | knowledge_write | database_write | direction | acceptance_change`); non-`none` tasks cannot become READY without `ownerApprovalRef`.
- Unknown task fields and spoofed approval keys are rejected; legacy tasks default to `none`.
- Added `CursorRunner`: injected executor command only, LeaseDispatcher claim, workspace/baseline/version checks, stdin task payload, timeout/non-zero `fail`, success stops at REVIEW, secret redaction, one active execution per project.
- Production default refuses to discover or start Cursor. Julius isolation and dispatcher gates are unchanged.

### TASK-029 — Chief Content Intake

- Added a Julius content intake contract for `knowledge_ingest` and `candidate_research` with source, subject and target-stage normalization.
- Intakes deduplicate by person and source identity, separate facts/quotes from analysis, and atomically publish exactly one DRAFT task.
- Intake never writes Julius, enters READY, or skips Codex review toward Story Ready/Brief.

### TASK-028 — Executor Report

- Added immutable executor reports bound to the exact REVIEW task, completed lease, executor identity and lease baseline.
- Added structured acceptance, test, file, risk and provenance evidence with idempotent submission and read-only CLI/API queries.
- Report submission never changes task state or bypasses the independent Review Gate.

### TASK-020 — Read-only Shadow closeout

- Added explicit `no_change` review evidence so read-only executor tasks can be accepted without fabricating commits.
- Kept commit uniqueness and current-baseline enforcement for code-changing evidence while binding no-change evidence to its completed historical lease.
- Reject no-change evidence that reports either a commit or changed files.

### TASK-018 — Lease-based Executor Dispatcher

- Added executor profiles with project and risk ceilings, registered project baselines, and exclusive task leases.
- Added idempotent next/claim/heartbeat/complete/fail service and CLI operations with atomic concurrency control.
- Added expired-lease recovery, stale-baseline rejection and read-only executor/baseline/lease APIs.
- Completion stops at REVIEW so TASK-021 evidence validation remains authoritative for DONE.
- Added a deterministic executor fuse: two consecutive reported failures disable the executor, while a successful completion resets the sequence.
- Added a read-only `dispatch get-baseline` command so executors can compare the registered baseline with Git HEAD before claiming without reading SQLite directly.

### TASK-017 — Feishu Owner Control Channel

- Added an owner-only Feishu `card.action.trigger` inbox using the official long-connection SDK.
- Added event/nonce idempotency, expiry checks, structured payload allowlisting and audit evidence.
- Added atomic owner decisions for `NEEDS_DECISION` tasks with optimistic task-version checks.
- Added requirement and direction intake previews plus separate confirmation; confirmation leaves active tasks unchanged and routes the record to Planner review.
- Added read-only APIs for owner decisions and requirement intakes, operations documentation, and security tests.
 Aligned Card JSON 2.0 controls with strict select, form-submit and callback-behavior schemas; added a private owner-only transport test card and sanitized callback diagnostics.
 Live verification accepted exactly one allowlisted callback into `PREVIEW_PENDING` without creating a READY task or writing either managed project.
