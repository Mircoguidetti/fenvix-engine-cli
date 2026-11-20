DONE: the tests of findings #3, #4, #11 and R-050 D4 pass locally on CPython 3.12, 3.13 and 3.14 (MEASURED below); the CI run on the PR head confirms

# P1 Python leaks: review P1 findings #3, #4, #11 (+ R-050 D4)

Session 2026-11-20, branch `claude/p1-python-leaks`, from trunk `claude/release-1` @ 71f8081. PR into
`claude/release-1`. Labels: MEASURED (with the command), ESTIMATED, DECLARED, UNKNOWN.

## What was wrong and what changed

| finding | wrong result | fix | test |
|---|---|---|---|
| #4 (F-01/F-03) | under `--det` the PID, `tempfile` names, `/dev/urandom` read as a file, `/proc/uptime` and files outside the project were silently real: values and outcomes flipped between identical runs, `fenvix verify` said identical | new Level 0 control `os` (`python/detpy/osstate.py`), see below | `tests/test_review_p1_python_leaks.py::test_f03_no_test_whose_value_differs_is_reported_identical`, `::test_f01_det_result_does_not_depend_on_the_pid_or_os_entropy` |
| #3 (F-03, G-0180) | threads started with `_thread` and pool threads started before the test (import, wider fixture) raced while verify said identical | `python/detpy/uncontrolled.py`: `_thread.start_new_thread` / `start_new` / `start_joinable_thread` mark the test `uncontrolled.thread`; every non-infrastructure thread alive when a test starts is remembered with its thread CPU clock (Linux), and one that consumed CPU time or ended during the test marks it `uncontrolled.thread` (a Python thread unknown to `threading`: its top frame is compared) | `::test_f03_a_test_that_uses_threads_is_never_reported_identical`, and the thread rows of `::test_f03_no_test_whose_value_differs_is_reported_identical` |
| #11 (F-01, G-0168) | the first `-n` run after any serial run was "cold" (bytecode input differed), every test divergent | the cold count was the xdist **controller's** own rewrites of xdist's modules (imported only by a `-n` controller; MEASURED by instrumenting `_rewrite_test`: all 12 cold rewrites in the controller's PID, all `site-packages/xdist/*.py`). The controller runs no test, so its own count is no longer a run input (`plugin._controller_meta`); the workers' counts still are. With the D4 fix below those modules are also pre-warmed | `tests/test_verifier_truth.py::test_parallel_trace_records_inputs` (unchanged) |
| R-050 D4 (PY-01; added by the coordinator) | the first `--det` run in a fresh environment rewrote the modules of every pytest-plugin distribution (hypothesis, xdist) from source: run 1 vs run 2 of an unchanged checkout verified divergent | `plugin._plugin_rewrite_files`: the pre-warm also covers every `.py` file of every distribution with a `pytest11` entry point (what pytest marks for rewrite) | `tests/test_review_p1_packages_d4.py` (copied verbatim from `claude/review-p1-packages@0119874`) |

### The `os` control (finding #4: the class, not the cases)

Rule: under `--det` every OS source a test can observe is controlled or recorded; none stays silently real.

