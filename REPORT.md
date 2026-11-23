DONE

# REPORT: CI until 22 December, Python tests shared with Node on every push, the rest nightly; workflow index

Branch `claude/ci-python-shared`, started from `claude/release-1` @ 81f838c6 (Lane B merged). Spec: "CI until 22 December"
(gstack /spec revision 2, approved by the founder 2026-11-22). This file replaces the trunk's previous REPORT.md (Lane B,
still readable in history at 81f838c6).

## What changed

- `release/python-tests.txt` (new): every Python test file `release/shard.py` selects under `tests/`, one line each,
  labelled `shared` or `python-product`; header states the rule and "valid until 2026-12-22, then reviewed".
- `release/shard.py`: optional `--only LABEL LIST-FILE` (filters before the size split). Without it the output is unchanged.
  With it: unknown label, unclassified file, or no file with the label -> exit 1 (a LIGHT run can never go green on zero files).
- `release/python_tests.py` (new): the list parser shared by `shard.py --only`, the workflow (`select`), and the test.
- `tests/test_python_tests_classified.py` (new, `shared`): the classification guard plus tests of `--only` and `select`.
- `.github/workflows/release-1.yml`: job-level `env.FULL` in the `python` job, the same expression as its version matrix
  (a test checks the two are identical); LIGHT main step passes `--only shared release/python-tests.txt`; a new
  shard-0 step computes the extra-suite targets (all on FULL, `shared` only on LIGHT) and each extra step is skipped
  when it has none; the R-001 step runs on FULL only; header comment updated (C5). No other job changed.
- `.github/workflows/README.md` (new): the gate section and 30 rows, one per other workflow.

## Acceptance criteria

### AC1: classification file, counts (MEASURED)
```
$ grep -c "^shared " release/python-tests.txt; grep -c "^python-product " release/python-tests.txt
52
59
$ for k in 0 1 2 3; do python3 release/shard.py 4 $k tests 'test_*.py' '**/test_*.py' '*_test.py' '**/*_test.py'; done | wc -l
111
```
52 + 59 = 111 = every selected file, each once (checked by the test below). 111 = 109 at bfaf70b4 + `tests/test_exit_status_contract.py`
(Lane B) + `tests/test_python_tests_classified.py` (this change).

Method (spec): `shared` = every file matched by
`git grep -l -E 'detpy\._core|_core\.|detpy\.fenvix|fenvix_js|attacks|wheel|exit-cases' -- tests/` (45 files), plus
`tests/test_clock.py` (spec), the new guard test, and files read by hand and found to exercise code Node uses:
`tests/test_repro_rust.py` (`from detpy import _core`), `tests/test_fingerprint.py` (`python -m detpy verify` = `_core.verify_with`,
the verifier `detjs verify` calls natively), `tests/test_shared_cache.py` (`detpy.cache_service`, the service `node/src/cache/remote.js`
talks to), `tests/test_py_cache.py` (`python -m detpy verify`, line 633) and `tests/test_parallel_proof_round3.py`
(`from detpy import _core`, Rust shared store). The last two were moved to `shared` after the /review adversarial pass.
Runner-suite files (django, nose2, ward, zope) are `python-product`; `test_clock_rust.py`, `test_level0_seeds_fsorder_rust.py`,
`test_clock.py` are `shared`, as the spec requires.

### AC2: the classification test passes, and fails when it should (MEASURED, local, Python 3.13.18, pytest 9.1.1)
```
$ python3 -m pytest -q -p no:randomly tests/test_python_tests_classified.py
8 passed in 0.40s
```
One line removed (`python-product tests/test_epoch.py`), then restored:
```
E       AssertionError: selected by release/shard.py but not in release/python-tests.txt: ['tests/test_epoch.py']
FAILED tests/test_python_tests_classified.py::test_every_selected_file_is_classified
1 failed, 7 passed in 0.39s
```
Empty `tests/test_tmp_unclassified.py` added, then deleted:
```
E       AssertionError: selected by release/shard.py but not in release/python-tests.txt: ['tests/test_tmp_unclassified.py']
FAILED tests/test_python_tests_classified.py::test_every_selected_file_is_classified
1 failed, 7 passed in 0.45s
```
Both reverted; `git status` clean afterwards. The test gets the selected files by running `release/shard.py` for all
4 shards without `--only`, with the root and globs read from the workflow's own `shard.py` command (no copied globs).

