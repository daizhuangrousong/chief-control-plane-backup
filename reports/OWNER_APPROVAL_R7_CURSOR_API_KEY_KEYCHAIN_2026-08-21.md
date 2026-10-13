# Owner Approval · R7 Cursor API Key via macOS Keychain

Date: 2026-08-21

Owner approved the Chief recommendation to use a dedicated Cursor API key for the headless Executor service.

Frozen handling rules:

- The key is created by Owner in the Cursor dashboard and stored directly in macOS Keychain.
- Keychain service name: `com.pojian.chief-cursor-api`; account: `pojian`.
- The trusted parent may retrieve the key at runtime and inject only `CURSOR_API_KEY` into the sandboxed Cursor process.
- Executor HOME returns to the independent clone; TMP/TEMP/XDG remain inside the clone.
- No key or derived credential may appear in plist, JSON, repository, stateRoot, task payload, stdout/stderr, logs, evidence, process argv, or chat.
- The R6 kernel write profile remains clone plus `/dev/null` only.
- Missing, locked, empty, or unreadable Keychain data fails closed before Cursor `--print`.

This approval does not authorize merge, LaunchAgent activation, production project access, push, deploy, or knowledge-base changes. Those remain gated by a successful real canary and Chief Review.