- **Controlled:** `os.getpid` / `os.getppid` / `threading.get_native_id` for user code (project and libraries):
  virtual `10000` (`10001+N` on xdist worker gwN, so per-process names stay unique), parent `9999`; the standard
  library and test infrastructure keep the real values (fork detection), and so do child processes (already
  `uncontrolled.child`). Temporary names: each session gets a fresh, locked `<tmp>/fenvix-det[-gwN]`
  (`tempfile.tempdir`; pytest's `tmp_path` lives under it), so a seeded name no longer collides with an earlier run's
  leftovers (the cause of the flip, MEASURED: the two names of the reviewer's test both existed in `/tmp`). `/dev/urandom`
  and `/dev/random` opened as files: a stream seeded from the test; `/proc/uptime`: the virtual monotonic clock. The
  `open` audit event is still raised for these, so the cache with proof's /proc-/sys-/dev rule sees them.
- **Recorded:** an `open` audit hook records, for every file user code opens for reading (outside the interpreter's
  installation, the session's temporary directories and the import system's `.py`/`.pyc`/extension reads), one
  `fs.read` event with the path and a digest of the content (or `<absent>`); `/proc` and `/sys` files included. Other
  devices, FIFOs and sockets opened as files mark the test `uncontrolled.device`. `os.getloadavg`, `os.statvfs`,
  `os.fstatvfs`: one event with a digest of the value.
- **Run input:** `os` (the control's description; names the temporary directory a contended session took).
  `--det-disable=os` turns it off and is recorded as `real (os control off)`.
- **Not covered (DECLARED, recorded gaps per the coordinator):** reads done in C without Python's I/O (`fopen` in an
  extension), `Thread.native_id` attributes, `multiprocessing.current_process().pid`, the memory / I/O counters of
  `resource.getrusage` (recording every call made G-1515's test, which reads only the virtual CPU times, never
  identical), `/proc/self/task/*/children` (the virtual sleep's own probe, read in the test's frame).

## Tests changed (none skipped, xfailed or weakened)

- `tests/test_fingerprint.py::test_outcome_only_divergence`: its premise was "state the controls do not observe (file
  contents) flips the outcome", asserting reason `outcome-only`. The read is now observed: the test asserts reason
  `fs` and that the first divergent event is the `fs.read` of the counter file (stronger).
- `tests/rust_hotpaths_ref/_ref_proofcache.py` (the Python reference of the Rust cache, not a test assertion): its
  `/etc/hosts` / `nsswitch.conf` read runs under `_state.quiet()`, as the Rust path reads them with `std::fs`, which the
  audit hook never sees (otherwise `test_capture_rust.py` compared fingerprints that differed only by this read).
- `tests/test_harness_parallel_proof.py::test_synthetic_project_and_comparison`: the synthetic project's
  `test_reader` reads a file `test_writer` writes outside the project, from the other worker under `--dist loadfile`.
  That cross-worker race was real but unobserved; the read is now an event, so the reader may differ by placement and
  between the two parallel runs. The test now requires: placement = the victim (when apart) plus at most the
  reader, parallel noise at most the reader, and for the reader the first differing event must be that `fs.read`
  (every other assertion unchanged).
- Copied tests: of the reviewer's 7 tests in `test_review_p1_verifier.py`, the 3 of findings #3/#4 are in
  `tests/test_review_p1_python_leaks.py` verbatim (only the module docstring differs); the other 4 (findings 5, 8, 9,
  10) belong to `claude/verifier-cli` and would be red here.

## Shared areas

No Rust code changed (no Node suite needed). Files the verifier session may also touch: `python/detpy/plugin.py`
(two small hunks: `_controller_meta`, `_plugin_rewrite_files` + one line in `prewarm_rewrite_cache`) and
`python/detpy/_level0.py` (control list, install, begin/end test, one run input). Nothing in `repro.py`, `fenvix.py`,
`verify.rs`, env handling.

## Measurements

Full Python suite as the CI job runs it, each version with a fresh `XDG_CACHE_HOME` and its own `TMPDIR` (the three
ran at once on a 4-core machine), on commit 0e5a47a of this branch (engine code final; before the harness test edit):
`python -m pytest -q -p no:randomly tests --deselect tests/test_review_r017.py::test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does -rfE`

| version | MEASURED result | failures and their status |
|---|---|---|
| 3.12.3 | 2 failed, 1043 passed, 72 skipped, 1 xfailed | `test_harness_parallel_proof.py::test_synthetic_project_and_comparison` (fixed afterwards, see above; then `2 passed`, MEASURED with `-p no:randomly tests/test_harness_parallel_proof.py`); `test_clock_rust.py::test_rust_clock_is_faster_than_the_reference` (a timing comparison while three suites shared 4 cores: `1 passed` alone, MEASURED) |
| 3.13.18 | 1 failed, 1045 passed, 71 skipped, 1 xfailed | the harness test above (fixed: `2 passed` × 3 runs, MEASURED) |
| 3.14.6 (uv build) | 5 failed, 1041 passed, 71 skipped, 1 xfailed | the harness test (fixed); `test_clock_rust.py::test_traces_match_reference`, `::test_children_alive_and_its_audit_events_match_reference`, `test_review_r023b.py::test_2e_os_getrandom_is_entropy[serial,n2]`: **pre-existing in this interpreter**: the same 4 fail on trunk 71f8081 with the same interpreter (MEASURED: `PYTHONPATH=<worktree of 71f8081>/python python3.14 -m pytest -q -p no:randomly tests/test_review_r023b.py::test_2e_os_getrandom_is_entropy tests/test_clock_rust.py` → `4 failed, 12 passed`); this 3.14.6 build has no `os.getrandom` (`hasattr(os, "getrandom")` → False) and its `mock_open` differs. UNKNOWN whether CI's 3.14 shows them; CI on trunk is the reference |

Targeted, after the last edits: `python -m pytest -q -p no:randomly tests/test_harness_parallel_proof.py
tests/test_review_p1_python_leaks.py tests/test_review_p1_packages_d4.py tests/test_verifier_truth.py
tests/test_fingerprint.py` → 3.12: `35 passed` (MEASURED); 3.13: `35 passed`; 3.14: `35 passed` (MEASURED, each run alone). A 3.14 run made at the same time as the 3.13 one, both with the default `TMPDIR`, gave `5 failed, 30 passed`; ESTIMATED cause: the two sessions contended for `/tmp/fenvix-det`, and the session that took `fenvix-det.1` has a different `os` run input, so traces compared across them differ by input (the intended, honest behaviour; CI jobs do not share a machine).

Before the fix (MEASURED, 3.13, trunk code): `tests/test_review_p1_python_leaks.py` → 3 failed (pid, tempfile name,
/dev/urandom, /proc/uptime, outside file, raw thread race, pre-started pool race all "stable" although they differed;
8 runs gave `['1 failed, 1 passed', '2 passed']`); `tests/test_verifier_truth.py` → `1 failed, 18 passed`; the D4
test → `1 failed` (fresh `XDG_CACHE_HOME`). After: all pass (fresh `XDG_CACHE_HOME` for #11 and D4: `19 passed`,
`1 passed`).

Cost (ESTIMATED, not measured separately): one audit-hook call per audit event of the process, one `stat` and a
digest of up to 1 MiB per file a test reads, one thread CPU-clock read per non-infrastructure thread per test. The
full suite took 39–42 min per version here, as before (UNKNOWN: no same-machine baseline run).

No Node suite run: no Rust or Node code changed (DECLARED).

### After merging trunk (f84dde7, then a996b68)

`origin/claude/release-1` merged twice (no conflict). Wheel rebuilt as the new workflow does (`dist/fenvix-*.whl`).

- Main Python suite on the f84dde7-merged tree, same command, fresh `XDG_CACHE_HOME`, own `TMPDIR` per version
  (MEASURED): 3.12 `2 failed, 1073 passed, 73 skipped, 1 xfailed`; 3.13 `1076 passed, 72 skipped, 1 xfailed`;
  3.14 `4 failed, 1072 passed, 72 skipped, 1 xfailed` (exactly the 4 local-interpreter failures listed above).
  The 2 on 3.12 pass alone (`2 passed`, MEASURED): `test_level0_seeds_fsorder_rust.py::test_rust_stand_ins_are_faster_than_the_reference`
  (timing) and `test_level0_rust.py::test_level0_traces_match_reference`, which also fails on trunk a996b68 itself
  when four copies run at once (MEASURED: 4 concurrent runs with trunk's `python/` on `PYTHONPATH` → 3 failed,
  1 passed; this branch, 2 concurrent → passed, alone → passed): a pre-existing load flake.
- The suites the a996b68 merge touches plus this branch's files, on the final tree (MEASURED, each version):
  `python -m pytest -q -p no:randomly tests/test_review_p1_packages_d123.py tests/test_packaging.py
  tests/test_fenvix_cli.py tests/test_review_p1_python_leaks.py tests/test_review_p1_packages_d4.py
  tests/test_verifier_truth.py tests/test_fingerprint.py tests/test_harness_parallel_proof.py` → 3.12, 3.13, 3.14:
  `84 passed, 1 skipped`.
- **Not run locally:** the workflow's extra environments (runner suites, numpy/time-machine, hypothesis/benchmark)
  and the exam's det2 check on attrs and itsdangerous: pypi.org was unreachable from this container from about
  21:45 UTC (`curl https://pypi.org/simple/attrs/` → `Could not resolve host`), so their dependencies could not be
  installed. They run in the full CI on the PR head and in the exam on its artifact (coordinator's decision).

Build: as `.github/workflows/release-1.yml` (`maturin build --release --compatibility linux -o dist`, wheel installed
`--no-deps` in three venvs with pytest 9.2.0 and pytest-xdist; `_core` copied into `python/detpy/`).
