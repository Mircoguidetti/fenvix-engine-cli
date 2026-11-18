DONE (Block 3 exit for `--det-threads` met at the final code: 0 tests broken in calm mode on all 26 suites, 0 hangs in 1,080 runs, easypy 10/10 with one fingerprint, slowdown median +2.6% / worst +6.9% on the 5 most thread-heavy suites)

# L1 threads fix round (P-012 continuation) · final report

Engine: `Mircoguidetti/fenvix-engine-cli`, branch `claude/l1-threads-fix`. Base `1573079` + patches 0001-0017, then 14 fix commits. **Final engine code `3a5ce02`**, measured as `78a9295` (that commit only changes `run.json`).
Measurements: GitHub Actions, workflow `.github/workflows/l1-threads-fix.yml`, one runner per project.
**Final round f4**: run 44177164657. Raw results are in `tracks/l1-threads-fix/results/f4/` and the aggregate in `tracks/l1-threads-fix/f4-aggregate/`.
Earlier rounds f1 (code `9eaa926`, all suites) and f2 (code `665a996`, 19 suites, then cancelled to free the queue) agree with f4 wherever both exist.

## Exit numbers (all MEASURED on Actions, round f4, final code)

| exit | result |
|---|---|
| tests broken by `--det-threads`, calm, all 25 popular suites + easypy | **0 of 26 suites** (before: anyio 9, requests 5, plus jinja 1 from a Level 0 leak). 7 suites ran 3 rounds (anyio, requests, more-itertools, networkx, structlog, attrs, dateutil), 19 ran 1 round, as the prompt asked. "Broken" = passes in every `--det` run and fails in every calm run; also 0 that fail in some calm run |
| tests broken by exploration seeds | **0**: anyio, requests, attrs and dateutil with seeds 1, 2, 3 (3 runs each); seed 1 on the other 22. Before: structlog 1, anyio 4-5, requests 5 |
| hangs | **0**. Suite runs: 40 calm, 64 seeded and 26 warm-up runs (`--det --det-threads`), 0 hit the timeout. easypy corpus: 950 runs, 0 timeouts. Before: anyio 2 of 3 calm runs, 1 of 3 requests seed-1 runs; f1 also showed attrs and dateutil seed-1 hangs (a Level 0 clock bug, fixed) |
| deadlocks reported in calm runs | anyio 0 (before 6 per run), requests 0 (before 6) |
| easypy, 10 Block 2 thread tests | **10/10 with one fingerprint** over 10 quiet runs and over 5 runs under CPU load (`--det --det-threads --det-urandom`); each replays 10/10 with one fingerprint. Level 0 alone: 0/10 (10 fingerprints each). 9/10 pass when run alone; the 10th (`test_multiobject_logging`) is the known Level 0 false failure |
| slowdown vs `--det`, 5 most thread-heavy suites (by managed threads) | anyio -2.7% (656 threads), more-itertools -4.6% (167), networkx +2.6% (65), structlog +5.9% (41), requests +6.9% (35). **Median +2.6%, worst +6.9%.** Before: anyio at least +237% (lower bound; 2 runs hung), more-itertools +27.8%, median +1.3% |
| same, vs plain pytest | median +12.1%, worst structlog +96% (a 1.4 s suite; `--det` alone costs +85% there) |
| slowdown of exploration seeds, same 5 | median +41.3%, worst more-itertools +970% (line preemption: 535k scheduling decisions per run) |
| engine test suite | 130 passed, 5 skipped on Actions (was 115 passed). Locally (this container): 128 passed, 5 skipped before the last 2 tests were added |

Noise labels on the slowdown: one runner per project, 3 runs for these 5 suites. The more-itertools `--det` runs swung between 19 and 28 s in f4: one test (`TestConcurrentTee`, 100 threads on one lock) is bimodal under plain `--det` (1.2 s or over 25 s, MEASURED locally with both the old and the new clock code). Calm `--det-threads` was steady at 22.4-22.7 s. In f2 the same suite measured +32.4%, so its slowdown lies between -5% and +32% (MEASURED, NOISY). Over all 26 suites, calm vs `--det`: median +1.1%, range -66% (easypy: virtual sleeps) to +10.2% (humanize, one run).

## What was wrong and what changed (each fix with a test that fails or hangs before and passes after, in `tests/test_threads_blocking.py`)

