# R-052 review: PR #5 (claude/py-cache @ 33bb5ff), rows F-05, PY-05, PY-08

Reviewer session, 2026-11-21. Independent Opus reviewer. No product code changed. Nothing pushed to `claude/py-cache`.

**Result: FAIL.** The three named fixes hold. Decision (b) is only PARTLY fixed. I found 4 new wrong results: each
reports a test **passed, exit 0, where plain `pytest` and `pytest --det` fail it**. All 4 also happen on the trunk
cec096c, so PR #5 does not introduce them. PR #5 is strictly better than the trunk on my attacks (it fixes S4 below).
But the rule is 0 wrong results, so F-05 and PY-08 are not OK to merge as rows CHIUSO.

## Setup (MEASURED)

- Wheel built from 33bb5ff (`maturin build --release`, abi3, one wheel for every version). One venv per version,
  each with pytest, pytest-xdist and the wheel. `_core` copied into `python/detpy`, as in the CI `python` job.
  strace was present.
- Versions: CPython 3.12.13, 3.13.18 and 3.14.6.
- Trunk comparison: a wheel built from cec096c, in its own 3.13 venv.
- Attack suites: the scripts are in this folder (`harness.py`, `attack_s*.py`). Run them as
  `<venv>/bin/python attack_s1.py <this folder> [-n 2]`. Each script runs: run 1 with a cold cache, then the change,
  then run 2 with the warm cache, compared with plain pytest on the same files.
- Every attack suite has **no conftest**, and imports its modules as `import helper`. With a conftest that imports a
  library, or with `from helper import X` (matched as a library), every test carries every earlier test. The rule is
  then sound by over-carrying, and none of the holes below shows. Real suites have both, which makes the holes rarer
  there (ESTIMATED), but they are reachable.

## Earlier findings and the session's claims

| item | verdict | evidence |
|---|---|---|
| R-050 P2: a failure an earlier file causes was reported passed | **FIXED** | `tests/test_review_r050_pycache.py` (c5f9c39) copied in: 2 passed on 3.12/3.13/3.14 |
| R-050 P1: a real failure stays failed, no finding | **FIXED** (guard) | same file, passes |
| `785b77a`: `--det-cache` runs in the session's process(es); per-file children only under `--det-isolate` | **FIXED** | `test_in_process_is_the_default_under_the_cache_and_per_file_is_a_choice` passes; R-050 P2 shows `1 failed, 1 passed`, with no "forked children" line |
| `c5dfe5a` decision (b): a test with no entry keeps its needs; unknown means rerun | **PARTLY** | fixed: an unchanged failing test (R-050 P2 warm) and a not-cacheable test (S4: wrong on the trunk, correct on 33bb5ff). NOT fixed: a failed test whose code is edited runs with its old `loose_needs` (S3, wrong result) |
| `4b1c006`: a late failure keeps the earlier independent tests reused, serial and `-n` | **FIXED** | `test_r050_a_late_failure_keeps_the_earlier_independent_tests_reused[serial,n2]` passes; my probe: a failing victim with no connection gets `loose_needs` `[]`, and the warm run says `reused 1 … ran 1` |
| `docs/LIMITS.md` section 10 | present | it describes the in-process default, decision (b) and the cost. It does not mention the stale-needs holes below |

Command (each version):

```
<venv>/bin/python -m pytest -q -p no:randomly -p no:cacheprovider tests/test_review_r050_pycache.py \
  tests/test_py_cache.py::test_r050_p2_a_failure_an_earlier_file_causes_in_the_normal_run_is_not_reported_passed \
  tests/test_py_cache.py::test_r050_p1_a_real_failure_stays_failed \
  tests/test_py_cache.py::test_r050_a_late_failure_keeps_the_earlier_independent_tests_reused \
  tests/test_py_cache.py::test_in_process_is_the_default_under_the_cache_and_per_file_is_a_choice \
  tests/test_py_cache.py::test_py08_a_test_that_starts_a_process_runs_every_time
3.12: 8 passed   3.13: 8 passed   3.14: 8 passed
```

`tests/test_py_cache.py` as a whole, run with `-n 4 -x` on 3.13: 41 passed, then 1 failure
(`test_g2214_a_test_that_crashes_its_worker_is_a_record_of_the_merged_trace`). That test passes when run alone
(serial). I put it down to my parallel run, not a finding. The full suites are GitHub's job.

## New wrong results (blocking): the stored needs go stale after a code change

**Cause.** A test's needs are the earlier tests whose in-process state it may consume (`Entry::needs`, or
`Store::loose_needs` for a test with no entry). They are computed from the code as it was when the test last ran.
Later, either the earlier test or the later test is edited, so that the two become connected (both now reach the same
module, or the interpreter). The warm run still uses the old needs, which say "no earlier test":

