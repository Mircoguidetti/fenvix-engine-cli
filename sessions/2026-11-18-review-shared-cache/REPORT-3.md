FIX 7

# R-008d review: the start-up subprocess rule (cache with proof)

* **Delivery under review.** `sessions/2026-11-18-shared-cache/REPORT-4.md`, fix commits `63a7efb` and `fc5b70b`, file `python/detpy/proofcache.py`, tests `tests/test_startup_spawn.py`.
* **Commit tested.** `5845b51` (the delivery plus `review-input/`; `proofcache.py` is identical to `fc5b70b`).
* **Failing tests.** `tests/test_review_r008d.py`, committed on this branch (`claude/review-r008d`) as the launch message asked, not on a separate `review-<branch>` branch.
* **Verdict.** FIX 7.
  * The rule makes start-up `Popen` processes cacheable without keying anything they produce. Seven concrete suites now reuse a `passed` result although a fresh run of the same suite FAILS.
  * Before the rule, each of these suites was uncached, because the start-up spawn tainted every test. So all seven holes were opened by this delivery.
  * Each is proven by a test, below. The engine suite numbers in REPORT-4 reproduce exactly.

## 1. Re-run of the delivery's numbers (MEASURED)

**Setup.**
* This container: Python 3.13.18, 4 CPUs.
* Two uv venvs, each with `maturin develop --release`:
  * **CI set:** maturin, pytest, numpy, requests, pytest-benchmark (5.x);
  * **plain set:** the same without pytest-benchmark.
* Command: `python -m pytest tests -q -p no:randomly`, at `5845b51`, before my test file was added.

| package set | REPORT-4 (after `fc5b70b`) | this re-run |
|---|---|---|
| CI set | 165 passed, 0 failed, 5 skipped | **165 passed, 0 failed, 5 skipped** (637 s, NOISY: both sets ran at the same time on 4 CPUs) |
| plain set | 163 passed, 0 failed, 7 skipped | **163 passed, 0 failed, 7 skipped** (600 s, NOISY) |

**The numbers match.**

**`tests/test_startup_spawn.py` reviewed.**
* The tests do measure what they claim. Each one asserts reuse or non-reuse on a second run, not just an exit code.
* The `push_entries > 0` guard in `test_review_r008._two_machines` closes the earlier vacuous pass.
* **The gap is in what the tests do not ask.** No test makes the start-up process produce something a test depends on. Only "nothing depends on it" cases are tested, plus the live-pipe case.

## 2. Proven errors (tests that FAIL at `5845b51`)

**How every test works.**
* **Run 1.** It passes, and the test is recorded with no "not cached" reason. That assert proves the rule made it cacheable.
* **Between runs.** One thing changes, and it is outside the recorded inputs.
* **Run 2 must run the test fresh, and the fresh run fails.** Each failing test fails on `assert c2["reused_ids"] == []` with `<nodeid> reused although a fresh run differs`.
* **The fresh failure is real by construction.** Each test body asserts the run-1 value, and that value changed. After the reuse assert, each test also asserts `failed=1` on run 2. In the two guard tests of §3, where the cache misses correctly, that fresh FAILED was observed (MEASURED).

**Results (MEASURED).** Same results in both package sets:
* CI set: 7 failed, 3 passed, 111 s.
* Plain set: 7 failed, 3 passed, 92 s.

