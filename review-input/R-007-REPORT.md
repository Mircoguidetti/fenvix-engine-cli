FIX 4

# R-007 · Independent review of Block 3 (L1 threads, `--det-threads`)

Reviewed: `fenvix-brain-cli/sessions/2026-11-17-l1-threads/REPORT.md` (DONE), prompt P-012 and the handover exit in `tracks/l1-threads/STATUS.md` (origin/claude/loving-maxwell-58mv2w).
Code: fenvix-engine-cli `3a5ce02` (detached worktree). Built like the CI tests job: uv venv, Python 3.13.12, `maturin develop --release`. For the suites, `maturin build --release` produced an abi3 wheel that was installed in each project venv.
Raw data: run 44177164657 (head `78a9295`, the same code as `3a5ce02` plus `run.json`; conclusion success, all 29 jobs success, verified with `gh`). Files are in `tracks/l1-threads-fix/results/f4/*.json` on `origin/claude/l1-threads-fix`. The 26 result names match the `suites` list in `harness/l1/threads-corpus.json`.

## Verdict on the Block 3 exit

The calm-mode exit holds: 0 broken, no hangs, and slowdown is reported. The easypy exit holds only with `--det-urandom` added. Four claims need correcting (FIX 1-4). None of them reopens the calm-mode exit as the harness defines it ("passes in `--det`, fails in calm"). FIX 4 shows that this definition hides one false failure made by the engine.

| check | result | label |
|---|---|---|
| 1a. tests broken by calm `--det-threads`, 26 suites (25 popular + easypy) | **0**. In every one of the 26 suites, every `l1` run has exactly the `--det` passed count. Where test names exist, the `l1` failures are a subset of `broken_by_det`: anyio 2 of 3, jinja 20/20, requests 4/4. Rich's 7 failures also fail in plain. dateutil (3) and easypy (49) fail identically in plain, `--det` and `l1`; that is checked at the count level only, because `--det` rows store no test names | MEASURED (Actions, recomputed) |
| 1b. hangs | **0** `timed_out` in 40 plain, 40 det, 40 calm, 64 seeded and 26 warm-up suite runs. **0** in 950 easypy corpus runs | MEASURED (Actions, recomputed) |
| 1c. easypy 10 thread tests, one fingerprint | **10/10** in `l1-u` (`--det --det-threads --det-urandom`): 10 quiet runs and 5 loaded runs, and each replays 10/10 with 1 fingerprint: 9 confirm runs plus the seed-1 explore run, which has the same fingerprint. **0/10** in `l1` (`--det --det-threads`): 10 fingerprints per test. See FIX 1 | MEASURED (Actions, recomputed) |
| 1d. slowdown calm vs `--det`, 5 heaviest popular suites | anyio -2.7, more-itertools -4.6, networkx +2.6, structlog +5.9, requests +6.9: **median +2.6%, worst +6.9%**, as reported. vs plain: median +12.1%, worst +96%, as reported | MEASURED (Actions, recomputed) |
| 1e. seed slowdown, same 5 | reported "median +41.3%". That is the median of 9 pooled values (anyio and requests count 3 times each). Per suite at seed 1: 9.0, 36.1, 78.5, 282.0, 969.7, so the **median is +78.5%**. See FIX 2 | MEASURED (recomputed) |
| 2a. easypy, 10 tests × 3 runs, harness orders (`--det-order`), Python 3.9, sha 9501c3e | `--det --det-threads --det-urandom`: **1 fingerprint each, 10/10**. `--det --det-threads`: **3 fingerprints in 3 runs for every test (0/10)**. `--det --det-urandom` (no L1): 1 fingerprint on 9/10. 0 timeouts | MEASURED (local) |
| 2b. anyio `tests/test_to_thread.py`, calm, 3 runs | 84 passed, 15 skipped, exit 0, 6-7 s each. The stats line, read on run 1 only, shows 0 deadlocks and 0 escapes. `--det` alone: 1 failed (`test_asyncio_worker_pool_concurrent_loops`, which passes in plain) | MEASURED (local) |
| 2c. requests, whole suite (covers the 5 tests that broke before) | calm: 615 passed, 4 failed (the 4 `TestTimeout` connect tests, which also fail under `--det`), 85 s, 0 deadlocks. `--det`: the same 4, 81 s. 0 broken by threads, no hang | MEASURED (local) |
| 3. fix commits: fix reverse-applied on `3a5ce02`, then the commit's own test run | `9de31a8` (thread-id reuse): fails before with DeadlockError, passes after. `0adc057` (finalizer re-entry): fails before with `RuntimeError: release unlocked lock`, both reverse-applied on HEAD and at the original parent. It does not hang (the claimed symptom was a hang), and it passes after. `88a425c` (gc callback in the clock): before, it hangs and pytester kills it at 60 s; it passes after. Bonus, `1e13f29` (uvloop): fails before and passes after, but only with uvloop installed (see notes) | MEASURED (local) |
| 4. watchdog on a true two-thread deadlock (lock A/B with a Barrier) | `DeadlockError`, and the whole pytest process exits in about 1 s of wall time (pytest itself reports 0.03 s). The message names MainThread (join of worker-A), worker-A and worker-B, each with "waits for lock 0x…" | MEASURED (local) |

## FIX items