- either the earlier test runs while the later test is reused (S1, C3, C5);
- or the later test runs while the earlier test is reused, that is, not executed (S3, S5).

The same change made in a shared non-test module *is* handled: S6/S7, where `wrapper.py` starts reading
`helper.STATE`, rerun both tests and are correct. The gap covers edits to the test files themselves.

All rows below are serial, with the victim in `tests/test_b.py` and the earlier test in `tests/test_a.py`. Plain
`pytest` and `pytest --det` give `test_victim` FAILED, exit 1, in every row (MEASURED, 3.12 / 3.13 / 3.14).

| id | run 1 → run 2 change | `--det-cache` run 2 | trunk cec096c |
|---|---|---|---|
| **S1** | only the earlier test is edited: `pass` → `helper.STATE['mode'] = 'bad'`; the victim passed in run 1 (entry, needs `[]`) | `reused 1, ran 1`, victim **passed**, exit 0 | same |
| **S3** (decision b) | the victim failed in run 1 for its own reason (`assert 0`: no entry, `loose_needs` `[]`); it is edited to assert on `helper.STATE` | earlier test reused, victim **passed**, exit 0 | same |
| **S5** | as S3, but the victim passed in run 1 (`assert 1`, entry, needs `[]`) | victim **passed**, exit 0 | same |
| **C3** (C state) | earlier test edited: `pass` → `sys.setrecursionlimit(120)`; the victim, which imports nothing, recurses to depth 400 | victim **passed**, exit 0 | same |
| **C5** (PY-08) | earlier test edited: `pass` → `subprocess.run([python, -c, "open('flag.txt','w').write('bad')"])`; the victim reads `flag.txt` | victim **passed**, exit 0 | same |
| S4 | as S3, but the victim in run 1 started a subprocess (not cacheable) | correct (victim failed) | **wrong** (fixed by PR #5) |

What does not break (MEASURED, serial, the same pattern):

- **C1:** the same file write done in-process. The written-file gate catches it.
- **C2:** env var set by the earlier test, read by the later test (the victim reaches a library, so it carries every
  earlier test).
- **C4:** `decimal` context (a C extension).
- **C6:** a later test's child process inherits an env var the earlier test starts setting.
- **C7:** only the script that the earlier test's child process runs is changed.
- **C8:** only a data file that the earlier test copies is changed.
- **Same-file variants of S1/S3/S5:** the file change reruns the whole file.

**C5 has a second cause, specific to PY-08.** The same write made in the test's own process is caught (C1). Made by
its child process, the write is not seen as a write of this session, so the reused reader is not withdrawn. This holds
only when nothing leaves the file on disk before the cached run. A fresh CI checkout is exactly that case.

**`-n 2` (PY-05).** I ran S1/S3/S4/S5 across files: the cached `-n 2` run reports the victim passed. Plain
`pytest -n 2` (and `--dist loadfile`) also passes it, because the two files run on different workers. So the cache
equals plain `-n` there. Same-file variants under `-n 2`: the cache gives the serial verdict. I did not build a case
where both files land on the same worker. The stale-needs cause should apply there too (UNKNOWN, not measured).

**Failing tests:** `tests/test_review_r052_pycache.py` on this branch, with S1, S3, C3 and C5.

- Each test asserts its preconditions: plain pytest and `--det` fail the victim.
- Each test passes once the cached run reports the victim failed.
- MEASURED: 4 failed on 33bb5ff with 3.12, 3.13 and 3.14, and 4 failed on the trunk cec096c with 3.13.

```
E AssertionError: --det-cache reports {'tests/test_a.py::test_a': 'passed', 'tests/test_b.py::test_victim': 'passed'}
  (exit 0); plain pytest and --det fail tests/test_b.py::test_victim:
  reused 1 result(s) with proof, ran 1, recorded 1 ...
```

**Fix direction (suggestion; the owner decides).** Do not trust stored needs across a code change of the test
itself or of any earlier test of its process. Either recompute the carried set at check time from the current files'
reference closure (the S6/S7 path already does this for non-test modules), or treat such needs as unknown, which means
every earlier test. For C5, also count writes made by a followed child process as writes of this session.

## Verdict

| row | MERGE OK | why |
|---|---|---|
| F-05 | **no** | 4 wrong results (S1, S3, S5, C3) serial on 3.12/3.13/3.14. They also happen on the trunk, so the PR does not regress them, and it fixes R-050 P2 and S4 |
| PY-05 | **yes** | no `-n`-specific wrong result found: R-050 late failure n2 OK, and the cross-file `-n 2` cases equal plain `-n 2`. The F-05 holes may also apply inside one worker (UNKNOWN) |
| PY-08 | **no** | C5: a file written by an edited earlier test's child process; the reused reader is reported passed, while plain pytest fails it |

Not a wrong result, noted: decision (b)'s cost is still UNKNOWN on moto and litellm (LIMITS 10 says so).
