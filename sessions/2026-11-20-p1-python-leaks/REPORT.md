STATUS-LINE

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
- Copied tests: of the reviewer's 7 tests in `test_review_p1_verifier.py`, the 3 of findings #3/#4 are in
  `tests/test_review_p1_python_leaks.py` verbatim (only the module docstring differs); the other 4 (findings 5, 8, 9,
  10) belong to `claude/verifier-cli` and would be red here.

## Shared areas

No Rust code changed (no Node suite needed). Files the verifier session may also touch: `python/detpy/plugin.py`
(two small hunks: `_controller_meta`, `_plugin_rewrite_files` + one line in `prewarm_rewrite_cache`) and
`python/detpy/_level0.py` (control list, install, begin/end test, one run input). Nothing in `repro.py`, `fenvix.py`,
`verify.rs`, env handling.

## Measurements

SUITE-RESULTS

Build: as `.github/workflows/release-1.yml` (`maturin build --release --compatibility linux -o dist`, wheel installed
`--no-deps` in three venvs with pytest 9.2.0 and pytest-xdist; `_core` copied into `python/detpy/`).
