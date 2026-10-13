# R7 Chief Review · 2026-08-21

## Decision

`BLOCKED / OWNER_DECISION_REQUIRED / DO_NOT_MERGE_OR_ACTIVATE`

Implementation commit `6efc99ef0b38fe461f91a3d36e08f12898725722` is one commit after `13127b9` and stays inside the R7 code/test/doc whitelist. Chief independently reran the suite in the real macOS permission environment: 167 tests, 0 failures, 0 skips.

## What passed

- The resident runner now requires a lifecycle config and constructs `TaskWorktreePool`; missing/old config and path overlap stop before Executor invocation.
- The wrapper accepts the R6 `verification` field, requires a scoped single commit, and strictly unwraps one Cursor CLI result into `executor-result/1.0.0`.
- Fake production-entry canary reaches REVIEW. Main, R4, R6, LaunchAgent and all production projects remain unchanged.

## Blocking evidence

The required real Cursor canary did not start. The first setup attempt failed before Cursor because the wrapper process lacked `PYTHONPATH`; after that was corrected, two separate tasks failed at the same authentication gate and stopped as required. Actual Cursor `--print` calls: 0.

Sanitized evidence proves:

- Host environment: Cursor status returns authenticated.
- Same R6 `sandbox-exec` profile with host HOME: authenticated.
- Same profile with HOME redirected to clone `.sandbox-home`: unauthenticated / not logged in.

Root cause: R6 redirects HOME into the clone while the existing Cursor login is discovered through the host HOME/keychain relationship. No credential was copied and no authentication setting was changed.

## Recommended Owner decision

Approve a narrow revision of the R6 environment rule: for the real Cursor process only, preserve the host HOME value so it can locate the existing login; keep the kernel profile denying every write outside the task clone and `/dev/null`; keep TMP/TEMP/XDG inside the clone. Add real tests proving host HOME writes and child/symlink escapes remain `EPERM`, then rerun the real canary.

This does not add filesystem read permission: the current `(allow default)` profile already permits reads. It changes credential discovery and therefore changes a frozen acceptance rule; Chief will not apply it without Owner approval.

Alternative: keep HOME redirected and provision a dedicated `CURSOR_API_KEY` through the service environment. That preserves the original rule but adds secret lifecycle/cost/rotation work and requires Owner credential setup; it is not recommended for this first activation.
