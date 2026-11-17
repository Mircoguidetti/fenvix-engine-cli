# STATUS · track l1-threads (P-012)

Updated 2026-11-17. Local branch `track-l1-threads` in worktree `.claude/worktrees/track-l1-threads`
of /home/user/fenvix-engine-cli; base `1573079` (origin/claude/gracious-rubin-eyswxd). Patches:
`patches/` (`git am` on the base).

## Done
- Asyncio prototype brought in (one squashed commit), design note `docs/L1-THREADS.md`.
- Prototype `python/detpy/threads.py`, `--det-threads` (+ `-seed`, `-grace`, `-deadlock`, `-preempt`).
- tests/test_threads.py: 11 tests (fail with Level 0 only / pass with --det-threads).
- Fixes found on easypy: patch `_thread.start_new_thread` (threadtree), exiting threads leave the
  scheduler and are reaped, futures hash/lock by creation order, verifier: entropy in a worker = Entropy.
- easypy 10 bundles, local, `--det --det-threads --det-urandom`, 10 runs: 10/10 tests one fingerprint.

## Next
- class-a 31 list, Actions workflow (easypy + class-a + popular pool + slowdown), REPORT.md.
