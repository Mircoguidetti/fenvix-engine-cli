# Known limits of detpy Level 0

Level 0 works at the **Python API level**: it controls and observes what goes
through the Python entry points it patches. Everything below that line (C
code, the kernel, other processes) is out of reach until a syscall-level
backend exists (see `docs/ARCHITECTURE.md`). Each limit below says whether it
was found by the plugin's own tests (**T**), by the harness on real
repositories (**H**) or by design analysis (**D**), and what mitigates it.

## Scope of interception

| # | limit | found | mitigation |
|---|---|---|---|
| S1 | C extensions and native libraries are not controlled: their clock reads, RNGs, directory walks, sockets (grpc core, pycurl, database drivers) bypass the patches. | D | Syscall backend (future). |
| S2 | Subprocesses (`subprocess`, `multiprocessing` spawn, `pytester.runpytest_subprocess`) are not controlled, but inherit `PYTHONHASHSEED`. A child that runs pytest with `--det` controls itself. | D | — |
| S3 | References bound **before** installation keep the real objects: stdlib modules bound on purpose (`threading`, `queue`, `subprocess`, `sched`, `socketserver` — they need real time for blocking waits); third-party modules imported earlier are rebound, **except pytest plugins**, which are infrastructure and keep real timers (`pytest-benchmark`, `pytest-timeout`). Function references stored in default arguments, instance attributes, `functools.partial`, closures of already-imported code are never rebound. | T,H | Import the code under test after pytest starts (the normal case). |
| S4 | `datetime.datetime.now/utcnow` and `date.today` are patched *in place on the C types* via `gc.get_referents(type.__dict__)` + `PyType_Modified`. This is CPython-specific (not PyPy) and relies on interpreter internals. Replacing the classes instead (freezegun-style) was tried first and broke `freezegun` itself (metaclass conflict on `class FakeDate(datetime.date, metaclass=...)`) and C extensions that require the exact type. | H | — |

## 1. Order