**FIX 1. easypy: the report's "Level 0 alone: 0/10" is not a like-for-like baseline. The exit holds only with `--det-urandom`.**
- The 10/10 result is `l1-u`, which adds `--det-urandom`. The report's "Level 0 alone" figure is `det`, which has neither L1 nor urandom.
- Like for like (`det-u` vs `l1-u`), Level 0 + urandom already gives one fingerprint on **7/10** quiet runs and **5/10** under load on Actions, and on **9/10** locally (3 runs). L1's own share is therefore 3/10 quiet and 5/10 under load on Actions.
- Without `--det-urandom`, `--det --det-threads` gives 0/10 on Actions (10 fingerprints per test) and 0/10 locally.
- The fix: state the flag set in the exit line, replace "Level 0 alone 0/10" with the `det-u` numbers, and decide whether `--det-threads` should imply `--det-urandom`.
- Repro, in an easypy@9501c3e checkout, py3.9, with the order file built from `threads-corpus.json` `orders`:
  `python -m pytest -p no:randomly --det-order=order-0.txt --det --det-threads --det-outcomes=o.json` (run 3 times: 3 different `fingerprints[target]`)
  `python -m pytest -p no:randomly --det-order=order-0.txt --det --det-urandom --det-outcomes=o.json` (run 3 times: 1 fingerprint)

**FIX 2. The seed slowdown median is understated.**
- `harness/l1_threads_final_table.py` line 41 pools all seed values: 3 for anyio and requests, 1 for the others.
- One value per suite (seed 1) gives a **median of +78.5%**, not +41.3%. The worst is +970%, as reported.
- Repro: `final-table.json` → `seed_vs_det["1"]` for anyio, more-itertools, networkx, structlog, requests.

**FIX 3. "0 tests broken by exploration seeds" hides a failed seed run: seed mode disables coverage tracing.**
- In f4, arrow `l1-s1` exited 1 with 1904 passed and 0 failed. The per-test metric counts it as clean.
- Cause, reproduced locally: with `--det-threads-seed=N`, `_install_tracer` calls `sys.settrace(LineTracer…)` at every test start and `sys.settrace(None)` at the end (`threads.py` 1244, 1092, 1906). This replaces coverage's tracer.
- Effect: arrow's `--cov-fail-under=99` fails at 39.24%.
- Calm mode is not affected (99.93%, exit 0).
- Repro, in arrow@2224255c4acc, py3.13, `pip install -e .[test]` + detpy:
  `pytest -p no:randomly --det --det-threads --det-threads-seed=1` gives exit 1, "FAIL Required test coverage of 99% not reached. Total coverage: 39.24%"
  `--det-threads-seed=0` gives exit 0
- The fix: disclose this in the report. Have the harness count a non-zero exit with no failed tests as a broken run. Engine follow-up: chain the previous trace function, or use `sys.monitoring` on 3.12+.

**FIX 4. easypy `test_multiobject_logging` is a detpy false failure under L1 too. Calling it only "the known Level 0 false failure" is incomplete.**
- It passes in plain pytest (baseline `passed=10`). It fails under `--det` because the test's stack inspection sees the frame `detpy/clock.py:251, in sleep`.
- Under calm `--det-threads` it fails on a different detpy frame: `detpy/threads.py:547, in _wait_gate`. The f4 `tests.csv` marks it `artifact=True`.
- `broken_by_l1` cannot see it, because `--det` already fails it.
- So the "10/10 one fingerprint" is 9 deterministic real failures plus 1 failure the engine made. Fixing the Level 0 clock frame alone would not make it pass under L1 (my inference from the two messages).
- The fix: say this in the report, and treat L1's own frame visible to user stack inspection as an L1 defect.
- Repro, in easypy@9501c3e, py3.9, run alone:
  `pytest -p no:randomly tests/test_concurrency.py::test_multiobject_logging` passes
  `... --det` fails (`clock.py:251, in sleep`)
  `... --det --det-threads --det-urandom` fails (`threads.py:547, in _wait_gate`)

## Notes (no fix needed)

- "5 most thread-heavy suites (by managed threads)" leaves out easypy, which has 93 managed threads and ranks 3rd. Including it (-66%) would lower the median, so leaving it out is the conservative choice. Better wording: "5 most thread-heavy popular suites".
- The worst calm slowdown of +6.9% rests on 3 runs. more-itertools `--det` ranged from 19.3 to 28.3 s, and the report labels this as noisy (DECLARED by the report, consistent with the raw data).
- The uvloop fix test (`test_a_uvloop_loop_runs_outside_the_scheduler`) is skipped in the CI tests job because uvloop is not installed there. Locally with uvloop it fails without the fix and passes with it. CI should add uvloop so the test runs.
- Some rows in "each fix with a test" are not engine fixes with a fails-before test: the jinja row is a harness fix, and the more-itertools speed-fix guard passes before too. The report says both.
- The DeadlockError lists each waiting thread and lock address, but not which thread holds each lock. This is a usability improvement, not a defect.
- easypy: 9 of the 10 targets pass when run alone (`alone-l1-u`). Their failure is the order-dependent RecursionError, so "replayed" here means a deterministic failure, not a found race.
- Engine tests: 130 passed, 5 skipped on Actions (DECLARED from `engine-tests.txt`). Locally, `tests/test_threads_blocking.py` gives 13 passed and 1 skipped (uvloop).
- Not rechecked: the "before" numbers (anyio +237%, the earlier deadlock counts per run, the f1 seed hangs), "f1 and f2 agree with f4", and the local `TestConcurrentTee` bimodality. All are DECLARED by the report.
- Housekeeping: my first build accidentally ran inside another session's scratchpad worktree `wt` (Node L0 review, created 2 minutes earlier). I removed the `.venv`, `target/maturin` and `python/detpy/_core.abi3.so` that I added. Its tracked files were never touched. Its owner has since removed that worktree, so none of my outputs remain. My own worktree `r007-wt` and every file I created are removed.
