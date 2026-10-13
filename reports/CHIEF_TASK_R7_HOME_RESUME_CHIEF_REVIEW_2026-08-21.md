# R7 HOME Resume Chief Review · 2026-08-21

## Decision

`BLOCKED / OWNER_DECISION_REQUIRED / DO_NOT_MERGE_OR_ACTIVATE`

Amended implementation commit: `c37ed84372eb207366047a669d7e42ac4ac69fba`, exactly one commit after `13127b9`.

Chief independently reran the complete suite in the real macOS permission environment: 169 tests, 0 failures, 0 skips. Tests prove trusted host HOME discovery, clone-local TMP/XDG, missing/illegal HOME fail-closed, and EPERM for host HOME create/overwrite/child/symlink writes while clone Git commit still succeeds.

## Real Cursor evidence

- Authentication preflight under the same sandbox profile succeeded: `isAuthenticated=true`.
- One real `--print` invocation started.
- Cursor then attempted to create `~/.cursor/projects/<workspace>` and was denied by the unchanged kernel profile with `EPERM`.
- The task ended FAILED before any workspace file or Git ref was created; no execution report exists.
- Runtime, target main, state sentinel, host HOME sentinel, live LaunchAgent, Control Plane main, Julius and Director all remained unchanged. Merge/promotion/push/deploy are 0.

This is not a model-quality failure. Browser login and Cursor's runtime session storage share host HOME. Read-only host HOME can authenticate, but a real run requires writing its own project session directory.

## Chief recommendation

Do not allow writes to host `~/.cursor/projects`; that would violate the core requirement that an untrusted Executor process can write only its independent clone.

Use a dedicated `CURSOR_API_KEY` for the headless service, stored in macOS Keychain and injected only by the trusted parent. Restore HOME to the clone so Cursor's session files stay inside the kernel write allowlist. Cursor's official documentation recommends API-key authentication for automation/CI. No key may be written to a plist, JSON config, repository, stateRoot, log, or chat.

This changes the production authentication method and introduces a managed secret, so it requires Owner approval. Until then, keep R1 safe-idle and do not merge `c37ed84`.
