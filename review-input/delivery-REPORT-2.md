DONE (R-007 FIX 1-4 fixed. Exit at the final code, flags `--det --det-threads`: 0 tests and 0 runs broken in calm mode on 26 suites; 0 hangs in 1,153 runs; easypy 10/10 with one fingerprint; slowdown median +1.0%, worst +16.4%, on the 5 most thread-heavy popular suites)

# L1 threads fix round 2 (after review R-007) · report

Engine: `Mircoguidetti/fenvix-engine-cli`, branch `claude/l1-threads-fix`. **Final engine code `c01795a`**, measured as `bfd88ab` (that commit only changes `run.json`).
Re-measured on GitHub Actions: round **f5**, run 44259573904. All 29 jobs succeeded, on 26 suites plus the easypy corpus. Raw results: `tracks/l1-threads-fix/results/f5/`. Aggregate: `tracks/l1-threads-fix/f5-aggregate/`.
I re-ran all suites, not only arrow and easypy. FIX 1 changes what `--det-threads` does by default, and FIX 3 changes every seed run, so the old numbers no longer described the code.

Every number is MEASURED on Actions (f5, or f4 for "before") unless labelled otherwise.

## FIX 1. easypy: flag set, like-for-like baseline, `--det-threads` implies `--det-urandom`

Done: `--det-threads` now implies deterministic `os.urandom` / `uuid4` / `secrets`. `--det-threads-real-urandom` opts out.
Why: a worker thread that draws entropy (easypy draws `uuid4()` per worker) makes every fingerprint differ, so an L1 user would get no replay without knowing to add a second flag.
Test: `test_det_threads_implies_deterministic_entropy` (`tests/test_engine_frames.py`). It fails before (3 fingerprints in 3 runs) and passes after (1 fingerprint; with the opt-out, 2 in 2).

easypy, the 10 Block 2 thread tests, each with its minimised order. "one fp" = the tests with a single fingerprint over the runs.

| flags | before (f4) | after (f5) |
|---|---|---|
| `--det` (Level 0) | 0/10 (10 fingerprints each) | 0/10 |
| `--det --det-urandom` (Level 0 + entropy), like for like | 7/10 quiet, 5/10 under load | 8/10 quiet, 6/10 under load |
| `--det --det-threads` | 0/10 (10 fingerprints each) | **10/10** quiet |
| `--det --det-threads --det-urandom` | 10/10 quiet, 10/10 under load | 10/10 quiet, 10/10 under load |

What Level 1 itself adds, like for like (det-u vs l1-u):
* after (f5): 2/10 quiet (`test_multiobject_1`: 8 fingerprints → 1; `test_logged_condition`: 4 → 1) and 4/10 under load;
* before (f4): 3/10 quiet and 5/10 under load.

The other tests are deterministic once entropy is fixed: their failure comes from the order (a RecursionError), not from the interleaving.

Replay: the 9 tests that fail replay 10/10 with one fingerprint. The 10th now passes (FIX 4).

## FIX 2. Seed slowdown: one value per suite

