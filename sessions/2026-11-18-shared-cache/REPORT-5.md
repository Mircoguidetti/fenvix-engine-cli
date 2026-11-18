DONE

> **One deviation from "each of the 7 passes after": `test_finished_startup_process_that_left_a_daemon_is_not_ignored` still FAILS, at its run-1 precondition.**
> * Line 59 asserts that the suite is cacheable on run 1.
> * The review's own condition 2 (implemented here) refuses the exemption for that suite: `pass_fds` is set and a daemon is left running. So the suite is never cached.
> * The wrong reuse the test guards against no longer happens. Run 2 runs fresh and fails (MEASURED in `tests/test_startup_digest.py::test_daemon_with_a_passed_descriptor_keeps_every_test_uncached`).
> * The review file was kept unchanged, as instructed. See §2.

# R-008d FIX 7: what a finished start-up process gave back is an input of every test

* **Branch.** `claude/shared-cache`.
* **Fix commit.** `65384fa`. This report is in the commit after it.
* **Base.** `a20b93d` (REPORT-4).
* **Review.** `claude/review-r008d`, `sessions/2026-11-18-review-shared-cache/REPORT-3.md` §4 "Cheapest correct rule".
* **Review tests.** `tests/test_review_r008d.py`, copied byte for byte, guard tests included.

## 1. Results (MEASURED)

**Setup.**
* This container: Python 3.13.18, 4 CPUs.
* Two uv venvs, each with `maturin develop --release`:
  * **CI set:** maturin, pytest, numpy, requests, pytest-benchmark 5.3.1;
  * **plain set:** the same without pytest-benchmark.
* Command: `python -m pytest <files> -q -p no:randomly`.
* **"Before"** for the review file is `a20b93d`.
* **"Before"** for the new file is `a20b93d`'s `proofcache.py` and `remote_cache.py` on the new extension. The new `record(startup=)` argument is optional, so the old Python runs unchanged.

### Review tests (`tests/test_review_r008d.py`)

| # | test | before, CI set | before, plain set | after, CI set | after, plain set |
|---|---|---|---|---|---|
| 1 | `test_startup_tool_output_kept_in_config_is_an_input` | FAILED | FAILED | **PASSED** | **PASSED** |
| 2 | `test_startup_git_describe_is_an_input` | FAILED | FAILED | **PASSED** | **PASSED** |
| 3 | `test_startup_output_put_in_os_environ_is_an_input` | FAILED | FAILED | **PASSED** | **PASSED** |
| 4 | `test_startup_process_writing_a_file_under_pytest_cache_is_an_input` | FAILED | FAILED | **PASSED** | **PASSED** |
| 5 | `test_finished_startup_process_that_left_a_daemon_is_not_ignored` | FAILED (run 2 reused) | FAILED | **FAILED at run 1** (`not_cached_ids == {'test_m.py::test_daemon_answer': 'subprocess'}`, line 59), see §2 | same |
| 6 | `test_variable_read_by_the_hook_that_also_copies_the_environment_for_a_child_is_an_input` | FAILED | FAILED | **PASSED** | **PASSED** |
| 7 | `test_environment_copy_kept_and_handed_to_a_child_is_an_input` | FAILED | FAILED | **PASSED** | **PASSED** |
| guard | `test_startup_tool_found_through_path_is_an_input` | PASSED | PASSED | PASSED | PASSED |
| guard | `test_startup_process_writing_a_file_in_the_root_is_checked` | PASSED | PASSED | PASSED | PASSED |
| guard | `test_finished_startup_process_that_left_a_socket_daemon_keeps_its_client_uncached` | PASSED | PASSED | PASSED | PASSED |
| | **total** | 7 failed, 3 passed | 7 failed, 3 passed | 1 failed, 9 passed | 1 failed, 9 passed |

### New tests (`tests/test_startup_digest.py`)

| test | before, CI | before, plain | after, CI | after, plain |
|---|---|---|---|---|
| `test_daemon_with_a_passed_descriptor_keeps_every_test_uncached`: review test 5's suite, decided as the rule says; run 1 uncached with `pass_fds` in the detail, run 2 not reused and fresh FAILED | FAILED | FAILED | PASSED | PASSED |
| `test_process_left_running_by_a_finished_startup_process_keeps_every_test_uncached`: no channel, daemon alive | FAILED | FAILED | PASSED | PASSED |
| `test_output_read_outside_subprocess_run_keeps_the_old_flag`: `p.stdout.readline()` before `communicate()` | FAILED | FAILED | PASSED | PASSED |
| `test_startup_program_that_cannot_be_started_is_an_input`: plugin probes a missing tool; the tool is installed before run 3 | FAILED (**run 3 reused 'passed'; a fresh run fails**) | FAILED | PASSED | PASSED |
| `test_file_python_wrote_under_pytest_cache_is_not_an_input`: condition 3 must not cost this reuse | PASSED | PASSED | PASSED | PASSED |
| `test_pytest_benchmark_startup_digest_is_stable_and_portable`: real plugin; the digest is set, equal on both runs and in a second checkout; run 2 reuses both tests | FAILED (no digest stored) | skipped | PASSED | skipped (not installed) |

