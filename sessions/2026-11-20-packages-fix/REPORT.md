DONE — R-050 D1, D2, D3 fixed, the reviewer's tests pass, touched suites green locally on 3.12/3.13/3.14 (the final CI round is the coordinator's)

# Fix round of review R-050 (rows F-09, PY-01; JS-01 passed), defects D1-D3

Session 2026-11-20, branch `claude/packages` brought to `claude/release-1` @ f84dde7 (PR #2 merged), one push, a new PR
into `claude/release-1`. Scope: D1, D2, D3 of `sessions/2026-11-20-review-p1-packages/REPORT.md` (branch
`claude/review-p1-packages` @ 0119874); D4 is the Python leaks session's and is not touched here
(`plugin.prewarm_rewrite_cache` / `_level0` REWRITE unchanged). The fix branch is `claude/packages`, not
`claude/packages-fix`: this session may push only to `claude/packages` (its standing permission), and a message from
another session does not widen it.
Numbers are MEASURED (with the command) unless marked otherwise.

## The reviewer's tests

`tests/test_review_p1_packages_d123.py`: D1-D3 of `tests/test_review_p1_packages.py` @ 0119874, copied unchanged (a
file of their own, so the D4 session's copy of the reviewer's file does not conflict). On f84dde7: 4 failed. Now:
4 passed on CPython 3.12.3, 3.13 and 3.14.6.

## D1 (PY-01) — CPython newer than 3.14 refused

- `detpy/_support.py`: `MAX = (3, 14)`; a newer CPython gets one sentence ("fenvix is not built or tested for CPython
  3.15 yet (the newest supported is 3.14); this is ...") and every entry refuses with exit 4 as below 3.12 (the
  pytest plugin, `python -m detpy`, `detpy`, `fenvix` engine commands).
- `release/engine/install.sh`: the interpreter check accepts only `(3, 12) <= version <= (3, 14)` (exit 4, the same
  sentence as before: "needs CPython 3.12, 3.13 or 3.14").
- Tests: `test_d1_newer_cpython_than_supported_is_refused_by_the_engine`, `..._by_the_installer`.

## D2 (F-09) — `fenvix version` names the installed artifact

- `detpy.fenvix.artifact_line()`: from `$FENVIX_HOME/VERSION.json` (copied there by `install.sh`): "artifact
  fenvix-engine 0.1.0 build r<run>.<sha7> commit <full sha> (linux-x86_64, glibc 2.28+)"; without one it says so
  ("none installed in ... (no VERSION.json; a wheel or a checkout)"). Second line of `fenvix version` /
  `fenvix --version`, also on an unsupported interpreter.
- MEASURED on an artifact assembled here (`release/engine/assemble.sh`, ENGINE_BUILD r4242.f84dde7) and installed
  with its `install.sh`: `artifact fenvix-engine 0.1.0 build r4242.f84dde7 commit f84dde74f3a415acc4678b2e0d6f71a03a2c9903
  (linux-x86_64, glibc 2.28+)`.
- Tests: `test_d2_fenvix_version_names_the_installed_artifact`; the install test in clean containers gains the check
  `fenvix_version_names_artifact` (build and full commit of the artifact's own VERSION.json).

## D3 (F-09) — a job's own venv gets the engine from the runner image

- The engine moves, not the job: `install.sh` and `release/install-image.sh` also install the wheel without
  dependencies into `$FENVIX_HOME/python` (`pip install --no-deps --target`: package and distribution metadata).
- `release/fenvix` (= the artifact's `bin/fenvix`): runs with the job's `python3`; when that Python cannot import
  the engine, it takes `$FENVIX_HOME/python` (or, from a checkout, the `python/` next to it), puts it on that
  Python's path for the command and on `PYTHONPATH` for the processes it starts. The engine's own interpreter check
  still decides (a 3.11 job venv: one sentence, exit 4, MEASURED).
- `detpy.fenvix`: `fenvix python|pytest` adds `-p detpy.plugin` only when no installed distribution provides the
  plugin's `pytest11` entry point (otherwise pytest would register it twice).
- MEASURED end to end on the assembled artifact (system CPython 3.13): job venv with pytest only (`import detpy`:
  ModuleNotFoundError), `PATH=<job venv>/bin:... $FENVIX_HOME/bin/fenvix python -q -p no:cacheprovider --det
  test_a.py` → "detpy (Level 0)", "1 passed", exit 0.
- `docs/INSTALL.md`: such a job installs nothing; how the image's copy is found; the newer-CPython refusal.
- Tests: `test_d3_a_job_venv_gets_the_engine_from_the_runner_image`; the install test in clean containers gains
  `job_venv_part` (a fresh venv with pytest only, `fenvix python --det` through the image's `bin/fenvix`).

## Local verification (before the one push)

Wheel and addon built as CI builds them (`maturin build --release --zig --compatibility manylinux_2_28`,
`cargo zigbuild -p detpy-node --target x86_64-unknown-linux-gnu.2.28`), the artifact assembled with
`release/engine/assemble.sh`.

Touched suites (every test file that runs `detpy._support`, `detpy.fenvix`, `release/fenvix` or the installers):
`test_review_p1_packages_d123.py`, `test_packaging.py`, `test_fenvix_cli.py`, `test_f01_gaps.py`,
`test_controls_f01.py`, `test_network_gaps.py`, `test_runners_ward_support.py`, `test_verifier_truth.py`:

| | CPython 3.12.3 | CPython 3.13 | CPython 3.14.6 (uv) |
|---|---|---|---|
| passed / failed / skipped | 112 / 1 / 4 | 112 / 1 / 4 | 112 / 1 / 4 |

The one failure on every version is `test_verifier_truth.py::test_parallel_trace_records_inputs` (input `bytecode`
"precompiled" in one run, not in the other): it fails identically on `claude/release-1` @ f84dde7 without this
change (MEASURED, two runs each), it is D4's class (the rewrite cache's cold first run), and D4 belongs to the Python
leaks session. Not fixed here.

`_support` is imported everywhere, but the change only adds a refusal above 3.14: nothing changes on 3.12-3.14.
Node: no file under `node/`, `crates/detpy-node` or `crates/detpy-core` changed since 7e36c39, where the detjs
suites passed locally on Node 22 (630 passed / 0 failed / 1 skipped) and Node 26 (630 / 0 / 1). Node 24 is not
installed in this container: its suite runs in CI.
Not run locally: `release/install_test.py` as a whole (it clones two third-party projects and runs `npm install`,
which this session's policy refused earlier); its new parts were run by hand on the assembled artifact (above).

## Per il fondatore

Correzioni D1-D3 della revisione R-050 fatte su `claude/packages` (un solo push) con una nuova PR verso
`claude/release-1`: CPython più nuovo di 3.14 rifiutato con una frase (uscita 4); `fenvix version` mostra build e
commit dell'artefatto installato; un job con il suo venv usa il motore dell'immagine senza `pip install`. Il test
`test_parallel_trace_records_inputs` fallisce già sul trunk (f84dde7): è la classe di D4, della sessione Python.
