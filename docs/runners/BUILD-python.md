# All runners, Python builder: build summary

Branch `ar-python` (worktree of `claude/all-runners`). Labels: **MEASURED** (local container, 4 shared CPUs:
timings NOISY), **ESTIMATED**, **UNKNOWN**. Per-runner details: `unittest.md`, `django.md`, `nose2.md`, `doctest.md`,
`zope-testrunner.md`, `ward.md`, `hypothesis.md` (this directory).

## Shared layer (one design, no copy per runner)

| piece | what |
|---|---|
| `python/detpy/_level0.py` | the `--det*` option table, controls, epoch, hash-seed re-exec, control installation, per-test bracket, trace header: called by the pytest plugin and by the driver (moved out of `plugin.py`, not copied) |
| `python/detpy/_proof.py` | the runner-neutral part of `proofcache.py`: `Capture`, identities, `ProofSession` (decide, start/stop, report, record, receipts, summary); `proofcache.py` keeps pytest's hooks and configuration digest |
| `python/detpy/runners/driver.py` | `DetRun`: the lifecycle of the contract (`docs/ALL-RUNNERS.md`) for every non-pytest runner; trace meta `runner` |
| `CacheSession.regroup` (Rust, `session.rs`) | units of reuse larger than a test (all or none) |
| `_statcap.py` + `CaptureCore.probe` (Rust) + `proof::probe_now` | **new inputs, fixing wrong reuses that pytest had too** (below) |
| `seeds._hypothesis` | Hypothesis under every runner (pytest included): seed per test id, no database, no storage, no local constants |

### Two shared holes found and fixed (they were wrong reuses under pytest as well)

| hole | before (MEASURED, pytest 9.2, `--det --det-cache`) | fix |
|---|---|---|
| `os.stat` / `os.path.exists` / `isdir` / `getsize` / `getmtime` / `access` / `readlink` / `realpath`: no audit event, so not inputs | 3 of 4 probe tests reused as passed after the probed file appeared / grew / became a directory (fresh run: failed) | probes are inputs of their own (`\x01<mode><path>` data keys): existence and kind, or kind + mode + size + mtime (+ symlink target); the checker recomputes them (`probe_now`) |
| an optional module that appears (`try: import x except ImportError`): the import system's cached listing kept the miss out of the test | the test reused as passed after `x.py` appeared (fresh run: failed) | a failed import (`_find_and_load`, `importlib.util.find_spec`) makes every path the path finder would have found the module at an existence input |

Also in the shared capture: the capture's own Python calls (`realpath` of code files) and frames of the runner
shell's entry (`runners._detpy_runner_entry`) are not inputs (as pytest's own frames are infrastructure).
The engine has no switch that leaves the probes out; the equivalence test with the pre-probe Python reference
(`tests/test_capture_rust.py`) removes them from its test-only plugin (`tests/rust_hotpaths_ref/_capref.py`,
`DETPY_EQ_NO_PROBES=1`).

## Per runner

### 1. unittest (`python -m detpy unittest ...`)

| support | control tests | adversarial tests | walk specs | local mini-walk | not covered |
|---|---|---|---|---|---|
| det + skip | `tests/test_runners_unittest.py`: `test_two_det_runs_give_identical_fingerprints`, `test_seeded_shuffle_is_reproducible_and_keeps_classes_together`, `test_controls_are_active_inside_unittest_tests`, `test_hypothesis_is_seeded_per_test_and_has_no_database`, `test_reused_results_are_reported_to_the_runner`, `test_verify_mode_compares_every_would_be_reuse`: 6/6 pass | `test_wrong_reuse[27 cases]` (shared table, R-009/R-017/R-021: content, os.open, pathlib, size, mtime, mode, symlink, realpath, listing, recursive walk, recursive glob, exists, pathlib exists, kind, optional module, mock target, env single, env enumeration, TZ, child reads file, child /dev/shm, loopback socket, sqlite real clock, .git HEAD, O_EXCL, sqlite `file:` URI, child file timestamp) + 8 own (class state unit, setUpClass/setUpModule reads, load_tests reads, `-p` change, `-b`, new module, tearDownClass error, file written by another test): 35/35 pass. Fail on a naive adapter: class state (MEASURED: `test_b` reused, fresh fails), tearDownClass error; size/mtime/mode/symlink/realpath/exists/kind/optional module (MEASURED before the shared fix) | `runner-unittest-jc` (kellyjonbrazil/jc, head d8698b5829bd, 21 commits, TZ=America/Los_Angeles as its runtests.sh), `runner-unittest-icecream` (gruns/icecream, 05af3e95b008, 21) | jc, 4 commits: 99.1% of test time reused at commits 1-2, 1678/1678 reuses verified, 0 wrong (MEASURED, below) | import-time side effects of one test module on another's tests (the pytest plugin's rule); `python test_x.py` with `unittest.main()` |

