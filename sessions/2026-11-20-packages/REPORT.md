PARTIAL — pending the final CI evidence (section 2); see section 0 for what is left.

# Rows F-09 (the engine artifact for our machines), PY-01 (Python versions), JS-01 (Node versions)

Session 2026-11-20, branch `claude/packages` (from `claude/release-1` @ 7d5a552), PR #2 into `claude/release-1`.
Scope after the founder decision of 2026-11-20 (relayed by the coordinator): the go-live runs only on our machines;
no PyPI/npm publishing, no macOS, no Linux arm64. F-10 (packages) became the single engine artifact of F-09.
Numbers are MEASURED (with run id or command), ESTIMATED (with derivation), DECLARED (with source) or UNKNOWN.

## 0. Status

(filled with the final CI run)

## 1. Per row

### F-09 — one versioned engine artifact for our machines

True now (code on the branch; CI evidence in section 2):
- **One artifact**: `fenvix-engine-<version>-r<run>.<sha7>-linux-x86_64.tar.gz` plus `.sha256`, assembled by
  `release/engine/assemble.sh` in the trunk CI (`.github/workflows/release-1.yml`, job `build`) from the very
  binaries every gate job tests:
  - the wheel `fenvix-<v>-cp312-abi3-manylinux_2_28_x86_64.whl` (maturin `--zig --compatibility manylinux_2_28`,
    `twine check --strict`): pytest plugin, `python -m detpy` runners, the `fenvix` command;
  - the Node shells and the napi core `detjs.linux-x64.node` (`cargo zigbuild --target x86_64-unknown-linux-gnu.2.28`);
  - `bin/fenvix`, `install.sh`, `VERSION`, `VERSION.json` (version, build, commit, supported versions, the sha256 of
    every file), LICENSE, CHANGELOG.
  Reproducible: fixed order, owner and mtimes, gzip without name or time (MEASURED: two assemblies of one build give
  the same sha256, `501abc57…` locally; test `test_engine_artifact_is_reproducible_and_complete`).
- **Platform floor glibc 2.28**: `release/check_floor.py` fails the build if any native file needs a newer glibc
  symbol (MEASURED locally: wheel and addon max `GLIBC_2.28`; the former build method gives `GLIBC_2.34` and is
  rejected by the same check).
- **Published by every FULL run of the trunk** (nightly `schedule`, or "Run workflow" with depth `full` on
  `claude/release-1`): job `publish-engine` (after build, python, node, smoke and install pass) runs
  `release/engine/publish.sh`, which creates the GitHub pre-release
  `engine-<version>-r<run>.<sha7>` with the tarball and its `.sha256` at the stable URL
  `https://github.com/Mircoguidetti/fenvix-engine-cli/releases/download/<tag>/<file>`. On every pull request the
  same script runs with `--dry-run`: every check, the tag, URL and notes; only the
  release is not created. The dry run is a step of the job `build` on every pull request.
- **Runner image pins URL + sha256 and fails closed**: `release/engine/fetch.sh URL SHA256 DEST` downloads, compares
  the sha256 and only then unpacks; another checksum, no checksum, a download error or an archive with absolute or
  `..` paths installs nothing (test `test_runner_image_fetch_is_pinned_and_fails_closed`; the dry run also proves it
  on the real tarball: accepted with its sha256, refused with another). `runner/bootstrap.sh` installs from
  `FENVIX_ENGINE_URL` + `FENVIX_ENGINE_SHA256` (both or neither) through it.
- **Installer**: `install.sh [PREFIX]` (with `PYTHON=`): refuses another OS/CPU and an unsupported interpreter
  (exit 4, one sentence), installs the wheel into that Python's environment, the Node shells into `PREFIX/node`,
  then runs `fenvix doctor` and refuses the installation if the native core does not load or another distribution
  writes the import package `detpy/` (the unrelated PyPI project; G-0170, G-0737).
- **Install test in clean containers** (job `install`, no checkout: only the artifact and `install_test.py`):
  checksum and manifest, `install.sh`, `fenvix --version` (Python command and Node shell), `fenvix doctor`, then
  `pytest --det` twice (traces verified identical) and `--det-cache` twice (second run reuses, no outcome differs)
  on a small real Python project (itsdangerous 2.2.0) and `fenvix node vitest run --det` twice and `--det-cache`
  twice on a small real Vitest project (ufo v1.6.1, Vitest 3); images: `quay.io/pypa/manylinux_2_28_x86_64`
  (AlmaLinux 8, glibc 2.28, CPython 3.12, **pytest 8.1**, Node 22), `python:3.13-slim-bookworm` (Debian 12, Node 24),
  `python:3.14-slim` (Debian 13, Node 26), and `python:3.11-slim` for the refusal.