### AC3: shard.py without --only is unchanged (MEASURED)
```
$ diff <(git show 81f838c:release/shard.py | python3 - 4 0 tests GLOBS) <(python3 release/shard.py 4 0 tests GLOBS); echo rc=$?
rc=0
$ diff <(git show 81f838c:release/shard.py | python3 - 4 1 tests GLOBS) <(python3 release/shard.py 4 1 tests GLOBS); echo rc=$?
rc=0
$ diff <(git show 81f838c:release/shard.py | python3 - 4 2 tests GLOBS) <(python3 release/shard.py 4 2 tests GLOBS); echo rc=$?
rc=0
$ diff <(git show 81f838c:release/shard.py | python3 - 4 3 tests GLOBS) <(python3 release/shard.py 4 3 tests GLOBS); echo rc=$?
rc=0
```
(GLOBS = `'test_*.py' '**/test_*.py' '*_test.py' '**/*_test.py'`; empty diff, rc=0, for k = 0..3.)

### AC4: two workflow_dispatch runs of release-1.yml on this branch (MEASURED, head 7ada7e8)
Both runs on commit 7ada7e8, the commit before this REPORT.md (which changes no file the workflow reads).
The two runs went one after the other: the workflow's concurrency group allows one running and one pending run per ref,
so queueing a second dispatch cancels the pending one. Earlier runs 45155642421/45155646998 (d70e99a),
45156125063/45156130191 (d8dc5d1), 45156454337 (cancelled by concurrency) were superseded by review fixes.

**LIGHT: run 45156487688** (depth `light`), python job env `FULL: false`:
| python (3.13, shard k/4) | line | result |
|---|---|---|
| 0 | `shard 0/4: 13 files` | failure: 3 failed, 210 passed, 15 skipped (failures listed under AC "merge rule") |
| 1 | `shard 1/4: 13 files` | cancelled by fail-fast after shard 0 failed |
| 2 | `shard 2/4: 13 files` | cancelled by fail-fast after shard 0 failed |
| 3 | `shard 3/4: 13 files` | success: 145 passed, 4 skipped |

13 + 13 + 13 + 13 = 52 = the number of `shared` files. Shard 0 extra steps:
- selection step printed `runners=` (empty), `numpy=tests/test_clock.py::test_time_machine_travel_is_honoured tests/test_clock_rust.py tests/test_level0_seeds_fsorder_rust.py`,
  `hyp=tests/test_clock.py::test_real_pytest_benchmark tests/review_r032/test_review_r032_python.py::test_p12_hypothesis_profile_env`
- runner suites step: **skipped**; R-001 step: **skipped**
- numpy step: ran its 3 `shared` targets (all of them are shared): `30 passed in 60.73s`
- hypothesis step: ran its 2 `shared` targets (`tests/test_runners_unittest.py::...` is python-product, left out): `2 passed in 11.37s`
- `install` and `publish-engine`: skipped (LIGHT, as before).

**FULL: run 45156460246** (depth `full`), python job env `FULL: true`:
- Jobs: 41, the same 41 job names as the trunk's last FULL run 45019748065 (`diff` of the sorted name lists: empty),
  `publish-engine` skipped on both (it runs only on the trunk). Every python shard-0 job has every step of the trunk's
  (main suites, runner suites, numpy, hypothesis, R-001) plus the new selection step.
- python 3.13 shard lines: `shard 0/4: 28 files`, `shard 1/4: 27 files`, `shard 2/4: 28 files`, `shard 3/4: 28 files`
  -> 111 = all selected files. The selection step printed the full target lists (all runner, numpy and hypothesis targets).
- Conclusions: failure, like the trunk's FULL runs; fail-fast cancelled many jobs (as in 45019748065). Failing: attacks
  (py 3.12, node 26), node (22, shard 0/4), python (3.13, shard 3/4: 14 failed, the same 14 tests as the trunk's
  LIGHT python 3.13 shard 3/4 in run 45154789017), python 3.13 shard 0/4 main step (2 `test_py_cache.py` failures,
  pre-existing, see below).

