PARTIAL · fix round in progress (track l1-threads, broken tests and hangs under --det-threads)

# STATUS · track l1-threads (P-012), fix round

Updated 2026-11-17. Worktree `.claude/worktrees/track-l1-threads` (branch `track-l1-threads`), base `1573079`.
Patches: `patches/` (`git am` on the base).

## Done
- Local reproduction (MEASURED): requests `tests/test_requests.py` + `tests/test_utils.py` under calm
  `--det-threads`: the 5 broken tests fail with `DeadlockError` (main thread waits for the httpbin socket,
  the plugin's server thread is still serving an earlier `delay/10` request; declared after 5 s).
  anyio `tests/test_to_thread.py`: 10 failed + 1 error, 6 deadlocks, 47 escapes.
- Harness: hang dumps (faulthandler per test, SIGABRT at the suite timeout), l1 failure messages.
- Actions r7-diag launched: anyio + requests suites on the old scheduler code, to capture the 97% hang stack.

## Next
- Fix: zero-timeout polls (select(0)) must let time and other threads progress (anyio checkpoint spin).
- Fix: outside activity (unmanaged server thread) must not be declared a deadlock after 5 s.
- Fix: asynchronous exceptions (pytest-timeout) inside scheduler waits.

## Handover (2026-11-17, coordinator)
The fix-round agent was stopped and the work moves to a separate long-running session. Patches 0001-0017 on base 1573079 are the whole state (worktree clean). Last findings of the stopped agent, not yet committed as fixes: requests passes when the scheduler's wait bound is longer (only the 4 Level 0 network tests remain broken there); the SIGABRT stack dump on timeout works under --det. Next: fix the anyio worker-pool breakages and hangs, then re-measure.