- **Single entry point** `fenvix` (wheel console script, `bin/fenvix` of the image): `--version`, `version`,
  `doctor`, `python`, `python-runner`, `node`, `verify`, `detect`.
- **One version** for every component (`release/version.py`; Cargo.toml, `detpy/_version.py`,
  `node/package.json`), `CHANGELOG.md`, `docs/INSTALL.md` (contents, install, requirements, containers, uninstall).
- **Removed** (founder decision): `packages.yml` (macOS and arm64 jobs), the npm packaging and publishing
  (`release/npm/`), TestPyPI. `release.yml` keeps the PyPI trusted-publishing job **disabled** (`if: false`) with
  the names of the pending publisher (project `fenvix`, workflow `release.yml`, environment `pypi`); test
  `test_pypi_publishing_is_off_and_keeps_the_reserved_publisher_names`. The macOS branches of
  `detpy_core::host` stay in the source but are compiled only on macOS, which nothing builds.

### PY-01 — CPython 3.12, 3.13, 3.14

True now:
- Full Python suites on 3.12, 3.13, 3.14 in `release-1.yml`; the runner suites (Django, nose2, ward, zope,
  pytest-django) and the tests that need numpy, time-machine, hypothesis or pytest-benchmark run in their own
  environments instead of being skipped (G-0010; each group in its own venv because auto-loaded plugins change
  the main suites: MEASURED: with them all installed into the main environment, 3.13 had 32 failures in run 44719938120, 6 of
  them from a since-fixed test of this branch, against 1 on the trunk in run 44714888645). Locally (3.13, clean venv
  as in CI): `tests/test_runners*.py` 205 passed / 2 skipped; numpy + time-machine group 30 passed; hypothesis +
  benchmark group 3 passed.
- **Runner tests that failed once their library was installed** (G-0010 exposed them; full run 44756797015, 3.12
  and 3.13): `test_runners_ward.py::test_module_and_global_fixture_reads_are_inputs_of_their_users` and
  `::test_a_suite_run_inside_a_test_is_that_tests_code`. Cause (this branch, G-2194): the runner driver wrote
  `.detpy/.gitignore` after the input capture had started, so the session recorded its own write in the project and
  nothing was reused. Fixed in `detpy/runners/driver.py` (the state directory is marked before the capture starts);
  both tests are the regression tests, neither skipped nor xfailed (MEASURED locally: with the write after the capture
  2 failed / 30 passed, after the fix 32 passed). The pytest plugin already wrote it before its capture.
- **Runner suites on CPython 3.14** (full run 44763521026, 33 failures in the runner environment):
  - nose2 `test_wrong_reuse[optional_module_appears]`: a precision defect of the engine. On 3.14
    `pathlib.Path.exists` is a kind check, so nose2's fixed probes of its start directory at every session
    (`__init__.py`, `.pyc`, `.pyo`, `lib`, `src`, `conftest.py`, `nose2.cfg`, `unittest.cfg`, `pyproject.toml`:
    nine, MEASURED from the recorded entry) crossed the per-directory compaction threshold of 8; every test then
    depended on the whole listing of `tests/`, and one new test module invalidated the whole suite. Fixed:
    `STATS_PER_DIR` 8 → 32 (`detpy_core::record`, and the Python reference `_ref_record.py`); regression test
    `record::tests::a_runner_start_directory_probes_stay_per_name`; `test_many_existence_checks_in_one_directory_are_one_dependency`
    now proves the compaction with 60 checks. Locally on 3.14: nose2, Django, zope, django_order,
    django_pytest_cache 111 passed / 1 skipped.
  - ward (32 tests): **explicit exclusion on 3.14** (coordinator decision). ward 0.68.0b0, its newest release,
    does not run on CPython 3.14 at all, without fenvix (MEASURED on 3.14.6, `ward` in a one-test project):
    `AttributeError: module 'textwrap' has no attribute '_leading_whitespace_re'` (from `ward/_rewrite.py`, line 99),
    exit 1. `python -m detpy ward` now refuses there before anything runs, with one sentence and exit 4
    (a capability check on `textwrap`, not a version check): "detpy ward: error: ward 0.68.0b0 does not run on Python
    3.14.6: it uses textwrap._leading_whitespace_re, which this Python no longer has (plain `ward` stops the same
    way). Run ward suites on CPython 3.12 or 3.13" (MEASURED). Test `test_runners_ward_support.py` asserts it on
    every interpreter (for real on 3.14, with the name removed in a child on 3.12/3.13); the ward suite runs where
    ward runs (3.12, 3.13). textwrap is not patched.