### AC5: workflow index
`.github/workflows/README.md`: the gate section (release-1.yml, LIGHT on push/pull_request, FULL nightly and by hand,
`publish-engine` on FULL only) and 30 rows (`grep -c '^| \`' .github/workflows/README.md` -> 30), one per other `.yml`,
with file, one-sentence purpose, trigger as written in its `on:` block, and "in the 22 Dec plan". `parallel-node.yml`'s
row states that its push trigger names `claude/parallel-node`, already merged (5a6463f). `fenvix-demo-jobs.yml` is listed with
its callers (`fenvix-demo.yml`, `fenvix-demo-hosted.yml`).

### AC6: no workflow deleted; diff limited to the allowed paths (MEASURED)
```
$ git diff --stat 81f838c..HEAD
 .github/workflows/README.md           |  55 +++++++++++++++
 .github/workflows/release-1.yml       |  56 +++++++++++----
 REPORT.md                             | 583 ++++++++----------- (replaces Lane B's report)
 release/python-tests.txt              | 124 ++++++++++++++++++++++++++++++++++
 release/python_tests.py               |  53 +++++++++++++++
 release/shard.py                      |  30 +++++++-
 tests/test_python_tests_classified.py | 116 +++++++++++++++++++++++++++++++
```
No change under `node/`, `python/detpy/`, `crates/`, `harness/`, and no other workflow file.

## Merge rule (red trunk, founder 2026-11-23)

LIGHT on the branch vs LIGHT on the trunk (same depth, same Python/Node versions):

| | trunk run 45154789017 (push, 81f838c) | branch run 45156487688 (light, 7ada7e8) |
|---|---|---|
| failing jobs | `attacks (py 3.13, node 24)`, `node (24, shard 0/4)`, `python (3.13, shard 3/4)` | `attacks (py 3.13, node 24)`, `node (24, shard 0/4)`, `python (3.13, shard 0/4)` |
| count | 3 | 3 |

The python job index differs because LIGHT splits a different file set (52 files instead of 111), so shard k holds
other files. At test level, every failing Python test of the branch run also fails on the trunk:
- `tests/test_packaging.py::test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs`
  (`AssertionError: parallel-node.yml`): fails in the trunk run's python (3.13, shard 3/4) (MEASURED, its log) and
  locally on 81f838c (MEASURED: `python3 -m pytest -q tests/test_packaging.py::test_gate_runs...` -> 1 failed, on both commits).
- `tests/test_py_cache.py::test_the_virtual_clocks_own_probe_of_threads_is_not_the_tests_read` and
  `tests/test_py_cache.py::test_g2214_a_test_that_crashes_its_worker_is_a_record_of_the_merged_trace`: on the trunk run
  this file was in python (3.13, shard 0/4), cancelled by fail-fast before pytest reported. MEASURED locally with a
  wheel built from this tree (`maturin build --release`, engine code identical on both commits:
  `git diff --stat 81f838c..HEAD -- crates python node tests/test_py_cache.py tests/conftest.py` is empty):
  `2 failed` on a worktree of 81f838c and `2 failed` on this branch. They also fail in the branch FULL run.
The 13 other tests failing in the trunk's python job are `python-product` (`test_r023c_fixes.py`, `test_review_r056_pycache.py`)
and now run on FULL only, where they still fail (branch FULL run, python 3.13 shard 3/4).
Conclusion: failing jobs on the branch (3) <= on the trunk (3), with no new failing test. The rule holds.

## gstack /review

Run on the branch (5 specialists: testing, maintainability, security, performance, simplification; adversarial pass;
adversarial re-review of the fixes). No unresolved highest-severity finding. Fixed:
- unknown `--only`/`select` label or an empty `shared` selection gave a green LIGHT run with 0 tests -> now exit 1;
- the empty-shard early exit applied to FULL too -> LIGHT only;
- a failing selection step would have skipped shard 0's main suites -> the step now runs after them;
- the FULL expression is copied from the matrix -> a test asserts they are identical;
- no tests for `--only`/`select` -> added; the guard test uses the CI parser and also rejects listed-but-unselected files;
- two files mislabelled `python-product` -> `shared` (see AC1).
Gate edits: 7 listed, 4 read, 0 findings. Record logged with `completed: true`, `converged: false`, `cycles: 2`.

