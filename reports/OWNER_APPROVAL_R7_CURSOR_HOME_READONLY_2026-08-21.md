# Owner Approval · R7 Cursor HOME 只读登录态

Date: 2026-08-21

Owner approved the Chief recommendation:

- The real Cursor process may preserve the host `HOME` value to locate the existing authenticated session.
- The R6 kernel profile remains unchanged: deny all `file-write*` outside the independent task clone, except `/dev/null`.
- `TMPDIR` / `TMP` / `TEMP` and all XDG paths remain redirected into the clone.
- No credential, keychain item, API key, or `~/.cursor` content may be copied into the clone, repository, logs, or stateRoot.
- Tests must prove host HOME writes, child writes, and symlink escapes remain `EPERM` and host files remain byte-identical.

This approval narrowly revises the frozen R6 HOME-location acceptance rule. It does not approve merge, LaunchAgent activation, production project access, push, deploy, knowledge-base changes, or any other permission expansion.