| # | test (`tests/test_review_r008d.py`) | what changes between runs | why it matters |
|---|---|---|---|
| 1 | `test_startup_tool_output_kept_in_config_is_an_input` (line 68) | `pytest_configure` runs `/abs/fenvixtool --version` and puts the result in `config.tool_version`. The tool is upgraded from 1.0 to 2.0. | This is the main suspicion, confirmed. Any plugin that exposes a tool's version or answer (`node --version`, `uname`, `file`, `ffmpeg -version`) gives wrong reuse when the tool changes on a machine, or differs between machines sharing the cache. |
| 2 | `test_startup_git_describe_is_an_input` (line 115) | `git describe --tags` at configure. A new commit + tag `v2.0` touches only `NOTES.txt`, which no test reads, plus `.git/`. | This is the setuptools_scm / version-plugin pattern. `.git/` is in `_SKIP_PARTS`, so nothing at all keys the value. A version check is reused across a release tag. |
| 3 | `test_startup_output_put_in_os_environ_is_an_input` (line 144) | Configure sets `os.environ["FENVIX_TOOL_VERSION"]` from the tool's output, and the test reads it. The tool goes from 1.0 to 2.0. | Environment digests come from `env0`, the environment before start-up (`proofcache.py:1174`). A variable set at start-up digests as "absent" in both runs, so the read is not a real input. |
| 4 | `test_startup_process_writing_a_file_under_pytest_cache_is_an_input` (line 164) | A start-up process writes `.pytest_cache/d/gen/version.txt` (1.0, then 2.0), and a session fixture reads it. | Reads under `.pytest_cache` are skipped (`_SKIP_PARTS`, line 67). A child's write raises no audit event. So generated data in a skipped place is never keyed. |
| 5 | `test_finished_startup_process_that_left_a_daemon_is_not_ignored` (line 192) | The start-up process forks a daemon and exits at once. The daemon answers through a descriptor given with `pass_fds`. The test reads the answer with `os.read`. The daemon's program changes. | `_end_startup` (line 203) checks only the `Popen`'s own `returncode` and its three pipes. A surviving descendant, and any descriptor other than `stdin/stdout/stderr`, is invisible. |
| 6 | `test_variable_read_by_the_hook_that_also_copies_the_environment_for_a_child_is_an_input` (line 230) | The same hook does `config.mode = os.environ.get("FENVIX_APP_MODE", "dev")` and `env = dict(os.environ, LC_ALL="C")`, then `subprocess.run(..., env=env)`. `FENVIX_APP_MODE` is set to `prod`. | `fc5b70b` drops every start-up environment read of the spawner frame (`proofcache.py:522-524`, filter `x[0] is not spawner`), not only the reads made by the copy. A variable the hook reads for itself is lost. REPORT-4 did not name this case. |
| 7 | `test_environment_copy_kept_and_handed_to_a_child_is_an_input` (line 250) | `env = dict(os.environ); config.env = env; subprocess.run(..., env=env)`. The test reads `config.env["FENVIX_FLAG"]`, and the variable is set between runs. | REPORT-4 lists this case under "Limits". It is a wrong reuse, so per RULES.md it is a proven error, not a risk. |

**How these differ from REPORT-4's "Limits".**
* REPORT-4 named the output case as a trade-off. It argued that for pytest-benchmark the output depends only on the interpreter, which is keyed.
* That holds for pytest-benchmark. But the rule exempts every finished start-up `Popen`, not only pytest-benchmark's.
* Tests 1 to 5 show that the exemption reaches outputs that are not keyed at all.

## 3. Checks that hold (kept in the file as guards, not defects)

| test | result | why |
|---|---|---|
| `test_startup_tool_found_through_path_is_an_input` (line 86): same command, PATH points at another `fenvixtool` | PASSES: miss `env: environment variable PATH` | The PATH lookup is a recorded environment read. This holds only while the binary is found at a different PATH; test 1 shows that the same path with new bytes is reused. |
| `test_startup_process_writing_a_file_in_the_root_is_checked` (line 271): a start-up process rewrites `version.txt` in the root | PASSES: miss `data: version.txt (f)` | The digest is checked after start-up, so a file in the root that the child regenerates is a real input. |
| `test_finished_startup_process_that_left_a_socket_daemon_keeps_its_client_uncached` (line 293): a daemon reached over a Unix socket | PASSES: the client test is uncached (`connect`) | Python sockets are flagged per test, as REPORT-4 says. |

## 4. Cheapest correct rule (proposal)

The idea: key what the process gave back, not what it was given. This follows the import-time rule: code run at start-up is an input of every test, and its result becomes one too. A finished start-up `Popen` is exempt only if the four conditions below hold. Otherwise it keeps flagging the start-up context, as before `63a7efb`.

