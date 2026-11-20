PARTIAL

# py-cache: rows F-05, PY-05, PY-08 (session 2026-11-20)

Branch `claude/py-cache` (from `claude/parallel-proof-3` @ dce6c36e, with `claude/release-1` merged at d27c1a59 and
71b12503). PR #5 into `claude/release-1`.

Why PARTIAL, in one paragraph: the wrong results this session targeted are closed by class and tested (below), the
memory item is done and measured on a synthetic suite, but the row-level DONE conditions are not all met: the
real-repository walks (item 5) and the before/after memory pairs on real repositories run in GitHub Actions run
__WALK_RUN__ and their numbers are __WALK_STATUS__; PY-05 is "never silent" (a finding that fails the session), not
"the same outcomes as serial" by construction; a test with no stored entry (new, or never cacheable) does not run its
reused predecessors (gap listed below).

## 1. What is now true, per row

### F-05 cache with proof (serial and -n), with receipts

* **Process-level state is part of every key** (`python/detpy/_proof.py: process_identity`, folded into the
  configuration digest by `level0_identity`, so every runner gets it): the whole process environment except the
  variables of `ENV_ALLOWLIST` (each with its written reason: detpy's own bookkeeping variables, pytest-xdist's
  per-worker variables, `PYTEST_CURRENT_TEST`, shell bookkeeping `PWD/OLDPWD/SHLVL/_`, GitHub Actions per-run ids and
  per-step file paths, systemd/terminal/SSH session ids, detpy's own equivalence-test switch `DETPY_L0_REF`), the usable
  CPUs (`sched_getaffinity`) and `cpu_count`, the umask, every `RLIMIT_*`, the host name, uid/gid/groups,
  `sys.warnoptions`, `-X` options and `sys.flags`. A Python-level read of an allowlisted variable is still an input of
  the test that reads it (os.environ is recorded per test).
  Closes G-0160 (CPUs), G-0161 (umask), G-0162 (rlimits), G-0163 (host name), and the PYTHONWARNINGS family (the
  former strict xfail `test_culprit_keys.py::test_pythonwarnings_is_an_input` now passes).
* **Code outside the project** (`ProofSession._outside_modules`): every module loaded from outside the root, the
  standard library and every installed distribution's RECORD (PYTHONPATH, a `.pth` directory, a file dropped into
  site-packages) is a content input of every test of the process. Closes G-0164.
  `sys.path` itself, the `.pth` files and the mapped shared objects (LD_PRELOAD included, through the environment and
  the start-up map scan) were already in the runtime identity / start-up inputs; unchanged.
