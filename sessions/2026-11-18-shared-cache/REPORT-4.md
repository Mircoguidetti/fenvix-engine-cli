DONE

# R-008c: a process started at start-up no longer taints the tests (pytest-benchmark)

Branch `claude/shared-cache`. Fix commits: `63a7efb` (start-up Popen, new tests, `push_entries` guard) and `fc5b70b` (the per-key environment reads of the same copy, found by the CI-set run). This report is in the commit after them. Base: `7037182` (REPORT-3).

## 1. Product bug: start-up `Popen` made every test uncacheable

### Cause (MEASURED)

* pytest-benchmark's `pytest_configure` builds a `BenchmarkSession`, which calls `get_machine_id()` → `platform.architecture()` (`pytest_benchmark/utils.py:68`).
* That calls `platform._syscmd_file`, which does two things:
  * it runs `subprocess.check_output(['file', '-b', <python>], env=env)`;
  * just before, it builds that env with `env = dict(os.environ, LC_ALL='C')`.
* **The spawn.** detpy recorded the spawn on the start-up context `""`. That context is an input of every test, so every test was `not cacheable: subprocess`. Where: `file (subprocess.Popen) at <site>/pytest_benchmark/utils.py:68 (startup)`.
* **A second effect, found once the first was fixed.** The `dict(os.environ, ...)` copy enumerates the environment (`*`) and reads every value. Both were recorded as start-up inputs of every test.
  * A variable whose value differs between machines then missed every test with `env`. In the shared-cache tests this was `FENVIX_RUNTIME_MEMO`; in CI it would be `GITHUB_RUN_ID` and the like.
  * So shared-cache reuse stayed at 0 even after the spawn fix. Second commit, `fc5b70b`.

### Rule implemented

* **Start-up window.** From the start of capture until the first collection, fixture or test context. This covers `pytest_configure`, `pytest_sessionstart`, and anything else that runs in the `""` and `"s"` contexts before collection.
* **A `subprocess.Popen` started in that window** (not at import time) is not flagged when it starts. It is decided when start-up ends:
  * **Finished:** `returncode` set and every pipe closed. It is **ignored**, because nothing can talk to it any more. This is the pytest-benchmark case.
  * **Still running, or a pipe still open:** the start-up context keeps the spawn, as before. Detail: `"..., still running when the tests start"`.
    * So every test is uncached. A test that talks to it is therefore never reused.
    * This is the conservative side of the rule: per-test attribution of a live start-up process is not done here (see Limits).
* **Environment reads in the start-up window are held until start-up ends.**
  * Those made by a frame that enumerated the environment and then started such a process with an explicit `env=` (the `dict(os.environ, ...)` copy) are that process's inputs. They are dropped.
  * All other start-up environment reads stay inputs of every test, as before.
* **Unchanged:**
  * a spawn inside a test, a fixture or collection;
  * a spawn at import time (`test_refusal_names_the_program_and_the_context` still passes);
  * a spawn between tests after start-up;
  * `os.fork`, `posix_spawn`, `os.system` and `os.spawn*` at start-up (still flagged: there is no object to check).

### Exact lines changed (`python/detpy/proofcache.py`, line numbers at `fc5b70b`)

Only start-up attribution was touched. No child-process tracking code (the area `claude/cache-proof-step1` reworks) was changed.

| lines | where | what |
|---|---|---|
| 158–165 | `Capture.__init__` | new fields `startup`, `_startup_popens`, `_startup_env` |
| 178–179 | `Capture.switch` | the first switch to a non-global context calls `_end_startup()` |
| 203–215 | `Capture._end_startup` (new) | flags start-up Popens still running or with an open pipe on context 0; puts the held environment reads back |
| 516–526 | `Capture._audit`, spawn branch (was line 493) | a start-up `subprocess.Popen` is held instead of flagged; its spawner frame's copy of the environment is dropped |
| 618–626 | `_note_env` (was line 585) | start-up environment reads (global context, not import time) are held with their frame |
| 1334–1365 | module level (new) | `_SUBPROCESS_FILE`, `_ENV_ITER_FILES`, `_outer_frame()`, `_popen_being_started()` |

### Tests (written first; MEASURED failing before the fix)

The tests are in the new file `tests/test_startup_spawn.py`.

