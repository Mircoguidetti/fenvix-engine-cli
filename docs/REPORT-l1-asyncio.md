# REPORT — L1 study: deterministic asyncio (P-006)

DONE (with gaps listed below: the real-project corpus is small and its flaky tests do not flake in isolation).

Intended path: fenvix-brain-cli `sessions/2026-11-16-l1-asyncio/REPORT.md`; this session cannot push to fenvix-brain-cli `main` (permission policy), so it is delivered on the work branch as `sessions/README.md` prescribes.

Repository fenvix-engine-cli, branch `claude/l1-asyncio-study` (from `claude/gracious-rubin-eyswxd` at 227c161). Key commits: 8843427 prototype; 2ec240f shared event vocabulary (own commit, `event.rs`/`trace.rs`/`verify.rs` only); 9a39641 choices recorded in that vocabulary; 68c11ae and 2d36e12 fixes found on the corpus. No PR opened (not requested by the prompt).
Files: `docs/L1-ASYNCIO.md` (design note), `python/detpy/aio.py` (scheduler), `tests/test_aio.py`, `harness/l1_async.py`, `harness/l1/corpus.json`, `harness/l1/repro/`, `harness/l1/results/` (REPORT.md, summary.json, raw per-run JSON), `.github/workflows/l1-async.yml`, `.github/workflows/l1-measure.yml`.
Measurement runs (GitHub-hosted runners, one job per project): **43925910072 (run 4, final code at 2d36e12; all numbers below unless stated)** and 43920396238 (run 3, before the webssh fix). Results: `harness/l1/results/` (run 4).

## Numbers against "Done means"

### Design note and prototype

| item | value | label |
|---|---|---|
| design note | `docs/L1-ASYNCIO.md`: sources, what L0 fixes (none of the asyncio sources: L0 keeps the loop on real time), seeded scheduler, shared vocabulary, Node mapping, 3 approaches compared, limits | — |
| prototype | `--det-async` (needs `--det`), `--det-async-seed`, `--det-async-grace/wait/settle`; 858 lines of Python + ~150 lines of Rust | MEASURED (line count) |
| tests | 12 tests in `tests/test_aio.py`; plugin suite 60/60 on CPython 3.13 (container) and 3.12 (CI); on 3.10/3.11 (CI) 59/60, the one failure is a pre-existing L0 test (`datetime.utcnow` warning exists only on 3.12+) | MEASURED |
| fail without / pass with | without the prototype (`DETPY_ASYNC_FLAGS="--det"`) 4/4 race tests fail on 3.10–3.13 (CI); with it they pass; 24 parallel runs on a loaded host gave identical results for 5/5 races | MEASURED |
| Rust core | 42 tests; `Source::Sched`, `ENCODING_VERSION = 2`, verifier refuses mixed encodings | MEASURED |

### Corpus (step 3)

* IDoFT Python section: 1,618 rows, every test file fetched at its detection commit: **45 async-related tests in 7 projects** (MEASURED); 32 more asyncio rows belong to a deleted repository (tukio). 30 of the 45 are order-dependent (OD), which L0 already targets.
* 25+25 round: **anyio 17** and **easypy 2** baseline-flaky async tests (DECLARED by the round, run 43892303433, `harness/results/mixed`).
* Real async *timing* races in these sources are scarce, so the corpus adds **14 minimal reproductions** of classic races (`harness/l1/repro`).
* Corpus: **78 tests in 10 projects**. Measurable: **65 tests in 6 projects** (anyio 17, webssh 29, l1-repro 14, easypy 2, tornado-swirl 2, python-dugong 1). Not measurable: plcx 7, aiotasks 4 (dependencies no longer resolve), aiopylimit 1 (collection error), pyps4-2ndscreen 1 (setup.py fails); dugong's test does not collect. 7 anyio tests are `asyncio+uvloop` parametrisations, outside the prototype (uvloop is not a `BaseEventLoop`). The target "≥ 20 tests in ≥ 5 projects" is met by count, **not by substance**: see below.

### Measurement (step 4), 58 tests without uvloop, run 4, MEASURED on GitHub-hosted runners

Protocol per project: 10 quiet baseline runs, 10 baseline runs under CPU contention (one spinning process per core), 10 `--det`, 10 `--det --det-async` (calm, seed 0), 10 calm under contention, seeds 1..20, 10/10 confirmation of the first failing seed with fingerprint comparison, test order fixed, serial.

| | real projects (44 tests) | minimal reproductions (14) |
|---|---|---|
| flaky in the baseline (quiet or loaded, run alone) | **0/44** | 8/14 (quiet 2, CPU-loaded 6 more) |
| `--det` only: same outcome in all 10 runs | 40/44 | 13/14 |
| `--det --det-async` calm: same outcome in all 10 runs | **43/44** | 13/14 |
| calm under CPU load: same outcome in all 10 runs | 42/44 | 13/14 (baseline under the same load: 6/14 stable) |
| reproduced 10/10 with a seed **and** passing with another seed | 0/44 | **8/14** (4 of the 8 baseline-flaky ones; 4 are latent races never seen failing in the baseline) |
| fingerprints identical across the 10 confirmation runs | — | 8/8 of the reproduced ones |

