# STATUS · track l1-threads (P-012)

Updated 2026-11-17. Local branch `track-l1-threads` in worktree `.claude/worktrees/track-l1-threads`
of /home/user/fenvix-engine-cli; base `1573079` (origin/claude/gracious-rubin-eyswxd). Patches:
`patches/` (`git am` on the base). Final code d447170.

## Done
- `--det-threads` prototype, design note, 17 tests, harness + workflow, fixes found on easypy/boltons/anyio.
- REPORT.md (PARTIAL: all exit numbers measured; anyio/requests/werkzeug suites and r5 anyio corpus
  still running on Actions: anyio and requests suites).

## Next
- r4 cancelled after 19 jobs. When r5 (run 44089216622, anyio suite) and r6 (run 44095974555, requests suite) finish: re-aggregate
  (`python3 harness/l1_threads.py --aggregate results/r4 --out ...`, same for r5), replace the r1 rows
  and the local anyio rows in REPORT.md, first line DONE.
