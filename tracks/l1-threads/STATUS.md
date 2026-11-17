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

- Fix: stdlib time-left clock (threading._time, queue.time) virtual; timeouts round up (easypy sync tests).
- Harness `harness/l1_threads.py` + corpus `harness/l1/threads-corpus.json`; workflow
  `.github/workflows/track-l1-threads.yml` (trigger: `tracks/l1-threads/run.json`), round r1 pushed.
  Results land in `tracks/l1-threads/results/r1/`.

## Next
- Aggregate r1 (`python3 harness/l1_threads.py --aggregate tracks/l1-threads/results/r1 --out ...`), REPORT.md.
