PARTIAL

# py-cache: rows F-05, PY-05, PY-08 (session 2026-11-20)

Branch `claude/py-cache` (from `claude/parallel-proof-3` @ dce6c36e; `claude/release-1` merged at d27c1a59 and
71b12503). PR #5 into `claude/release-1`.

**Why PARTIAL** (blockers named, per the coordinator's rule):
1. __CI_LINE__
2. __WALK_LINE__
3. Gaps left open in these rows (section 3, "not fixed"): the carried-refusal family (G-1507, G-1508, G-1511,
   G-1537, G-1563) and PY-05's equivalence when no serial result is stored. Both need a new mechanism (attributing
   in-process writes to the test that made them; a serial reference run), not a rule change: every rule that would
   make them reuse more today is one that could reuse a wrong result. They are listed with what was measured.

## 1. What is now true, per row

### F-05 cache with proof (serial and -n), with receipts

* **Process-level state is part of every key** (`python/detpy/_proof.py: process_identity`, in the configuration
  digest through `level0_identity`, so every runner has it): the whole process environment except the variables of
  `ENV_ALLOWLIST`, each with its written reason (detpy's own bookkeeping variables, `DETPY_L0_REF` (detpy's own
  equivalence-test switch), pytest-xdist's per-worker variables, `PYTEST_CURRENT_TEST`, shell bookkeeping
  `PWD/OLDPWD/SHLVL/_`, GitHub Actions per-run ids and per-step file paths, systemd/terminal/SSH session ids); the
  usable CPUs (`sched_getaffinity`) and `cpu_count`; the umask; every `RLIMIT_*`; the host name; uid/gid/groups;
  `sys.warnoptions`, `-X` options and `sys.flags`. A Python read of an allowlisted variable is still an input of the
  test that reads it (os.environ is recorded per test). Closes G-0160, G-0161, G-0162, G-0163 and the PYTHONWARNINGS
  case (the former strict xfail `test_culprit_keys.py::test_pythonwarnings_is_an_input` passes).
* **Code outside the project** (`ProofSession._outside_modules`): a module loaded from outside the root, the
  standard library and every installed RECORD (PYTHONPATH, a `.pth` directory, a file dropped into site-packages) is a
  content input of every test of the process. Closes G-0164. (`sys.path`, the `.pth` files and the mapped shared
  objects, LD_PRELOAD included, were already inputs.)