**1. Its output is an input of every test (fixes 1, 2, 3).**
* For each held `Popen`, wrap `Popen.communicate` once at capture start. `check_output`, `run` and `platform._syscmd_file` all go through it.
* Record the digest of `(argv, cwd, returncode, stdout bytes, stderr bytes)`.
* Fold the digests of all exempt start-up processes into one "start-up digest". This digest joins every test's key, the same way `g_data` does.
  * It must be computed in `_decide`, after start-up. It cannot go into `config_digest`, which is taken at detpy's own `pytest_configure`, before other plugins' hooks run.
* **A pipe that was read some other way:** `p.stdout.read()`, `readline`, or a file object handed on. Its bytes are not seen, so keep the old flag (conservative).
* **Executable bytes are not needed** once output bytes are keyed. A different binary that answers the same output gives the same test results. That is the cheaper and more precise key.
* **The child's environment no longer needs any treatment for correctness.** It matters only through the output, which is now keyed. So it stays dropped, and the R-008c `FENVIX_RUNTIME_MEMO`/`GITHUB_RUN_ID` fix is kept.
* **Cost:** pytest-benchmark's `file -b <python>` output is stable on one machine. Reuse stays at 100% (ESTIMATED; the CI-set suite would show it).

**2. Nothing outlived it, and it had no extra channel (fixes 5).**
* At capture start, call `prctl(PR_SET_CHILD_SUBREAPER, 1)` through `ctypes`. This is Linux; on other platforms keep the conservative flag.
* At `_end_startup`, read `/proc/self/task/*/children`. Any child that is not a live, still-referenced `Popen` means a descendant outlived its start-up parent. Flag context 0 with "left a process running".
* Also refuse the exemption when `pass_fds` is non-empty or `close_fds=False`.
* **Cost:** detpy must reap the orphans it adopts. A `waitpid(-1, WNOHANG)` at session end is enough.

**3. Reads in skipped places are inputs when this session's Python did not write them (fixes 4).**
* For user-code reads under `.pytest_cache`: if the path is not in `self.writers`, record a digest instead of skipping.
* pytest's own `config.cache.get` reads come from infra, so they stay skipped.
* **Cost:** a test that opens `.pytest_cache` files directly re-runs when they change.

**4. Precise attribution of the copy (fixes 6, 7).**
* **Fix 6.** Attribute to the child only the per-key reads made inside the enumeration call itself. Store `(id(frame), frame.f_lasti)` at the `*` read, and treat a per-key read from the same frame at the same `f_lasti` as part of the copy. Do not store frame objects: they keep the copy alive.
* **Fix 7.** At `_end_startup`, if the `env` dict passed to the held `Popen` is still referenced by anything other than detpy, the copy was kept: its reads are inputs of every test. Check with `sys.getrefcount` on the strong reference detpy holds, once frame references are gone.

**Next test.** Re-run `tests/test_review_r008d.py` (all 10 must pass) and the engine suite in both package sets.
* CI set: 165 + 10 passed.
* Plain set: 163 + 10 passed.
* `test_pytest_benchmark_installed_does_not_taint_the_tests` must still pass, which shows that condition 1 does not cost the pytest-benchmark reuse.

## 5. Risks and notes (do not block)

* **NOTE: files a start-up child writes into the run's basetemp.** The basetemp path changes per run, so these files are a likely miss, not a wrong reuse. It is UNKNOWN whether a fixed `--basetemp` makes this a wrong reuse.
  * **Cheapest test:** test 4 with `--basetemp=<fixed>` and the file written there.
* **NOTE: a start-up process with stdout inherited (not piped).** It writes to pytest's capture file, which a plugin could read back. I found no plugin that does. UNKNOWN.
  * **Cheapest test:** a conftest with `capsys`-like readback at `pytest_sessionstart`.
* **NOTE: child processes started from a `pytest_collection` hook** (session-level, before any `c|` context) also fall under the start-up rule. The same four conditions apply; no separate defect was found.

## Files

* `tests/test_review_r008d.py`: 7 failing tests and 3 guards.
* This report.
