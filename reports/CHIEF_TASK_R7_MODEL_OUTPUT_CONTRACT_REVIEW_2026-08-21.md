# R7 Model Output Contract · Chief Review · 2026-08-21

## Verdict

`AUTH_AND_EXECUTION_PASS / TRUST_BOUNDARY_FIX_REQUIRED`

## Facts

- r7k8 used one real `--print`; authentication passed and Cursor created exactly one scoped commit `6d5d3a8` containing only `reports/R7_REAL_CURSOR_CANARY.md`.
- The transcript's final text was JSON, but it used model-invented fields (`type`, `id`, `passed`) and omitted the required trusted fields (`schemaVersion`, `commitRef`, `commandId`, `status`, `evidence`).
- Control Plane rejected it before Chief verification/import/official report, leaving the task `FAILED` rather than `REVIEW`.
- `authJsonAnywhere=0`, `exactKeyHitCount=0`, write allows=2; main, LaunchAgent and project HEADs were unchanged.

## Decision

Do not improve the prompt and keep trusting model-authored acceptance evidence. The model is responsible only for changing the leased workspace and making one commit. The trusted adapter validates only the Cursor CLI outer success envelope; Control Plane derives identity and commit from its lease and Git, then runs Chief-authored verification commands. Only those trusted facts may populate the execution report and REVIEW transition.

The previous brief also misstated the candidate count as nine. Git proves the validation commit contains eight code/tests/docs paths. Future checks use the exact Git path list.