| found on | cause | fix |
|---|---|---|
| anyio `test_to_thread.py` (10 failed + hang) | the event-loop thread spins on `await checkpoint()`, a zero-timeout `select`. That was no switch point, so the worker thread it waited for never got the baton | zero-timeout polls are switch points: `select(0)`, a failed non-blocking acquire, `sleep(0)`, `Event.is_set()` false, `Queue.get_nowait()` empty, `is_alive()` true. Runnable threads go first (calm: the poller goes last). If none can run, the poll is charged virtual time (1 µs doubling, at most 1 ms), so due timers fire |
| requests, 5 tests (DeadlockError) | the OS reused thread ids. Finished managed threads (`test_lowlevel.py` servers) left their ids behind, and pytest-httpbin's unmanaged server threads were taken for managed ones. The scheduler saw no outside work and declared a deadlock after 5 s while the server was still answering a `delay/10` request | an id is forgotten when its thread exits. A wait on outside work (unmanaged thread, child process, escaped thread) is a real wait, and a socket timeout against it is real time. Such a wait is bounded by `--det-threads-stuck` (60 s), after which a DeadlockError names the waiting threads and every thread outside the scheduler |
| pure-Python spin on a flag | no switch point at all: the watchdog never escaped a holder in state R | holder escaped after 1 s while another thread is runnable (10 s if the others only wait for time), recorded as uncontrolled |
| anyio full suite (later tests) | my first fix introduced a watchdog TypeError that killed the watchdog thread | fixed; the watchdog restarts after any error |
| pytest-timeout / KeyboardInterrupt | an asynchronous exception while waiting for the baton corrupted the scheduler | the thread keeps running outside the scheduler until its next controlled point |
| requests seeds (the historical hang) | a finalizer run by the garbage collector inside the scheduler (urllib3 pools release locks in `__del__`) re-entered it: a self-deadlock | inside the scheduler's critical section the thread is unmanaged; nested holds are counted |
| structlog `test_recursive` (seed 1) | the Python trace function used for preemption added a frame, so the RecursionError was raised inside detpy | the trace function is a C callable in Rust (`detpy._core.LineTracer`) |
| anyio uvloop tests (about 3x slower) | uvloop waits in C; each `to_thread` call waited for a 50 ms escape | a uvloop `run_forever` runs outside the scheduler (one uncontrolled event); escape after 5 ms when another thread is runnable. anyio escapes per calm run: 873 → 33 |
| anyio uvloop (blockbuster) | the lock's unmanaged path called `lock.acquire` by attribute, and blockbuster patches it | internal calls use the C method captured at import |
| anyio: interpreter never exits | at session end, waits still running computed "time left" across two clocks (virtual deadline, real now) | "now" and `queue.time` / `threading._time` stay continuous after the session |
| attrs, dateutil seed 1 (hang) | **Level 0**: a garbage collection inside the clock's `read()` ran hypothesis's gc callback, which reads the same clock (plain lock, self-deadlock). Possible under plain `--det` too | re-entrant lock in `VirtualClock` |
| more-itertools (+32% calm) | **Level 0**: the child-process check runs on every sleep and opened one `/proc` file per thread (1.9 s of a 5 s test) | one `waitid(WNOHANG \| WNOWAIT)` call; guard test (it passes before too: this is a speed fix) |
| jinja `test_caches_template_based_on_mtime` | Level 0 cross-run leak: the test stamps a repository file with the virtual time | harness restores the checkout's file times before every suite run (measurement hygiene; the Level 0 issue remains, see below) |

Harness changes: per-seed suite modes (`--suite-seeds`), timed-out runs counted per mode, a discarded warm-up run (the first `--det` run of a job pays several seconds of one-off cost: more-itertools 16.6 s vs 12.5 s), checkout file times restored before each run. The design note `docs/L1-THREADS.md` has a new section, "No blocking point can hang a test".

## Decisions

* **Outside work gets real time, bounded.** A plain run would wait for an unmanaged server too. Declaring a deadlock after 5 s was a false failure. Waiting forever was a hang. 60 s, then a DeadlockError that names the threads.
* **uvloop runs outside the scheduler.** Its waits are in C and cannot be controlled. Escapes on every call cost time and were uncontrolled anyway. One recorded uncontrolled event per loop is honest and costs nothing. The asyncio loop stays under the scheduler.
* **Polls are charged virtual time only when nothing else can run.** This is the same rule as the idle scheduler's clock jump, applied to a spinning thread.
* I cancelled my own rounds f2 (after 19 suites) and f3 to free the shared queue for f4 at the final code.

## What is missing or not done

* The class-a corpus (31 tests from the mixed round) was not re-measured; it is not in this exit. Its earlier result (0/13 reproduced) stands, cause: real I/O timing and asyncio.
* uvloop tests run uncontrolled: their fingerprints say "uncontrolled", not "identical".
* Determinism of whole-suite fingerprints under calm `--det-threads` was not measured, only outcomes. anyio still records 33 escapes per run.
* Level 0 findings for the coordinator, not fixed here:
  * jinja `test_caches_template_based_on_mtime` fails in any `--det` run that follows another `--det` run (virtual time stamped on a repository file);
  * jinja's 20 `[trio]` tests, anyio 3 and requests 4 (network) are broken by plain `--det`;
  * more-itertools `TestConcurrentTee` is bimodal under plain `--det` (1.2 s or over 25 s): a lock convoy with 100 threads.
* Exploration cost on CPU-heavy suites is high (more-itertools x10). It is a seed-only cost.

## Links

* Branch: https://github.com/Mircoguidetti/fenvix-engine-cli/tree/claude/l1-threads-fix (final code `3a5ce02`; aggregate `5a456f5`)
* Tests: `tests/test_threads_blocking.py` (14 tests); code: `python/detpy/threads.py`, `python/detpy/clock.py`, `crates/detpy-py/src/lib.rs` (LineTracer)
* Harness and workflow: `harness/l1_threads.py`, `harness/l1_threads_final_table.py`, `.github/workflows/l1-threads-fix.yml`, trigger `tracks/l1-threads-fix/run.json`
* Runs: f4 https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44177164657, f1 https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44136991919, f2 https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44149517641
* Intermediate reports: `INTERMEDIATE-1.md` .. `INTERMEDIATE-3.md` in this folder

## Errors or gaps in this brain

* P-012 told the earlier agent to deliver on `claude/loving-maxwell-58mv2w`, while CLAUDE.md says sessions report under `sessions/`. This session followed CLAUDE.md, as its prompt asked.
* The session's environment named a development branch other than `claude/l1-threads-fix`. I followed the prompt: engine work is only on `claude/l1-threads-fix`, and reports are pushed to `main` of this repository.