| test | before (`7037182`), CI set | before, plain set | after (`fc5b70b`), both sets |
|---|---|---|---|
| `test_finished_startup_process_does_not_taint_the_tests[pytest_configure(config)]` (tiny plugin: `check_output` + `Popen().wait()` at configure; reused on run 2) | FAILED | FAILED | PASSED |
| `test_finished_startup_process_does_not_taint_the_tests[pytest_sessionstart(session)]` | FAILED | FAILED | PASSED |
| `test_startup_process_a_test_talks_to_keeps_that_test_uncached` (live helper with pipes; the test that talks to it is never reused) | FAILED (uncached, generic detail) | FAILED | PASSED |
| `test_spawn_inside_a_test_still_keeps_that_test_uncached` | FAILED | FAILED | PASSED |
| `test_environment_handed_to_a_startup_process_is_not_an_input_of_the_tests` (new and changed variables between runs) | FAILED | FAILED | PASSED |
| `test_environment_kept_at_startup_is_still_an_input_of_every_test` (`config.env_copy = dict(os.environ)` + a spawn in the same hook; changing a variable misses with `env`) | FAILED | FAILED | PASSED |
| `test_pytest_benchmark_installed_does_not_taint_the_tests` (the real plugin) | FAILED | skipped (not installed) | PASSED in the CI set; skipped in the plain set |

* **The value-change case.** It was added to the environment test after `63a7efb`. With `63a7efb`'s `proofcache.py`, that test fails (MEASURED); with `fc5b70b`, it passes.

## 2. Test-suite blind spot

### Change

* `tests/test_review_r008.py`, `_two_machines` (lines 202–205) now asserts `rep1["push_entries"] > 0`.
* The message lists `not_cached_where`.
* All three end-to-end wrong-reuse tests go through this helper, so none of them can pass with machine 1 recording nothing.

### Engine suite (MEASURED)

**Setup.** This container, Python 3.13.18, 4 CPUs. Two uv venvs, each with `maturin develop --release`. Run with `python -m pytest tests -q -p no:randomly`.

* **CI set** (`harness.yml`): maturin, pytest, numpy, requests, pytest-benchmark 5.3.1.
* **Plain set:** the same without pytest-benchmark.

**Code under test.** The "before" rows use the test files of this change, with `proofcache.py` from `7037182`.

| package set | before | after (`fc5b70b`) |
|---|---|---|
| CI set (with pytest-benchmark) | **40 failed**, 125 passed, 5 skipped (471 s) | **165 passed, 0 failed**, 5 skipped (470 s) |
| plain set | 6 failed, 157 passed, 7 skipped (517 s) | **163 passed, 0 failed**, 7 skipped (460 s) |

* **CI set, before: the 40 failures are:**
  * the **30 reuse tests from REPORT-3**;
  * the 7 new start-up tests;
  * the 3 end-to-end tests, now failing on the new guard: `machine 1 pushed nothing: {...: 'file (subprocess.Popen) at <site>/pytest_benchmark/utils.py:68 (startup)'}`.
* **CI set, after: all 30 pass.** They are:
  * `test_proofcache`, 22 tests: `test_cached_failure_is_never_reused`, `test_clock_reader_depends_on_the_epoch`, `test_comment_and_formatting_changes_keep_the_results`, `test_conftest_fixture_change_reruns_only_its_directory`, `test_data_file_change_reruns_its_reader`, `test_environment_variable_read_is_an_input_and_unread_ones_are_not`, `test_external_service_through_a_loopback_proxy_is_never_cached`, `test_find_library_at_import_time_is_not_a_subprocess`, `test_function_change_reruns_only_the_tests_that_executed_it`, `test_function_run_at_import_time_is_an_input_of_every_reader`, `test_import_time_read_of_a_test_module_serves_only_its_own_tests`, `test_name_lookup_and_c_level_sockets_are_never_cached`, `test_network_connection_and_subprocess_are_never_cached`, `test_new_test_in_one_module_keeps_the_other_modules`, `test_os_entropy_is_cached_only_when_controlled`, `test_read_write_open_is_an_input`, `test_reading_a_file_another_test_wrote_is_not_cached`, `test_refusal_names_the_program_and_the_context`, `test_runtime_identity_change_reruns_everything`, `test_skip_and_xfail_are_reused_with_their_reports`, `test_unchanged_suite_is_reused_with_a_receipt`, `test_verify_runs_reusable_tests_and_compares`;
  * `test_review_r008`, 1 test: `test_hole_entry_with_no_recorded_inputs_is_reused`;
  * `test_runner_wrapper`, 1 test: `test_second_job_reuses_with_proof_and_verify_finds_no_wrong_reuse`;
  * `test_shared_cache`, 6 tests: `test_candidates_are_checked_when_the_project_looks_as_the_tests_saw_it`, `test_entries_pushed_while_the_service_was_down_are_pushed_later`, `test_fenvix_run_on_two_machines_sharing_the_service`, `test_second_machine_reuses_with_proof_what_the_first_recorded`, `test_service_down_falls_back_to_the_local_mirror`, `test_service_on_a_non_loopback_address_is_reachable_under_the_closed_network`.
