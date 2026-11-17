PARTIAL (all exit numbers measured; 3 server-in-thread suites and the anyio Actions rerun are still running)

# Report · track l1-threads (P-012) · Level 1 for threads (`--det-threads`)

Engine branch: local `track-l1-threads` (base `1573079` = origin/claude/gracious-rubin-eyswxd),
delivered as `tracks/l1-threads/patches/` (`git am` on the base). Final code `c25485d`.
Measured on GitHub Actions, workflow `track-l1-threads` (one runner per project):
* round r4, code `e29b9fd`, run 44074323368;
* round r5, code `d447170`, anyio only;
* round r1, code `4d88a2f`, run 44042691111, where noted.

`d447170` differs from `e29b9fd` only when a tool patches `lock.acquire` on the C type (blockbuster, used by
anyio's conftest). Raw results are in `results/r4/`, `results/r5/` and `results/r1/`. The r2 and r3 runs were
cancelled because their code was stale.

Still running on Actions when this was written:
* round r5 (anyio corpus and suite at `d447170`);
* r4's requests, werkzeug and remaining suites.

The anyio class-a rows are local at the final code. The rows marked r1 are at `4d88a2f`, which
predates the I/O change in c2596b0.

## Headline (exit numbers)

| exit number | result | label |
|---|---|---|
| easypy, 10 Block 2 thread tests: one fingerprint over the runs | **10/10** with `--det --det-threads --det-urandom`, over 10 quiet runs and 5 under CPU load. Level 0 alone 0/10; Level 0 + `--det-urandom` 8/10; `--det-threads` without `--det-urandom` 0/10 | MEASURED (Actions r4) |
| easypy: replays 10/10 with one fingerprint and passes somewhere | **9/10** ("passes" = the test run alone, i.e. without its polluter: a different order, not a thread seed). The 10th, `test_multiobject_logging`, fails in every detpy mode: a Level 0 false failure | MEASURED |
| 31 class-a tests: flake reproduced (replay 10/10, one fingerprint, passes with another seed, the baseline's exception) | **0/31**. 18/31 have no stable id (one marshmallow test with the wall-clock time in its id: not a thread problem). Of the 13 measurable: **0/13**. The condition differs from the mixed round, where these flakes were seen 1–2 times in 10 (full suite, xdist, random order). Here only the targets ran, serially, in a fixed order, and plain reruns did not show them either | MEASURED |
| class-a: failing interleavings found by 20 thread seeds | pymq 1 (seed 9, fails 10/10 but 2 fingerprints, `NoSuchRemoteError` instead of the baseline AssertionError). The anyio failures of r1 and of a local run were all scheduler artefacts; at `d447170` 0/20 seeds fail | MEASURED |
| plain reruns, same targets and condition (comparison) | 0 failures in 10 quiet runs for all 13; under CPU load pymq failed 1/5 | MEASURED (Actions r4) |
| tests broken by `--det-threads` (calm), Block 1 popular pool | **0 caused by threads**: 13 suites at the final behaviour (r4) and 9 at `4d88a2f` (r1, before the I/O change). **3 not measured yet: anyio, requests, werkzeug**, which run servers in threads and are the ones that change touches most. r1 showed 3 broken tests: boltons 2, fixed (I/O in flight, event-loop clock; 0 in r4), and jinja 1, a Level 0 cross-run effect (it also fails `--det` after `--det`) | MEASURED |
| tests broken by an exploration seed (seed 1, line preemption on) | 2: structlog `test_recursive` (cause ESTIMATED: the trace function adds stack depth in a recursion test), and jinja (same as above) | MEASURED |
| slowdown vs `--det`, 5 most thread-heavy popular suites (by managed threads, chosen after the run; easypy left out) | more-itertools **+27.8%** (167 threads), networkx −2.4% (65), structlog +1.3% (41), flask −1.0% (27), click +0.5% (26); **median +0.5%**. vs plain pytest: median +44.7% (`--det` alone +43.1%). With easypy (131 threads, −57.6%) in place of click the median is +1.3% | MEASURED, NOISY (one runner per project) |
| slowdown of exploration (seed ≥ 1, line preemption via `sys.settrace`) | median +71.5% on the same 5; more-itertools +1188% | MEASURED |

Plainly:
* Level 1 for threads makes the easypy thread tests replay with one fingerprint, in every run and
  under load.
* It breaks no measured popular-pool test.
* In calm mode it costs almost nothing over `--det`. Suites that sleep in threads get faster because
  sleeps are virtual (easypy −57.6%, rich −45.8%).
* It did **not** reproduce any of the 13 measurable class-a flakes in 20 seeds. Neither did plain
  reruns under the same condition.
* Those 13 are TLS/socket/asyncio tests (anyio), an external Redis (pymq), a ticking clock
  (freezegun) and a stream test (panamah). Their flakiness lives in real I/O timing and asyncio,
  which `--det-threads` does not control: asyncio needs `--det-async` with it, and external
  processes are Level 2.

## easypy: the 10 Block 2 thread tests (each with its minimised order)

| test | plain, same order (10 + 5 loaded) | `--det` | `--det --det-urandom` | `--det-threads` | `--det-threads --det-urandom` (10 + 5 loaded) | test alone | 20 thread seeds | replay of seed (fails, fingerprints) |
|---|---|---|---|---|---|---|---|---|
| `test_multiexception_api[concurrent]` | failed=10; failed=5 | 10 fp | 1 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |
| `test_multiobject_1` | failed=10; failed=5 | 10 fp | 5 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |
| `test_multiobject_exceptions` | failed=10; failed=5 | 10 fp | 1 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |
| `test_multiobject_logging` | passed=10; passed=5 | 10 fp | 1 fp | 10 fp | 1 fp / 1 fp | failed=1 | failed=20 | 10/10, 1 fp |
| `test_thread_stacks` | failed=10; failed=5 | 10 fp | 1 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |
| `test_logged_condition` | failed=10; failed=5 | 10 fp | 2 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |
| `test_logged_lock` | failed=10; failed=5 | 10 fp | 1 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |
| `test_synchronization_coordinator_failing_context_manager` | failed=10; failed=5 | 10 fp | 1 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |
| `test_synchronization_coordinator_timeout` | failed=10; failed=5 | 10 fp | 1 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |
| `test_synchronization_coordinator_with_multiobject_exception` | failed=10; failed=5 | 10 fp | 1 fp | 10 fp | 1 fp / 1 fp | passed=1 | failed=20 | 10/10, 1 fp |

One fingerprint over the runs: `--det` 0/10, `--det --det-urandom` 8/10, `--det-threads` 0/10, `--det-threads --det-urandom` 10/10 (quiet) and 10/10 (under CPU load).

* Failure messages of the replays:
  * RecursionError, 7 tests: logging polluted by an earlier test;
  * `assert False` and `assert 0 > 3`, one test each;
  * the Level 0 false failure.
* The failure itself comes from the order. Plain pytest with the same order fails 10/10 too, but
  gives no fingerprint.
* Without `--det-urandom` every run differs, because easypy draws `uuid4()` per thread. The verifier
  now names this `entropy`, not `thread`.
* What Level 1 adds over Level 0 + `--det-urandom`: `test_multiobject_1` (5 fingerprints → 1) and
  `test_logged_condition` (2 → 1). On these two the interleaving changed the execution; on the
  other 8 it did not.

## class a (31 tests of the mixed round)

* **18/31 excluded.** They are one marshmallow test parametrised with the wall-clock time at
  collection. Its id changes every run ("missing" in the baseline). Under `--det` the clock is frozen
  and the id is stable. This is not a thread problem. The list is in
  `harness/l1/threads-corpus.json`.
* **13 measured.** Rows for freezegun, panamah and pymq come from Actions r4. Rows are local at `d447170` (MEASURED locally, without the CPU-loaded runs); r5 repeats them on Actions.
* "Flake reproduced" requires all of the following:
  * the replay fails 10/10 with one fingerprint;
  * the test passes with some seed;
  * the failure is not a scheduler artefact (DeadlockError, pytest-timeout, BlockingError, a
    `threads.uncontrolled` deadlock);
  * the exception is the one the baseline flake raised.

| project | test | mixed round: baseline (full suite, xdist, random order) and exception | this harness: plain (10 + 5 loaded; targets only, serial, fixed order) | `--det` fp | `--det-threads --det-urandom` outcome, fp | 20 thread seeds | replay (fails, fp) | failure message of the replay | flake reproduced |
|---|---|---|---|---|---|---|---|---|---|
| idoft-freezegun | `test_ticking_time` | passed=8;skipped=2,  | passed=10; passed=5 | 1 | passed=10, 1 | passed=20 |   |  | no |
| idoft-panamah-sdk-python | `TestStream::test_events` | failed=1;passed=9, JSONDecodeError | passed=10; passed=5 | 4 | passed=10, 1 | passed=20 |   |  | no |
| idoft-pymq | `RedisRpcTest::test_channel_expire` | failed=2;passed=8, AssertionError | passed=10; failed=1;passed=4 | 10 | passed=10, 7 | failed=4;passed=16 | 10/10 / 2 fp | FAILED pymq.exceptions.NoSuchRemoteError: tests.test_provider_redis.RedisRpcTest.test_chan | no |
| anyio | `TestTLSStream::test_alpn_negotiation[asyncio+uvloop]` | failed=1;passed=9, PytestUnraisableExceptionWarning | passed=10; not run | 10 | passed=10, 2 | passed=20 |   |  | no |
| anyio | `TestTLSStream::test_alpn_negotiation[asyncio]` | failed+teardown-error=1;passed=9, RuntimeError | passed=10; not run | 1 | passed=10, 1 | passed=20 |   |  | no |
| anyio | `TestTLSStream::test_ragged_eof_on_receive[asyncio+eager]` | failed+teardown-error=1;passed=9, RuntimeError | passed=10; not run | 1 | passed=10, 1 | passed=20 |   |  | no |
| anyio | `TestTLSStream::test_ragged_eofs[asyncio+uvloop-server_standard]` | error=1;passed=9, PytestUnhandledThreadExceptionWarning | passed=10; not run | 1 | passed=10, 1 | passed=20 |   |  | no |
| anyio | `TestTLSStream::test_ragged_eofs[asyncio-neither_standard]` | error=1;passed=9, PytestUnhandledThreadExceptionWarning | passed=10; not run | 1 | passed=10, 1 | passed=20 |   |  | no |
| anyio | `TestTLSStream::test_receive_invalid_max_bytes[asyncio+uvloop-0]` | failed+teardown-error=1;passed=9, RuntimeError | passed=10; not run | 1 | passed=10, 1 | passed=20 |   |  | no |
| anyio | `TestTLSStream::test_send_receive[asyncio+eager]` | failed=1;passed=9, ExceptionGroup | passed=10; not run | 1 | passed=10, 1 | passed=20 |   |  | no |
| anyio | `TestTLSStream::test_unicode_hostname_idna2008[asyncio+eager]` | error=1;passed=9, PytestUnhandledThreadExceptionWarning | passed=10; not run | 10 | passed=10, 1 | passed=20 |   |  | no |
| anyio | `:test_unretrieved_future_exception_server_crash[ipv6-asyncio+uvloop]` | failed=1;passed=9, ExceptionGroup | skipped=10; not run | 1 | skipped=10, 1 | skipped=20 |   |  | no |
| anyio | `Stream::test_unretrieved_future_exception_server_crash[ipv6-asyncio]` | failed=1;passed=9, ExceptionGroup | skipped=10; not run | 1 | skipped=10, 1 | skipped=20 |   |  | no |

* Where Level 1 makes the fingerprint identical and Level 0 did not:
  * panamah: 4 → 1;
  * anyio `test_unicode_hostname_idna2008`: 10 → 1.
* The anyio fingerprints are "identical, with uncontrolled events": each calm run records 2
  escapes (`threads.uncontrolled`: a holder sleeping in C). The uvloop rows stay variable, because
  uvloop is not controlled.
* pymq: seed 9 fails 10/10 with `NoSuchRemoteError`, while the baseline flake is an AssertionError.
  The fingerprint has 2 variants because the Redis server is a real external process. This is a
  failing interleaving, not the flake.
* The 2 anyio IPv6 tests are skipped where IPv6 is unavailable.
* Before the final fixes, r1 and a local run had anyio "failures" in up to 8/10 tests. All were
  artefacts:
  * an instant deadlock when only I/O waiters were left (fixed in c2596b0);
  * blockbuster flagging the baton hand-over as a blocking call (fixed in d447170).

  This is why the harness now checks the exception.

## Popular pool (Block 1, 25) and easypy: broken tests and slowdown

Each value is the median of 3 runs per mode. The modes are interleaved: plain → `--det` →
`--det-threads` (calm) → seed 1. "Broken" means the test passes in every run of the reference mode
and fails in every run of the mode. The `code` column gives the round.

| project | tests | code | plain s | `--det` s | `--det-threads` s | vs `--det` | seed 1 vs `--det` | managed threads | escapes | broken by `--det` | broken by `--det-threads` | broken by seed 1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| arrow | 1904 | r4 | 8.556 | 15.191 | 15.407 | 1.4% | 34.9% | 1 | 0 | 0 | 0 | 0 |
| attrs | 1412 | r4 | 7.516 | 9.565 | 9.59 | 0.3% | 136.1% | 1 | 0 | 0 | 0 | 0 |
| boltons | 621 | r4 | 2.323 | 4.125 | 3.596 | -12.8% | 56.7% | 13 | 0 | 0 | 0 | 0 |
| click | 2651 | r4 | 3.778 | 5.407 | 5.432 | 0.5% | 71.5% | 26 | 1 | 0 | 0 | 0 |
| dateutil | 5344 | r4 | 21.903 | 29.382 | 29.605 | 0.8% | 228.4% | 14 | 0 | 0 | 0 | 0 |
| faker | 2470 | r4 | 24.787 | 29.433 | 29.52 | 0.3% | 171.2% | 1 | 0 | 0 | 0 | 0 |
| flask | 494 | r4 | 1.864 | 3.325 | 3.293 | -1.0% | 62.3% | 27 | 0 | 0 | 0 | 0 |
| humanize | 908 | r4 | 7.023 | 8.932 | 9.164 | 2.6% | 10.8% | 1 | 0 | 0 | 0 | 0 |
| idoft-easypy | 212 | r4 | 13.3 | 13.228 | 5.605 | -57.6% | -40.4% | 131 | 0 | 0 | 0 | 0 |
| isort | 794 | r1 | 27.672 | 31.802 | 31.597 | -0.6% | 134.0% | 4 | 4 | 0 | 0 | 0 |
| jinja | 911 | r4 | 1.802 | 4.083 | 3.939 | -3.5% | 112.3% | 1 | 0 | 20 | 1 | 1 |
| jsonschema | 8529 | r1 | 12.643 | 14.858 | 15.227 | 2.5% | 142.0% | 2 | 0 | 0 | 0 | 0 |
| marshmallow | 1192 | r1 | 0.945 | 2.287 | 2.301 | 0.6% | 46.8% | 1 | 0 | 0 | 0 | 0 |
| more-itertools | 771 | r4 | 12.985 | 14.692 | 18.783 | 27.8% | 1188.3% | 167 | 0 | 0 | 0 | 0 |
| networkx | 10191 | r4 | 111.01 | 126.268 | 123.219 | -2.4% | 242.4% | 65 | 0 | 0 | 0 | 0 |
| packaging | 63798 | r1 | 29.751 | 39.381 | 39.494 | 0.3% | 198.5% | 1 | 0 | 0 | 0 | 0 |
| pluggy | 226 | r1 | 0.393 | 1.096 | 1.105 | 0.8% | 28.6% | 1 | 0 | 0 | 0 | 0 |
| pygments | 5346 | r1 | 11.178 | 11.961 | 12.929 | 8.1% | 225.7% | 1 | 0 | 0 | 0 | 0 |
| rich | 981 | r4 | 4.41 | 5.326 | 2.885 | -45.8% | -3.1% | 12 | 0 | 0 | 0 | 0 |
| sortedcontainers | 366 | r1 | 4.533 | 6.981 | 7.051 | 1.0% | 490.1% | 1 | 0 | 0 | 0 | 0 |
| sqlparse | 540 | r1 | 1.375 | 2.389 | 2.359 | -1.3% | 150.4% | 1 | 0 | 0 | 0 | 0 |
| structlog | 921 | r4 | 1.2 | 2.198 | 2.227 | 1.3% | 63.0% | 41 | 0 | 0 | 0 | 1 |
| toolz | 193 | r1 | 0.423 | 1.541 | 1.787 | 16.0% | 35.1% | 4 | 4 | 0 | 0 | 0 |

jinja: broken by `--det-threads`: tests/test_loader.py::TestFileSystemLoader::test_caches_template_based_on_mtime

* jinja `test_caches_template_based_on_mtime` is not caused by threads (Level 0 finding 2 below).
* The 20 jinja `[trio]` tests are broken by `--det` itself, not by threads.
* The escapes (click 1, isort 4, toolz 4) are holders that slept in C code. Each one is recorded as
  `threads.uncontrolled` in the fingerprint.

## What was built

* `--det-threads` (Level 1 for threads, prototype, `python/detpy/threads.py`, design note
  `docs/L1-THREADS.md`). One managed Python thread runs at a time (a baton). Switches happen
  only at controlled points: lock / condition / event / semaphore / queue operations, sleep,
  thread start / join / exit, socket and selector I/O. Exploration seeds add a seeded line budget
  that preempts project code (`sys.settrace`). Waits and sleeps are timers on the virtual clock.
  Every choice among two or more runnable threads is a `sched.thread` event (tag 9, shared with
  the asyncio prototype). Every managed thread blocked with nothing pending raises
  `detpy.threads.DeadlockError`, with each thread's waiting site. The escape hatch: a watchdog
  moves a holder that sleeps inside uncontrolled C code out of the scheduler. The escape is
  recorded as a `threads.uncontrolled` event, and `with detpy.threads.external():` does the same
  explicitly.
* Options: `--det-threads`, `--det-threads-seed` (0 = calm; default = `--det-seed`),
  `--det-threads-grace`, `--det-threads-deadlock`, `--det-threads-preempt`.
* Tests: `tests/test_threads.py`, 15 test functions (18 cases). Each control test fails without its
  control or fix (or with Level 0 alone) and passes with it. Two exceptions are marked in the table
  below: they are guard tests that did not fail before. The full engine suite on Actions at
  `e29b9fd` gives 115 passed, 5 skipped (MEASURED, `results/r4/engine-tests.txt`).
* Harness: `harness/l1_threads.py`, `harness/l1/threads-corpus.json`, workflow
  `.github/workflows/track-l1-threads.yml`. The workflow is triggered by
  `tracks/l1-threads/run.json` and builds the engine from the base plus `patches/`.

## What real code needed beyond the design (each found on a measured project)

| found on | problem | fix | test (before → after) |
|---|---|---|---|
| easypy | `threadtree` captures `_thread.start_new_thread` | patch the low-level entry points too | covered by the easypy runs (no unit test) |
| easypy multiobject_1 (3 fingerprints in 25 runs) | an exiting thread's teardown consumed seeded choices and ran beside the next holder | an exiting thread leaves the scheduler; the next holder waits until it has really ended | `test_thread_exit_is_serialised`: guard, did not fail before |
| easypy multiobject_1 | `concurrent.futures` iterates futures in `id()` order (`_AcquireFutures` sorts by id; `wait`/`as_completed` use sets) | futures hash and sort by creation number; pool threads pop in insertion order | `test_futures_follow_creation_order_not_addresses`: fail → pass |
| easypy coordinator_timeout, logged_condition | `threading._time` / `queue.time` were real while waits were virtual, so a Barrier timeout never fired; a 1e-17 s wait spun | stdlib time-left clock is virtual; positive timeouts round up to 1 ns | `test_stdlib_time_left_is_virtual`: fail → pass |
| boltons netstring (r1) | only socket waiters left, so the clock jumped to their 10 s timeout while data was still in the kernel (Nagle / delayed ACK) | I/O waiters get up to min(grace, time to next timer) of real time; deadlock with only I/O waiters after `--det-threads-deadlock` | `test_io_in_flight_and_event_loop_waits`, ping-pong part: guard, did not fail before |
| boltons wraps_async (r1) | event-loop selector timeout did not advance the virtual clock under the scheduler | same rule as Level 0 | same test, event-loop part: fail → pass |
| anyio + blockbuster (local, exploration) | a Python wrapper around `lock.acquire`, traced as project code, was preempted while holding the scheduler lock | no line preemption while the thread holds the scheduler mutex | no unit test (found locally; `test_preemption_finds_a_lost_update_and_replays_it` checks preemption still works) |
| anyio exploration (r1, local) | blockbuster flagged the baton hand-over inside an event loop as a blocking call: false failures in up to 8/10 anyio tests | the scheduler's own waits call the C `lock.acquire` captured at import | `test_scheduler_waits_bypass_a_patched_lock_acquire`: fail → pass |
| easypy suite, exploration seeds (r3, local) | a RecursionError raised inside the scheduler (lock held, state half changed) wedged every thread | near the recursion limit, raise RecursionError before entering the scheduler (slow paths only; an uncontended lock costs the same, MEASURED locally) | `test_recursion_limit_does_not_wedge_the_scheduler`: hang → pass |

## Level 0 findings for the coordinator (not caused by `--det-threads`, not fixed here)

1. **easypy `test_multiobject_logging` fails under plain `--det`** (passes with plain pytest).
   easypy walks the stack to find the caller of `sleep()` and finds detpy's `clock.py` sleep
   frame. The patched `time.sleep` is visible as a Python frame. This is a false failure of Level 0.
2. **jinja `test_caches_template_based_on_mtime`**: the test sets a repository file's mtime with
   `time.time()`. Under the virtual clock that value is the same in every run, so the second
   deterministic run in a row finds the mtime unchanged and fails. `--det` after `--det` fails the
   same way (MEASURED locally). It shows up as "broken by --det-threads" only because the harness
   runs l1 after det.
3. **jinja: 20 `[trio]` tests broken by `--det`** (plain passes) in r1. This is not a thread issue.
4. **Seeded tempfile names collide with leftovers.** With about 1,500 `tmp*` entries left in
   /tmp by earlier `--det` runs, `tempfile.mkdtemp` under `--det` exhausts its 100 attempts
   (`FileExistsError: No usable temporary directory name found`). The engine test
   `test_waiting_for_a_child_process_waits_for_real` failed locally until I set TMPDIR to a
   fresh directory.
5. **Brain repository mismatch.** P-012 says to deliver `tracks/l1-threads/REPORT.md` on
   `claude/loving-maxwell-58mv2w`; CLAUDE.md says work sessions report under `sessions/` on the
   brain repo's main. I followed the prompt.

## Limits (what `--det-threads` does not control)

* asyncio keeps real time unless `--det-async` is also given.
* External processes and real network (pymq's Redis) are outside the scheduler: Level 2.
* Sets keyed by objects with the default (address) hash iterate in address order, except futures
  and pool threads.
* Exploration with line preemption runs under `sys.settrace`:
  * cost: median +71.5% on the 5 thread-heavy suites, more-itertools ×12;
  * it can change recursion-depth tests.
* uvloop and free-threaded CPython are not modelled.

## Reproduce

* Run: `pytest --det --det-threads [--det-urandom] [--det-threads-seed=N]`. A replay is the same
  command.
* Harness: `python harness/l1_threads.py --kind corpus|suite --project NAME --wheel W` (the
  workflow runs this).
* Aggregate: `--aggregate results/r4 --out DIR`.
