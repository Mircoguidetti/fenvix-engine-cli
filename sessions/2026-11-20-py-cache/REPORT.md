PARTIAL

# py-cache: rows F-05, PY-05, PY-08 (session 2026-11-20)

Branch `claude/py-cache` (from `claude/parallel-proof-3` @ dce6c36e; `claude/release-1` merged at d27c1a59 and
71b12503). PR #5 into `claude/release-1`.

**Why PARTIAL.** The coordinator's condition for F-05 (DECISIONS 2026-11-20) is 0 wrong reuses AND cached runs
faster than uncached on moto, pydantic-ai, litellm and esphome. Wrong reuses: 0 in every measured run. Speed: green on
unchanged reruns and on moto's serial walk, red on moto's `-n 4` walk (MEASURED, CI run 44825894259, 10 commits):

| moto 96f50b1a walk, 10 commits | cached | uncached |
|---|---|---|
| unchanged rerun, -n 4 (commit 0) | 24.8 s | 67.3 s |
| whole walk, -n 4 | 755 s | 648 s |
| whole walk, serial | 1,577 s | 1,702 s |

6 of the 10 commits change moto core, so every test misses there and the per-file mode pays its fixed cost. Breakdown
of one such commit (MEASURED, this container, `-n 4`, 2,496 tests, cached 64 s against 46.5 s): tests themselves run
~8 s per worker slower (test time 176.5 s against 144.5 s, almost all `test_ec2`: each file's fresh child reloads
botocore's EC2 service model), recording ~3 s per worker (`record_session_keys` 7.8 s + plan 3 s of CPU over 105
children), forks and pipes ~1 s per worker, the rest collection and balance. Removing the recording cost entirely would
leave the walk near 730 s: still red. The founder decides at 08:00 (coordinator, 2026-11-21 01:36); the frozen exam's
F-05, PY-05 and PY-08 checks are the done-means of the rows (section 4.1).

## 0. The design decision of this session