* **Plain set, before:** the 6 failures are the new start-up tests; the pytest-benchmark one is skipped.
* **Skips after the fix:**
  * CI set (5): time_machine and pytest_django are not installed (4 tests); the two-interpreter test is the fifth.
  * Plain set (7): the same 5, plus the 2 pytest-benchmark tests.
* **First version of the fix (`63a7efb` only), CI set:** 5 failed, 160 passed, 5 skipped. The failures were 4 shared-cache tests and the runner-wrapper test, all `env` misses on `FENVIX_RUNTIME_MEMO`. `fc5b70b` fixed them.

### End-to-end wrong-reuse tests on the unfixed runtime identity (MEASURED)

* **What "unfixed" means for each test.**
  * The R-008b test checks R-008b FIX A-B. Those fixes came after `1d430a6`, so its unfixed `runtime_id.py` is `1d430a6`.
  * The two round-1 tests check R-008 FIX 1-3 (`d7b7ec9`). Those are already in `1d430a6`, so their unfixed `runtime_id.py` is `95ae49c`, the parent of `d7b7ec9`. `d7b7ec9` changes only `runtime_id.py` under `python/`.
* **How it was run.** Only `runtime_id.py` was swapped.

| test | `runtime_id.py` | CI set, before (`proofcache` `7037182`) | CI set, after (`fc5b70b`) | plain set, after |
|---|---|---|---|---|
| `test_e2e_wrong_reuse_symlinked_package_on_an_import_path` | `1d430a6` (unfixed) | FAILED: `machine 1 pushed nothing` (REPORT-3: it used to PASS here vacuously) | **FAILED: `machine 2 reused 'passed' from the service`** | FAILED: same |
| `test_e2e_wrong_reuse_module_outside_site_and_root` | `95ae49c` (unfixed) | FAILED: `machine 1 pushed nothing` with `1d430a6` (it used to PASS vacuously) | **FAILED: `machine 2 reused 'passed'`** | FAILED: same |
| `test_e2e_wrong_reuse_ld_preload` | `95ae49c` (unfixed) | FAILED: `machine 1 pushed nothing` with `1d430a6` (it used to PASS vacuously) | **FAILED: `machine 2 reused 'passed'`** | FAILED: same |
| all three | current (`fc5b70b`) | – | **PASSED** | **PASSED** |

* **The two round-1 tests at `1d430a6`.** With the fix and `1d430a6`'s `runtime_id.py`, they PASS in both sets, as they should: `1d430a6` already has FIX 1-3.
* **Conclusion.** In the CI package set, each end-to-end test now does catch the wrong reuse it was written for. The `push_entries` guard makes a silent pass impossible.

## Limits and risks (for the planner)

* **The output of a finished start-up process is not keyed.** If a plugin turns it into Python state that a test reads, the result can be reused wrongly on a machine where the program answers differently.
  * Example: a conftest that does `config.sha = check_output(['git', 'rev-parse', 'HEAD'])`, or `has_ffmpeg = run(['which', 'ffmpeg']).returncode == 0`, and a test reading it.
  * This is the trade-off the rule asks for. For pytest-benchmark the output (`file -b <python>`) depends on the interpreter binary, which the runtime identity already keys.
  * A possible next step: key the started program's binary and argv into the global identity.
* **A live start-up process uncaches every test, not only the ones that talk to it.**
  * Talking through pipes, inherited descriptors, signals or C-level clients raises no audit event, so per-test attribution could not be made sound here.
  * Left for the child-process tracking work on `claude/cache-proof-step1`.
* **A frame that copies the environment for a child and also keeps the copy is misattributed.** Example: `env = dict(os.environ); config.env = env; check_output(..., env=env)` in one function would lose that environment as a test input.
  * The test with a separate `config.env_copy` plus a spawn in the same hook keeps it, because the spawn passes no `env=`.
  * If the copy is itself passed as `env=`, it is attributed to the child.
* **Daemons forked by a finished start-up shell are not tracked**, as before.
  * Tests reaching them over Python sockets are still flagged per test (`connect`).
  * C-level clients are flagged only for internet sockets left open.

No GitHub Actions run was made, as instructed.