### 2. Django (`python -m detpy django manage.py test ...`)

| support | control tests | adversarial tests | walk specs | local mini-walk | not covered |
|---|---|---|---|---|---|
| det + skip; `--parallel` forced to 1 (said); Django's groups kept under a shuffle | `test_two_det_runs_give_identical_fingerprints`, `test_seeded_shuffle_keeps_django_groups`, `test_parallel_is_forced_to_one`: 3/3 | shared table 26 (TZ skipped: Django sets TZ from settings) + `test_json_fixture_change_reruns_its_testcase`, `test_template_from_the_cached_loader_is_an_input_of_every_renderer`, `test_settings_module_change_is_configuration`, `test_migration_change_reruns_database_tests`: 30/30 pass, 1 skipped. Fails on a naive adapter: the cached template (MEASURED: `test_render_b` reused as passed, fresh fails; **pytest-django has the same hole**) | `runner-django-healthchecks` (healthchecks/healthchecks, 4b0fd38b7a57, 21, sqlite), `runner-django-debug-toolbar` (django-commons/django-debug-toolbar, 53d092c4a15a, 21, `python -m django test tests`, sqlite in memory) | not run locally | whole environment is an input of every test (wsgiref reads it at import, as under pytest-django); non-sqlite databases |

### 3. nose2 (`python -m detpy nose2 ...`)

| support | control tests | adversarial tests | walk specs | local mini-walk | not covered |
|---|---|---|---|---|---|
| det + skip; `-N` refused (exit 4) | `test_two_det_runs_give_identical_fingerprints_and_stable_ids`, `test_seeded_shuffle_is_reproducible`, `test_controls_are_active_inside_nose2_tests`: 3/3 | shared table 27 (as nose2 function tests) + `test_configuration_file_is_an_input`, `test_plugin_module_change_reruns`, `test_multiprocess_plugin_is_refused`: 30/30 | `runner-nose2-nose2` (nose-devs/nose2, c6decb29bed3, 21), `runner-nose2-howdoi` (gleitz/howdoi, 033dd3ced067, 21, page_cache, no network) | not run locally | `layers` plugin not wired (its set-up is global: sound, coarse); mp plugin turned on from a config file: its workers are child processes (not reused) |

### 4. doctest (`python -m detpy doctest FILE...`)

| support | control tests | adversarial tests | walk specs | local mini-walk | not covered |
|---|---|---|---|---|---|
| det + skip | `test_two_det_runs_give_identical_fingerprints`, `test_seeded_shuffle_is_reproducible`, `test_controls_are_active_inside_doctests`: 3/3 | shared table 27 (as docstring examples) + `test_text_file_change_reruns_it`, `test_docstring_change_reruns_the_module_doctests`, `test_option_change_is_configuration`: 30/30 | `runner-doctest-autopep8` (hhatto/autopep8, d6b5b3342aac, 21, `python -m doctest -v README.rst`). **Only one**: no second repository whose CI runs `python -m doctest` was found without code search here (the sample has 0; the raw code-search file keeps one item). The coordinator can list more with `gh api search/code -f q='"python -m doctest" path:.github/workflows' -f per_page=100` | not run locally | `testmod()` from a `__main__` block; report format is unittest's |

### 5. zope.testrunner (`python -m detpy zope-testrunner ...`)

| support | control tests | adversarial tests | walk specs | local mini-walk | not covered |
|---|---|---|---|---|---|
| det + skip; `-j` forced to 1 | `test_two_det_runs_give_identical_fingerprints`, `test_seeded_shuffle_is_reproducible`, `test_controls_are_active_inside_zope_tests`: 3/3 | shared table 27 + `test_layer_setup_read_is_an_input_and_a_reused_layer_is_not_set_up`, `test_test_suite_function_reads_are_inputs`, `test_processes_forced_to_one`: 30/30 | `runner-zope-irclog2html` (mgedmin/irclog2html, cd63e13d44ed, 21), `runner-zope-datetime` (zopefoundation/DateTime, b157397e2162, 21) | not run locally | layers resumed in a subprocess (`CanNotTearDown`): outside the driver, not reused |

### 6. ward (`python -m detpy ward test ...`)

