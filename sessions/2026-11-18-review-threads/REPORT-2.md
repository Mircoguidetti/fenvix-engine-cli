FIX 1

# R-007 round 2 · Re-check of FIX 1-4 (Block 3, L1 threads, `--det-threads`)

Checked: `review-input/delivery-REPORT-2.md` (DONE) against my round-1 report `review-input/R-007-REPORT.md` (FIX 1-4), prompt P-012.
Code: `c01795a` (final engine code). `git diff c01795a bfd88ab` changes only `tracks/l1-threads-fix/run.json`.
"Before" means `5a456f5`, the code I reviewed in round 1 (`3a5ce02` plus results).
Build: uv venv, `maturin develop --release`, as in the CI tests job. abi3 wheels of both commits were installed into project venvs. Local Pythons: 3.13.18 and 3.9.25.
Raw data: run 44259573904. Head `bfd88ab`, conclusion success (checked with one GitHub API call). Files: `tracks/l1-threads-fix/results/f5/`.

Result: FIX 1, FIX 2 and FIX 3 are fixed. Each has a test that fails before and passes after, and the numbers match the raw data. FIX 4 is fixed for the false failure it named: easypy `test_multiobject_logging` now passes in every mode, both locally and on Actions. But the fix's own claim, "detpy's frames are invisible to stack inspection of other threads", is still false under `--det-threads`. One failing test shows it (the new FIX 1 below). It is narrow and does not change any exit number.

## Tests: fail before, pass after (MEASURED, local, py3.13)

The new test files from `c01795a` were copied onto `5a456f5` and run there.

| test | before (`5a456f5`) | after (`c01795a`) |
|---|---|---|
| `test_engine_frames.py::test_stack_inspection_does_not_see_detpy[plain]` | passed | passed |
| `...[det]` | **failed**: top frame `detpy/clock.py sleep` | passed |
| `...[det-threads]` | **failed**: top frame `detpy/threads.py _wait_gate` | passed |
| `test_engine_frames.py::test_det_threads_implies_deterministic_entropy` | **failed**: 3 fingerprints in 3 runs | passed |
| `test_harness_l1.py::test_a_run_that_fails_as_a_session_is_a_broken_run` | **failed**: no `broken_runs` | passed |
| `test_harness_l1.py::test_seed_slowdown_takes_one_value_per_suite` | **failed**: median 10.0 | passed |
| `test_threads_blocking.py::test_preemption_keeps_the_projects_trace_function[0]` | passed | passed |
| `...[1]`, `...[2]` | **failed** | passed |
| `test_threads_blocking.py::test_waits_on_outside_threads_are_real_waits_not_deadlocks` (holds the tightened 4 s socket test) | **failed** | passed |

The 4 new test files on `c01795a` give 23 passed. The full engine suite on Actions gives 139 passed and 5 skipped (DECLARED from `results/f5/engine-tests.txt`). The 5 skips are listed with reasons. The uvloop test now runs. The full local run is in the last section.

## FIX 1: easypy, the flag set, and `--det-threads` implies `--det-urandom`: FIXED

Recomputed from `idoft-easypy.corpus.json`. A test counts as "one fp" when every run has the same, non-null fingerprint.

| mode | f4 | f5 |
|---|---|---|
| `det` | 0/10 | 0/10 |
| `det-u` quiet / loaded | 7/10 / 5/10 | **8/10 / 6/10** |
| `l1` (`--det --det-threads`) | 0/10 | **10/10** |
| `l1-u` quiet / loaded | 10/10 / 10/10 | **10/10 / 10/10** |

All numbers in the delivery report match (MEASURED, Actions, recomputed).

- **What L1 itself adds, like for like, in f5:** 2/10 quiet (`test_multiobject_1`: 8 fingerprints → 1; `test_logged_condition`: 4 → 1) and 4/10 under load (adds `test_multiobject_exceptions` and `test_thread_stacks`, 2 fingerprints each). This matches the delivery report.
- **The implication is real:** for all 10 tests, the `l1`, `l1-u` and `loaded-l1-u` fingerprint sets are identical.
- **Confirm:** 9 tests, 10/10 fails, 1 fingerprint each.
- **Hangs:** 941 runs, 0 timeouts.