- Install test on 3.12 (glibc 2.28, pytest 8.1), 3.13, 3.14.
- **Below 3.12: refused, never a crash** (`detpy/_support.py`, decided before the native core is imported):
  `install.sh` exits 4 with "fenvix: needs CPython 3.12, 3.13 or 3.14 (default build); … is cpython 3.11"; a copy
  forced into 3.11 answers `pytest --det` (also via `PYTEST_ADDOPTS`, `--det-isolate`, `--det-cache`, `-n`),
  `python -m detpy <runner>`, `detpy` and `fenvix python` with "fenvix: fenvix needs CPython 3.12 or newer; this is
  Python 3.11 (…). Supported: CPython 3.12, 3.13, 3.14 on Linux x86_64 (glibc 2.28+)." and exit 4; a plain `pytest`
  runs unchanged. MEASURED in CI job `install (CPython 3.11 refused)` and locally on a real CPython 3.11.
  Wheel metadata `Requires-Python >=3.12`, stable ABI 3.12 (pip on 3.11 against an index: "Ignored the following
  versions that require a different python version: 0.1.0 Requires-Python >=3.12", MEASURED).
- pytest floor `>=8.1` (8.0 broke `--det-isolate` on unittest classes, 7.0–7.2 broke cache reuse: G-0171, G-0529);
  pytest-xdist < 3.7 under `--det -n` is a usage error naming the version (G-0530); `--det-isolate` raises no
  pytest-10 deprecation (G-1543).

### JS-01 — Node 22, 24, 26

True now:
- detjs suites on Node 22, 24, 26 in `release-1.yml`; install test with Node 22, 24, 26.
- **The trunk's Node 26 job** (red on the trunk, run 44714888645) is fixed: MEASURED locally on Node v26.13.1,
  5 failures in `r021b-fixes.test.js`:
  - a **wrong reuse** on Node 26: recursive `fs.promises.readdir` with `withFileTypes` enters linked directories from
    Node 26 (MEASURED: 3 entries instead of 2 on the fixture; Node 22: 2), and the capture keyed it as a
    non-following listing, so a file added behind a link was reused. Fixed in `node/src/cache/capture.js`
    (`PROMISES_TYPED_FOLLOWS`); the test now measures the platform behaviour and expects no wrong reuse where the
    listing follows (Node 26) and kept reuse where it does not (Node 22/24) — both pass, Vitest and Jest.
  - Node 26 Stats objects carry own symbol-keyed fields (`Symbol(partialAtimeNs)`, …) that `structuredClone` drops
    (MEASURED with plain Node 26, no detjs): the test compared a clone with `{...st}`; it now compares clone with
    clone.
  - the lstat-inode test's precondition depended on the filesystem not handing the freed inode back; the mutation
    now retries until the new link has another inode.
- `fenvix` / `detjs` answer `--version` and `--help` (exit 0), name an unknown runner, print a user error without a
  JavaScript stack; on any platform other than Linux x86_64 with glibc 2.28+ the loader stops with one sentence
  (`node/test/platform.test.js`).
- `.detpy/` and `.detjs/` carry a `.gitignore`: a `--det` run leaves a git checkout clean (G-2194, G-2177).

## 2. CI evidence

(final run ids below)

### CI load (coordinator tasks of 2026-11-20, founder decisions)

- The gate (`release-1.yml`, merged as PR #6 rule) has two depths of the same jobs, no sharding:
  - LIGHT on every pull request into `claude/release-1` and every merge into it: build, Python 3.13 full suite,
    Node 24 full suite, smoke python/node (5 jobs);
  - FULL by hand (`workflow_dispatch`, depth `full`) and nightly (`schedule`): Python 3.12/3.13/3.14, Node 22/24/26,
    smoke, the 4 install containers and, on the trunk, `publish-engine` (12 jobs);
  - pushes to session branches run no gate. Sharding (founder decision: 20, then 40 concurrent jobs; more jobs would queue more). A sharded variant with a
  coverage check and a serial-vs-sharded proof was built (commit 3483da1) and withdrawn by that decision before its
  run finished (run 44743656144, cancelled); nothing of it remains.
- Concurrency: one group per event and ref; on a pull request a new head cancels that pull request's older gate run,
  never the latest head's; a trunk run is never cancelled (test
  `test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs`).
- Jobs outside the go-live scope are gone from the gate: `go`, every `jvm (*)`, `smoke (go)`, `smoke (jvm)`, the
  Go/JVM build steps, `other-os (macos-14)`, `other-os (ubuntu-24.04-arm)`; Rust tests limited to `detpy-core` and
  `detpy-node`.
- Results commits of the harness workflows (24 commit messages in 18 workflow files, e.g. `parallel-proof.yml`, which
  pushes to `claude/py-cache` as "parallel-proof bot") carry `[skip ci]`, so a bot commit on a session branch starts
  no pull-request gate run. A branch runs its own copy of a workflow: `claude/py-cache` gets this when it merges the
  trunk. The harness launchers that start on a committed RUN file on a session branch (path filters) are not the
  gate and stay as they are: `workflow_dispatch` works only from the default branch, so they are how those sessions
  start their runs.

## 3. Every audit gap of these rows

Legend: FIXED (regression test) · REFUSED (explicit message; out of the supported set) · OUT (founder decision or
go-live scope) · FOUNDER (needs an account or settings action) · OTHER ROW (belongs to another row; owner named
where known).

| gap | status | evidence / regression test |
|---|---|---|
| G-0010 optional runners and plugins not installed in the gate | FIXED | release-1.yml steps "runner suites…", "suites that need numpy and time-machine", "tests that need hypothesis and pytest-benchmark" |
| G-0170, G-0248, G-0521 the PyPI name `detpy` is another project | FIXED | distribution `fenvix`; `install.sh` and `fenvix doctor` refuse a foreign `detpy/`; `test_foreign_detpy_distribution_reported`, `test_install_metadata_refuses_old_python_and_names_fenvix` |
| G-0737 import name `detpy` collides with that project | FIXED (refused) | the import name stays (`python -m detpy` is in scope); an environment where both write `detpy/` is refused by `install.sh` (doctor) |
| G-0171 `--det-isolate` broken on pytest 7.0–8.0 | FIXED | `pytest>=8.1`; `test_pytest_floor_excludes_versions_that_break_det`; install test on pytest 8.1 |
| G-0529 cache INTERNALERROR on pytest 7.0–7.2 | FIXED | same |
| G-0530 xdist < 3.7 INTERNALERROR | FIXED | `test_old_xdist_refused_with_usage_error` |
| G-1543 pytest 10 deprecation in `--det-isolate` | FIXED | `test_isolate.py::test_wider_fixtures_set_up_in_the_parent_raise_no_pytest10_deprecation` |
| G-0547, G-0548, G-0550, G-0551, G-0556, G-0470, G-2219 `pytest --det` crashes below 3.12 | FIXED (refused) | `test_unsupported_interpreter_pytest_det_refused_with_message_not_crash[*]`, `…other_det_options_refused[*]`, `…det_from_addopts_refused`; CI install job on CPython 3.11; RELEASE-1.md corrected |
| G-0549, G-0471 `python -m detpy` crashes on 3.9 | FIXED (refused) | `test_unsupported_interpreter_commands_refused[*]` |
| G-0414, G-0552, G-1133 cache needs 3.12 | REFUSED | 3.11 and older are not supported |
| G-0553, G-0555, G-0557, G-1576 free-threaded builds | REFUSED | `…[free-threaded]`; `install.sh` |
| G-0554 PyPy | OUT / REFUSED | `…[pypy]` |
| G-0695, G-1574 Python 3.14 never run | FIXED | 3.12/3.13/3.14 in the gate and the install test |
| G-0694 only the newest pytest tested | FIXED | install test on the glibc 2.28 image with pytest 8.1 (the floor), others pytest 9 |
| G-0692, G-1336, G-1443 Node 22 only | FIXED | Node 22/24/26 suites and install test; the Node 26 job fixed (section 1) |
| G-2188 Node 16 | OUT | |
| G-2189 supported Node versions stated nowhere | FIXED | `install.sh` warns outside 22/24/26; docs/INSTALL.md |
| G-0241, G-0251, G-0417, G-0254, G-0249, G-0523 no release channel, nothing installable | FIXED | the engine artifact and its GitHub pre-release per merge; `test_engine_artifact_is_reproducible_and_complete`, CI install jobs, `publish-engine-dry-run` |
| G-0731 install-image.sh is an image builder without checksum | FIXED | artifact + `install.sh` + `fetch.sh` (pinned sha256, fail closed); `test_runner_image_fetch_is_pinned_and_fails_closed` |
| G-0732, G-2193 no version discipline | FIXED | `release/version.py`, CHANGELOG, `VERSION.json`; `test_one_version_everywhere`, `test_fenvix_command_version_and_doctor` |
| G-0479, G-0481, G-0488, G-0489, G-0446 binaries need glibc 2.34 | FIXED | manylinux_2_28 build, `release/check_floor.py` in the build job, install test on AlmaLinux 8 (glibc 2.28) |
| G-0250, G-0524, G-1488 wheel tagged `linux_x86_64` | FIXED | manylinux_2_28 tag, `twine check --strict` |
| G-1499 only Ubuntu 24.04 exercised | FIXED | install test on AlmaLinux 8, Debian 12, Debian 13 |
| G-0478, G-0496, G-0497, G-0240 hard-coded linux-x64 / `.so` in the installers | FIXED | `test_installers_pick_the_machine_s_files` (the arm64/macOS side of these gaps is OUT) |
| G-0413, G-0738 plugin only in the image's Python / tox envs | FIXED (docs) | docs/INSTALL.md: `pip install wheels/fenvix-*.whl` into any environment |
| G-0730 README install section | FIXED | README "Install" |
| G-0766, G-0767, G-1490, G-1884 install/requirements/containers/uninstall docs | FIXED | docs/INSTALL.md |
| G-2212, G-2213 licence file, metadata | FIXED | `LICENSE`, `license-files`, metadata; `twine check --strict` |
| G-2171, G-2173, G-2174, G-2175, G-2176 Node CLI | FIXED | `node/test/platform.test.js` |
| G-2172 npm package fields | OUT | no npm package (founder decision) |
| G-2177, G-2194 state directories dirty the checkout | FIXED | `test_state_directory_keeps_the_checkout_clean`, `platform.test.js` (.detjs) |
| PY-03 ward tests red once ward is installed (caused by the G-2194 fix in the runner driver) | FIXED | `test_runners_ward.py::test_module_and_global_fixture_reads_are_inputs_of_their_users`, `::test_a_suite_run_inside_a_test_is_that_tests_code` |
| PY-01/PY-03 nose2 on 3.14: a new test module invalidates the whole suite | FIXED | `test_runners_nose2.py::test_wrong_reuse[optional_module_appears]` on 3.14, `record::tests::a_runner_start_directory_probes_stay_per_name` |
| PY-01/PY-03 ward on 3.14 (ward itself crashes) | REFUSED (explicit exclusion) | `test_runners_ward_support.py::test_ward_refused_with_one_sentence_where_ward_cannot_run[*]` |
| suite determinism: a followed child's lifetime started at strace's first logged call (tracer latency decided which later tests got its refusal; `test_child_still_running_at_the_end_is_never_cached` on 3.14, `test_clock_rust::test_cache_matches_reference` locally) | FIXED | `follow.Spawn.started` (real clock at the spawn) in `collect_children` and its reference; `test_proofcache_follow.py::test_child_still_running_at_the_end_is_never_cached` expects the deterministic outcome |
| suite determinism: `test_clock_rust::test_wall_derived_and_gettime_match_reference` compared two real CPU-clock readings (clock id -7 is this process's CPU clock on Linux) | FIXED | the test compares negative clock ids by kind, as the named CPU clocks |
| G-0205, G-0242, G-0561 default branch is a Block 2 tip | FIXED (by the founder) | default branch `claude/release-1` (MEASURED via the repository API, 2026-11-20); section 4 |
| G-0522, G-1439 names unregistered | FOUNDER / OUT | PyPI `fenvix` reserved by the founder's pending publisher; npm dropped |
| G-0155, G-0156, G-0157, G-0158, G-0472..G-0477, G-0492..G-0495, G-0415, G-0416, G-0255, G-0526, G-0527, G-0441..G-0443, G-0723, G-1500..G-1506 macOS and Linux arm64 | OUT | founder decision; the Node loader names the supported platform; `detpy_core::host` keeps the loaded-image list of Linux in one place |
| G-0444, G-0528, G-0256, G-0499..G-0508, G-1869, G-2195 Windows / WSL2 | OUT | |
| G-0445, G-0482..G-0487, G-0525 musl / Alpine | OUT / REFUSED | Node loader message; `install.sh` |
| G-0480, G-0490, G-0491 fenvix-skip / fenvix-go / JNI glibc | OUT | Go and JVM out of the go-live scope |
| G-0217 runner bootstrap installs no Node engine | OTHER ROW (runner image) | `fetch.sh` + `FENVIX_ENGINE_URL/SHA256` in `runner/bootstrap.sh` give it the artifact |
| G-0733 stores of another engine version | OTHER ROW (cache) | |
| G-0734, G-1440, G-1441, G-1442 configuration file, runner plugins | OTHER ROW (Node runners) | |
| G-0243 docs site | OTHER ROW (docs repository) | |
| G-0410 Vitest < 1.4 | OTHER ROW (Node runners) | |
| G-0153, G-0154 service containers and the closed network | OTHER ROW (network control) | |
| G-1492, G-1575 ASLR under seccomp | OTHER ROW (Level 0 controls) | documented in docs/INSTALL.md |
| G-1497, G-1498, G-1544 cc / strace at run time | OTHER ROW (cache) | documented in docs/INSTALL.md |
| G-1493, G-1494, G-1495 Go pid, gVisor, Docker-in-Docker | OUT / OTHER ROW | |
| G-1503 replay across operating systems | OUT | |

| PY-01 `detpy repro` on 3.14: the Rust path worded a missing test's error as CPython 3.12/3.13 do (`'missing::x' is not in list`), the reference raises 3.14's (`list.index(x): x not in list`); red on the trunk too (run 44714888645, job 136217550170) | FIXED | `repro_prefix_through` raises the interpreter's own `list.index` error; `test_repro_rust.py::test_prefix_through_missing_target_raises_this_interpreters_list_index_error`, `::test_prefix_through_matches_reference` (MEASURED locally: 3.14 19 passed, 3.13 passed) |

Trunk failure not in these rows: `test_proofcache_follow.py::test_child_own_temporary_files_are_not_inputs` (fixed by
PR #4).

## 4. Per il fondatore (passi da fare a mano)

Il go-live gira solo sulle nostre macchine: niente PyPI, niente npm, niente macOS/arm64.

1. **Artefatto del motore**: ogni run FULL di `claude/release-1` (notturno, o "Run workflow" con depth `full`)
   pubblica una pre-release GitHub
   `engine-<versione>-r<run>.<sha7>` con `fenvix-engine-…-linux-x86_64.tar.gz` e il suo `.sha256`. L'immagine del
   runner deve fissare **URL e sha256** di una precisa release (variabili `FENVIX_ENGINE_URL` e
   `FENVIX_ENGINE_SHA256` di `runner/bootstrap.sh`) e installarla con `release/engine/fetch.sh`, che rifiuta
   qualunque file con checksum diverso. Per aggiornare il motore si cambiano entrambi i valori insieme.
2. **Permessi**: il job `publish-engine` usa il `GITHUB_TOKEN` con `contents: write`; se in Settings → Actions →
   General → "Workflow permissions" è impostato "Read repository contents" il permesso a livello di job basta,
   ma se un'organizzazione lo vieta va consentito lì.
3. **PyPI**: il nome `fenvix` è riservato dal tuo publisher "pending" (progetto `fenvix`, workflow `release.yml`,
   environment `pypi`). Il job di pubblicazione esiste ma è spento (`if: false`); per accenderlo un giorno basta
   cambiare quella riga e creare l'environment `pypi` in Settings → Environments. Nessun token.
4. **Branch di default** (G-0561): fatto da te verso le 13:25 UTC: oggi il default è `claude/release-1`
   (MEASURED: `GET /repos/…` → `default_branch: claude/release-1`, 2026-11-20 ~14:47 UTC). Così il run notturno
   completo (`schedule`) e "Run workflow" funzionano. Consiglio ancora: proteggi il branch (PR obbligatoria con il
   check `release-1` verde) e, se un giorno lo rinomini in `main`, cambia il nome del branch nei trigger di
   `release-1.yml` e nella condizione di `publish-engine`.
5. **Licenza**: `LICENSE` è MIT con titolare "fenvix" (segnaposto): sostituiscilo con il tuo nome o quello della
   società.