* **Status reads** (review R-023c E1-E4, ported onto release-1's `_proof.py`): user-ness is decided by walking out
  through standard-library and infrastructure frames (`_reaches_user`; code compiled from a string, such as execnet's
  worker bootstrap, is not user code). An existence/kind check keys the kind; a stat for its own sake the metadata
  probe (kind, mode, size, mtime); `st_mtime/st_ctime` reads key the times (`y:`), other field reads the status
  fields (`x:`; this branch's `w:` renamed: release-1 uses `w:` for recursive listings); `st_atime`/`getatime`
  refuse; `os.fstat`/`os.stat(fd)` are named through /proc/self/fd; a descriptor of an unlinked file is the process's
  own (only its times refuse; found on moto, where it refused every test); `os.access` with a permission keys the
  owner and permission bits; a kind check of `/tmp`, `/var/tmp`, `$TMPDIR` is an input; a mkdir of an existing path is
  a kind input.
* **Libc through ctypes** (`CDLL(None)`, `ctypes.pythonapi`, dlsym, call_function) refuses (R-023c E3).
* **Infrastructure objects** (the pytest module, `request.config`, ...) connect writer and reader (R-023c E5).
* **Epoch (G-0159)**: under `--det-cache` with `--det-epoch=auto` the epoch is the virtual day, today 00:00 UTC (the
  rule of the other languages); the nightly check `--det-cache-real-clock` runs every test on the real clock, reuses
  and records nothing, and reports (failing the session) every test that passed on the virtual day under the same
  inputs and fails on the real clock (`REAL-CLOCK FINDINGS`).
* **numpy (G-0510, G-0179)**: the OS entropy numpy draws when detpy's own reseed imports `numpy.random` seeds only a
  state detpy reseeds at once; it is not recorded (it refused the first test of every numpy process and every later
  one). A test's own entropy read still refuses.
* **Receipts and the cache command**: a miss for "config" names the parts that changed (`(changed:
  process.environment.TZ)`; G-2197, G-1509); every run's receipts are kept in `DIR/receipts/` (last 30; G-2196);
  `python -m detpy cache stats|explain|gc|clear DIR` (G-1510).
* **Memory (item 4)**: an entry's data dependencies are content-defined, content-addressed chunks
  (`crates/detpy-core/src/datachunks.rs`, store version 2): one `Arc` per distinct chunk in memory, written once per
  store file, entries list chunk addresses. Pairs, order and values are exactly the recorded list, so the checker is
  exactly as strict (measured: identical decisions, 4.2). `_proof.load_store()` expands a store file for readers.
* R-023c's review file is merged unchanged. The shared cache across machines is out of go-live scope: every test
  passing `--det-cache-shared` is skipped with that reason (tests/conftest.py), as is the Node shared-service suite.

### PY-05 pytest-xdist -n under --det

* **A difference with the serial outcome is never silent**: for every test that runs, the controller (and an
  isolated session, through a read-only store view under the serial configuration) knows the outcome of its stored
  serial result when its inputs are unchanged; a test whose outcome differs is a `PLACEMENT FINDING` and the session
  fails. Closes G-0175, G-0172, G-0176, G-0169 where a serial result is stored (see 2.1).
* **E7** (review R-023c): a test that runs runs after every reused predecessor of its worker (process) whose state it
  may need (`Entry::needs`; all earlier ones when it reached the library node). Closes G-0173.
* xdist modes: `--dist each` with the cache is a usage error with its reason (G-1548); remote `--tx` under `--det` is
  a usage error (G-1552); the header says what happened to the asked `--dist` (`no` -> `load`, `worksteal` -> the
  fixed plan; G-2215, G-1553); planned tests a dead worker never ran are listed (`NOT RUN`) and fail the session
  (G-1551); a test that crashed its worker is a record of the merged trace, outcome "crashed", so `detpy verify`
  compares it (G-2214); the work-stealing callback keeps the plan instead of raising (G-0708); a failure under `-n`
  prints the command that replays its worker's list from this run's plan (G-1549, G-1557); a serial `--det` session's
  `testrun_uid` fixture is the derived value, not xdist's uuid4() (G-0174); worker-id readers keep their recorded plan
  and are reused (G-1550: not reproducible, regression test).

### PY-08 native code and subprocesses

* A process started by a test or a wider-scoped fixture runs, and that test is never reused (`capture.rs
  credit_child_impl`: "... [a test that starts a process is never reused]"). Children of the import, collection and
  start-up contexts are still followed and keyed. Repository native code ("native") and C through ctypes ("cdll")
  refuse. Without strace the summary says that processes started outside a test are not followed (G-1544).

## 2. What is not true

1. **PY-05 is detection where the store has the serial result; otherwise nothing is compared.** On a first run, or
   for a test whose inputs changed, a placement-dependent outcome under `-n` is not checked against serial.
2. **E7 for a test without an entry** (new, or never cacheable) does not run its reused predecessors (review R-009's
   gate requires the reusable predecessor of a never-cacheable test to stay reused); such a test can see another
   in-process state than in a serial session. Its result is never reused, but it is reported as it is.
3. **Carried refusal (G-1507, G-1511, G-1537, G-1563) and prefix over-invalidation (G-1508)**: a refused test's
   refusal (entropy, network, /proc, a process) is carried into every later test of its process that reaches the
   library node, and a changed input reruns every later such test. Measured on moto (4.4): serial reuse 35 of 292
   (12%), `-n 4` reuse 180 of 292 (62%, the refused tests are quarantined on their own worker). E7 adds the earlier
   tests of a running test with an entry.
4. **Receipts** name the changed configuration parts but not the old and new values (the environment is stored as
   value digests).

## 3. Audit gaps of these rows (audit 2026-11-20), one line each

| gap | status | evidence (regression test in tests/test_py_cache.py unless named) |
|---|---|---|
| G-0004 fa290d64 not on release-1 | fixed | merged; tests/test_round4_capture.py |
| G-0159 virtual-day epoch, real-clock check | fixed | test_g0159_cache_epoch_is_the_virtual_day_and_the_real_clock_check_reports; test_proofcache_follow.py::test_cache_epoch_is_the_virtual_day_across_commits |
| G-0160 CPU count | fixed | test_g0160_usable_cpus_are_an_input |
| G-0161 umask | fixed | test_g0161_umask_is_an_input |
| G-0162 rlimits | fixed | test_g0162_resource_limits_are_an_input |
| G-0163 host name | fixed | test_g0163_host_name_is_an_input (root + unshare; skipped without) |
| G-0164 module outside the root | fixed | test_g0164_module_from_pythonpath_outside_the_root_is_an_input |
| G-0169 --det-isolate changes a verdict | fixed (finding when a serial result is stored) | test_placement_difference_is_a_finding[isolate] |
| G-0172 -n flips a serial outcome | fixed (finding when a serial result is stored) | test_placement_difference_is_a_finding[n2] |
| G-0173 rerun without reused predecessors | fixed (E7) | test_review_r023c.py::test_4a_*[serial,n2] |
| G-0174 serial testrun_uid | fixed | test_g0174_serial_testrun_uid_is_derived_under_det |
| G-0175 -n outcomes differ silently | fixed (finding when a serial result is stored) | test_placement_difference_is_a_finding[n2] |
| G-0176 cache changes -n verdicts | fixed (E7 per worker + finding) | test_review_r023c.py::test_4a_*[n2] |
| G-0510 numpy: nothing reused | fixed | test_g0510_numpy_random_imported_by_detpys_reseed_is_not_the_tests_entropy; test_g0510_entropy_read_by_the_test_itself_still_refuses |
| G-0708 worksteal NotImplementedError | fixed | test_g0708_work_stealing_callback_keeps_the_plan |
| G-1284, G-1540 children and C uncontrolled | fixed for the cache (PY-08: never reused) | test_py08_a_test_that_starts_a_process_runs_every_time; test_py08_a_fixture_that_starts_a_process_refuses_its_tests; test_py08_ctypes_libc_is_never_reused |
| G-1507, G-1511, G-1537, G-1563 carried refusal | **not fixed** (2.3) | moto numbers 4.4 |
| G-1508 prefix over-invalidation | **not fixed** (2.3) | — |
| G-1509 receipts are counters | fixed in part: config misses name the parts; `detpy cache explain` lists the inputs | test_g2197_..., test_g1510_... |
| G-1510 no cache command | fixed | test_g1510_cache_command_stats_explain_gc_clear |
| G-1539 isolate in runner shells | fixed (refused with the reason) | test_g1539_runner_shells_refuse_pytest_only_options |
| G-1542 no overhead number | fixed (measured, 4.4) | — |
| G-1544 strace missing: nothing said | fixed | test_g1544_missing_strace_is_said |
| G-1548 --dist each | fixed (refused with the reason under the cache) | test_g1548_dist_each_with_the_cache_is_refused_with_a_reason |
| G-1549 plan depends on the worker count | fixed (replay command printed per failure) | test_g1549_a_failure_under_n_prints_its_worker_replay |
| G-1550 worker-id readers withdraw reuse | not reproducible on this engine | test_g1550_worker_id_readers_keep_their_plan_and_are_reused |
| G-1551 dead worker's tests not run | fixed (NOT RUN, session fails) | test_g1551_tests_a_dead_worker_never_ran_fail_the_session |
| G-1552 remote --tx | fixed (refused with the reason) | test_g1552_remote_workers_are_refused_with_a_reason |
| G-1553 worksteal replaced silently | fixed (said in the header) | test_g2215_g1553_header_says_what_happened_to_the_asked_dist |
| G-2196 receipts overwritten | fixed | test_g2197_a_configuration_miss_names_what_changed_and_g2196_receipts_are_kept_per_run |
| G-2197 TZ change named "config" | fixed | same test |
| G-2211 isolate pytest-10 deprecation | fixed | test_g2211_isolate_sets_up_unittest_classes_without_the_teardown_deprecation |
| G-2214 crashed test has no record | fixed | test_g2214_a_test_that_crashes_its_worker_is_a_record_of_the_merged_trace |
| G-2215 --dist no header | fixed | test_g2215_g1553_header_says_what_happened_to_the_asked_dist |
| G-0546 threads L1 | moved to PY-07 | — |
| G-1545 parallel for the other runners | moved to the runner rows (PY-05 is pytest-xdist) | — |
| G-0511, G-0414, G-0552, G-0558 Python < 3.12 | out of scope | — |
| G-1552-like G-0399 remote --tx (limits) | fixed with G-1552 | — |
| G-1572, G-2217, G-0218, G-0219, G-0270, G-0559 shared cache | out of scope | tests skipped "out of go-live scope" |
| G-0676 start-up git makes tests uncacheable | unchanged by design (start-up children keep the R-008d rule) | tests/test_review_r008d.py |

## 4. Numbers

### 4.1 Gates

* Reviews R-023c (unchanged file), R-023, R-023b, R-032b and tests/test_py_cache.py, serial, Python 3.13.18: 131
  passed, 10 skipped, 0 failed at 5311faa7 (MEASURED,
  `sessions/2026-11-20-py-cache/gates/reviews-r023c-r023-r023b-r032b-pycache.txt`); test_py_cache.py has grown since
  (31 tests, all passing locally at 6a739ee9, MEASURED).
* Full `tests/` locally (`pytest -n 4`, 1096 cases) at 67ceafbb: 19 failures in that run; rerun serially, 15 passed
  (artifacts of pytester suites under an outer `-n`) and the 4 others were fixed in 6a739ee9 and pass (MEASURED).
* `cargo test --workspace --exclude detpy-py`: 0 failed (MEASURED, local). Node 22.23.5 `node --test test/*.test.js`:
  619 tests, 618 passed, 1 skipped (shared service, out of scope), 0 failed (MEASURED, local).
* GitHub Actions `release-1` on PR #5: __CI__.

### 4.2 Memory and time, synthetic suite (MEASURED, this machine, 4 CPUs, a test suite running beside it)

3,000 tests in 60 files; conftest reads 400 files at import, each module 40, each test one; `-n 4`; before = d27c1a59
(inline data), after = the chunked store. `os.wait4` ru_maxrss of pytest and its reaped workers.

| | before | after |
|---|---|---|
| store file | 101,128 KB | 11,828 KB (−88%) |
| cold peak RSS / wall | 551.9 MB / 17.5 s | 372.6 MB / 10.2 s |
| warm peak RSS / wall (3,000 reused) | 688.4 MB / 5.9 s; 688.1 MB / 6.0 s | 149.6 MB / 4.9 s; 149.8 MB / 5.2 s |
| decisions after one module's input changes | 2,950 reused, 50 data | identical |
| decisions after a conftest input changes | 0 reused, 3,000 data | identical |

### 4.3 Memory on real repositories (before/after pairs; run __WALK_RUN__)

__MEM__

### 4.4 Overhead and reuse, moto subset (MEASURED, local, one run each, NOISY: the machine ran other jobs)

moto 96f50b1a, `tests/test_sqs tests/test_batch -m 'not requires_clean_slate'`, 292 tests (12-13 fail in every
mode, plain included). Wall seconds:

| plain serial | --det | cache cold | cache warm | plain -n 4 | --det -n 4 | cache -n 4 cold | warm 1 | warm 2 |
|---|---|---|---|---|---|---|---|---|
| 281.9 | 29.0 | 33.0 (35 recorded) | 27.0 (35 reused) | 75.0 | 12.0 | 14.8 (53 recorded) | 15.7 (4 reused, 176 recorded) | 14.4 (180 reused) |

`--det-urandom` for the `--det` and cache runs (moto draws uuid4 everywhere); `--det` is faster than plain because
sleeps are virtual. Cache cold overhead over `--det`: +14% serial, +23% `-n 4`. The first warm `-n 4` run records
what the quarantine (refused tests on a worker of their own) makes cacheable; from the second, 62% is reused.

### 4.5 Reuse on real repositories after the stricter rules (run __WALK_RUN__)

__REUSE_TABLE__