| support | control tests | adversarial tests | walk specs | local mini-walk | not covered |
|---|---|---|---|---|---|
| det + skip | `test_two_det_runs_give_identical_fingerprints`, `test_seeded_shuffle_is_reproducible`, `test_controls_are_active_inside_ward_tests`: 3/3 | shared table 27 (as ward tests) + `test_module_and_global_fixture_reads_are_inputs_of_their_users`: 28/28. Fails on a naive adapter: module fixture (MEASURED: the second user reused as passed, fresh fails) | `runner-ward-ward` (darrenburns/ward, 3289bd641e9b, 21, Python 3.12), `runner-ward-pointers` (ZeroIntensity/pointers.py, 37fa094230bf, 21, Python 3.12) | not run locally | the generate_test_runs loop is a copy of ward 0.68's |

### Hypothesis (under each)

`test_hypothesis_is_seeded_per_test_and_has_no_database` (unittest; the same `seeds.start_test` runs under every
runner and under pytest): the same fingerprint in two runs and when the test runs alone (MEASURED before the fix:
fingerprints differed between two identical runs, the constants cache written by the first). `hypothesis.md`.

## Commands and counts (MEASURED, 2026-11-19)

    python -m pytest tests/test_runners_unittest.py tests/test_runners_django.py tests/test_runners_nose2.py \
        tests/test_runners_doctest.py tests/test_runners_zope.py tests/test_runners_ward.py -p no:cacheprovider
    -> 204 passed, 1 skipped (381 s, NOISY)

Engine suite, whole (`python -m pytest tests -p no:cacheprovider --ignore=tests/rust_hotpaths_ref`): 741 passed,
4 failed, 9 skipped (1290 s, NOISY). The 4 failures are the ones of the base commit before any change of this
branch (baseline run on 86ce112: 4 failed, 537 passed, 8 skipped): two speed comparisons with the Python references
under a loaded machine (`test_rust_clock_is_faster_than_the_reference`, `test_precompile_stamps_and_todo_match_reference[4,9]`)
and `test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does` (a review test over a recorded results file: `AttributeError` on a missing entry of that file, unrelated to this branch).

## Local mini-walk (MEASURED, local, NOISY)

`python3 harness/cache_proof/walk.py --spec harness/cache_proof/specs/runner-unittest-jc.json --commits 4` (the 4
first-parent commits ending at d8698b5829bd); raw output `/tmp/claude-0/scratch-python/walk/out/runner-unittest-jc.json`,
log `/tmp/claude-0/scratch-python/walk/jc.log`.

| commit | tests | reused | share of test time reused | reuses checked against a full run | wrong | A (cache) wall | B (full) wall |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 7e67daf237 | 1708 | 0 (cold) | 0% | 0 | 0 | 16.2 s | 12.8 s |
| 1 1ff397ccb5 | 1708 | 1678 | 99.1% | 1678 | 0 | 3.0 s | 14.4 s |
| 2 04c3c0af7c | 1708 | 1678 | 99.1% | 1678 | 0 | 3.3 s | 14.9 s |
| 3 d8698b5829 | 2495 | 0 | 0% | 0 | 0 | 29.5 s | 19.4 s |

