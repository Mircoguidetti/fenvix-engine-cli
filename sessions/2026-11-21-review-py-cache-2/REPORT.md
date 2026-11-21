# R-053 review: PR #5 (claude/py-cache @ 29ef940), round 2. Rows F-05, PY-05, PY-08

**FIX 3.** R-052's four wrong results are fixed. C5 is fixed too. Item 3 (`-n` code prefix) holds. R-050 P1/P2, the
late-failure test and S4 are still green. But I found **3 new families of wrong results**: each reports a test
**passed, exit 0, where plain `pytest` and/or uncached `pytest --det` fail it**. One family (P) **came into PR #5
with the trunk merge** (trunk 9e3663a has it too; 33bb5ff did not). The other two were already on 33bb5ff and the
trunk. The rule is 0 wrong results, so F-05 is not OK to merge as CHIUSO.

Independent Opus reviewer, 2026-11-21. I changed no product code and pushed nothing to `claude/py-cache`.

## Setup (MEASURED)

- Wheel from 29ef940: `maturin build --release --compatibility linux` (abi3), then `_core` copied into
  `python/detpy`, as the CI job does. Venvs: CPython **3.13.18** and **3.12.3**, each with pytest 9.2.0 and
  pytest-xdist 3.8.0. 3.14 is not installed in this container (the prompt asks for at least one version). strace,
  taskset and unshare are present, and the user is root.
