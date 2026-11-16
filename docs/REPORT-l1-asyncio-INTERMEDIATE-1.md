# INTERMEDIATE-1 — L1 study: deterministic asyncio (P-006), after step 2

NOT DONE (intermediate delivery: design note and prototype done; corpus measurement running on GitHub Actions).

Intended path: fenvix-brain-cli `sessions/2026-11-16-l1-asyncio/INTERMEDIATE-1.md`. This session could not push to fenvix-brain-cli `main` (refused by the session's permission policy; `add_repo` with push access was also refused, read access was granted), so it is delivered here as `sessions/README.md` prescribes for that case.

Repository: fenvix-engine-cli, branch `claude/l1-asyncio-study` (from `claude/gracious-rubin-eyswxd` at 227c161), commits 8843427 (prototype), 020d187 (design note, corpus, harness, workflows).
Main files: `docs/L1-ASYNCIO.md`, `python/detpy/aio.py`, `tests/test_aio.py`, `harness/l1_async.py`, `harness/l1/corpus.json`, `harness/l1/repro/`, `.github/workflows/l1-async.yml`, `.github/workflows/l1-measure.yml`.

## Step 1 — design note (`docs/L1-ASYNCIO.md`)

* Sources: everything goes through `BaseEventLoop._run_once`; `_ready` is FIFO (an API guarantee), so the nondeterminism is *what enters `_ready` at which iteration*: timers vs. real elapsed time, I/O readiness and kernel order, executor completions, `call_soon_threadsafe` arrivals; cancellation inherits them through timeouts.
* Finding: **Level 0 fixes none of the asyncio sources.** `clock.install` deliberately keeps `BaseEventLoop.time` on real `time.monotonic` (the selector waits for real), so under `--det` asyncio timers are real, and `time.monotonic()` (virtual) disagrees with `asyncio.sleep` (real). L0 contributes the hash seed, ASLR off, per-test seed derivation, the event sink and the verifier.
* Approaches compared: custom loop + policy, instrumenting `BaseEventLoop` internals, selector shim. **Chosen: instrumenting `BaseEventLoop`** (reaches every loop: asyncio.run, Runner, pytest-asyncio, anyio's asyncio backend, tornado; controls every choice point; reuses CPython's own handles and transports). Cost: private attributes, stable on 3.10–3.13, to re-check for every CPython release.

## Step 2 — prototype `--det-async` (on top of `--det`)

* A scheduler per loop run by the test thread, seeded with `derive_seed(seed, nodeid + loop index)`; seed from `--det-async-seed` (default `--det-seed`); seed 0 = calm profile (reproducible, no exploration).
* Choice points: virtual loop clock with a seeded per-callback cost model and jumps to the next deadline (mirrored into the L0 clock); I/O polled without blocking, each ready file object delivered or deferred, delivered ones in seeded order; executor jobs waited for and delivered at `submit + virtual sleeps of the job + seeded cost` (independent of worker speed); foreign `call_soon_threadsafe` batched and merged FIFO-per-thread in seeded order; `shutdown_default_executor` joined in the loop thread. The FIFO of `_ready` is never broken (no executions that CPython cannot produce).
* Fingerprint: new `Source::Sched` / `Reason::Sched` in the Rust core (tag appended, existing fingerprints unchanged). Example verifier output: `event #1: first diverging scheduling choice at <loop 0>: it=3 jump=5030000ns executor=[job#1] <> it=3 jump=2685762ns executor=[job#2]`.

## Numbers

| item | value | label |
|---|---|---|
| Rust core tests | 40 passed (39 existing + 1 new) | MEASURED (container) |
| plugin tests, CPython 3.13 | 59 passed (incl. 11 new in `tests/test_aio.py`) | MEASURED (container) |
| `tests/test_aio.py` on 3.10 / 3.11 / 3.12 | all pass | MEASURED (container) |
| race tests **without** the prototype (`DETPY_ASYNC_FLAGS="--det"`) | 4 of 4 fail; 4–5 of 5 races give different results between runs with the same seed | MEASURED (container) |
| the same 5 races with `--det-async`, 24 runs in parallel on a loaded host | 5/5 races: identical results in all 24 runs | MEASURED (container, deliberately loaded) |
| seeds 1..6 | every race reaches ≥ 2 different outcomes; each seed replays | MEASURED (container) |
| local smoke run of the harness (14 minimal reproductions, 2 runs, 4 seeds) | 6/14 reproduced with a seed and passing with another | MEASURED (container; smoke only, real numbers come from Actions) |

## Corpus (step 3, in progress)

* IDoFT Python section: 1,618 rows; every test file fetched at its detection commit and scanned for `async def` or imports of asyncio/anyio/trio/aiohttp/pytest_asyncio/asynctest/tornado/twisted: **45 tests in 7 projects** (webssh 29 tornado, plcx 7, aiotasks 4, tornado-swirl 2, aiopylimit 1, pyps4-2ndscreen 1, python-dugong 1). 93 rows not fetchable (deleted repositories, e.g. tukio with 32 asyncio rows). Most are order-dependent (OD), which L0 already targets; only webssh has non-order-dependent (NOD) ones (20).
* 25+25 round (`harness/results/mixed`, read from the round branch): **anyio 17** baseline-flaky tests (TLS streams, sockets, task groups; asyncio, asyncio+eager, asyncio+uvloop), none reproduced under `--det`; **easypy 2** (`test_signals.py::test_async*`, reproduced by L0: order).
* Few real async *timing* races exist in these sources, so I added **14 minimal reproductions** of classic races (`harness/l1/repro`). Corpus total: 78 tests in 10 projects.
* Measurement: `l1-measure.yml`, one hosted-runner job per project (10 baseline / 10 `--det` / 10 calm `--det-async` runs, seeds 1..20, 10/10 confirmation, 3 timed full-suite runs per mode). Results are committed to `harness/l1/results/` on the branch.

## Problems found

* Round artifact downloads (blob.core.windows.net) are blocked by this container's network policy; the round results were read from the branch instead.
* The default branch of fenvix-engine-cli is `claude/gracious-rubin-eyswxd`, so a workflow that exists only on my branch cannot be dispatched; the measurement is triggered by pushing `harness/l1/run.json`.
* Pre-existing L0 test failure on CPython 3.10/3.11: `tests/test_clock.py::test_clock_behaviour` expects a `DeprecationWarning` from `datetime.utcnow()`, which exists only on 3.12+. Not caused by this work; the round CI runs only 3.13.
* Brain gap: `sessions/README.md` assumes every session can push to fenvix-brain-cli `main`; this one cannot.

## Addendum (coordinator messages of 16:20–16:45 UTC, read at 17:08 UTC)

* **Shared event vocabulary, own small commit: `2ec240f`** ("Core: shared event vocabulary, ENCODING_VERSION 2, verifier refuses mixed encodings"), on `claude/l1-asyncio-study`. Contents: `Source::Sched` (tag 9, `sched`), `ENCODING_VERSION = 2`, `SCHED_OPS` (`sched.ready`, `sched.timer`, `sched.io`, `sched.executor`, `sched.microtask`, `sched.thread`), `sched_value` / `parse_sched_value` for `<chosen index>/<set size>:<stable id>`, `TraceError::Incompatible` returned by `verify_paths` when encodings differ; 42 core tests pass (MEASURED, container). Only `event.rs`, `trace.rs`, `verify.rs` are touched; the Node and Detpy branches can cherry-pick it alone.
* Commit `9a39641`: the asyncio scheduler records its choices in that vocabulary (`sched.io`, `sched.ready`, `sched.executor`, `sched.timer`, stable id = creation site + per-site counter, site = `path:line` from the root); trace header meta now has `runtime`, `runtime_version`, `runner`, `seed`, `controls` (with `async`). 60 plugin tests pass on CPython 3.13 (MEASURED, container).
* `docs/L1-ASYNCIO.md` section 4: mapping of the choice-point model onto Node's event loop (libuv phases, nextTick and promise queues as non-choices, `sched.microtask` for the macrotask choice, threadpool as `sched.executor`, where to intercept).
* The first measurement run (43914981044) failed to install every project (relative wheel path in the harness); fixed, re-running as of 17:3x UTC.