Coordinator, 2026-11-20 14:46 and 15:04 (founder's decision, recorded in DECISIONS): under `--det-cache` the Python
cache isolates per test file, a fork per file, as Jest/Vitest do. On Linux this is now the default, serial and `-n`;
`--det-cache-in-process` (or `DETPY_CACHE_IN_PROCESS=1`) keeps the session's process and its carried-set rule, and
stays sound (every gate of R-023, R-023b, R-023c runs in that mode, unchanged, and passes).

Why: in one process every moto entry depended on "every earlier test" (each reaches moto core and boto3), so a change
anywhere invalidated everything after it and E7 re-ran everything before it: CI run py-cache-2026-11-20e, full moto
-n 4, 10 commits: 0 to 36 reused per commit (MEASURED, `tracks/parallel-proof/results/py-cache-2026-11-20e/moto-walk`).
Attributing in-memory writes between tests soundly is not possible in Python without isolation.

What the per-file mode guarantees (coordinator's conditions):
1. **Soundness.** A reused result equals what its file gives when run in a fresh child forked from the session after
   collection. Inside a file the strict in-process rules hold: the carried set (earlier tests of the file), E7 (a test
   that runs runs after the earlier tests of its file; a test without an entry too), and a result is reused only
   after the same earlier tests of its file (`prefix-file.json`: a test added before it, or deselected when it was
   recorded, reruns it). State left in memory by file A never reaches file B. Files are not isolated: the cross-file
   write rules hold (a reused result whose input an earlier file's test wrote in this session runs, with its whole
   file; under -n the controller checks every worker's children's shards).
2. **Never silent.** A test whose outcome differs from the in-process session's outcome with the same inputs is a
   `PLACEMENT FINDING`: named in the run summary, the session fails, the finding is kept in the cache directory
   (`placement-findings.json`) and the test is never reused in this mode until this mode gives the in-process outcome
   or an in-process session gives this mode's. The comparison needs an in-process result in the store (a run with
   `--det-cache-in-process`); a plain `--det` run without the cache records none (see 2).
3. **Cold-start cost** measured per project (4.3, 4.4).
4. **Measured** on moto, pydantic-ai, litellm, esphome (4.4).

## 1. What is now true, per row

### F-05 cache with proof (serial and -n), with receipts

* **Per-file default** (section 0; `python/detpy/isolate.py: FileIsolate`, `plugin.py`): one child per test file;
  the file's tests run in it in order and the cache records them at the end of the child; children's shards are folded
  into one per process (`Shard::absorb`). A file whose tests are all reused forks no child. Under -n the files are the
  plan's atoms, balanced by recorded durations on the tests that run; files of tests that read the worker id
  (`PYTEST_XDIST_WORKER`) stay on their recorded worker (or one fixed by the file's name when their tests disagree).
* **Process-level state is part of every key** (`_proof.process_identity`, in the configuration digest): the whole
  environment except `ENV_ALLOWLIST` (each entry with its written reason), usable CPUs and `cpu_count`, umask, every
  `RLIMIT_*`, host name, uid/gid/groups, `sys.warnoptions`, `-X` options, `sys.flags`. G-0160..G-0163.
* **Code outside the project** is a content input (G-0164). `sys.path` is in the runtime identity with each directory
  once (a later copy resolves no import differently; esphome's workers had the root once more than the controller and
  every worker result missed).
* **Status reads** (R-023c E1-E4), **ctypes libc** (E3), **infrastructure objects** (E5), **virtual-day epoch and the
  real-clock check** (G-0159), **numpy reseed** (G-0510), **receipts and `python -m detpy cache`** (G-2197, G-2196,
  G-1510): as listed in section 3.
* **Wrong reuses found and closed this session** (each with a regression test):
  1. In-process, serial: results recorded with `-k` deselecting an earlier test that writes state; selecting it reused
     the later test as passed while a fresh run fails it. Every in-process result now carries the tests before it in
     its process (`prefix-session.json`; -n: the planned predecessors as before).
  2. Per-file, serial and -n: an earlier file's test writes a file a later file's reused test reads (R-023b F2 with an
     absent input, found by running the R-023b gate under the per-file default).
  3. Per-file: a test added before a reused test of the same file.
* **Refusals that were the engine's own reads** (each refused whole files of real tests): detpy's virtual clock's
  `/proc/self/task` probe (moto 128 of 292) refuses only when it finds a live child; `_` read inside a copy of
  `os.environ` is part of the whole-environment read; GitHub runners' `cat` statx of a file its own process tree
  wrote is not a real-clock read.
* **Memory and fixed costs** (item 4; 4.2, 4.3): content-addressed data chunks; entries list groups of chunk addresses;
  shards written by chunk and folded per process; the checker memoises proven chunks and code units and uses the key
  recorded with the entry; chunk addresses hashed once per allocation.
* R-023c's review file is merged unchanged. The shared cache is out of go-live scope: tests using
  `--det-cache-shared` are skipped with that reason.

### PY-05 pytest-xdist -n under --det

* -n never changes an outcome silently where the store holds the in-process result: `PLACEMENT FINDING`, persisted
  until resolved (section 0.2). E7 per worker in-process; per file in the default mode.
* xdist modes and failures (G-1548, G-1552, G-2215, G-1553, G-1551, G-2214, G-0708, G-1549, G-1557, G-0174, G-1550):
  as in section 3.

### PY-08 native code and subprocesses

* A process a test or a wider-scoped fixture starts runs and its test is never reused. In a file's child such a
  process is not followed under strace (following it from a forked child deadlocked on esphome's
  `tests/script/test_setup.py`: strace's detached tracer kept the test's pipe open); its test is refused all the same.
  Repository native code and C through ctypes refuse.
* `test_cancel_pending_job` (moto) races a thread against `cancel_job`. It is never reused while racy: a run that
  fails records nothing (failures are never recorded), and wherever its outcome differed from the uncached run it had
  run, not been reused (MEASURED, local walks 4.4). Thread scheduling itself belongs to PY-07.

## 2. What is not true

1. **Placement findings need an in-process result in the store.** A plain `--det` run without the cache records
   nothing, so a test whose outcome differs only between that run and the per-file run (it relied on state another
   file left in memory) is not reported until an in-process cached run (`--det-cache-in-process`) records it. The
   review gates show the class: 11 of 101 gate cases (R-023, R-023b, R-023c) under the per-file default have
   another outcome than in one process, by design.
2. **Cold runs cost more than no cache.** esphome: 227 s cold against 60 s (4.3); the in-process mode's cold run
   costs the same order (CI run f, esphome-inproc: 196-221 s against 67-71 s). The cost is recording (capture during
   the test, ~1.7 ms of recording per test) and, per file, a fork. Warm runs are faster than no cache (4.3, 4.4).
3. **Fast unit suites gain little.** A subset of 824 esphome tests that runs in 4 s without the cache: 4.4 s warm
   (163 tests that cannot be cached or rerun with their file set the floor).
4. **A process started inside a file's child is not followed**: its test is refused (PY-08 refuses it anyway); a
   wider-scoped fixture that starts one in the parent is followed as before.
5. **Receipts** name the changed configuration parts, not old and new values (the environment is stored as digests).
6. **macOS** (Apple Silicon is in the go-live scope) is not exercised: the `other-os (macos-14)` job of the release-1
   workflow is cancelled within a second on every run of this repository, trunk included (it has
   `continue-on-error`); Linux x86_64 and arm64 run.

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
| G-0169 --det-isolate changes a verdict | fixed (finding, persisted) | test_placement_difference_is_a_finding[isolate,file,default] |
| G-0172 -n flips a serial outcome | fixed (finding, persisted) | test_placement_difference_is_a_finding[n2,default-n2] |
| G-0173 rerun without reused predecessors | fixed (E7; per file in the default mode) | test_review_r023c.py::test_4a_*; test_file_scope_a_test_that_runs_runs_after_the_earlier_tests_of_its_file |
| G-0174 serial testrun_uid | fixed | test_g0174_serial_testrun_uid_is_derived_under_det |
| G-0175 -n outcomes differ silently | fixed (finding, persisted) | test_placement_difference_is_a_finding |
| G-0176 cache changes -n verdicts | fixed | test_review_r023c.py::test_4a_*[n2]; test_file_scope_tests_of_a_file_share_their_child_and_no_other_file_sees_it[n2] |
| G-0510 numpy: nothing reused | fixed | test_g0510_* (2) |
| G-0708 worksteal NotImplementedError | fixed | test_g0708_work_stealing_callback_keeps_the_plan |
| G-1284, G-1540 children and C uncontrolled | fixed for the cache (PY-08) | test_py08_* (3); test_file_scope_a_subprocess_in_a_files_child_runs_and_is_never_reused |
| G-1507, G-1511, G-1537, G-1563 carried refusal | fixed by the per-file default (a refusal is carried within its file only) | test_file_scope_tests_of_a_file_share_their_child_and_no_other_file_sees_it; reuse numbers 4.4 |
| G-1508 prefix over-invalidation | fixed by the per-file default (a change reruns its file, not the process) | test_proofcache.py::test_new_test_in_one_module_keeps_the_other_modules_only_when_files_are_isolated[file] |
| G-1509 receipts are counters | fixed in part (config misses name the parts; `detpy cache explain`) | test_g2197_..., test_g1510_... |
| G-1510 no cache command | fixed | test_g1510_cache_command_stats_explain_gc_clear |
| G-1539 isolate in runner shells | fixed (refused with the reason) | test_g1539_runner_shells_refuse_pytest_only_options |
| G-1542 no overhead number | fixed (measured, 4.3, 4.4) | — |
| G-1544 strace missing: nothing said | fixed | test_g1544_missing_strace_is_said |
| G-1548 --dist each | fixed (refused under the cache) | test_g1548_dist_each_with_the_cache_is_refused_with_a_reason |
| G-1549 plan depends on the worker count | fixed (replay command per failure) | test_g1549_a_failure_under_n_prints_its_worker_replay |
| G-1550 worker-id readers withdraw reuse | fixed (pinned per file; found again on esphome under per-file) | test_g1550_worker_id_readers_keep_their_plan_and_are_reused |
| G-1551 dead worker's tests not run | fixed | test_g1551_tests_a_dead_worker_never_ran_fail_the_session |
| G-1552 remote --tx | fixed (refused) | test_g1552_remote_workers_are_refused_with_a_reason |
| G-1553 worksteal replaced silently | fixed (header) | test_g2215_g1553_header_says_what_happened_to_the_asked_dist |
| G-2196 receipts overwritten | fixed | test_g2197_a_configuration_miss_names_what_changed_and_g2196_receipts_are_kept_per_run |
| G-2197 TZ change named "config" | fixed | same test |
| G-2211 isolate pytest-10 deprecation | fixed | test_g2211_isolate_sets_up_unittest_classes_without_the_teardown_deprecation |
| G-2214 crashed test has no record | fixed | test_g2214_a_test_that_crashes_its_worker_is_a_record_of_the_merged_trace |
| G-2215 --dist no header | fixed | test_g2215_g1553_header_says_what_happened_to_the_asked_dist |
| G-0546 threads L1 | moved to PY-07 | — |
| G-1545 parallel for the other runners | moved to the runner rows | — |
| G-0511, G-0414, G-0552, G-0558 Python < 3.12 | out of scope | — |
| G-0399 remote --tx (limits) | fixed with G-1552 | — |
| G-1572, G-2217, G-0218, G-0219, G-0270, G-0559 shared cache | out of scope | tests skipped "out of go-live scope" |
| G-0676 start-up git makes tests uncacheable | unchanged by design (R-008d) | tests/test_review_r008d.py |

## 4. Numbers

### 4.1 Gates

__GATES__

### 4.2 Memory, synthetic suite (MEASURED, this container, 4 CPUs)

3,000 tests in 60 files; conftest reads 400 files at import, each module 40, each test one; `-n 4`; before = d27c1a59
(inline data), after = the chunked store (in-process mode).

| | before | after |
|---|---|---|
| store file | 101,128 KB | 11,828 KB (−88%) |
| cold peak RSS / wall | 551.9 MB / 17.5 s | 372.6 MB / 10.2 s |
| warm peak RSS / wall (3,000 reused) | 688.4 MB / 5.9 s | 149.6 MB / 4.9 s |
| decisions after one module's input changes | 2,950 reused, 50 data | identical |

### 4.3 Fixed cost on esphome, before and after (MEASURED, this container, 4 CPUs, -n 4, one run each)

esphome 141789d2, `tests --ignore=tests/integration --ignore=tests/benchmarks -k 'not udp'`, 14,446 tests (31 fail in
every mode, plain `--det` included). `--det -n 4` without the cache: 59.6-61.4 s.

| engine (per-file default) | cold | warm (reused) | peak RSS warm | store |
|---|---|---|---|---|
| first per-file version | 479 s | 122 s (11,593) | 1.6 GB | 220 MB |
| shards folded per process, chunk addresses hashed once | 248 s | 82-92 s (11,593) | 1.6 GB | 220 MB |
| + checker chunk memo, worker-id pinning | 242 s | 62-69 s (11,593) | 1.6 GB | 220 MB |
| + grouped chunk addresses | 231 s | 57-58 s (11,593) | 1.0 GB | 95 MB |
| + recorded key, code-unit memo (controller decision 6.3 -> 1.0 s) | 227 s | 49.8 / 53.4 s (11,593) | 0.9 GB | 95 MB |

Where the warm time goes (py-spy, earlier engine): workers' collection (as without the cache), 2,853 tests that run
every time (1,604 never cacheable: /proc reads, processes, failures; 1,249 earlier tests of the same files, strict
E7), per-file recording. Cold: ~1.7 ms of recording per test plus a fork per file (648 files).

Serial subset (30 files, 2,375 tests): no cache 13.7 s; per-file cold 25.9 s, warm 9.5 s.

### 4.4 Reuse and time on real repositories (CI run __WALK_RUN__)

__REUSE_TABLE__

Local (MEASURED, this container), moto 96f50b1a `tests/test_sqs tests/test_batch` (292 tests), -n 4: no cache
13.9 s; per file: cold 18.0 s, then 11.6 s with 264 reused (90%); in-process: 15.0 s, 20.1 s (32 reused), then 12.6 s
(264 reused). Outcomes equal to the uncached run in every mode except the thread race of `test_cancel_pending_job`,
which had run (not been reused) wherever it differed.
