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
| O1 | pytest-xdist is not supported: the order is only fixed inside each worker and distribution is dynamic. | D | Run without `-n`. |
| O2 | Plugins that reorder (`pytest-randomly`, `pytest-random-order`) are unregistered under `--det`; any other reordering done in `pytest_collection_modifyitems` is undone (deselection is kept). Reorderings done in other hooks are not detected. | T | `--det-seed` gives reproducible shuffles. |
| O3 | Shuffle granularity is module → class → test; tests depending on a sibling module's side effects can still break under a shuffle (that is the point of nightly multi-seed runs). | D | — |

## 2. Seeds and hashing

| # | limit | found | mitigation |
|---|---|---|---|
| R1 | `PYTHONHASHSEED` can only be fixed by re-executing the interpreter. Not possible for in-process sessions (`pytest.main()`, pytester inline), on Windows, or on Python < 3.10 (`sys.orig_argv`). The status is printed in the header and stored in the trace (`meta.reexec`). | T | Export `PYTHONHASHSEED=0` yourself. |
| R2 | **`.pyc` state changes set iteration order.** A set literal is compiled to a `frozenset` constant; the `.pyc` stores it in the iteration order of the compiling process, and loading it rebuilds the set by inserting in that order, which can yield a different layout than compiling from source — even with the same hash seed. So the first run after a source change can differ from later runs. | T | `--det-fresh-bytecode` (never read/write `.pyc`; slower start-up). |
| R3 | Address-based hashes (`id()`, default `__hash__`, `repr` with `0x…`) are deterministic only with ASLR disabled, done by the re-exec on Linux via `personality(ADDR_NO_RANDOMIZE)`; it fails silently under seccomp profiles that forbid it, and does not exist elsewhere. | D | `--det-keep-aslr` to opt out. |
| R4 | Only `random`, `numpy.random` (global state and `default_rng()` without seed) are seeded. `torch`, `tensorflow`, `jax`, `faker`'s own generators, etc. are not. numpy is reseeded only if already imported when the test starts. | D | — |
| R5 | `os.urandom`, `uuid4`, `secrets`, `SystemRandom` are **observed, not controlled** (they are meant to be unpredictable). They show up as `entropy` divergences. | T,H | `--det-urandom` makes them deterministic (never for crypto tests). |
| R6 | `random.Random` instances created before installation (by plugins) are reseeded once, not per test. | D | — |

## 3. Virtual clock

| # | limit | found | mitigation |
|---|---|---|---|
| C1 | **Time-calibrated loops never terminate.** Code that measures how long CPU work takes, without reading the clock inside the work, sees a constant duration of one tick. `pytest-benchmark` calibration doubled its loop count forever (humanize). | H | Benchmarks are switched to `--benchmark-disable` under `--det` (and `--codspeed` is dropped). Other such code: `--det-disable=time`. |
| C2 | Polling loops with a timeout that wait for *real* work (another process, a thread doing I/O) burn virtual time faster than real time: virtual `sleep` returns immediately, so the timeout can expire before the work is done. | D | `--det-sleep=real` (sleep waits *and* advances the clock). |
| C3 | asyncio keeps real time: its selector blocks for real, so `loop.time()` is not virtualised (virtualising it made `asyncio.sleep` spin). | T | — |
| C4 | Blocking primitives that time out (`Condition/Event.wait`, `Queue.get`) advance the virtual clock by their timeout; whether they time out depends on real scheduling. `Lock.acquire(timeout=)`, `select`, socket timeouts, `subprocess.wait(timeout=)` use real time and do not move the clock. | T | — |
| C5 | One clock for all threads: reads from several threads interleave by real scheduling, so values (and the fingerprint) depend on it → `thread` divergences. | T | — |
| C6 | The wall clock restarts at the epoch for every test, the monotonic clock does not (it must never go backwards in a process). Absolute monotonic values depend on the test position; fingerprints record them relative to the test start. | D | — |
| C7 | Not virtualised: `time.process_time`, `thread_time`, `resource.getrusage`, file timestamps (`os.stat().st_mtime`, `touch`), `time.localtime()` depends on `TZ`. | D | — |

## 4. Filesystem order

| # | limit | found | mitigation |
|---|---|---|---|
| F1 | Only the *order* of enumeration is normalised; file contents, sizes, timestamps, inode numbers, free space are not observed. Tests whose outcome depends on files left by previous runs show up as `outcome-only`. | T | — |
| F2 | `glob.iglob`, `Path.glob/rglob/iterdir` become eager (the whole result is materialised to sort it). | D | — |

## 5. Network

| # | limit | found | mitigation |
|---|---|---|---|
| N1 | Only Python sockets are guarded: native clients and subprocesses (`curl`, `git`, `pip`) reach the network. | D | Syscall backend / network namespace. |
| N2 | Local proxies are recognised only through `*_PROXY` environment variables. | T | — |
| N3 | Replay matches connections by (test, host, port, n-th connection); request bytes that differ from the recording are only reported (`replay.mismatch` event), not rejected. | T | Re-record. |
| N4 | TLS is replayed with a plaintext stand-in (`ReplayTLSSocket`) that is **not** an `ssl.SSLSocket` instance; asyncio TLS (memory BIO: aiohttp, async httpx) cannot be replayed. UDP is never recorded. A replayed socket is an `AF_UNIX` socketpair end: TCP socket options are ignored and `getpeername` is faked. Verified with `urllib` and `requests`/urllib3 2.x over HTTPS. | T | — |

## 6. Fingerprints

| # | limit | found | mitigation |
|---|---|---|---|
| P1 | The fingerprint only covers sources detpy observes. A test can be flaky with an identical fingerprint and only its outcome differing (`outcome-only`): the cause is outside the observed set (file contents, C code, scheduling without clock reads, external state). | T | Syscall backend. |
| P2 | Events from threads that outlive their test are attributed to the test that is running when they happen. | D | — |
| P3 | Divergences are located exactly within the first `--det-max-events` events (default 10 000); later ones are bracketed by checkpoints every 256 events (`beyond-trace`). | T | Raise `--det-max-events`. |
| P4 | Events whose first non-stdlib frame is pytest or detpy (e.g. `tmp_path` creation) are not recorded; fixtures implemented in third-party pytest plugins are recorded. | T | — |