* **Status reads reach user code through any frame** (R-023c E2/E4, ported onto release-1's `_proof.py`):
  `os.stat/lstat/access/readlink/fstat` decide user-ness by walking out through the standard library and
  infrastructure frames (`_reaches_user`); an existence or kind check of the standard library keys the kind; a stat
  asked for its own sake keys the metadata probe (kind, mode, size, mtime); a read of `st_mtime/st_ctime` keys the
  times (`y:`), of any other field the status fields (`x:`, renamed from this branch's `w:` because release-1 uses
  `w:` for recursive listings); `st_atime` and `getatime` refuse; `os.fstat`/`os.stat(fd)` are named through
  /proc/self/fd; `os.access` with a permission keys the permission bits and owner. Code compiled from a string
  (execnet's worker bootstrap) is not user code: its caller decides (this was making -n entries differ from serial).
* **Libc through ctypes** (`CDLL(None)`, `ctypes.pythonapi`, dlsym, call_function) refuses (R-023c E3, kept).
* **Temporary roots**: a kind check of `/tmp`, `/var/tmp`, `$TMPDIR` is an input; a mkdir of an existing path is a
  kind input, not a write (R-023c E1, kept).
* **Infrastructure objects** connect writer and reader (R-023c E5, kept: pytest, pluggy, xdist and detpy imports reach
  the library node; pytest's session objects are dynamic markers).
* **Memory (item 4)**: an entry's data dependencies are stored as content-defined, content-addressed chunks
  (`crates/detpy-core/src/datachunks.rs`; store version 2). A chunk boundary follows a pair whose key hashes to 0 mod
  16 (or 64 pairs); each distinct chunk is one `Arc` in memory and is written once per store file
  (`Store::chunks`); an entry lists chunk addresses. The pairs, their order and their values are exactly the recorded
  list, so the checker sees the same dependencies. `_proof.load_store()` expands a store file for readers.
* The R-023c review file (`tests/test_review_r023c.py`) is merged unchanged; its shared-store test is skipped as out
  of go-live scope (tests/conftest.py skips every test that passes `--det-cache-shared`; the Node shared-service
  suite is skipped the same way).

### PY-05 pytest-xdist -n under --det

* **A difference with the serial outcome is never silent**: the controller (and an isolated session) knows, for every
  test that runs, the outcome of its stored serial result when its inputs are unchanged (`_expect_serial`); a test
  whose outcome here differs is reported in a `detpy PLACEMENT FINDINGS` section and the session's exit status is
  "tests failed". `--det-isolate` reads the store through a second read-only view keyed with the serial session's
  configuration digest (`config_identity(as_if={"det_isolate": False})`). Closes G-0175, G-0169, G-0172 and G-0176
  as "never silent" when a serial result is stored.
* **R-023c E7**: a test that runs runs after every reused predecessor of its process (worker) whose in-process state
  it may need (`Entry::needs`; every predecessor when it reached the library node). Applies to tests with a stored
  entry; closes G-0173 (test_review_r023c 4a, serial and n2).
* G-0174: a serial `--det` session with pytest-xdist installed gets the derived `testrun_uid`, not xdist's uuid4().

### PY-08 native code and subprocesses

* A process started by a test or by a wider-scoped fixture runs, and that test is never reused
  (`capture.rs credit_child_impl`, reason "... [a test that starts a process is never reused]"). Children of the
  import, collection and start-up contexts are still followed and keyed (a library's `find_library` at import time).
* Native code of the repository ("native") and C reached through ctypes ("cdll") refuse, as before.

## 2. What is not true (missing)

1. **Real-repository walks and memory pairs (items 4 and 5 on real repositories)**: __WALK_STATUS__.
2. **PY-05 is detection, not equivalence**: when no serial result is stored under unchanged inputs (first run, a
   changed test), a placement-dependent outcome under -n is not compared with anything. The finding needs the store.
3. **E7 for tests without an entry**: a new or never-cacheable test that runs does not make its reused predecessors
   run (review R-009's gate `test_git_head_read_is_an_input` requires the reusable predecessor of a never-cacheable
   test to be reused). Such a test can see a different in-process state than in a serial session; its outcome is never
   reused, but it is reported as it is.
4. **Reuse cost of E7**: when a test with an entry must run, every earlier test of its process that reaches the library
   node runs too (most real test modules do). Measured effect on real repositories: __REUSE__.
5. **Receipts name "config" for a process-environment change** (G-2197 class): the receipt does not say which
   variable or limit changed.
6. Not attempted: G-1509/G-1510 (cache audit/explain command), G-1548 (`--dist each`), G-1549/G-1550 (plan depends on
   the worker count; worker-id readers), G-1551 (dead worker), G-1553 (worksteal), G-2214/G-2215 (crash records,
   header wording), G-2211 (pytest 10 deprecation in isolate), G-1539 (isolate in runner shells), G-1545 (parallel for
   other runners), G-0159 (virtual-day epoch), G-0510/G-1507/G-1511/G-1537 (carried refusal granularity).

## 3. Audit gaps of these rows (2026-11-20 audit), one line each

| gap | status | evidence |
|---|---|---|
| G-0004 fa290d64 not on release-1 | fixed (merged with the branch) | tests/test_round4_capture.py |
| G-0159 virtual-day epoch for Python | not fixed (not attempted) | — |
| G-0160 CPU count not an input | fixed | test_py_cache.py::test_g0160_usable_cpus_are_an_input |
| G-0161 umask not an input | fixed | test_py_cache.py::test_g0161_umask_is_an_input |
| G-0162 rlimits not an input | fixed | test_py_cache.py::test_g0162_resource_limits_are_an_input |
| G-0163 host name not an input | fixed | test_py_cache.py::test_g0163_host_name_is_an_input (needs root+unshare; skipped elsewhere) |
| G-0164 module from PYTHONPATH outside root | fixed | test_py_cache.py::test_g0164_module_from_pythonpath_outside_the_root_is_an_input |
| G-0169 --det-isolate changes a verdict silently | fixed as a finding when a serial result is stored | test_py_cache.py::test_placement_difference_is_a_finding[isolate] |
| G-0172 -n flips a serial outcome silently | fixed as a finding when a serial result is stored | test_py_cache.py::test_placement_difference_is_a_finding[n2] |
| G-0173 --det-cache makes an order-dependent test fail | fixed (E7) | test_review_r023c.py::test_4a_* (serial, n2) |
| G-0174 serial testrun_uid uuid4 | fixed | test_py_cache.py::test_g0174_serial_testrun_uid_is_derived_under_det |
| G-0175 -n outcomes differ from serial silently | fixed as a finding when a serial result is stored | test_py_cache.py::test_placement_difference_is_a_finding[n2] |
| G-0176 cache changes -n verdicts | same mechanism (finding) + E7 per worker | test_review_r023c.py::test_4a_*[n2] |
| G-0510 numpy entropy refuses every later test | not fixed | — |
| G-0511, G-0414, G-0552, G-0558 Python < 3.12 | out of scope (go-live: 3.12-3.14) | — |
| G-0546 threads L1 | not this row | — |
| G-1284 / G-1540 subprocesses and C extensions uncontrolled | closed for the cache by PY-08 (never reused) | test_py_cache.py::test_py08_* |
| G-1507, G-1511, G-1537 carried refusal granularity | not fixed | — |
| G-1508 prefix-rule over-invalidation | not fixed; E7 adds predecessors (measured in 2.4) | — |
| G-1509, G-1510 receipts / cache command | not fixed | — |
| G-1539, G-1545 isolate / parallel for other runners | not fixed | — |
| G-1542 overhead number | partly: synthetic warm -n 4 time below; real repositories __WALK_STATUS__ | — |
| G-1544 strace missing message | moot for test children (refused anyway); not changed for import-time children | — |
| G-1548..G-1553, G-2214, G-2215 xdist modes and wording | not fixed | — |
| G-1552, G-0399 remote --tx | out of scope (shared/remote machines) | — |
| G-1572, G-2217, G-0218, G-0219, G-0270, G-0559 shared cache | out of scope (shared cache across machines) | tests skipped "out of go-live scope" |
| G-2196 receipts overwritten | not fixed | — |
| G-2197 TZ change named "config" | not fixed (now every process-environment change says "config") | — |
| G-2211 isolate deprecation warning | not fixed | — |
| G-0676 start-up git makes tests uncacheable | unchanged (start-up children keep the R-008d rule) | test_review_r008d.py |

## 4. Numbers

### 4.1 Gates (MEASURED)

* `tests/test_review_r023c.py`, R-023, R-023b, R-032b review files and `tests/test_py_cache.py`, serial, Python 3.13.18:
  **131 passed, 10 skipped, 0 failed** (`sessions/2026-11-20-py-cache/gates/reviews-r023c-r023-r023b-r032b-pycache.txt`;
  the skips: runner modules not installed here, the shared-store test, host-name test needs).
* Full `tests/` locally (`pytest -n 4`, 1081 cases): 18 failed in the run on b859c84b's parent; 13 of them were
  artifacts of running pytester suites under an outer `-n 4` (they pass serially), the other 5 were fixed in b859c84b
  and pass (`DETPY_L0_REF` allowlist, replayed worker uid).
* `cargo test --workspace --exclude detpy-py`: 140 + 19 + 13 + 2 passed, 0 failed (MEASURED, local).
* Node: `node --test --test-concurrency=1 test/*.test.js` locally (Node 22.23.5): 619 tests, 618 passed, 1 skipped (the shared cache service suite, out of go-live scope), 0 failed (MEASURED).
* GitHub Actions `release-1` on PR #5: run __CI_RUN__: __CI__.

### 4.2 Memory and time, synthetic suite (MEASURED, this machine, 4 CPUs, other jobs running)

3,000 tests in 60 files, 400 files read by conftest at import, 40 per test module, one per test; `-n 4`; `--det
--det-cache`; engine before = d27c1a59 (merge, inline data), after = this branch (chunks). Command:
`/tmp/.../synth/measure.py` (`os.wait4` ru_maxrss of pytest and its reaped workers).

| | before | after |
|---|---|---|
| store file (proof-cache.json) | 101,128 KB | 11,828 KB (−88%) |
| cold -n 4 peak RSS / wall | 551.9 MB / 17.5 s | 372.6 MB / 10.2 s |
| warm -n 4 peak RSS / wall (all 3,000 reused) | 688.4 MB / 5.9 s; 688.1 MB / 6.0 s | 149.6 MB / 4.9 s; 149.8 MB / 5.2 s |
| decisions after one test file's input changes (-n 4) | 2,950 reused, 50 data | 2,950 reused, 50 data (identical sets) |
| decisions after a conftest input changes | 0 reused, 3,000 data | 0 reused, 3,000 data |

### 4.3 Memory on real repositories (before/after pairs, run __WALK_RUN__)

__MEM__

### 4.4 Reuse on real repositories after the stricter rules (run __WALK_RUN__)

__REUSE_TABLE__