* **The "cannot start" row is an eighth wrong reuse of the R-008c rule.** The review did not list it.
  * A `Popen` whose program is missing ends with `returncode=255` and its pipes closed, so R-008c ignored it.
  * pytest-benchmark hits this case on images without `file`.

### Engine suite (`tests`, MEASURED, both sets at the same time on 4 CPUs)

| package set | REPORT-4 (`a20b93d`, 165 / 163 tests) | after (`65384fa`, +10 review +6 new) |
|---|---|---|
| CI set | 165 passed, 0 failed, 5 skipped | **180 passed, 1 failed, 5 skipped** (508 s). The 1 failure is review test 5 (§2). |
| plain set | 163 passed, 0 failed, 7 skipped | **177 passed, 1 failed, 8 skipped** (477 s). Same failure; the extra skip is the pytest-benchmark digest test. |

* **Everything else stays green in both sets:**
  * `test_startup_spawn.py`: 7 tests, including `test_pytest_benchmark_installed_does_not_taint_the_tests`;
  * `test_review_r008.py` and `test_review_r008b.py`, including the three end-to-end wrong-reuse tests with the `push_entries > 0` guard;
  * the 22 `test_proofcache` reuse tests;
  * the 6 `test_shared_cache` tests;
  * the runner-wrapper test.
* **Rust.** `cargo test -p detpy-core`: 48 passed. The new test is `startup_processes_output_is_an_input_and_absent_keeps_the_key`.

**pytest-benchmark projects keep their reuse (MEASURED, CI set).**
* `file -b <python>` is now keyed. The start-up digest is non-empty, identical on runs 1 and 2, and identical for the same project in a second directory.
* Run 2 reuses 2/2 tests (`test_pytest_benchmark_startup_digest_is_stable_and_portable`).
* The shared-cache tests, where two "machines" share the service, all pass in the CI set. So cross-machine reuse stays on one machine.

## 2. Why review test 5 cannot pass as written

* `_assert_recorded_then_not_reused` asserts `c1["not_cached_ids"] == {}` on run 1 ("the rule made it cacheable").
* For tests 1-4, 6 and 7, the fix keys the missing input, so run 1 is cacheable and run 2 misses.
* For test 5, the review's condition 2 says to refuse the exemption. Two parts of it apply:
  * "Also refuse the exemption when `pass_fds` is non-empty";
  * "Any child that is not a live, still-referenced `Popen` ... Flag context 0".
* The daemon's answer reaches the test through `os.read` on a passed descriptor, which nothing can key. No sound rule makes this suite cacheable.
* **Result.** Run 1 is uncached:
  * reason `subprocess: python (subprocess.Popen) at conftest.py:6, a descriptor passed with pass_fds (startup)`;
  * the daemon left running would refuse it too, but only the first cause of a context is reported. The no-channel case reports `a process left running by a start-up process` (second new test).
* Run 2 is not reused and fails fresh, so the hole is closed.
* **Suggestion for the reviewer.** Drop the run-1 precondition for this case, or replace the test with `test_daemon_with_a_passed_descriptor_keeps_every_test_uncached`.

## 3. Rule implemented (review §4, condition by condition)

**Condition 1: the output is an input of every test (fixes 1, 2, 3).**
* `subprocess.Popen.communicate` is wrapped once, at capture start. For a `Popen` held at start-up, it records what `communicate` returned.
* The digest of each exempt process is built from:
  * argv, with the executable;
  * cwd (`os.getcwd()` when `cwd=None`);
  * the exit code;
  * the digest of each stdout and stderr value (bytes, or text encoded back).
* The digests are folded, in start order, into `Capture.startup_digest`.
* **Store.**
  * New optional `Entry.startup` field. It is written only when non-empty, so every other entry keeps its JSON, its proof key and its shared-cache document address.
  * `Current.startup` and `ProofCache.set_startup()` are new.
  * The checker misses with kind `startup`: "a process started at start-up gave back a different output or exit code".
  * `key_of` includes it when it is non-empty.
  * `record(..., startup=)` takes it, and the remote cache pushes and injects it.
* **A pipe read some other way keeps the old flag.** Detail: `its output read outside subprocess.run (not keyed)`.
* **The child's environment stays dropped.** It now matters only through the keyed output, as the review says. So the R-008c `FENVIX_RUNTIME_MEMO` / `GITHUB_RUN_ID` fix is kept.