- Comparison wheels, each in its own 3.13 venv: **33bb5ff** (PR #5 before the R-052 fix and before the trunk merge)
  and **trunk 9e3663a**.
- My attack scripts are in this folder: `h53.py` is the harness, plus `attack_*.py` and `probe_*.py`. Run them as
  `<venv>/bin/python attack_X.py <this folder> [pytest args]`. Each one runs a cold cache, then the change, then a
  warm cache. It compares the warm run with **uncached `--det` under the same arguments** (the verdict), and also
  with plain pytest (reported as "vs plain"). Files a test writes are deleted before every run, as in a fresh
  checkout.
- New failing tests: `tests/test_review_r053_pycache.py` on branch `claude/review-py-cache-r053`.

## Items

| # | item | verdict |
|---|---|---|
| 1 | R-052 S1, S3, S5, C3, serial and `-n 2` | **FIXED** |
| 2 | C5 (PY-08), child-process write | **FIXED** as a wrong result; its second cause is not addressed in code, and I could not reach it |
| 3 | `033797f` / `c61f839`: code prefix in collection order, also recorded under per-test isolation | **holds**: no case found where the cache differs from `pytest --det -n 2` |
| 4 | R-050 P1/P2, late failure (serial, n2), S4 | **still green** |
| 5 | the three tests updated to the trunk's `--det` defaults (`29ef940`) | **PARTLY**: g0510 is fine; g0160/g0163 keep their point on the public calls, but `may_reuse=True` hides a wrong reuse through other read paths (finding P) |

### 1. S1, S3, S5, C3: FIXED

```
$ <venv>/bin/python -m pytest -q -p no:randomly -p no:cacheprovider tests/test_review_r052_pycache.py \
    tests/test_review_r050_pycache.py   # the R-050 file is copied from c5f9c399 (claude/review-p1-packages)
    tests/test_py_cache.py::test_r050_a_late_failure_keeps_the_earlier_independent_tests_reused \
    tests/test_py_cache.py::test_r050_p2_a_failure_an_earlier_file_causes_in_the_normal_run_is_not_reported_passed \
    tests/test_py_cache.py::test_r050_p1_a_real_failure_stays_failed
3.13.18: 10 passed in 47.65s      3.12.3: 10 passed in 45.01s
```

R-052's attack scripts on 3.13:

- Serial: all OK. That covers S1, S3, S4, S5, the same-file variants S1n/S3n/S5n, C1 to C8.
- `-n 2`: my `attack_s1_vs_det.py` and `attack_s3_vs_det.py` are R-052's scripts, compared with uncached
  `--det -n 2`. All 7 are OK. On the cross-file cases S1/S3/S4/S5 the cache also equals plain `-n 2`.

Note on `-n 2`: R-052's `attack_s1.py` prints WRONG under `-n 2`, but by design it compares with plain *serial*
pytest. It is not a finding. On the same-file cases, the cache and uncached `--det -n 2` both put the file on one
worker and fail the victim. Plain xdist `load` splits the file and passes it. That is the `--det` scheduler's
placement, not the cache.

### 2. C5 (PY-08): FIXED as a wrong result; the second cause is untouched

- `test_c5_py08_a_file_an_edited_earlier_tests_child_process_writes` passes on 3.12 and 3.13. The cause that gets it
  fixed is the test-file edit: the code prefix marks the victim stale, so it reruns.
- **Not fixed in code: "writes of followed child processes counted as session writes".** No commit in
  `33bb5ff..29ef940` touches the write accounting: `CaptureCore::written_input` and `recheck_hit` are unchanged. I
  tried to reach that cause without editing a test file (`probe_c5.py`, `attack_nontest.py`), serial and `-n 1`, and
  every attempt was correct, each for another reason:
  - K3: a config module turns on the child. The victim reruns as `code`, because the module is loaded at collection.
  - K6: a data file read at run time turns on the child. The victim reruns as `data`.
  - K4: the test always starts a child. Every later test of the process is "not cacheable: after an earlier test of
    this process".

  In-process controls with the same pattern (K3i, K6i) give `written 1`. So: no wrong result reachable today
  (MEASURED on these probes). The second cause itself stays open (UNKNOWN whether another path reaches it).

### 3. Code prefix under `-n`: holds

`attack_n2_same_worker.py` (3.13) runs S1, S3, S5, C3 and C5 with both files on **one worker**:

- under `-n 1`;
- under `-n 2 --dist loadgroup` with `xdist_group`, plus a third file for the other worker, and a variant with
  another worker's file collected between them.

All 12 are OK: the cache equals uncached `--det -n …`. Under `-n 1` it also equals plain `pytest -n 1`.

Under loadgroup, plain xdist 3.8.0 with pytest 9.2.0 did not group the two files here: it passed the victim. The
`--det` plan groups them and fails the victim, cached and uncached alike. This is a placement difference between
xdist and the `--det` scheduler, not a cache defect.

`attack_placement.py` changes the placement or mode between the recording run and the cached run, with no edit and
with an S1 edit: `-n 2 → -n 1`, `-n 2 → serial`, `--det-isolate → serial / -n 1`,
`--det-isolate-scope=file → serial / -n 1`. All 12 are OK. One reason it holds: a `-n` worker's list is always a
subsequence of the serial order (`schedule.rs`), so the collection-order prefix is a superset of each process's
prefix.

### 4. Still green

R-050 P1 and P2 (the `test_review_r050_pycache.py` file and the `test_py_cache.py` copies), the late-failure test
`[serial]` and `[n2]`, and S4 (`attack_s1.py` serial): all pass, MEASURED on 3.12 and 3.13 (item 1 command).
`test_in_process_is_the_default_under_the_cache_and_per_file_is_a_choice` and
`test_py08_a_test_that_starts_a_process_runs_every_time` also pass on both.

### 5. Tests updated in 29ef940: PARTLY

```
tests/test_py_cache.py::test_g0160_usable_cpus_are_an_input  ::test_g0163_host_name_is_an_input
  ::test_g0510_entropy_read_by_the_test_itself_still_refuses (+ the two tests above)
3.13: 5 passed   3.12: 5 passed
```

- **g0510:** keeps its point. Observed entropy is still refused, and controlled entropy is reused soundly: the same
  bytes in every fresh `--det` run for os.urandom, os.getrandom, secrets, uuid4 and random.SystemRandom
  (`probe_entropy.py`).
- **g0160 / g0163:** sound for the calls `pin_cpu_count` and `pin_hostname` patch. But the old tests guarded that
  "the CPU count and the host name are inputs". `process_identity()` (`_proof.py:883`, part of every key) reads
  `os.sched_getaffinity` and `os.uname`, and under `--det` those are now the **pinned** functions. So the real
  values are no longer in the key. A test that reads the real value through another path is reused on another
  machine shape. `may_reuse=True` accepts that reuse, and the test only probes the patched path, so it cannot see
  the hole. This is finding P below.

## New wrong results (blocking)

Each row was MEASURED on 3.13.18. Rows marked * were also MEASURED on 3.12.3. "29ef940", "33bb5ff" and "trunk" give
the cached verdict on each wheel.

### K1: conftest.py and `__init__.py` are outside the code prefix (F-05; on 33bb5ff and trunk too)

62be968 digests only the **test files** at or before a test. pytest also loads the `conftest.py` and `__init__.py`
files of the directories it collects, before any test runs. When one of those, next to an earlier test, starts
writing state that a later test in another directory reads, the later test's stored needs (`[]`) are trusted. It is
reused as passed. The test files are unchanged.

Layout: `tests/a/test_a.py` has `def test_a(): pass`. `tests/b/test_b.py` asserts `helper.STATE['mode'] == 'good'`.
There is no root conftest.

| id | change between run 1 and run 2 | 29ef940 | 33bb5ff | trunk |
|---|---|---|---|---|
| **K1*** | new `tests/a/conftest.py`: autouse fixture sets `helper.STATE['mode'] = 'bad'` (serial and `-n 1`) | **passed, exit 0** | wrong | wrong (serial) |
| **K1d*** | new `tests/a/conftest.py` writes the state at import | **passed** | wrong | wrong |
| **K1e*** | new `tests/a/conftest.py`: autouse `sys.setrecursionlimit(120)`; the victim imports nothing and recurses to depth 400 | **passed** | wrong | wrong |
| **K1g*** | existing `tests/a/conftest.py` (`import helper`) gains an import-time write | **passed** | wrong | wrong |
| **K1i** | new `tests/a/__init__.py` writes the state at import | **passed** | n/m | wrong |
| K1c | existing autouse fixture in `tests/a/conftest.py`, body edited | correct | n/m | **wrong** (fixed by PR #5) |
| K1f | new conftest's autouse fixture writes a file the victim reads | correct (written-file gate) | n/m | correct |
| K1h | new test file `tests/a/test_new.py` writes the state | correct | n/m | **wrong** (fixed by PR #5) |

In every row, plain `pytest` and `pytest --det` fail the victim, exit 1. n/m: not measured.

These pass, so the non-test closure path works for a non-test module of the earlier test, edited:

- K2: `tools.py` starts writing the state.
- K2b: `tools.py` starts lowering the recursion limit.
- K1b: the body of a conftest fixture the earlier test requests is edited.

**Fix direction (suggestion; the owner decides):** include in the code prefix every conftest.py and `__init__.py`
that pytest loaded for the files at or before the test (their contents, and whether they exist). Or include every
conftest/`__init__` of the session.

### P: the real CPU count and host name are no longer in the key (F-05; arrived with the trunk merge)

Run 1 is recorded on this machine (4 CPUs, real host name). Run 2 runs under `taskset -c 0` or
`unshare --uts … hostname otherbox-r053`. That is another runner shape, which is what CI has. The test asserts the
real value it read.

| id | read path | 29ef940 | 33bb5ff | trunk 9e3663a |
|---|---|---|---|---|
| **P1*** | `posix.sched_getaffinity(0)` | **reused, passed, exit 0**; uncached `--det`: failed | correct (not reused, failed) | wrong |
| **P2a*** | `_socket.gethostname()` | **reused, passed** | correct | wrong |
| **P2b*** | `posix.uname().nodename` | **reused, passed** | correct | wrong |
| controls | `os.sched_getaffinity`, `socket.gethostname` (pinned) | sound reuse | n/a | sound |
| controls | `/proc/self/status`, `/proc/sys/kernel/hostname`, ctypes `sched_getaffinity` | correct (data input or not cacheable) | correct | correct |

Cause: `process_identity()` calls `os.sched_getaffinity`, `os.cpu_count` and `os.uname` after `pin_cpu_count` and
`pin_hostname` have patched them, so it records the pinned values. On 33bb5ff it recorded the real ones.

**Fix direction:** keep the real values in the key (`_level0._machine` already holds the real CPU functions; take
the real uname from `posix`). Or pin `posix.*` and `_socket.gethostname` too. The second leaves C callers open, so
the first is the sound one.

### E: `posix.urandom` is neither controlled nor refused (F-05; on 33bb5ff and trunk too)

Under the default controlled entropy, `posix.urandom(8)` returns different bytes in every fresh `--det` run, and
the cache reuses the test (`reused 1`). On 33bb5ff, in observe mode, it is reused too: it is not seen as an entropy
read. `os.urandom` itself is controlled.

`probe_entropy_outcome.py` uses `assert posix.urandom(1)[0] % 2 == 0`:

- 5 cached runs: exit codes `[0, 0, 0, 0, 0]` (reused);
- 10 fresh `--det` runs: `[1, 1, 0, 1, 0, 1, 1, 1, 0, 1]`.

So the cache freezes one outcome of a flaky test (MEASURED). This is the least likely of the three in real suites
(ESTIMATED), but it is a wrong result by the rule.

**Failing tests:** `tests/test_review_r053_pycache.py`, 9 tests (K1 serial and n1, K1d, K1g, K1e, P1, P2 ×2, E1).

- Each test asserts its preconditions: plain pytest or uncached `--det` fails the case.
- MEASURED:
  - 29ef940: **9 failed** on 3.13 and **9 failed** on 3.12;
  - 33bb5ff: 6 failed (P1/P2 pass);
  - trunk 9e3663a: 8 failed (K1 under `-n 1` passes there).

```
E AssertionError: --det-cache reports {'tests/a/test_a.py::test_a': 'passed', 'tests/b/test_b.py::test_victim': 'passed'}
  (exit 0); plain pytest and --det fail tests/b/test_b.py::test_victim
E AssertionError: --det-cache reports {'tests/test_p.py::test_c': 'passed'} (exit 0); --det fails it
```

## Verdict

| row | MERGE OK | why |
|---|---|---|
| F-05 | **no** | K1 (5 variants), P (3) and E (1) are wrong results, serial on 3.12 and 3.13. P is new on this branch (it came with the trunk merge 80cb997); K1 and E were already on 33bb5ff. The PR is still better than the trunk: it fixes R-052 S1/S3/S5/C3/C5, K1c and K1h |
| PY-05 | **yes** | no `-n`-specific wrong result: same-worker S1/S3/S5/C3/C5, placement changes and mode changes all equal uncached `--det -n`. K1 under `-n 1` is the F-05 hole, not a `-n` one |
| PY-08 | **yes** | C5 fixed; K3/K4/K6 child-process probes correct. Caveat: a followed child's write is still not a session write (UNKNOWN whether reachable) |

Notes, not wrong results:

- Under `-n 2` the `--det` placement differs from xdist's own (`load` splits a file; loadgroup did not group here).
  The cache always equals uncached `--det -n 2`.
- I did not run the full suites (GitHub's job). 3.14 was not measured.

## Links

- Engine repository: `Mircoguidetti/fenvix-engine-cli`. Reviewed `claude/py-cache` @ 29ef940 (PR #5).
- My branch: `claude/review-py-cache-r053`, with `tests/test_review_r053_pycache.py` and this folder.
- Earlier review: `sessions/2026-11-21-review-py-cache/REPORT.md` on `claude/review-py-cache-r052`.

## Gaps in the brain or the prompt

- The prompt points to `tests/test_review_r050_pycache.py`, which is not on `claude/py-cache`. It is on
  `claude/review-p1-packages` (c5f9c399). Its two tests are also mirrored in `tests/test_py_cache.py`.
- The prompt asks to compare with plain `pytest -n 2`. Under `-n`, the meaningful yardstick is uncached
  `pytest --det -n 2`, because `--det` replaces xdist's placement. Worth stating in the exam (F-05/PY-05).