The 30 tests never reused read `/proc` (the capture's rule). Commit 3 changed a dependency file: the walk reinstalled,
the runtime identity changed, nothing was reused (`miss runtime 1678`), and it added 787 tests. The plain runner
(`python -m unittest`, no `--det`) failed 0 tests at commits 0 and 3 with `TZ=America/Los_Angeles` (172 failed
without it, under the plain runner as well: jc's tests expect that zone).

## Walk specs checked at their head commit (MEASURED, local, NOISY)

`walk.py --commits 1` per spec (install, cache run, full run, plain runner without `--det`, cold cache); raw output
`/tmp/claude-0/scratch-python/walkv/out/<spec>.json`. Every suite ran on Linux with no service; the tests failing
under `--det` are exactly the ones failing under the plain runner.

| spec | tests | fail under `--det` | fail under the plain runner | full `--det` run | plain run |
|---|---:|---:|---:|---:|---:|
| runner-unittest-jc (TZ=America/Los_Angeles) | 2495 | 0 | 0 | 19.4 s | (4-commit walk above) |
| runner-unittest-icecream | 65 | 0 | 0 | 0.7 s | 0.6 s |
| runner-django-healthchecks | 1646 | 8 | 8 | 29.3 s | 27.6 s |
| runner-django-debug-toolbar | 378 | 0 | 0 | 6.6 s | 7.8 s |
| runner-nose2-nose2 | 333 | 0 | 0 | 26.2 s | 27.4 s |
| runner-nose2-howdoi | 25 | 1 | 1 | 5.4 s | 5.8 s |
| runner-zope-irclog2html | 89 | 2 | 2 | 0.8 s | 0.9 s |
| runner-zope-datetime | 53 | 0 | 0 | 0.5 s | 0.6 s |
| runner-ward-ward | 409 | 3 | 3 | 1.9 s | 2.3 s |
| runner-ward-pointers | 24 | 0 | 0 | 0.8 s | 1.3 s |
| runner-doctest-autopep8 | 1 | 0 | 0 | 0.4 s | 0.2 s |

To run them on GitHub Actions: copy `tracks/all-runners-python/run.json.example` to
`tracks/all-runners-python/run.json` (edit `run_id`) on `claude/all-runners` and push; the workflow is
`.github/workflows/all-runners-python.yml` (the cache-proof workflow's jobs, results committed to
`tracks/all-runners-python/results/<run_id>/`).

## After the first Actions run (ar-py-1)

* Harness: a spec's own install commands now start from a removed environment at every reinstall (`uv venv`
  refused to overwrite it: healthchecks commits 1-20 were `install-failed`).
* ward: a suite run inside a test (ward's own tests run suites) took over the session (its loop replaced the
  session's tests: 0 recorded, every id `new` at every commit). Nested suites now run ward's own loop
  (`test_a_suite_run_inside_a_test_is_that_tests_code`). ward ids are stable: 371 of 389 of ward's tests reused in an
  unchanged second run (MEASURED, local).
* Shared capture: `shutil.rmtree` removes entries by name under a directory descriptor (`os.remove(name,
  dir_fd=...)`); those were taken as writes of the same names in the working directory, so every test reading
  e.g. `pyproject.toml` was "reading a file another test wrote" (ward: 376 of 389). Paths with a `dir_fd` are now
  resolved through `/proc/self/fd` (`test_rmtree_of_a_temporary_directory_is_not_a_write_in_the_project`). The
  pytest path had the same bug.
* Shared runtime identity: a `*.egg-info` inside the project's tree (`src/DateTime.egg-info`, left by a setuptools
  develop install and found through `src` on `sys.path`) was taken as an installed distribution with its version,
  so every commit that changed the version reran everything (`runtime` misses of zope-datetime, icecream, howdoi).
  It is the project itself and is left out now; a `.dist-info` in the tree stays a distribution (review R-002 N2).
* `clock` misses (zope-datetime, icecream, howdoi): the designed epoch rule. The cache keeps its epoch while HEAD's
  commit time is at most 30 days later; these projects' commits are weeks or months apart, so the epoch moves and
  every test that read the clock reruns.
* howdoi: 11 tests start processes (never recorded: `new` at every commit); the others are one `TestCase` class,
  so one changed test reruns the class (`unit`: the class is the unit of reuse).
* ward specs: `runner-ward-pointers` removed (its C extension uses frame internals that do not build on Python 3.12+,
  and the cache needs 3.12+); `runner-ward-ward` gets `setuptools<81` and a 4-commit window (older ward calls
  `FileFinder.find_module`, removed in 3.12; it fails under plain `ward` too). A second ward repository needs a code
  search (`"tool.ward" filename:pyproject.toml`).

## Hooks of the new shells that the pytest path needed too

| hook | pytest path | now |
|---|---|---|
| Django cached template loader re-read, translation catalogs in the global context | same hole under pytest-django (the second renderer reused as passed after the template changed: MEASURED, `test_template_from_the_cached_loader_is_an_input_of_every_renderer_under_pytest_django` fails before) | shared `detpy/_django.py`, applied by `ProofSession` (every runner) whenever Django's template engine or translations are imported |
| unittest `TestCase` class as the unit of reuse | same hole for `unittest.TestCase` classes run by pytest (`test_unittest_class_is_the_unit_of_reuse_under_pytest` fails before) | `proofcache._unittest_units`; plain pytest classes keep the plugin's rule (a fresh instance per test; class attributes follow the module-state rule) |
| class / module tear-down error never reused | already handled: pytest reports it on the last test's teardown | no change |
| ward nested suites, ward fixture contexts | ward only (pytest's nested in-process sessions are already the outer session's) | no change |
| runner entry frame as infrastructure | pytest's own frames are infrastructure already | no change |
| probes, import misses, `dir_fd` writes, in-tree `egg-info`, Hypothesis | shared from the start | — |