| # | limit | found | mitigation |
|---|---|---|---|
| O1 | pytest-xdist under `--det` (docs/PARALLEL-PROOF-DESIGN.md, build steps P1-P3): the controller computes one fixed plan (atoms from `--dist`: test for load/worksteal, module or class for loadscope, file for loadfile, `xdist_group` for loadgroup; LPT on recorded durations; sticky within 10 % + 1 s of the LPT makespan) and sends every worker its whole list, a subsequence of the serial order; each worker writes `<trace>.gwK.jsonl`, the controller merges them into `<trace>` (lines in serial order with `worker`/`worker_index`, `missing` for tests of a worker that died; the replacement runs the rest of its list). `testrun_uid` is derived (seed, paths, `--dist`, N). Under `--dist loadgroup` node ids stay the serial ids (no `@group` suffix). With `--det-cache` the reuse decision is made once in the controller (hits reported by the controller, never sent), workers record shards, the controller merges them with the cross-worker write rule. Not supported: `--dist each` (xdist's own scheduler, noted in the header), remote `--tx` (side files under `.detpy/`), work stealing. A test whose events depend on process state left by tests it no longer follows in its worker diverges from its serial fingerprint: `detpy verify serial merged` classifies it `placement` with the lost predecessors; nothing prevents it yet (P5 of the design). A test that reads `PYTEST_XDIST_WORKER` is reused under `-n` only for the worker it had in the previous plan. | D | `--det-plan` replays an assignment; `--det-plan-worker=gwK` replays one worker's list serially. |
| O2 | Plugins that reorder (`pytest-randomly`, `pytest-random-order`) are blocked under `--det` with `-p no:<name>` injected at the re-exec, before they load (unregistering them after loading left pytest-randomly's autouse `faker_seed` fixture active: 3 faker failures, test `test_conflicting_plugins_are_blocked_before_loading`); the options of a blocked plugin stay valid (review R-001: since `-p no:randomly` a project with `addopts = --randomly-dont-reorganize` or `--randomly-seed=...` stopped with a usage error): detpy calls the blocked plugin's own `pytest_addoption`, so they parse and do nothing (tests `test_det_runs_a_project_that_configures_pytest_randomly`, verified with the real pytest-randomly 5.1.0 and pytest-random-order); code that reads them with `config.getoption` gets the configured value although the plugin is not running; without a re-exec they are unregistered and their fixtures may stay; any other reordering done in `pytest_collection_modifyitems` is undone (deselection is kept). Exception: pytest-django's grouping (TestCase, then transactional tests that flush the database, then non-db tests) is re-applied to detpy's order by calling pytest-django's own stable sort, so `--det-seed` shuffles inside each group (without it, a flushing test ran before TestCase tests that read data-migration rows: false failures; test `test_django_order.py`). Reorderings done in other hooks are not detected. | T | `--det-seed` gives reproducible shuffles. |
| O4 | The fixed order (collection order, serial) exposes order dependencies that a random/parallel baseline hides: on easypy 41 tests fail in collection order with or without `--det` (e.g. a `logging` monkeypatch applied twice → `RecursionError`) and pass under xdist. These are real order dependencies, not Level 0 failures; the harness separates them with a serial fixed-order reference run without `--det`. | H | `--det-seed` explores other orders. |
| O3 | Shuffle granularity is module → class → test; tests depending on a sibling module's side effects can still break under a shuffle (that is the point of nightly multi-seed runs). | D | — |

## 2. Seeds and hashing

| # | limit | found | mitigation |
|---|---|---|---|
| R1 | `PYTHONHASHSEED` can only be fixed by re-executing the interpreter. Not possible for in-process sessions (`pytest.main()`, pytester inline), on Windows, or on Python < 3.10 (`sys.orig_argv`). The status is printed in the header and stored in the trace (`meta.reexec`). | T | Export `PYTHONHASHSEED=0` yourself. |
| R2 | **`.pyc` state changes set iteration order.** A set literal is compiled to a `frozenset` constant; the `.pyc` stores it in the iteration order of the compiling process, and loading it rebuilds the set by inserting in that order, which can yield a different layout than compiling from source — even with the same hash seed. Without a fix, the first run after a source change differs from later runs (reproduced by `test_without_precompilation_the_first_run_can_differ`). | T | Default under `--det` (control `bytecode`): before the re-exec, detpy (`_pycompile.py`) precompiles stdlib, site-packages and the project **under the fixed hash seed**, as checked-hash `.pyc` files (PEP 552: the import system validates each against its source's content, so stale bytecode never runs whatever the mtimes say), into `~/.cache/detpy/pyc/<tag>-hashseed<N>` (`PYTHONPYCACHEPREFIX`), and the session runs with `PYTHONDONTWRITEBYTECODE=1`: every module is either loaded from that cache or always compiled from source (pytest's assertion-rewritten test modules). Measured cost: ~3 s the first time for a venv (4 CPUs), ~0.6 s per later run (incremental check); ~100 MB of cache. Code imported from outside these directories is compiled from source every run. |
| R3 | Address-based hashes (`id()`, default `__hash__`, `repr` with `0x…`) are deterministic only with ASLR disabled, done by the re-exec on Linux via `personality(ADDR_NO_RANDOMIZE)`; it fails silently under seccomp profiles that forbid it, and does not exist elsewhere. | D | `--det-keep-aslr` to opt out. |
| R4 | Only `random`, `numpy.random` (global state and `default_rng()` without seed) are seeded. `torch`, `tensorflow`, `jax`, `faker`'s own generators, etc. are not. numpy is reseeded only if already imported when the test starts. | D | — |
| R5 | `os.urandom`, `uuid4`, `secrets`, `SystemRandom` are **observed, not controlled** (they are meant to be unpredictable). They show up as `entropy` divergences. | T,H | `--det-urandom` makes them deterministic (never for crypto tests). |
| R6 | `random.Random` instances created before installation (by plugins) are reseeded once, not per test. | D | — |

## 3. Virtual clock

| # | limit | found | mitigation |
|---|---|---|---|
| C1 | **Time-calibrated loops.** With a fixed tick, code that measures how long CPU work takes (without reading the clock inside the work) sees a constant duration, and loops that grow the work until it "lasts" long enough never end: `pytest-benchmark` hung on humanize. | H | **Adaptive tick** (`--det-tick-adapt=N`, default 8): after N consecutive clock reads with no other event (random, fs, net, sleep) every further read of the run doubles the tick (cap 1 s); any other event or a new test restores it. Deterministic (a function of the event sequence). Doubling *every N reads* (first attempt) was too slow: pytest-benchmark multiplies its loop count by 10 per measurement and reached 10^8 iterations; N=16 also hung; N=8 terminates. |
| C1b | pytest-benchmark then sizes its runs as `max_time / measured duration`; a virtual duration has no relation to CPU cost, so with the default `max_time` a cheap function ran ~6·10^8 times. | H | Under `--det` pytest-benchmark stays active but gets `--benchmark-max-time=0.000001` (minimum rounds). Its timings are meaningless under a virtual clock anyway. |
| C1c | Side effect of the adaptive tick: with a 1 s cap, a hot loop that checks a timeout with `perf_counter` saw virtual time run faster than real time and timed out (networkx graph edit distance, faker). | H | **Fixed**: the tick is capped at 16 µs, enough for pytest-benchmark calibration (~10 µs) and never faster than a real loop iteration. Test `test_adaptive_tick_does_not_trip_algorithm_timeouts`. Generic calibrators that need much longer durations (`timeit.autorange`, 0.2 s) still do not terminate. |
| C2 | **Virtual sleep and threads.** Code that sleeps so that *another thread* can make progress ("wait for stragglers", calls that must overlap while a worker sleeps) broke: a purely virtual sleep returns at once and the other thread never ran. Found on easypy (`test_tag_along_thread`, `test_multiobject_concurrent_find_*`): 3 false failures. Polling loops with a timeout against real external work burn virtual time faster than real time for the same reason. | H | **Fixed**: `time.sleep` stays virtual only while the process has a single thread; when other threads are alive it also waits for real (the clock still advances by the requested amount). Regression test `test_sleep_lets_other_threads_run`. easypy: 3 → 0 broken tests (MEASURED, 3 runs). `--det-sleep=real` makes every sleep wait. |
| C2b | **Other observers of real time.** A virtual sleep was also wrong (a) inside a running asyncio loop, whose deadlines use real time (anyio `fail_after` xfail-strict tests passed), and (b) after the test started another process that keeps working in real time even once detached (redislite daemonizes `redis-server` and polls a fixed number of times: 24-38 failures in pymq). | H | **Fixed**: sleeps also wait for real while an event loop runs in the thread, while a child process is alive, and for the rest of a test once it started a process (`subprocess`, `os.fork`, `posix_spawn`, `os.system`). Tests `test_blocking_sleep_inside_event_loop_moves_loop_time`, `test_waiting_for_a_child_process_waits_for_real`, `test_waiting_for_a_daemonized_process_waits_for_real`. |
| C2c | **asyncio waits in real time while `time.time()` is virtual**: `await asyncio.sleep(0.25)` measured ~0 s (boltons `test_wraps_async`). | H | **Fixed**: when a selector `select(timeout)` returns no event, the virtual clock advances by the timeout rounded up to 1 ms (same rule as `Condition.wait`). Test `test_asyncio_sleep_moves_the_virtual_clock`. |
| C2d | **time-machine** patches the C builtins (`time.time`, `datetime.now`) that detpy replaced, so its travels had no effect under `--det` (structlog: 43 failures). | H | **Fixed**: while a time-machine travel is active, its destination drives the virtual wall clock; a ticking travel advances with the virtual counter, not real time. Test `test_time_machine_travel_is_honoured`. |
| C2e | `date.today()` replaced in Python ignored a patched `time.time` (freezegun's FakeDate path) and added a frame to freezegun's stack inspection (2 failures). | H | **Fixed**: `date.today`/`datetime.today` are left to CPython, which already calls the (virtual) `time.time` through the module. Test `test_date_today_follows_a_patched_time_time`. |
| C2f | **C-level blocking waits** (posix_ipc / redis queue `get(timeout=1)`) take real time without any Python clock read: code measuring them sees ~0 s (pymq: 2 tests). | H | Not fixable at the Python level (syscall backend). |
| C3 | asyncio keeps real time: its selector blocks for real, so `loop.time()` is not virtualised (virtualising it made `asyncio.sleep` spin). | T | — |
| C4 | Blocking primitives that time out advance the virtual clock by their timeout: `Condition/Event.wait`, `Queue.get`, asyncio selector waits, and (since the round) `Lock`/`RLock.acquire(timeout=)` on locks created under `--det` (wrapped). `threading.Lock` stays a type where it is one (Python 3.13+): `isinstance(x, threading.Lock)` holds for real and wrapped locks (review R-001, test `test_threading_lock_stays_a_type_under_det`), but `type(threading.Lock()) is threading.Lock` is false and the wrapper is not a C lock for C code that checks the exact type. Found by the round: easypy's `LoggedRLock` retried `acquire(timeout=0.2)` until a `time.time()` deadline and hung forever under `--det-seed=2` (test `test_lock_acquire_timeouts_advance_the_clock`). Whether a wait times out still depends on real scheduling. Not covered: locks created before installation, raw `select`, socket timeouts, `subprocess.wait(timeout=)`, C-level waits (C2f). | T,H | — |
| C5 | One clock for all threads: reads from several threads interleave by real scheduling, so values (and the fingerprint) depend on it → `thread` divergences. | T | — |
| C6 | The wall clock restarts at the epoch for every test, the monotonic clock does not (it must never go backwards in a process). Absolute monotonic values depend on the test position; fingerprints record them relative to the test start. | D | — |
| C6b | Default epoch (`--det-epoch=auto`): the commit time of the checked-out git HEAD, else 2025-01-01T00:00Z. Found on django-oauth-toolkit @ 285ba9c: a test that takes a hard-coded 2025-09-04 expiry as past failed under the fixed 2025-01-01 epoch (T2, test `test_epoch_defaults_to_the_head_commit_time`). A test that assumes the real date is *later* than its commit by some margin (e.g. "a certificate issued at commit time is already valid for a day") still differs from a real run. Changing the epoch changes fingerprints: traces recorded with the old default are not comparable (`epoch_source` in the trace header). | D | `--det-epoch=ISO` fixes any other value. |
| C6c | Stand-ins for builtins (`time.*`, `os.listdir/scandir/urandom`, the `random` module functions, `threading.Lock` before 3.13) are callable objects without `__get__`: like the builtins they replace, they do not bind as methods when stored as class attributes (T1, DRF throttling `timer = time.time`, test `test_replacements_do_not_bind_as_methods`). `inspect.isbuiltin()` is false for them; each call costs about 45 ns more than a plain function (MEASURED, local). | T | — |
| C7 | Not virtualised: `time.process_time`, `thread_time`, `resource.getrusage`, file timestamps (`os.stat().st_mtime`, `touch`), `time.localtime()` depends on `TZ`. | D | — |

## 4. Filesystem order

| # | limit | found | mitigation |
|---|---|---|---|
| F1 | Only the *order* of enumeration is normalised; file contents, sizes, timestamps, inode numbers, free space are not observed. Tests whose outcome depends on files left by previous runs show up as `outcome-only`. | T | — |
| F2 | Sorting needs the whole listing. First version: `glob.iglob`, `Path.glob/rglob/iterdir` became eager and read the directory in the caller's thread; with anyio + blockbuster that is the asyncio loop thread → `BlockingError` (36 tests); detpy's own path normalisation also called `os.getcwd`/`os.path.relpath` (3 more). | H | **Fixed**: lazy generators (the listing happens on the first `next()`, in the iterating thread); path normalisation is string-only and uses a `getcwd` captured at import. Test `test_glob_stays_lazy_and_bookkeeping_never_blocks`. |

## 5. Network

| # | limit | found | mitigation |
|---|---|---|---|
| N1 | Only Python sockets are guarded: native clients and subprocesses (`curl`, `git`, `pip`) reach the network. | D | Syscall backend / network namespace. |
| N2 | Local proxies are recognised only through `*_PROXY` environment variables. | T | — |
| N3 | Replay matches connections by (test, host, port, n-th connection); request bytes that differ from the recording are only reported (`replay.mismatch` event), not rejected. | T | Re-record. |
| N5 | A test that expects a *connect timeout* to an unroutable address (requests `test_connect_timeout`, 10.255.255.1) gets `NetworkBlockedError` (a `ConnectionRefusedError`) under `--det`. **Decision**: keep it. Emulating a timeout would make a closed network look like a slow one and mislead tests that check refusals; these tests need real network semantics and are run with `--det-allow-host`. | H | `--det-allow-host`. |
| N4 | TLS is replayed with a plaintext stand-in (`ReplayTLSSocket`) that is **not** an `ssl.SSLSocket` instance; asyncio TLS (memory BIO: aiohttp, async httpx) cannot be replayed. UDP is never recorded. A replayed socket is an `AF_UNIX` socketpair end: TCP socket options are ignored and `getpeername` is faked. Verified with `urllib` and `requests`/urllib3 2.x over HTTPS. | T | — |

## 6. Fingerprints

| # | limit | found | mitigation |
|---|---|---|---|
| P1 | The fingerprint only covers sources detpy observes. A test can be flaky with an identical fingerprint and only its outcome differing (`outcome-only`): the cause is outside the observed set (file contents, C code, scheduling without clock reads, external state). | T | Syscall backend. |
| P2 | Events from threads that outlive their test are attributed to the test that is running when they happen. | D | — |
| P3 | Divergences are located exactly within the first `--det-max-events` events (default 10 000); later ones are bracketed by checkpoints every 256 events (`beyond-trace`). | T | Raise `--det-max-events`. |
| P4 | Events whose first non-stdlib frame is pytest or detpy (e.g. `tmp_path` creation) are not recorded; fixtures implemented in third-party pytest plugins are recorded. | T | — |

## 7. Plugin integration

| # | limit | found | mitigation |
|---|---|---|---|
| G1 | **Nested in-process pytest sessions** (pytester inline runs, `pytest.main()` from a test) ran detpy's module-level hooks: the inner session's `pytest_unconfigure` uninstalled the outer controls and the outer session died with INTERNALERROR (anyio: 2,820 tests never ran; faker: 385). | H | **Fixed**: the `--det` hooks and the outcome collection are objects registered on the owning config's plugin manager; a nested session never touches them. Test `test_nested_inprocess_session_does_not_break_the_outer_one`. |
| G2 | References to detpy's fake clock functions kept by libraries are still called after the session uninstalled the controls (anyio at interpreter shutdown: `AttributeError`). | H | **Fixed**: after uninstall every fake delegates to the real function. Test `test_references_kept_after_the_session_fall_back_to_real_time`. |

## 8. Cache with proof (`--det-cache`): real clock

What the cache cannot see of the real clock is bounded by `--det-cache-max-age` (default 30 days): an older entry is never reused.

| # | limit | found | mitigation |
|---|---|---|---|
| K1 | Real-clock reads in C code inside the test process other than sqlite (OpenSSL's certificate validity, `uuid.uuid1()`'s libuuid, database drivers). | D | Bounded by max-age. |
| K2 | **File timestamps** set by the real clock: read in the test process (`os.stat(p).st_mtime` after writing `p`, C7), or in a child through `fstat` on a descriptor. A child's stat **by path** of a file its process tree wrote, or of `/proc/<pid>`, is refused (review R-009b R4; `rm`, `rmdir`, `mkdir`, `ln`, `chmod`, `chown` exempt). | D | Bounded by max-age. |
| K3 | **Dynamically linked Go children** (cgo) load the clock library but read the clock through the vDSO, never through libc. Today every Go binary is refused by accident: the Go runtime reads `/sys/kernel/mm/transparent_hugepage/hpage_pmd_size` at start-up (a `/sys` content read). If a Go release stops reading it, a cgo binary's real-clock reads become invisible (review R-009b, F4 note). Static Go binaries are refused (no clock-library marker). | D | Bounded by max-age. |
| K4 | A trace callback set by the test on a sqlite connection replaces detpy's: its statements and schema are no longer checked for `'now'`. | D | Bounded by max-age. |

## 9. Cache with proof (`--det-cache`): inputs the recorder cannot see

The cache reuses a result only when every input it recorded is unchanged. An input it cannot see must not leave a
reusable result behind: such a test is **refused** (rerun every time) or keyed more coarsely, never reused on a
partial key. Each row has a test that changes only that input and requires the test to rerun, serially and under
`-n 2` (`tests/test_proofcache_import_lookups.py`); each test fails on `claude/parallel-proof-3` de41574.

| # | input not seen | found | handling | test |
|---|---|---|---|---|
| A1 | A file the **repository's native code** stats, opens or reads from C (an extension built in place, a `ctypes` library): S1, no Python event. | D (coordinator, dependency verdict REPORT-3) | A context in which a shared library from the project root is mapped (`/proc/self/maps`, read at every context switch) is **not cached** ("native code from the repository"), unless a distribution's RECORD lists it (an installed wheel's library under the root is a dependency). Installed and system libraries are inputs by content; what *their* C code reads stays S1. | `test_stat_from_c_code_of_the_repository` |
| A2 | A library `dlopen()`ed and `dlclose()`d within one context leaves no mapping to scan. | D (dependency verdict REPORT-2) | Through `ctypes`, the `ctypes.dlopen` audit event names the path: refused as A1 when it is in the project root. A load by C code without an event is A1 or S1 (that C code is itself mapped). | `test_library_loaded_and_unloaded_within_one_test` |
| A3 | `os.stat` / `os.lstat` / `os.access` bound before the session (`from os import stat` in a plugin loaded with `-p` at startup). | D (coordinator) | At capture start every module global that is the original function is rebound to the recording wrapper (except `posix`, the import system's own module, whose probes the module-lookup finder records). References in closures, default arguments or C code stay unseen (S3, S1). | `test_stat_bound_before_the_session` |
| A4 | `os.lstat` / `os.path.lexists` / `islink` of a dangling symlink: following the link, it reads as missing either way. | D (coordinator) | `os.lstat` (and `follow_symlinks=False`) records the kind without following a final symlink (`l:<kind>`, kinds `link`, `file`, `dir`, `other`, `missing`). | `test_dangling_symlink_that_goes_away` |

## A compiled extension nobody has audited makes a test NOT PROVEN (founder, 2026-11-22)

**What the customer sees.** A Python suite that imports **numpy, pydantic-core, lxml or psycopg** — and any
other third-party compiled extension that is not in `CONTROLLED_NATIVE` / `NODE_AUDITED_NATIVE` — comes out
`NOT PROVEN`. Its tests run and their outcomes are the suite's own; what the engine will not do is claim two
runs were identical, so those tests are **not skipped from the cache and not spread across cores**. Slower,
never wrong.

**Why.** A compiled extension's own C code is invisible to every in-process sensor, so the engine cannot say
what the test observed through it. The rule is "never a green on a doubt" (founder, 2026-11-21).

**What was audited instead, one at a time, by measuring** (evidence in `docs/NATIVE-AUDITS.md`): jest 30's own
module resolver `@unrs/resolver-binding-*`, Jinja2's `markupsafe._speedups`, the engine's own addon, and
`_time_machine` (the engine's own integration). Each entry carries its `strace` measurement.

**numpy was measured and NOT cleared.** Ordinary array work with a seeded generator makes two `getrandom`
calls that could not be attributed in-process (numpy 2.5.5, CPython 3.13.18, MEASURED). Clearing it on that
evidence would be a green on a doubt.

**Cost in the exam:** `F-03.probe.numpy` and `F-02.py-replay.idoft-py-autodoc` fail on this limit and only on
it (exam run 44996027924: F-01 33/33, F-02 16/17, F-03 17/18). The founder accepted them as failing on this
written limit on 2026-11-22, as he did for F-05/PY-05 on 2026-11-21.

**When it goes away:** with a sensor that sees under Python and Node, briefed in
`fenvix-brain-cli prompts/P-066-compiled-extensions-sensor.md`. Until then this limit stands.

## 10. Cache with proof (`--det-cache`): one process, as the user runs the suite; speed

Under `--det-cache` the tests run in the session's process(es), as plain `pytest` (or `pytest -n`) runs them
(coordinator decision 2026-11-21, review R-050 P2): the reported outcome of every test is that run's. A test is keyed
on the earlier tests of its process whose state it may have consumed (its carried set). A test with no stored result
(failed, or never cacheable: it starts a process, reads file times, ...) keeps the carried set it had when it last
ran, and those tests run before it whenever it runs; a new test runs after every earlier test of its process. Cost:
a failing or never-cacheable test reruns the tests of its carried set, every earlier test of the process when it
reached a library; the reuse share this costs on moto and litellm is UNKNOWN until measured.
A test whose test file, or the test file of any earlier test of its process, changed since its result was recorded
is not reused, and every earlier test of its process runs before it (review R-052: its stored needs were computed
from the old code). Cost: an edit to a test file reruns every later test of its process (worker), and their
predecessors.

**Written reuse limit (founder decision 2026-11-21: the Python cache closes with it).** A test that fails, or whose
test file (or a conftest.py / __init__.py loaded with it) changed, runs every time; when its carried set reached a
library (most real tests do), every earlier test of its process (worker) runs before it, because it may read state any
of them left in memory and that state is not tracked per test. Sound (0 wrong reuse), less reuse. MEASURED, exam run
44925123655 on 2b67ac0, attrs 25.3.0 (where 2 tests fail in the exam's checkout, positions 1,073-1,074 of 1,330):
unchanged rerun reused 256 of 1,322 passing serially and 0 under -n 2; itsdangerous, one test file edited: 0 of 298
reused. The same attrs suite with every test passing: 1,330 of 1,330 reused, serial and -n 2 (MEASURED locally).
Lifting it needs per-test tracking of the state each test changes (a separate session).

`--det-isolate` (one child per test file, or per test) is an explicit choice: no in-process state crosses files.

* **Outcomes under `--det-isolate` of tests that depend on earlier files.** A test that works only after another
  file's tests have left state in memory (moto 96f50b1a: `TestS3FileHandleClosuresUsingMocks.setUp` builds a boto3
  client outside the mock and needs the credentials or session an earlier file left behind) can fail in its file's
  own process. fenvix detects it and reports it. When a test fails in its file's process and the store has no
  in-process result to compare with, fenvix replays it in one process after the earlier tests of the session (or the
  worker). If it passes there, the run reports the pass, the user's normal outcome, and a `PLACEMENT FINDING` naming
  the earlier files. A test whose outcome differs from a stored in-process result is reported the same way. A test
  that passes only in its own process (an earlier file breaks it in one process) is reported as passed under
  `--det-isolate` unless an in-process result is stored: the isolation the user asked for. The replay reruns every
  earlier test once per failing file, and only for failures: moto `tests/test_s3/` with 5 failures that also fail
  without the isolation took 118 s against 45 s (MEASURED, 4 CPUs). `DETPY_PLACEMENT_REPLAY=0` turns the replay off;
  `DETPY_PLACEMENT_REPLAY_S` bounds it (default 900 s; past it the failure stands). Under `-n`, the replay runs the
  earlier tests of the same worker, as plain `pytest -n` does.
* **Speed numbers below were MEASURED with the earlier per-file default** (one child per test file, before
  2026-11-21); with the in-process default they are UNKNOWN until remeasured.
* **Speed when most tests miss** (founder decision 2026-11-21). On commits that change code most tests depend on, a
  cached `-n 4` run is slower than the uncached one, with no wrong result: moto 96f50b1a, 10 commits, 6 of them
  changing moto core: 755 s cached against 648 s uncached at `-n 4` (MEASURED, CI). Each file's process reloads the
  libraries' caches (botocore's service models) and the cache records every test. Unchanged reruns and the serial
  walk are faster cached: 24.8 s against 67.3 s, and 1,577 s against 1,702 s.
* **No reuse where every test resolves a name.** A name resolution is a network input, so a suite whose setup
  resolves `localhost` in every test (litellm's pytest-socket `socket_allow_hosts`) reuses nothing and pays the
  per-file cost: 220-240 s against 48 s at `-n 4` (MEASURED, litellm 17e6ea8c `tests/unit/llms/vertex_ai`).

## 10. Parallel lanes (`--det-workers=N`, and the default since G-1044): cross-file state on a first run

Since row JS-07 (gap G-1044) a `--det` run of the JavaScript runners uses this machine's CPUs as lanes unless the
user asks for something else. The guarantee the lanes are meant to keep is that a parallel run observes exactly what
a serial run observed: measured on real suites it holds (ufo 471 tests under the Vitest `threads` and `forks` pools,
luxon 1116 under Jest workers, simple-statistics 277 under node:test all verify `IDENTICAL` against their serial
run, 0 hazards, 0 not proven).

Since the P1 fix below it also holds on the **first** parallel run of files that share state the engine has not
seen yet: a run that reports a cross-worker hazard re-runs the files that hazard names in one lane and reports the
re-run's outcomes, so a placement can no longer decide an outcome. `docs/PARALLEL-PROOF-DESIGN.md` (design P6)
specifies preventing the conflict *a priori* from recorded footprints, which the Python/xdist path does and the
Node path still does not: the Node path detects the conflict after the fact and then pays for a second, safe run
of the files involved. P6's acceptance criterion ("0 new failures caused by the split") is met; its mechanism is
not the designed one. The limits below are the Node shell's.

| # | limit | found | mitigation |
|---|---|---|---|
| P1 (closed) | **A first parallel run of two files that share a path or a fixed port reported failures a serial run did not.** The lanes are planned before anything is known about what the files touch; the conflict is found only after the run, from the recorded footprints, and reported as `CROSS-WORKER <kind> <path>: <file> (lane i) / <file> (lane j); the next plan puts them in one lane`. The placement is corrected for the *next* run, so the first run's outcome has already been reported. Reproduced twice, in both conflict classes: `node/test/controls.test.js` "isolation: parallel workers interleave" (two files sharing `shared.log`: both pass serially, both fail in lanes), and two files binding one fixed port (2 passed serially; in 2 lanes one fails with `EADDRINUSE`, then passes on every later run once the edge is learnt). The signature is run 1 red, runs 2 and later green - the retry-flakiness the engine exists to remove. Detection itself is sound: the hazard names the exact path or port and the exact pair of files, which is why that test and `controls.test.js` "order: files run in sorted order" ask for `--det-workers=1` explicitly. Design P6 lists "0 new failures caused by the split" as an acceptance criterion, so this is a gap against the design, not an accepted cost. | Block 3 (row JS-07) | **Closed** (`node/src/parallel-rerun.js`). When a run reports cross-worker hazards, the files those hazards name are run again in ONE lane (`--det-workers=1`) and the re-run's outcomes are the ones reported, in the exit status and in the merged trace; `meta.hazard_rerun` records the files, the hazards, whether the re-run accounted for every affected test, and what the first run had failed. MEASURED on both conflict classes, Vitest and Jest, Node 22.23.5: shared path, wrapper off `1 failed / 1 passed` rc=1 -> on `2 passed` rc=0; fixed port 45321, wrapper off `EADDRINUSE` rc=1 -> on `2 passed` rc=0. A genuine defect in an affected file is still reported (rc=1, that test still `failed`), and a run with no hazard pays nothing: no second pass, no `hazard_rerun` key. Default-deny: if the re-run's trace cannot be read, or an affected test leaves no record in it, the first run's records stay in the trace and every unaccounted test is NOT PROVEN (exit 1), with the reason printed; and the first run's red is cleared only when all of it is inside the re-run files (failed records, `meta.file_failures`, unhandled errors; `firstRedInHazardFiles`), so a failure elsewhere keeps the run red. What it costs the customer: the affected files are run twice, so a suite with cross-file state pays those files' time again. |
| P2 | **A together-edge never expires.** Once two files are seen touching one path from two lanes, `state.together` in `.detjs/plan-state.json` keeps them in a single lane for every later run (`node/src/parallel.js`, the entry is written and never removed). The parallelism of a project therefore only decreases, and does not recover after the suite is fixed. Measured: the JS-07.kept probe reports 2 concurrent files on a fresh plan state and 1 on every run after it in the same project directory. (The exam check itself is unaffected: `lib.Ctx.clone()` removes the project directory once per `run.py` process, and `.detjs/plan-state.json` with it.) A second measured consequence, found while writing the P1 tests: once the edge is learnt, the conflict can no longer be reproduced in that project directory at all, because every later plan puts the pair in one lane. The first version of both P1 tests passed for the wrong reason because of it, and they now force the lanes with `--det-plan`. So the edge does not only cost parallelism over time: it also hides the very conflict it was learnt from, which is why a regression test for a hazard must never rely on the planner. | Block 3 (row JS-07) | Delete `.detjs/plan-state.json` (or `DETJS_PLAN_STATE`) to forget the edges; `--det-plan=TRACE\|JSON` replays a chosen plan. |
| P4 | **A sharded `node:test` run cannot yet be verified against the unsharded one.** node:test runs every test file in its own process (`isolation=process`), but the verifier still treats a serial trace as one undivided sequence: `Predecessors` in `crates/detpy-core/src/verify.rs` keys every test of a serial run under one empty worker id, so a test's predecessors are all the tests earlier in the whole run, not the earlier tests of its own file. Comparing a shard against the full run therefore reports an `order` divergence for every test whose file moved, although no test ran differently. MEASURED (exam run 44958011775, simple-statistics, 277 tests, both legs linux-x64/py3.13 node22 and node26): shard 1/2 against the full run gives `diverged: 151, missing: 125` with `reasons {"missing": 125, "order": 151}`, and the two shards together cover the serial run exactly (`serial passed=277, shards passed=277`). The same suite under `--test-concurrency=4` in ONE run verifies `IDENTICAL` 277/277 against serial, so what is missing is the scoping of the comparison, not the determinism of the run. What it costs the customer: node:test shards are run and proven **within** a shard, not across the split -- a sharded CI job still gets a deterministic, verified run, but the engine will not certify that shard 1 plus shard 2 equals the unsharded suite. The shell side is in place: the trace header now declares `meta.isolation_unit: "per-file"` whenever node:test ran with its own `isolation=process`, which is the fact the verifier needs; scoping `Predecessors` by that unit is a change to the comparison itself and belongs to the verifier's owner. Not set under `--test-isolation=none` (every file shares the driver process, so the claim would be false), and not set for Vitest or Jest (a fresh worker per file looks like the same guarantee, but it is not measured here). | Block 3 (row JS-07) | None today. `--test-concurrency=N` instead of `--test-shard=i/N` gives a single run that verifies identical to serial. |
| P5 | **In lanes, a Jest project with a `NODE_OPTIONS` preload is not cached at all.** A preload named in `NODE_OPTIONS` runs in every Jest worker *before* the capture starts, so what it reads is not observed; rather than reuse a result whose inputs it cannot see, the engine refuses the whole project (`node/src/jest/cli.js`, reason `NODE_OPTIONS preloads run in Jest workers before the capture`, recorded in the run summary's `misses`). Serially the refusal is per file and names the finer cause (`a preload module read the clock or OS entropy before Level 0`). MEASURED (`node/test/cache-p041.test.js`, G-1586, jest 30.5.2): with lanes, `misses` holds the project reason and `not_cached_detail` is empty; nothing of the project is reused on a second run, and a change the preload makes visible still fails the cached run exactly as a fresh one. So this costs **reuse, not correctness** -- the coarser refusal is strictly stronger than the per-file one. It is **not** the default experience: since Jest keeps the proof by default (P6 below) a defaulted `--det` run has one lane and the finer per-file refusal applies, so only a user who asks Jest for lanes by name meets this. | Block 3 (row JS-07) | Let Jest default to one lane (the current default), which restores per-file caching. |
| P6 | **Jest runs in one lane by default, because lanes cost the proof.** Jest 30 resolves modules with a native addon (`@unrs/resolver`), and in a worker it is loaded *outside any test*, so the general rule -- correctly, default-deny -- marks every test of the run NOT PROVEN (`meta.not_proven_outside_tests` holds exactly that one entry). Nothing is wrongly reused and nothing is wrongly called identical: what is lost is the proof itself, and the cache's reuse with it. MEASURED (jest 30.5.2, a suite of 8 files / 48 tests, two runs per configuration, `fenvix verify` on the pair): the serial default verifies `IDENTICAL` with `covered by Level 0: 48 of 48` in 1313 / 1364 ms; `-w 4` gives `NOT PROVEN: 48 of 48`, `covered by Level 0: 0`, in 1584 ms -- on that suite the lanes are not even faster, because worker start-up dominates eight small files on four cores. On a larger suite the lanes do win (luxon under Jest: 1.6x at 8 lanes, MEASURED). So the engine refuses the lanes only when the lane count came from the default, and says so; a user who names them (`--det-workers=N`, `-w N`, `--maxWorkers=N`) gets them, and loses the proof for that run. Vitest and node:test are unaffected and stay parallel by default (both verify IDENTICAL at 1 and at 4 lanes, MEASURED). | Block 3 (row JS-07) | `--det-workers=N` or `-w N` to take the lanes and give up the proof for that run. The proper fix, which gives Jest lanes **and** the proof, is auditing `@unrs/resolver` by what it asks the system for (founder, 2026-11-21, route 1) rather than whitelisting it on a look. |
| P3 | **In lanes, a Jest `globalSetup` that runs a child process is never reused from the cache.** The entry is recorded with a worker's start-up digest and checked against the main process's, which is empty, so the keys cannot match (`startupDigest()` in `node/src/cache/proof.js`, compared at `crates/detpy-core/src/proof.rs` `startup`). The miss is reported honestly ("a process started at start-up gave back a different output or exit code") and nothing is wrongly reused, so this costs reuse, not correctness. Predates G-1044 (reproduces on the previous commit with an explicit `--det-workers=4`); the default made it the default experience. | Block 3 (row JS-07) | `--det-workers=1` for such a suite until the two digests are computed in the same process. |

### Measured by row JS-07, owned elsewhere

These are recorded here with their measurement because row JS-07 measured them; none is the Node parallel path's to
fix, and each names its owner.

| # | what | owner |
|---|---|---|
| X1 | **The `seeds` control is about 8 s of the ~13 s of engine overhead on luxon** -- half the run. MEASURED (luxon 3.5.0 under Jest, this container, 4 cores, whole-command wall clock, controls disabled one at a time): with `seeds` disabled 7.60 s / 7.73 s against about 15 s with it; disabling `net` changes nothing (15.38 s / 15.15 s). `node/src/seeds.js` calls `require('./concur').sync()` on every intercepted draw (`mathRandom`, `nonce`, ...). It is the single biggest lever on whether "faster tests" is true for Jest suites, which is why it is written down rather than left in a report. | Level 0 (`node/src/seeds.js`), not the parallel path. |
| X2 | **Parallel costs more CPU than it saves in latency.** MEASURED (luxon under Jest, this container): serial 14.44 s; at 8 lanes the run does **4.1x the CPU work** of the serial run to finish **1.6x sooner** (59.66 s of core time against 14.44 s). Across three runners parallel gives 1.6x-2.2x on 4 cores. "Finishes sooner" is supported by the data; "and costs less" is supported only if we price wall clock, not core-seconds. | The founder (pricing); the coordinator is carrying it. |
| X3 | **`--det` pins UTC and `C.UTF-8` although `--det-help` declares the environment's value as the default.** DECLARED by the help text: `--det-tz=ZONE\|keep   time zone of the run (default: TZ when set, else UTC; recorded)`, and the same shape for `--det-locale`. MEASURED: with `TZ=Asia/Tokyo` in the environment, a `--det` run records `tz: "UTC TZ=UTC"` and `pinned: "tz=UTC;locale=C.UTF-8"`. The code agrees with the behaviour and not with the help: `pinned()` in `node/bin/detjs.js` defaults to the literal `'UTC'` and never reads `process.env.TZ`. Pinning is the right behaviour for a deterministic run (and `--det-tz=keep` opts out); the help text is what is wrong. | The time control's owner. |