Local check, easypy@9501c3e, py3.9, harness orders, 3 runs per cell (MEASURED):

| flags | before | after |
|---|---|---|
| `--det --det-threads` | 3 fingerprints for each of the 10 tests (0/10) | **1 fingerprint for each (10/10)** |
| `--det --det-urandom` | 8/10 | 9/10 |

The flag set is now stated in the exit line, and "Level 0 alone" has been replaced by the like-for-like rows.

## FIX 2: seed slowdown, one value per suite: FIXED

- `l1_threads_final_table.py` on `results/f5` reproduces `f5-aggregate/final-table.json` exactly.
- My own recomputation from the raw timing, as the median of each mode over its runs vs `--det`, MEASURED, NOISY (one runner per project):

| suite | seed slowdown vs `--det` (f5) |
|---|---|
| anyio | +0.5 / +1.9 / +1.9% (seeds 1, 2, 3), suite value +1.9% |
| requests | -11.5 / -10.7 / -10.6%, suite value -10.7% |
| structlog | +7.4% |
| networkx | +90.0% |
| more-itertools | +254.6% |

- **Median +7.4%, worst +255%**, as reported.
- The same script on f4 gives median +78.5%, matching my round-1 figure.
- Preemption still happens:
  - more-itertools seed 1: 498,602 decisions (535,108 in f4);
  - anyio seed 1: about 10.0k (about 9.9k in f4);
  - networkx: 2,131 (2,472 in f4).

  The calm numbers are unchanged (7,356 / 256 / 274), so the slowdown drop does not come from preemption being lost.
- Calm vs `--det`, 5 popular heavy suites: anyio -0.6, more-itertools +16.4, networkx +1.0, structlog +5.7, requests -11.5. **Median +1.0%, worst +16.4%.**
- Same suites, calm vs plain: median +12.4%, worst +88.6% (structlog).
- All 26 suites: median +1.2%, range -58.1% (easypy) to +16.4%.
- All of these match the delivery report (MEASURED, Actions, NOISY).

## FIX 3: seed mode and coverage: FIXED (engine and harness)

arrow@2224255, `pytest -p no:randomly --det --det-threads --det-threads-seed=N`, with arrow's own `--cov-fail-under=99` (MEASURED, local):

| | seed 0 | seed 1 | seed 2 |
|---|---|---|---|
| before, py3.13 | exit 0 | **exit 1, coverage 39.24%**, 1904 passed | — |
| after, py3.13 (`sys.monitoring` path) | exit 0, 99.93% | exit 0, 99.93% | exit 0, 99.93% |
| after, py3.9 (chained `settrace` path) | exit 0, 99.93% | exit 0, 99.93% | exit 0, 99.93% |

- **Actions f5:** arrow exits 0 in seeds 1, 2 and 3.
- **0 broken runs:** no `session_failed` run in any mode of any suite, and every mode's exit set equals the `--det` exit set in all 26 suites.
- **Hangs:** 0 timeouts in 40 plain, 40 det, 40 calm and 66 seeded suite runs (counted from the raw files).
- **Broken tests:** 0 tests broken by `l1` or by any seed, and 0 "sometimes".

The harness rule (`broken_runs`) does what the test says. A residual limit (NOTE): a run that fails coverage and also has a failing test is not counted as a session failure. In practice the per-test comparison still flags that run.

## FIX 4: detpy frames and stack inspection: the named false failure is FIXED; the claim is not fully true (new FIX 1)

easypy `tests/test_concurrency.py::test_multiobject_logging`, run alone, py3.9 (MEASURED, local):

| flags | before | after |
|---|---|---|
| plain | passed | passed |
| `--det` | failed | **passed** |
| `--det --det-threads` | failed | **passed** |
| `--det --det-threads --det-urandom` | failed | **passed** |
| `--det --det-threads --det-threads-seed=1` | failed | **passed** |

- **On Actions (f5):** the test passes 10/10 in `det`, `det-u`, `l1` and `l1-u`, and 5/5 loaded, with 1 fingerprint in every L1 mode.
- **What remains:** the delivered fix hides detpy only at the top of each thread's stack. Under `--det-threads`, every managed worker still has `detpy/threads.py boot` as its bottom frame, below threading's `_bootstrap`.
- **Example:** `traceback.extract_stack(sys._current_frames()[worker.ident])` gives:

| mode | stack |
|---|---|
| plain and `--det` | `threading.py _bootstrap`, `_bootstrap_inner`, `run`, `test_stack.py worker` |
| `--det --det-threads` | **`detpy/threads.py boot`**, then `threading.py _bootstrap`, `_bootstrap_inner`, `run`, `worker` |

- The worker's own `traceback.format_stack()` and `logging` with `stack_info=True` show the same extra frame.

## FIX items (round 2)

**FIX 1. Under `--det-threads`, a managed worker's whole stack still shows a detpy frame (`threads.py boot`). This contradicts the FIX 4 commit's claim that detpy's frames are invisible to stack inspection of other threads.**
- Test: `tests/test_review_r007b.py::test_whole_stack_of_another_thread_does_not_see_detpy[det-threads]`, on this branch. It fails on `c01795a` with `[('…/python/detpy/threads.py', 'boot')]`; `[plain]` and `[det]` pass (MEASURED, local, py3.13).
- Why it matters: thread dumps and tests that format other threads' stacks see a frame the engine made, only under L1. This is the defect class FIX 4 was about. It changes no exit number: the 10 easypy targets, the 26 suites and their broken counts all stand.
- Proposed remedy: start the managed thread through a C trampoline in `detpy._core`, as was done for `LineTracer`/`LineMonitor`. It would run the Python prologue (gate, tracer install), return, and then call `function`, with the epilogue in the C frame's cleanup, so no Python frame from detpy stays under the thread. A cheaper partial option is to document the frame. The test above decides either way.

## Notes (no fix needed)

- **Python < 3.12 with coverage's C tracer: exploration seeds barely preempt. This is not a regression: the same happens on `5a456f5`.**
  - Coverage's `CTracer`, once called, installs itself back as the C trace function on the first call event. That replaces detpy's chain: inside the test body, `sys.gettrace()` is the `CTracer`.
  - Worker threads also lose the chain to threading's own `settrace` hook in `_bootstrap_inner`, which runs after detpy's `boot` installs the tracer.
  - Measured, py3.9, a 4-thread lost-update loop at seed 1:

| py3.9, seed 1 | decisions | final count |
|---|---|---|
| without `--cov` | 186 | 7,027 (lost updates) |
| with `--cov`, after the fix | **3** | 12,000 (race hidden) |
| with `--cov`, before the fix | **3** | 12,000 (race hidden), and coverage 50% |

  - On py3.13 (`sys.monitoring`), `--cov` changes nothing: 186 decisions, the same fingerprint.
  - None of the f5 data is affected: easypy, the only 3.9 suite, does not run coverage.
  - The delivered test uses a pure-Python tracer that does not reinstall itself, so it cannot show this.
  - Cheapest deciding test: the loop above under `--cov` on 3.9, asserting that the decision count matches the run without `--cov`.
  - Possible remedy: `threading.settrace` chaining, plus re-asserting the chain at preemption-sensitive points, or document "seeds on < 3.12 need coverage off".
- **The `det-u` like-for-like rows are noisy at this sample size.** Locally, `test_multiobject_1` is the only det-u multi-fingerprint test after the fix (9/10), and `test_thread_stacks` varied before (8/10). The reported 8/10 and 6/10 match the raw data. The "L1 adds 2-4 of 10" figure moves by about 1 between rounds.
- **Socket timeout fix (`c01795a`, outside the 4 items):** its test fails before and passes after (see the table above).

## Local engine suite

`pytest tests -q -rs -p no:randomly` on `c01795a`, py3.13, with uvloop installed: **139 passed, 5 skipped**, 438 s (MEASURED, local; the timing is NOISY). This matches Actions f5. The skips are the same 5: pytest_asyncio 1, time_machine 1, pytest_django 3.

## Housekeeping

- All my work ran in scratchpad worktrees and venvs outside the repository, which I removed at the end.
- The only file added to this branch, besides this report, is `tests/test_review_r007b.py`.
