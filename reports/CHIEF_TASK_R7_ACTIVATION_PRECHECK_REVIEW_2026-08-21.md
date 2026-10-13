# R7 Activation Precheck · Chief Review · 2026-08-21

## Verdict

`MAIN_MERGE_PASS / ACTIVATION_SAFE_STOP`

## Accepted

- Control Plane main advanced by `ff-only` from `13127b9` to approved R7 `140b993`; full tests are `178/0/0` and diff-check is clean.
- All 2 tracked dirty files and 103 untracked Owner assets were preserved with zero SHA drift.
- The dedicated runtime clone is clean at `140b993`; R1 plist is backed up byte-for-byte.
- Precheck stopped before LaunchAgent replacement with `printCalls=0`, `authJson=0`; R1 remains running at the original PID and plist SHA.

## Root cause and decision

R6 correctly requires both runtime and target project repositories to be clean. The Owner main repository is intentionally dirty and must not be cleaned, stashed or reset. Production execution will therefore target a second clean integration mirror at the same approved commit. Cursor tasks stop at REVIEW there; a later independent merger is responsible for preserving and integrating into Owner main. This keeps the owner workspace out of the untrusted executor's write boundary and does not change R7 code or acceptance rules.
