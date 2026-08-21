# Security Boundary

## v0.1 guarantees

- Project adapters are read-only and never write to connected repositories, knowledge bases or assets.
- Knowledge scanning follows only explicitly configured roots, skips symbolic links and caps each run.
- Source document bodies are not stored in SQLite; only hashes, metadata and structural summaries are kept.
- Git inspection uses read-only commands. Release Agent cannot commit, push, merge, tag or deploy.
- The HTTP API is GET-only and listens on loopback by default.
- Task registration and transitions are local CLI operations with optimistic version checks and append-only audit evidence.
- Task policy uses explicit boolean facts and versioned deterministic rules; incomplete safety facts block execution, and model advice cannot grant READY status.
- Medium, high and critical risk plus architecture, production, permission, external, paid, destructive, release and scope-expansion actions require owner confirmation.
- Feishu owner actions arrive through the official SDK long connection, are restricted by an open_id allowlist, expire, and are deduplicated by both event_id and nonce.
- Feishu callbacks store only an allowlisted structured payload. Full messages, unknown form fields and credentials are never persisted.
- Requirement and direction changes require a stored preview plus a second confirmation; confirmation cannot mutate a running task or create a READY task.
- Executor identities are enforced by TASK-018 against both the task allowlist and an executor profile's project/risk ceiling. The Dispatcher grants a lease, not filesystem or command authority.
- Non-`none` `approvalClass` values require a non-empty `ownerApprovalRef` before READY. Knowledge writes, database writes, direction changes and acceptance changes cannot be granted by spoofed fields.
- The R0 Cursor adapter never auto-discovers Cursor, never concatenates task text into a shell, and redacts suspected secrets from logs and failure reasons.
- The R1 CLI wrapper requires an explicit absolute `cliPath` from gitignored local config, refuses secrets in that file, filters CLI subprocess env to a runtime/auth allowlist, and will not start `--print` when the CLI is unauthenticated.
- The R7 production entry cannot start without `--lifecycle-config`, Keychain service/account, and `/usr/bin/sandbox-exec`. There is no unsandboxed resident path. The trusted parent loads `CURSOR_API_KEY` from macOS Keychain into child memory only; it is never written to argv, plist, JSON, logs, or state. Cursor CLI JSON is accepted only as a single successful outer `type=result` object; inner model text/JSON is discarded. Control Plane fills `executorResult` from the registered task, active lease, `inspect_execution`, and Chief verification. Wrapper stdout never echoes credentials, the outer CLI envelope, or the inner payload.
- R7 sandbox HOME/TMP/XDG stay inside the independent clone. The kernel profile still allows writes only to the clone and `/dev/null`. Host HOME creates, overwrites, child writes, and symlink escapes remain EPERM. The sandboxed child always receives `AGENT_CLI_CREDENTIAL_STORE=file`; it cannot inherit `memory` or Darwin `default` from the host. Cursor may write `.sandbox-home/.cursor/auth.json` only while the child runs. The parent removes that regular file afterwards and fails closed on path escape or unexpected types. Same-process readers can see the file during the child; it must not remain after return.
- Cursor daemon halt files and LaunchAgent plists must not contain credentials. Permanent rejections stop for Chief instead of retrying forever.
- R2 Chief task envelopes are ordinary JSON files in a gitignored outbox. Symlinks, unknown fields, path escape, truncated JSON and oversized files are rejected. The importer never starts Cursor and never writes Julius or Director.
- Envelope identity is sealed after the first successful register. A later conflict receipt cannot change existing task state or replace the original hash. Missing or corrupt identity sidecars fail closed.
- Secrets, tokens, cookies, environment dumps and database contents must not enter findings or audit events.

## Not yet approved for production exposure

- The Feishu channel is not active until an operator configures a private enterprise app, owner allowlist and environment-only credentials.
- The Feishu process is an Owner control channel, not a general chat bot and not an executor transport.
- There is no write executor for approved review items.
- Docker, PostgreSQL, HTTP health and log adapters are not implemented in this first slice.
- The local API must not be exposed outside the host.

## Review requirements

Any future write path requires a separate process identity, explicit approval, version revalidation,
idempotency, rollback evidence and an AuditEvent. Adding a command to an adapter is not sufficient authorization.
