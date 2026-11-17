# STATUS · track l1-threads (P-012)

Updated 2026-11-17. Local branch `track-l1-threads` in worktree `.claude/worktrees/track-l1-threads`
of /home/user/fenvix-engine-cli; base `1573079` (origin/claude/gracious-rubin-eyswxd). Patches:
`patches/` (`git am` on the base).

## Done
- Asyncio prototype brought in as one squashed commit (code + docs).
- Design note `docs/L1-THREADS.md`.
- Prototype `python/detpy/threads.py`, `--det-threads` (+ `-seed`, `-grace`, `-deadlock`, `-preempt`).
  Smoke: 6 race tests identical fingerprints over 5 calm runs; deadlock raised with a clear message.

## Next
- tests/test_threads.py (fail without / pass with), easypy 10 bundles, class-a 31, workflow for Actions.
