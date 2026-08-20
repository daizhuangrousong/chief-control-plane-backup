# BLOCKED · CURSOR-RUNNER R1

## Real Cursor pilot

BLOCKED: official CLI `2026.08.11-e8db854` is installed, but `agent status` reports `isAuthenticated=false` and `CURSOR_API_KEY` is unset. The wrapper fail-closes without `--print`. Owner secrets were not requested. Real Cursor `--print` count remains 0.

## Feishu outbound

BLOCKED: `config/feishu-control.local.json` exists with an owner allowlist, but `FEISHU_APP_ID` and `FEISHU_APP_SECRET` are unset in this process. No test card was sent. Credentials were not requested or fabricated.

## LaunchAgent

Not enabled: the authorized real pilot did not pass.
