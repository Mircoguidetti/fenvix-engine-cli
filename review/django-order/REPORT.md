FALSE FAILURES: YES 3

The 3 are all in the minimal repro. The three real projects show 0 order-caused false failures, before and after the fix. The defect is real, but these suites do not trip it.

# --det vs pytest-django ordering (REPORT-2 item 7 / N6)

Branch `django-order` (local, not pushed), commit 53cc674 "Keep pytest-django's test groups under --det", on top of engine 87484c8.
Runs: 5 normal, `--det` (fixed order) x2, `--det --det-seed=1..10`, plus `--det --det-disable=order` as a control. Each run uses `-p no:randomly -p no:cacheprovider`.
"Extra" means failures under `--det` that never occurred in any of the 5 normal runs. All numbers are MEASURED.

## Cause
pytest-django stable-sorts the tests into three groups: TestCase first, then transactional tests, then tests without a database. detpy put back its own order and undid that sort. A transactional test flushes the database. Any TestCase test that runs after it loses the rows created by data migrations, so it fails only under `--det`.
The fix calls pytest-django's own hook on detpy's fixed or seeded order. The group order becomes a constraint, and detpy's permutation applies only inside each group. The result is still a pure function of detpy's order, so it stays deterministic.

## 1. Minimal repro (scratchpad/dj/mini): 7 tests, a data migration, a flushing transactional test and a TestCase that reads the seeded rows
| | normal x5 | det fixed x2 | det seeds 1..10 | det, order disabled |
|---|---|---|---|---|
| before fix | 0 | 3, 3 | 3 on 7 of 10 seeds (0 on seeds 1, 5, 10) | 0 |
| after fix | 0 | 0, 0 | 0 on all 10 | 0 |
The failures disappear when order control is disabled, so ordering is confirmed as the cause.

## 2. Real projects (pytest-django with mixed groups; group counts come from collection)
| project @ commit | tests | groups (TestCase / db / transactional / no-db) | normal x5 | det fixed | det seeds 1..10 | extra, before / after fix |
|---|---|---|---|---|---|---|
| django-celery-results @ c7ac5cc | 58 | 13 / 26 / 10 / 9 | 5 (same 5 every run) | 5 | 5 each | 0 / 0 |
| channels @ 531894e | 82 | 2 / 0 / 46 / 34 | 2 | 2 | 2 each | 0 / 0 |
| django-oauth-toolkit @ 285ba9c (`-o addopts= --ignore=tests/e2e`) | 2713 | 1341 / 487 / 62 / 823 | 10 | 24 | 24 each | 14 / 14 (not caused by ordering) |

- The old detpy order did break the groups in all three projects: after the fix, the trace records the adjustment "pytest-django: test groups kept" in each of them. Yet no test failed because of the order: these suites do not depend on data-migration rows in a way that a flush breaks.
- oauth-toolkit, 14 extra failures (throttling tests and one introspection test): the cause is **time control, not ordering**. On those 3 files: normal 41 passed; `--det` 14 failed; `--det --det-disable=order` 14 failed; `--det --det-disable=time` 41 passed. Errors: 6 x `TypeError: time() takes 0 positional arguments but 1 was given`, which suggests detpy's replacement `time.time` binds as a method when it is stored as a class attribute (DRF `timer = time.time`), unlike the builtin it replaces (ESTIMATED diagnosis). Also 1 x a `datetime` timezone mismatch. This is a separate detpy defect, not fixed here, and belongs in a new item.
- django-oscar was dropped. It needs PostgreSQL, which is not running after the container restart, and its earlier `--det` runs were invalid (3 s per run, stale junit output).

## 3. Test and suite
- `tests/test_django_order.py` (10 tests, in commit 53cc674): 10 passed with the fix. With the old `plugin.py` swapped back in, 8 failed and 2 passed, so the test catches the defect.
- Full plugin suite `tests/`: 71 passed, 1 skipped (a pre-existing skipif), 0 failed, in 186 s.
- No new commit was needed. The worktree is clean and 53cc674 is the deliverable.

Data is in scratchpad/dj/: mini*.json, celres*.json/log, channels*.json/log, oauth*.json/log, suite.log, bin/cmp.py (the runner) and bin/an.py (the analysis).
