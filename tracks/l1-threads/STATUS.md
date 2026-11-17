# STATUS · track l1-threads (P-012)

Updated 2026-11-17. Local branch `track-l1-threads` in worktree `.claude/worktrees/track-l1-threads`
of /home/user/fenvix-engine-cli; base `1573079` (origin/claude/gracious-rubin-eyswxd). Patches:
`patches/` (`git am` on the base). Final code c25485d.

## Done
- `--det-threads` prototype, design note, tests, harness + workflow, fixes found on easypy/boltons/anyio.
- All Actions runs finished (r5 run 44089216622: anyio; r6 run 44095974555: requests, werkzeug).
  Aggregates in r5-aggregate/ and r6-aggregate/.
- REPORT.md final: PARTIAL. All exit numbers measured on 25/25 popular suites; "broken by
  --det-threads must trend to 0" not met (anyio 9, requests 5; anyio calm suite hangs 2 of 3 runs).

## Next (for a follow-up task, not started)
- Get failure messages: anyio `tests/test_to_thread.py` and the 5 requests tests alone with `-rfE`
  under `--det --det-threads`; find why the anyio run hangs at 97% without DeadlockError.
