DONE

# R-008b: FIX A and FIX B (shared cache, runtime identity)

Branch `claude/shared-cache`. The fix commit is `195b756`; this report is in the commit after it. Reviewer report: `claude/review-r008b:sessions/2026-11-18-review-shared-cache/REPORT-2.md`.

## What changed

Only `python/detpy/runtime_id.py` changed: two helpers, used by both `_site_tree` (FIX 1's walker) and `_extra_paths` (FIX 2's walker).

* **FIX A, sourceless bytecode: `_cached_bytecode(f, fn)`.**
  * A `.pyc`/`.pyo` is skipped only when its `.py` is in the same directory (`f[:-1] in fn`), as the reviewer proposed.
  * A `name.pyc` with no `name.py` is the module itself, so it is keyed again.
  * `__pycache__` is still pruned.
* **FIX B, symlinked directories: `os.walk(..., followlinks=True)` plus `_no_cycle(top, dp, d)`.**
  * The walkers now go into symlinked directories, as the import system does.
  * **Cycle guard (differs from the reviewer's proposal).** The reviewer suggested a set of visited `realpath`s. That would key a second link to an already-walked directory under nothing. It would not see `a -> rel-1` change to `a -> rel-2` when `rel-2` is also walked elsewhere. Instead, a link is not entered only when it points to a directory on the path being walked (from the walk top down to the current directory). Any other link is walked under its own name.
  * Checked by hand on a tree with a link to its parent and two directories that link to each other: the walk ends, and each real directory is listed under each name that does not form a cycle.
  * `_extra_paths` keeps its 50,000-file cap.
* **Not changed (reviewer NOTE 4).** `_tree_digest` (the stdlib walker) still walks without following links.
* **Test file.** `tests/test_review_r008b.py` was copied unchanged from `claude/review-r008b`.

## Before / after (MEASURED, this container)

* **Before:** code `1d430a6`.
* **After:** `195b756`.
* **Setup:** venv without pytest-benchmark, Python 3.13.18, 4 CPUs. The next section says why this venv.

| test | before | after |
|---|---|---|
| `test_hole_sourceless_module_in_site_packages` | FAILED | PASSED |
| `test_hole_sourceless_module_on_an_import_path` | FAILED | PASSED |
| `test_hole_symlinked_package_directory_on_an_import_path` | FAILED | PASSED |
| `test_hole_symlinked_package_directory_in_site_packages` | FAILED | PASSED |
| `test_e2e_wrong_reuse_symlinked_package_on_an_import_path` | FAILED (machine 2 reused `passed`) | PASSED |

* **Targeted run after the fix:** `test_review_r008b.py` + `test_review_r008.py` + `test_runtime_id.py` = **27 passed, 1 skipped**.
* **The skip:** the test that needs two CPython interpreters of the same minor version. This matches the reviewer's figure.

## Engine suite

Both venvs are uv venvs with `maturin develop --release`.

* **Venv without pytest-benchmark** (maturin, pytest, numpy, requests): **157 passed, 6 skipped, 0 failed** (398 s).
  * Skips: pytest_benchmark, time_machine and pytest_django are not installed (5 tests). The two-interpreter test is the sixth.
  * Compared with the reviewer's 151 passed + 7 skipped, there are 5 new tests and one fewer skip, because numpy is installed here.
* **CI package set** (`harness.yml`: maturin, pytest, numpy, requests, pytest-benchmark): **30 failed, 128 passed, 5 skipped**.
  * The fix does not cause these failures. With `runtime_id.py` reset to `1d430a6`, the same suite fails exactly the same tests: the lists of failed node ids are identical (30 failed, 123 passed, 5 skipped, 5 deselected).
  * **Cause (MEASURED):** when installed, pytest-benchmark starts a subprocess as pytest starts (`pytest_benchmark/utils.py:68`, `subprocess.Popen`). detpy then marks every test of the sub-run "not cacheable: subprocess", so nothing is recorded or reused. Tests that expect reuse fail, for example `assert (0 == 5)` in `test_second_machine_reuses_with_proof_what_the_first_recorded`.

## Finding for the planner: in the CI package set the end-to-end wrong-reuse tests pass without checking anything

* **The new end-to-end test.** With pytest-benchmark installed, `test_e2e_wrong_reuse_symlinked_package_on_an_import_path` **passes on the unfixed code**. Machine 1 records nothing (`push_entries: 0`, `not_cached: subprocess`), so machine 2 has nothing to reuse, wrongly or not.
* **The round-1 end-to-end tests** (`test_e2e_wrong_reuse_module_outside_site_and_root`, `test_e2e_wrong_reuse_ld_preload`) behave the same way in that setup.
* **Consequence:** CI's engine job, which installs pytest-benchmark, currently cannot catch a wrong reuse. It also fails the 30 reuse tests at `1d430a6` and before, if CI really runs with that package set.
* **Possible remedies, not done here:**
  * make detpy ignore the startup `Popen` of pytest-benchmark;
  * or run the cache tests' sub-pytests with `-p no:benchmark`;
  * or install pytest-benchmark only in a separate job.

  No GitHub Actions run was made, as instructed.