## python-product files, one reason each (59)

| File | Reason it is `python-product` |
|---|---|
| `tests/test_absent_inputs_r019c.py` | R-019c: absent inputs of the pytest cache with proof (`--det-cache`), serial and `-n`; Python plugin behaviour. |
| `tests/test_carried_library_memo.py` | Parallel-proof round 3: carried-set rule for state memoised by a third-party Python library under pytest `--det-cache`. |
| `tests/test_culprit_keys.py` | `--det-cache-keys`, a pytest-plugin option (culprit-finder prototype). |
| `tests/test_dep_verdict_distid.py` | `--det-cache-dists` / `detpy.distid`: Python distribution identity for the dependency verdict (Python only). |
| `tests/test_dep_verdict_r020_fixes.py` | Dependency-update verdict fixes (R-020) in the pytest plugin. |
| `tests/test_dep_verdict_r020b_fixes.py` | Dependency-update verdict fixes (R-020b) in the pytest plugin. |
| `tests/test_det_stale_bytecode.py` | R-019b N5: pytest `--det` replay runs the checked-out source, not stale Python bytecode. |
| `tests/test_django_order.py` | pytest-django test groups under `--det` (runner integration; runner-suite step). |
| `tests/test_django_pytest_cache.py` | Django under pytest `--det-cache` (runner integration; runner-suite step). |
| `tests/test_epoch.py` | Python virtual wall clock starts at the HEAD commit time (Python-only control). |
| `tests/test_fsorder.py` | Python normalised filesystem order control (`detpy.fsorder`) through the plugin; no direct `_core` call. |
| `tests/test_harness_timing_report.py` | Timing report of the Python measurement harness (R-001 recheck); no engine code Node uses. |
| `tests/test_network.py` | Python closed-network control and record/replay (`detpy.network`). |
| `tests/test_nonbinding.py` | Python builtins replaced by detpy keep their (non-)binding as class attributes (Python-only control). |
| `tests/test_nonbinding_generic.py` | Same property over the Python patcher's undo log (R-003 E4). |
| `tests/test_order.py` | pytest test order and `--det-seed` shuffle (plugin behaviour). |
| `tests/test_parallel_proof_r023_fixes.py` | R-023 fixes of parallel with proof for pytest-xdist. |
| `tests/test_precompile_stamp.py` | `--det` Python bytecode precompile of library directories (`detpy.reexec`). |
| `tests/test_proofcache.py` | pytest cache with proof (`--det-cache`); its verify is `--det-cache-verify` (re-run and compare), not `fenvix verify`. |
| `tests/test_proofcache_follow.py` | pytest cache with proof: following child processes of Python tests. |
| `tests/test_proofcache_import_lookups.py` | Python negative import lookups in the pytest cache key. |
| `tests/test_r015_fixes.py` | R-015 fixes: Python code file changed during a pytest `--det-cache` session. |
| `tests/test_r015b_fixes.py` | R-015b fixes of the pytest cache with proof. |
| `tests/test_r023c_fixes.py` | R-023c fixes of the pytest parallel-proof rules. |
| `tests/test_r032b_engine.py` | R-032b F1-F3 on the pytest plugin. |
| `tests/test_repro.py` | `detpy repro` search and minimisation for pytest suites (Python product); the Rust decisions have their own `shared` file, `tests/test_repro_rust.py`. |
| `tests/test_review_b1_randomly_options.py` | Options of a blocked pytest plugin (pytest-randomly) registered in the child. |
| `tests/test_review_b4_p005_rule.py` | P-005 rule for pytest-xdist baselines (Python classification rule). |
| `tests/test_review_lock_type.py` | R-001: Python `threading.Lock` type under `--det` (Python-only control). |
| `tests/test_review_plugin_options.py` | R-001: pytest plugin options (`-p no:randomly`). |
| `tests/test_review_r008b.py` | R-008b: Python site directories and import paths in the pytest cache key. |
| `tests/test_review_r008d.py` | R-008d: subprocess started at pytest start-up. |
| `tests/test_review_r009.py` | R-009: child processes and cache epoch of the pytest cache with proof. |
| `tests/test_review_r009b.py` | R-009b: wrong-reuse holes of the pytest cache with proof. |
| `tests/test_review_r015.py` | R-015: pytest results recorded under code that did not produce them; reaches Rust only through the pytest plugin, never `detpy._core` directly. |
| `tests/test_review_r015b.py` | R-015b: same family (followed children, symlinked modules, doctest files) in the pytest plugin. |
| `tests/test_review_r017.py` | R-017: pytest assertion-rewrite pycs and temporary names under `--det`. |
| `tests/test_review_r017b.py` | R-017b: pytest assertion rewriting patched by a plugin under `--det-cache`. |
| `tests/test_review_r023c.py` | R-023c: adversarial tests of the pytest parallel-proof rules. |
| `tests/test_review_r052_pycache.py` | R-052: Python per-file cache, stale needs after a code change. |
| `tests/test_review_r053_pycache.py` | R-053: Python per-file cache wrong results. |
| `tests/test_review_r056_pycache.py` | R-056: channels through which a cached pytest outcome differs from an uncached one. |
| `tests/test_review_t1_extra.py` | R-003 T1: Python builtins as class attributes under `--det`. |
| `tests/test_rewrite_cache.py` | pytest assertion-rewritten modules in the deterministic bytecode cache. |
| `tests/test_rewrite_cache_own_format.py` | Same, detpy's own format for pytest < 9.2. |
| `tests/test_round4_capture.py` | Python input capture under tools that patch `os.path`. |
| `tests/test_runner_wrapper.py` | `runner/fenvix-run`, the Python CI wrapper; its `verify` re-runs pytest and compares outcomes (`cmd_verify`), not the trace verifier; Node does not use it. |
| `tests/test_runners_django.py` | `python -m detpy django` runner integration (runner-suite step). |
| `tests/test_runners_doctest.py` | `python -m detpy doctest` runner integration. |
| `tests/test_runners_nose2.py` | `python -m detpy nose2` runner integration (runner-suite step). |
| `tests/test_runners_unittest.py` | `python -m detpy unittest` runner integration. |
| `tests/test_runners_ward.py` | `python -m detpy ward` runner integration (runner-suite step). |
| `tests/test_runners_ward_support.py` | `python -m detpy ward` when ward cannot run (runner integration). |
| `tests/test_runners_zope.py` | `python -m detpy zope-testrunner` runner integration (runner-suite step). |
| `tests/test_seeds.py` | Python seeds for `random`, numpy and `PYTHONHASHSEED` (Python-only control); the Rust side is in the `shared` file `tests/test_level0_seeds_fsorder_rust.py`. |
| `tests/test_sqlite_virtual.py` | Python SQLite date/time and random functions under Level 0 (`crates/detpy-py`, the Python-only crate). |
| `tests/test_startup_digest.py` | R-008d FIX 7: pytest start-up process digest. |
| `tests/test_startup_spawn.py` | Process started while pytest starts is not a test input. |
| `tests/test_timed_lock_enter.py` | Python `detpy.clock._TimedLock` (pydantic-ai flaky verdict); Python-only control. |

## Left open

- The end date 2026-12-22 is written in comments and the list header only; nothing fails or warns after it
  (review finding, INFORMATIONAL). The founder decides at the review whether to extend, end or enforce it.
- Labels are per file: a `python-product` file is skipped on LIGHT as a whole. Five files were added to `shared` by
  reading them; the rest follow the spec's grep plus one reason each above.
- LIGHT and FULL split files into shards differently, so an order/site-packages interaction between files of one shard
  could show on one depth only (review finding, INFORMATIONAL).
- Pre-existing trunk failures seen in these runs (not changed here): `test_packaging.py` (parallel-node.yml push trigger),
  two `test_py_cache.py` verify tests, the `test_review_r056_pycache.py`/`test_r023c_fixes.py` group, attacks, node 24 shard 0.