`harness/l1_threads_final_table.py` now takes one value per suite (the median over that suite's seeds).
Test: `test_seed_slowdown_takes_one_value_per_suite` (`tests/test_harness_l1.py`). It fails before and passes after.

| seed slowdown vs `--det`, 5 most thread-heavy popular suites | before (f4 data) | after (f5) |
|---|---|---|
| as reported in REPORT.md (pooled) | median +41.3% | n/a |
| corrected (one value per suite) | **median +78.5%, worst +970%** (more-itertools) | **median +7.4%, worst +255%** (more-itertools) |

The drop from f4 to f5 is the FIX 3 engine change. `sys.monitoring` sends line events only from project code objects, while `sys.settrace` called detpy on every frame.
Preemption still happens:
* more-itertools seed 1: 499k scheduling decisions per run (535k in f4);
* anyio seed 1: 10.1k (10.0k in f4).

Per suite, f5:
* anyio +0.5 / +1.9 / +1.9% (seeds 1, 2, 3);
* requests -11.5 / -10.7 / -10.6%;
* structlog +7.4%;
* networkx +90.0%;
* more-itertools +254.6%.

## FIX 3. Seed mode replaced the project's trace function (coverage)

Engine:
* **Python 3.12+**: line preemption uses `sys.monitoring` with its own tool id (`detpy._core.LineMonitor`, C callbacks, a per-thread budget). `sys.settrace` is never touched.
* **Older Pythons**: the line tracer is chained to the trace function already installed, which is restored afterwards. `sys.gettrace()` returns the chain while a test runs.

Test: `test_preemption_keeps_the_projects_trace_function[0,1,2]`. Seeds 1 and 2 fail before; all pass after. The Python 3.9 path was checked by hand in the easypy venv: seeds 0, 1, 2 pass (MEASURED, local).

Harness:
* a run that exits non-zero with no failing test (coverage's `--cov-fail-under`) counts as a **broken run** of its mode (`broken_runs`), unless the reference mode fails the same way;
* output tails are kept for every non-zero exit.

Test: `test_a_run_that_fails_as_a_session_is_a_broken_run`. It fails before (no such function) and passes after.

| arrow (`--cov-fail-under=99`) | before | after (f5) |
|---|---|---|
| seed 1 | exit 1, 0 failed, coverage 39.24% (f4; the reviewer reproduced it locally) | exit 0, 1904 passed |
| seeds 2, 3 | not run | exit 0, 1904 passed |
| locally, seeds 1 and 2 | — | exit 0, coverage 99.93%, the same as calm (MEASURED, local) |

All suites in f5: **0 broken runs** in every mode (calm, every seed, `--det`), and **0 broken tests** in every seed mode. Seeds 1-3 ran on anyio, requests, attrs, dateutil and arrow; seed 1 on the other 21.

## FIX 4. easypy `test_multiobject_logging`: detpy frames visible to stack inspection

Cause: easypy reads other threads' stacks with `sys._current_frames()` and logs the first frame outside `threading`. In a plain run that is the caller of `time.sleep`. Under detpy it was the engine's own frame:
* `clock.py sleep` under `--det`;
* `threads.py _wait_gate` under `--det-threads`.

Fix (`python/detpy/frames.py`): under `--det`, `sys._current_frames()` returns each thread's innermost frame outside detpy. Threads that run only detpy code (the watchdog) are left out.
Test: `test_stack_inspection_does_not_see_detpy[plain,det,det-threads]` (`tests/test_engine_frames.py`). `det` and `det-threads` fail before; all pass after.

| `test_multiobject_logging` | plain | `--det` | `--det --det-threads` | `--det --det-threads --det-urandom` |
|---|---|---|---|---|
| before (f4) | passed 10/10 | failed 10/10 | failed 10/10 | failed 10/10 |
| after (f5) | passed 10/10 | **passed 10/10** | **passed 10/10** | **passed 10/10**, 1 fingerprint (5/5 also under load) |

The easypy full suite fails the same 48 tests in plain, `--det` and `--det --det-threads` (MEASURED, local, py3.9).

## Also fixed in this round (found by the engine test suite under load)

`test_socket_timeout_longer_than_the_outside_reply` failed once in a loaded local run.
Cause: an unmanaged thread's `time.sleep` advances the shared virtual clock at once, so a socket timeout counted on that clock against an outside server lost that time. A 4 s timeout fired after about 1 s for a reply that takes 3 s.
Fix: such a timeout counts real time from the start of the wait.
Test: the same test, tightened to a 4 s timeout. It fails before 2/2 and passes after 3/3.
requests is unchanged locally: 4 failed, the 4 Level 0 network tests.

## Exit, final code (f5)

| exit | result |
|---|---|
| tests broken by `--det --det-threads` (calm), 26 suites | **0**. Also 0 sometimes-broken and **0 broken runs** |
| tests and runs broken by exploration seeds | **0 / 0** (66 seeded runs) |
| hangs | **0**. Suite runs: 40 plain, 40 det, 40 calm, 66 seeded, 26 warm-up. Corpus: 941 runs |
| easypy, `--det --det-threads` | **10/10 one fingerprint** quiet. With `--det-urandom` also given explicitly: 10/10 quiet and 10/10 under load. 9 tests fail deterministically from their order and replay 10/10; `test_multiobject_logging` passes, as in plain |
| slowdown calm vs `--det`, 5 most thread-heavy popular suites (by managed threads; easypy, 93 threads, is left out) | anyio -0.6% (656), more-itertools +16.4% (167), networkx +1.0% (65), structlog +5.7% (41), requests -11.5% (35). **Median +1.0%, worst +16.4%**, NOISY: one runner per project, 3 runs. f4 had median +2.6% and worst +6.9%, with more-itertools between -5% and +32% |
| same, vs plain pytest | median +12.4%, worst structlog +88.6% (a 1.4 s suite; `--det` alone costs +78%) |
| seeds vs `--det`, same 5, one value per suite | median +7.4%, worst +255% |
| all 26 suites, calm vs `--det` | median +1.2%, range -58% (easypy: virtual sleeps) to +16.4% |
| engine tests | **139 passed, 5 skipped** on Actions. The skips are listed now (`-rs`): pytest_asyncio (1), time_machine (1), pytest_django (3). The uvloop test runs; uvloop has been installed in CI since `1e13f29` |

## Notes on the review's other points

* Wording: "5 most thread-heavy **popular** suites" (easypy left out), as suggested.
* FIX 1 "or justify": I made the flag implied rather than keep two flags. The cost was one full re-run, done.
* The `0adc057` fix test (finalizer re-entry) fails with `RuntimeError: release unlocked lock`, not a hang: the reviewer is right. At the base before my changes, the same re-entry self-deadlocks (a hang); with my intermediate code it raised. The commit message names both.
* DeadlockError still names the waiting threads and lock addresses, not the holders. Not changed; noted as a usability item.
* Level 0 items unchanged and still open: jinja's mtime test across consecutive `--det` runs, jinja `[trio]` 20, anyio 3, requests 4 broken by `--det`, the more-itertools `TestConcurrentTee` convoy.

## Links

* Branch: https://github.com/Mircoguidetti/fenvix-engine-cli/tree/claude/l1-threads-fix. Fix commits:
  * `8906379`: frames, FIX 4;
  * `5a44aff`: urandom, FIX 1;
  * `6cd74c4`: sys.monitoring, harness, table, FIX 2 and 3;
  * `c01795a`: real-time socket timeout.
  * Aggregate `013f8ae`.
* Run: https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44259573904
* Tests: `tests/test_engine_frames.py`, `tests/test_harness_l1.py`, `tests/test_threads_blocking.py`