**Condition 2: nothing outlived it, and it had no extra channel (fix 5).**
* At capture start, on Linux, detpy reads `PR_GET_CHILD_SUBREAPER`, sets `PR_SET_CHILD_SUBREAPER`, and records the children it already has.
* At start-up end:
  * every child that is not in that baseline, not a running held `Popen` and not a running infrastructure `Popen` is flagged on context 0: "a process left running by a start-up process";
  * the subreaper setting is restored.
* The exemption is refused when:
  * `pass_fds` is non-empty;
  * `close_fds=False`;
  * a standard stream is anything other than `None`, `PIPE`, `DEVNULL` or `STDOUT` (stderr only).
* Other platforms keep the conservative flag.

**Condition 3: user reads under `.pytest_cache` (fix 4).**
* An `open` or listing under `.pytest_cache` by user code is recorded as an input unless this session's Python wrote that path. The paths Python wrote there are tracked in `_cache_written`.
* pytest's own `config.cache` is infrastructure, so it stays out.

**Condition 4: precise attribution of the copy (fixes 6, 7).**
* Start-up environment reads now store `(id(frame), frame.f_code, frame.f_lasti, ...)`, never the frame itself.
* Per-key reads made by the same instruction as a `*` enumeration form one group, which is one copy.
* A `Popen(env=...)` started by that frame takes the most recent untaken group.
* At start-up end, the group is dropped only if `sys.getrefcount(env)` shows that only detpy holds the `env` dict. If the copy was kept (`config.env = env`), its reads are inputs of every test again.
* Reads outside a group, such as the hook's own `os.environ.get(...)`, always stay inputs.

## 4. Where this deviates from the review, and why

* **Computed when start-up ends, not in `_decide`.**
  * It is still after every plugin's `pytest_configure` and `pytest_sessionstart`: start-up ends at the first collection context, with a fallback in `pytest_collection_modifyitems` and `_decide`.
  * It is earlier than `_decide` because the shared-cache pull, which runs just before `_decide`, already calls `store.check` on local entries.
* **A separate `startup` field, not folded into `config_digest`.** The miss then says what changed, and entries without start-up processes keep their keys and addresses.
* **Output is keyed only when `communicate` is called by `subprocess.run`.** This is stricter than "wrap communicate".
  * A direct `p.communicate()` cannot prove that nothing read the pipe before it.
  * `run`, `check_output`, `getoutput` and `platform._syscmd_file` all go through `run`.
* **argv and cwd are made portable.**
  * Paths inside the root become `<root>/...`, and `sys.executable` becomes `<python>`.
  * Otherwise two checkouts of one project, or two runners, would never share. The output bytes are keyed raw.
* **Reaping targets the adopted pids, not `waitpid(-1)`.** `waitpid(-1)` could steal the exit status of a live `Popen` and make its `wait()` report 0.
* **Additions the review did not ask for.**
  * A start-up program that fails to start is keyed by its error, through a pass-through `Popen.__init__` wrapper. This avoids losing all reuse when pytest-benchmark runs without `file`, and closes the wrong reuse in §1.
  * Standard streams on a descriptor or file are refused like `pass_fds`. A file the child wrote through `stdout=f` would otherwise be skipped as "written by Python".
  * Directory listings under `.pytest_cache` follow condition 3 too.

## 5. Limits and risks (for the planner)

* **Inherited stdout or stderr.** A child writing to pytest's capture file is still exempt; the review's NOTE is unchanged.
  * `Popen().wait()` and `run([...])` without pipes are exempt with their exit code only.
  * UNKNOWN whether any plugin reads that capture back.
* **Files a start-up child writes elsewhere in skipped places are not keyed.** These are the basetemp (review NOTE), site or stdlib directories, and `__pycache__`, `.git`, `.mypy_cache` and `.hypothesis`. Only `.pytest_cache` was opened up.
  * Opening `.hypothesis` would cost hypothesis users all reuse, because its database changes every run.
  * Direct Python reads of `.git/` files (not through a child) were skipped before this delivery, and still are.
* **Linux only.**
  * On macOS and Windows, any user `Popen` at start-up keeps every test uncached, as before `63a7efb`. pytest-benchmark projects on macOS get no reuse.
  * Kernels without `/proc/<pid>/task/*/children` fall back to scanning `/proc/*/stat`.
* **Infrastructure processes.** A process forked at start-up by infrastructure code through `os.fork` or `posix_spawn`, still alive when start-up ends, is flagged as "left running". This is conservative; none was seen.
* **Copy attribution uses `id(frame)`.** A dead frame at the same address, with the same code and the same instruction, could merge groups. Frames are not stored because that would defeat the refcount check.
* **Old local stores and service entries miss once** with `startup` in pytest-benchmark projects. They were recorded without a digest.

No GitHub Actions run was made, as instructed.