* **Real projects:** none of the 44 real async flaky tests flaked when run on its own, quiet or loaded (anyio's 17 flaked in the round only inside the full suite with pytest-randomly and xdist `-n 2`; the IDoFT ones are mostly order-dependent or were flaky on 2019–2021 hardware). So the share of *real* async flaky tests made reproducible is **UNKNOWN**: the corpus does not exhibit the flakiness in isolation, with or without detpy. This is the main gap of the study.
* **Minimal reproductions:** reproducible with a seed (10/10, identical fingerprints) and passing with another: executor results order, `as_completed` order, tight timeout on a thread job, lock order after thread work (these 4 flaked in the baseline), plus `FIRST_COMPLETED` job vs timer, ordered appends after thread work, readers on sockets written by threads, thread signal vs timeout (seed 15) (latent: never failed in the baseline). Not reproduced: cancellation racing a job, subprocess vs a 50 ms timeout, queue fed by a thread (pass with every seed: the cost model makes executor work fast, subprocesses are external), two clients from threads connecting to a server (foreign threads: 5/10, fingerprint diverges, as designed). One test is broken in every mode (rate limiter).
* **False failures:** corpus tests: none in run 4 that pass under `--det` and fail under calm `--det-async` in quiet runs (webssh `test_app_with_wrong_hostname_domain` failed 1/10 under calm *with CPU load* only). Full suites, run 0 of the timing pass: anyio `--det` 50 failed vs calm 49 (no extra); webssh `--det` 18 vs calm 21 (3 more, not yet analysed; `--det` itself varies 18–20 on this suite); easypy, tornado-swirl, l1-repro: no extra. Two defects found and fixed on the way: blockbuster (anyio's suite) flagged detpy's `os.path` calls inside the loop, making 85 anyio tests fail only under `--det-async` (fixed in 68c11ae); the clock jumped past tornado's 5 s `gen_test` timeout while a paramiko connect ran on webssh's own thread pool, 3 tests failing 3/10 only under `--det-async` (fixed in 2d36e12; run 4: 0/10).
* **L0 itself** breaks 13 of webssh's 29 corpus tests (pass 10/10 in the baseline, fail under `--det`): a Level 0 issue (threaded paramiko server, virtual sleeps), reported here for the Detpy session.
* With `--det` alone, asyncio stays on real time and `time.monotonic()` on virtual time, which breaks some async code: `test_sleep_as_sync_with_executor` fails 9/10 under `--det` and passes 10/10 under calm `--det-async`.

### Slowdown, `--det --det-async` vs `--det`, full suites, serial, 3 runs each, medians (run 4)

| project | `--det` s | calm `--det-async` | seed 1 | label |
|---|---|---|---|---|
| anyio (4,812 tests, `tests/test_pytest_plugin.py` excluded) | 87.7 | 95.0 (**+8.3%**) | 95.1 (+8.5%) | MEASURED, NOISY (hosted runner) |
| webssh | 17.4 | 20.2 (**+16.0%**) | 19.1 (+9.6%) | MEASURED, NOISY |
| easypy | 12.97 | 12.87 (−0.8%) | 12.90 (−0.6%) | MEASURED, NOISY |
| tornado-swirl | 0.90 | 0.91 (+1.7%) | 0.91 (+1.7%) | MEASURED, NOISY |
| l1-repro | 0.89 | 0.88 (−0.8%) | 0.89 (+0.3%) | MEASURED, NOISY |

(python-dugong's suite errors at collection in every mode; excluded.) anyio, the one large asyncio suite: **≈ 8% over `--det`** (run 3: 8.0%). webssh became slower with the 2d36e12 fix (run 3: +1.6%): while thread-pool work is in flight an idle loop now waits the timer's full delay for real, and webssh's L0-broken tests then wait out tornado's 5 s timeout. Waits of pure-asyncio tests get shorter (virtual jumps).

## What worked

* Instrumenting `BaseEventLoop` reaches every loop real suites create (asyncio.run, pytest-asyncio, anyio's asyncio backend, tornado 6) without changing loop classes; `_run_once` is structurally identical on 3.10–3.13.
* Seeded choices are replayable: the same seed gives the same results and the same fingerprint (8/8 reproduced tests, 10/10 runs each); different seeds explore different interleavings; the verifier names the first diverging choice (`sched.io 1/3:tests/test_x.py:39#2 …`).
* Executor results delivered at virtual completion times remove thread speed from the outcome; this was the hardest part (the asyncio chaining of executor futures raced with job registration; replaced by waiting on the `concurrent.futures.Future` directly).
* The calm profile fixes L0's inconsistent clocks for asyncio code at ≈ 8% cost on anyio, and makes outcomes steadier than `--det` alone (43/44 vs 40/44 real tests stable; under CPU load 13/14 vs 6/14 for the baseline on the reproductions).

## What did not

* Foreign threads (threads the test starts, servers in threads, thread pools used outside `run_in_executor`) remain timing-dependent; the scheduler only batches their arrivals. Most of the remaining real-world asyncio flakiness in this corpus (anyio TLS tests with threaded servers, webssh with a paramiko server thread) is of this kind: it needs the *threads* half of L1.
* The CPU-cost model makes executor work fast and deterministic; races that in reality depend on *slow* thread or subprocess work (sleep-as-sync, cancel-vs-job) are not reached by the seeds explored. A heavier-tailed cost model or a seed dimension on job durations would reach them.
* Old IDoFT projects (2018–2021) mostly no longer install.

## How hard to copy

* The asyncio half is copyable by a strong engineer in **2–4 weeks** (ESTIMATED): the idea is public (trio's `MockClock(autojump)`, simulation testing à la FoundationDB, Coyote/Shuttle-style systematic schedulers), and the prototype is ~860 lines. What took most of the time here, and would take time for anyone, are the edge cases that only real suites reveal (executor chaining races, blockbuster, direct thread pools, timeouts racing real work) and making it cheap (≈ 8%).
* The barrier is not the asyncio scheduler alone but its combination with the fingerprint/verifier vocabulary shared across runtimes (Python now, Node next) and the threads half of L1.

## Go/no-go proposal for Block 3

**GO, re-scoped.**
1. Ship the calm `--det-async` into the main `--det` path once it has run on the full suites of ~10 asyncio-heavy repositories without extra failures (gate: 0 tests that pass under `--det` and fail under calm `--det-async` — webssh's 3 suite-level extra failures must be explained first; slowdown ≤ 15%). Reason: it fixes L0's real-time asyncio clock cheaply and makes async suites replayable.
2. Make **thread scheduling** (bytecode-count switches, or at least deterministic delivery of thread-pool work and threaded servers) the main Block 3 investment: in this corpus it is what blocks the remaining asyncio cases.
3. Measure exploration in **suite context** (full suite, xdist, random order, CPU contention), not on isolated tests: the real flaky tests of the corpus only flake there.
4. Exit metric for Block 3 stays as in ROADMAP; first checkpoint: on the anyio round set, reproduce in suite context at least 5 of the 10 non-uvloop tests with a seed (10/10) and a passing seed.

## Cockpit readiness (coordinator request, 18:03 UTC)

Rendering "S3 answered before DynamoDB at orders.ts:42" from sched events today:
* **Possible:** each sched event has the chosen callback's creation site (`path:line` from the root) and a per-site counter, plus `<chosen index>/<set size>`; the event site equals the creation site; the replay command is exact (`pytest --det --det-async --det-async-seed=N <nodeid>`).
* **Harder:** (1) the value names only the *chosen* callback, not the alternatives it beat; "A before B" needs the other members of the set (suggest: a sidecar or an optional field with the canonical set's stable ids); (2) the creation site is the first *user* frame, so for I/O it is where the connection was opened, not which response arrived — a protocol/peer label (e.g. remote host:port or the callback qualname) would read better; (3) timer and executor choices are `0/n` because their order is decided by virtual durations, which are not in the event; showing "job took 3 ms virtual" needs the virtual time in the trace; (4) worker-thread events are re-recorded on thread 0 at the delivery point (deterministic, but the thread identity is lost for display); (5) uncontrolled points are `other`/`asyncio.uncontrolled` events, which the cockpit should show as "not deterministic here" rather than as a cause.

## What blocks or is missing

* The real-project share made reproducible is UNKNOWN (see above); a suite-context exploration is the next measurement.
* Push to fenvix-brain-cli `main` refused by this session's permission policy (reports are on the work branch).
* Round artifacts are not downloadable from this container (blob storage host blocked); read from the round branch instead.
* Pre-existing L0 issues found: `datetime.utcnow` test expectation on 3.10/3.11; INTERNALERROR (`'NoneType' object has no attribute 'end_test'`) when a suite runs nested in-process pytest sessions (anyio `tests/test_pytest_plugin.py`); L0 breaks 13 webssh tests.

## Errors or gaps in the brain

* `sessions/README.md` assumes every session can push to fenvix-brain-cli `main`.
* ARCHITECTURE.md "L1 (designed)" should now point to `docs/L1-ASYNCIO.md` and to encoding version 2.
* The default branch of fenvix-engine-cli is another session's branch, so workflows that exist only on a work branch cannot be dispatched; this study triggers its measurement by pushing `harness/l1/run.json`.
