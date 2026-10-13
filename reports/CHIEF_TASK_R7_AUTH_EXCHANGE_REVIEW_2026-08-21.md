# R7 Auth Exchange · Chief Review · 2026-08-21

## Verdict

`PASS_DIAGNOSTIC / MEMORY_STORE_POST_EXCHANGE_BLOCKED`

## Accepted evidence

- `/Users/pojian/chief-state/r7auth/auth-exchange.json` records four Key/header shape checks as true.
- Exactly one authenticated exchange reached Cursor and returned `2xx` with a valid access/refresh token schema.
- `printCalls=0`, `authenticatedExchangeCalls=1`, `writeAllowCount=2`; no key or token was written to evidence.
- Therefore the User API Key, network, TLS, Node runtime and R6 sandbox path are healthy. The r7k6 failure occurs after exchange inside this Cursor CLI version's `credential-manager/memory` path.

## Owner decision

Owner approved the documented fallback `AGENT_CLI_CREDENTIAL_STORE=file`. Credentials may exist only at the isolated task clone's `.sandbox-home/.cursor/auth.json` while the Cursor subprocess is alive. The trusted parent must remove that exact file on success, failure and timeout; it must never enter logs, evidence, Git, parent import, host HOME or another task clone.

## Gate

This approval permits one narrow implementation and at most one real `--print` canary. It does not approve merge, deployment, LaunchAgent replacement or production activation. R1 remains `SAFE_IDLE`.
