FIX 4 — rows F-09, PY-01, JS-01 are not CHIUSO on trunk f84dde7: 4 defects (D1–D4), each a failing test in `tests/test_review_p1_packages.py` on this branch; JS-01 passes.

# Review R-050: rows F-09, PY-01, JS-01 (Passo 1, packages)

Reviewer session 2026-11-20, branch `claude/review-p1-packages` (based on trunk `claude/release-1` @ f84dde7, the merge of
PR #2). Fixed checklist only. Numbers are MEASURED (command or log) unless marked otherwise.

## 0. Verdict

| row | exam checks (local, trunk build) | verdict |
|---|---|---|
| JS-01 | 15/15 PASS (Node 22, 24, 26) | passes; nothing blocking |
| PY-01 | install PASS ×3; itsdangerous DET2/CACHE2 PASS ×3; attrs CACHE2 PASS ×3; **attrs DET2 FAIL ×3** (D4) | blocked by D4; D1 also open |
| F-09 | install, node-addon, py-det2, py-cache2, node-det2, node-cache2 PASS; **artifact-identity FAIL** (D2); **job-venv FAIL** (D3, plus exam harness H3) | blocked by D2, D3 |

The exam as committed on `claude/exam` (36397ec) cannot pass on this trunk anyway, whatever the engine does: see the
harness findings H1–H3 in section 3. They are exam defects, not engine defects. The coordinator has to get them fixed on `claude/exam` before the
dispatched run (rows=F-09,PY-01,JS-01) can say anything.

## 1. How this was checked

- The tree of f84dde7 equals 7e36c39 (the commit of full run 44804076830) except `sessions/2026-11-20-packages/REPORT.md`
  (`git diff --stat 7e36c39 f84dde7`). I did not read the CI runs (budget rule). Everything below was rebuilt and run
  locally.
- Build exactly as `release-1.yml` job `build`: `maturin build --release --zig --compatibility manylinux_2_28`,
  `cargo zigbuild -p detpy-node --target x86_64-unknown-linux-gnu.2.28`, `release/check_floor.py` (wheel and addon max
  `GLIBC_2.28`), `release/engine/assemble.sh` → `fenvix-engine-0.1.0-rlocal.f84dde7-linux-x86_64.tar.gz`.
- Interpreters: CPython 3.12.13, 3.13.18, 3.14.6, 3.11 (refusal), 3.15.0b4 (D1). Node v22.23.5, v24.22.3, v26.13.1
  (the official tarball, sha256 checked against SHASUMS256.txt).
- Exam legs: `exam/run.py` of `claude/exam` @ 36397ec, one leg per row × version as `exam/legs.json` names them
  (PY-01 × py3.12/3.13/3.14 × node22; JS-01 × py3.13 × node22/24/26; F-09 × py3.13 × node22). The engine was installed
  the way `exam/install.sh` does it (`release/install-image.sh` on the CI `dist/`, i.e. the `engine-linux-x64`
  contents), with one deliberate change: `EXAM_WHEEL` pointed at the real wheel (see H1). The projects were cloned at
  the exam's pinned commits.

## 2. Defects (each a test that FAILS on f84dde7; all fail on 3.12, 3.13 and 3.14: `5 failed`)

### D4 (PY-01, blocking): two `--det` runs of an unchanged checkout verify as divergent when the tests import a pytest-plugin library
Test: `test_d4_two_det_runs_of_an_unchanged_checkout_verify_identical_with_a_plugin_library`.
Why it matters: the exam's own PY-01 project fails DET2 on every in-scope version. `fenvix verify` says
"not reproducible" for runs that are identical. MEASURED: python-attrs/attrs@3dca08ce, 1330 of 1330 tests diverged,
`reasons: {config: 1330}`, fingerprints and outcomes identical, on 3.12, 3.13 and 3.14.
Cause, reproduced in a 2-test project with only `hypothesis` installed:
- Run 1 records the input `bytecode` as `"precompiled; test modules rewritten from source in this run (cold rewrite
  cache: 75)"`. Run 2 records `"precompiled"`. Run 2 against run 3 verifies identical.
- pytest marks every module of a distribution that has a `pytest11` entry point for assertion rewrite (hypothesis ships
  `_hypothesis_pytestplugin`). The G-0168 pre-warm (`plugin.prewarm_rewrite_cache`, `_rewrite_candidates`) walks only
  the project's own `conftest.py` and `python_files`. So the library modules are rewritten cold in the first run of
  every fresh environment, and every rewrite miss counts in `_level0.REWRITE["cold"]`.
- The mechanism comes from 248a6d3 (F-01, G-0168), not from the packages work, but it is on the trunk and it fails
  the PY-01 row.
The test builds a stand-in plugin distribution (entry point plus a library) under `tmp_path`, so it needs neither the
network nor hypothesis.

### D3 (F-09, blocking for exam check F-09.job-venv / G-0413): a job's own venv does not get the engine from the runner image
Test: `test_d3_a_job_venv_gets_the_engine_from_the_runner_image`.
Why it matters: G-0413 (BLOCKS-USE) is assigned to F-09 and the exam expects `fenvix python --det` to work in a job
that makes its own venv. On f84dde7 the image's `$FENVIX_HOME/bin/fenvix` (`release/fenvix`, `#!/usr/bin/env python3`)
runs with the venv's python3 and stops with "fenvix: the Python package fenvix is not installed in …/.venv/bin/python3"
(exit 127). `docs/INSTALL.md` instead tells such jobs to `pip install wheels/fenvix-*.whl` themselves. That is a
design disagreement between the delivery and the exam. It fails loudly, not silently. The coordinator decides which
side moves. Until then the check fails.

### D2 (F-09, blocking for exam check F-09.artifact-identity / G-0251): `fenvix version` does not name the installed artifact
Test: `test_d2_fenvix_version_names_the_installed_artifact`.
Why it matters: every artifact prints `fenvix 0.1.0 (engine: detpy 0.1.0, …)`. The build (`r<run>.<sha7>`) and the
commit are in the tarball's `VERSION` and `VERSION.json`, and `install.sh` copies `VERSION.json` to `PREFIX`, but
`detpy.fenvix.version_lines()` never reads them. So two different artifacts cannot be told apart from the command, and
the exam check (`release_commit[:8]` in `fenvix version`) fails.

### D1 (PY-01): an unsupported newer CPython is let through
Tests: `test_d1_newer_cpython_than_supported_is_refused_by_the_engine`, `…_by_the_installer`.
Why it matters: the supported set is CPython 3.12, 3.13, 3.14. `detpy._support.SUPPORTED`, the installer's own message
("needs CPython 3.12, 3.13 or 3.14") and docs/INSTALL.md ("otherwise: install.sh exits 4 with one sentence") all say so.
But `_support.problem()` and the `install.sh` guard only refuse versions *below* 3.12. MEASURED on CPython 3.15.0b4:
`install.sh` installs (exit 0) and `pytest --det` runs with no warning, on an interpreter nobody tested. The row text
says "below 3.12 refused", so if the founder wants forward compatibility this becomes a NOTE: then the message and the
docs must say so and the tests be dropped.

## 3. Exam harness findings (on `claude/exam`; no tests here because they are not engine code; they block the exam itself)

- **H1 (blocks PY-01 and F-09 entirely).** `exam/install.sh` exports `EXAM_WHEEL=$(ls "$dist"/detpy-*.whl)`. The trunk
  wheel is `fenvix-0.1.0-cp312-abi3-manylinux_2_28_x86_64.whl`, so `EXAM_WHEEL` is empty and `lib.venv` skips the
  engine install. MEASURED (PY-01, py3.13): all four DET2/CACHE2 checks FAIL "not run: engine install into the venv
  failed: EXAM_WHEEL unset". F-09.py-det2/py-cache2 fail the same way. Fix: glob `fenvix-*.whl`.
- **H2 (F-09 checks the wrong artifact).** F-09.install and F-09.artifact-identity use the CI artifact
  `engine-linux-x64` (the raw `dist/`: wheel and addon) and `release/install-image.sh`, which checks no checksum. The
  versioned tarball with its `.sha256` and `VERSION.json` is the artifact `engine-artifact` (or the `engine-…`
  pre-release), and it is installed through `release/engine/fetch.sh` and `install.sh`. As written, artifact-identity
  finds "manifest shipped in the artifact: none" even after D2 is fixed. And no exam check covers the fail-closed
  property of row F-09 (wrong checksum or missing file refuses). Also, "newest release-1 run that has it" can pick a
  later nightly instead of f84dde7's run.
- **H3 (F-09.job-venv cannot pass for any engine).** The job venv gets `-e . pytest` but not itsdangerous's test
  dependency `freezegun` (`projects.py` lists it). Plain pytest in that venv also stops with 2 collection errors
  (MEASURED).
- Minor: PY-01.gaps and JS-01.gaps are in PLAN.md but `gap_map.json` assigns no probe to either row, so no such check
  exists. For JS-01 on simple-statistics, outcomes are compared by exit status and counts only (as PLAN.md allows for
  non-JSON runners).

## 4. Checklist results, item by item

**1. Exam checks: implemented? does the trunk pass?** (local legs; full lines in the logs listed in section 6)

| check | implemented | f84dde7 |
|---|---|---|
| PY-01.install (3.12/3.13/3.14) | yes | PASS ×3 |
| PY-01.det2 itsdangerous / attrs | yes (needs H1 fix) | PASS ×3 / **FAIL ×3 (D4)** |
| PY-01.cache2 itsdangerous / attrs | yes (needs H1 fix) | PASS ×3 (297/297 reused) / PASS ×3 (≥1321 reused, 0 differing) |
| PY-01.gaps | no check (no probe assigned) | n/a |
| JS-01.install (22/24/26) | yes | PASS ×3 |
| JS-01.det2 simple-statistics / ufo | yes | PASS ×3 (277 / 471 identical) |
| JS-01.cache2 simple-statistics / ufo | yes | PASS ×3 (277 / 471 reused) |
| JS-01.gaps | no check | n/a |
| F-09.install | yes, but on the raw dist (H2) | PASS |
| F-09.artifact-identity | yes, but on the raw dist (H2) | **FAIL (D2 + H2)** |
| F-09.job-venv | yes, broken (H3) | **FAIL (D3 + H3)** |
| F-09.node-addon | yes | PASS |
| F-09.py-det2 / py-cache2 | yes (needs H1 fix) | PASS / PASS |
| F-09.node-det2 / node-cache2 | yes | PASS / PASS |

**2. Row definitions.**
- PY-01: 3.12/3.13/3.14 install and run (above). Below 3.12 refused, MEASURED on a real CPython 3.11:
  - `install.sh` exits 4 with "fenvix: needs CPython 3.12, 3.13 or 3.14 (default build); … is cpython 3.11".
  - A copy forced into 3.11 refuses with exit 4 and the one sentence: `pytest --det`, `--det-cache`, `-n 2 --det`,
    `PYTEST_ADDOPTS=--det`, ini `addopts = --det`, `python -m detpy unittest`, `fenvix python`, `fenvix verify`.
  - Plain `pytest` on 3.11 runs unchanged.
  - Versions above 3.14 are let through: D1.
- JS-01: Node 22/24/26 work (above). Node 26's recursive `fs.promises.readdir` link-following is detected by a runtime
  probe (`capture.js` `probePromisesTypedReaddir`), not by version, and defaults to "follows" (the safe side). MEASURED:
  22 and 24 give 2 entries, 26 gives 3.
- F-09: one versioned manylinux_2_28 artifact with a sha256 (reproducible build: two assemblies gave the same digest
  in the delivery's own test). `fetch.sh` is fail-closed. MEASURED with the real tarball:
  - correct sha256: unpacked, exit 0;
  - wrong sha256: "checksum mismatch … (nothing installed)", exit 1, no destination created;
  - empty sha256 or uppercase hex: refused;
  - missing file: "download failed", exit 1.
  `runner/bootstrap.sh` aborts if the pinned fetch fails or the wheel is missing. `fenvix version` prints the version
  (0.1.0) but not the build (D2).

**3. Wrong results.**
- D4 is the one silent-style wrong result: the verifier reports identical runs as divergent.
- I found no wrong outcome in any in-scope run: every DET2/CACHE2 outcome map equalled the plain run.
- No tampered or wrong artifact was accepted by `fetch.sh`.
- No unsupported interpreter below 3.12 got through.
- Tests that cannot fail: none found among the delivery's new or changed tests. I read `test_packaging.py` (refusal,
  fetch, artifact), `test_runners_ward_support.py`, `node/test/platform.test.js`, the r021b Node 26 changes and the
  Django `timezone_pinned` change. Each asserts its precondition or a state it can miss.

**4. Known exclusion.** ward on CPython 3.14 is not counted (`python -m detpy ward` refuses with exit 4 and one
sentence there, by design).

## 5. Notes (non-blocking, recorded)

- `release/engine/install.sh` does not check the files against `VERSION.json`. A tarball unpacked by hand without
  `sha256sum -c` (docs/INSTALL.md says to run it first) and then edited is installed. One with the Node addon removed
  installs and says "installed", and `fenvix node` fails later. Through `fetch.sh` (pinned tarball sha256) this cannot
  happen.
- `runner/bootstrap.sh` (pinned mode) installs only the wheel from the artifact, not the Node shells. `fetch.sh`
  extracts into `$FENVIX_HOME/engine` on top of an older directory of the same name without clearing it.
- Docstring of `detpy/_unsupported_plugin.py` says `DETPY=1` counts as asking for the engine. Nothing reads `DETPY`
  (plain run on 3.12 too), so this is a stale comment, not a hole.
- If an image's Python directory is on `PATH` before `$FENVIX_HOME/bin`, a job venv without the engine picks up the
  image's `fenvix` console script, and `fenvix python` then runs pytest in the image's interpreter rather than the
  job's. Observed locally with that PATH order: collection errors, loud, not silent. On GitHub-hosted runners
  `$GITHUB_PATH` puts `$FENVIX_HOME/bin` first (D3's exit 127 instead).

## 6. Evidence files (local, this container)

Leg results: `<scratchpad>/legs/<ROW>-py<V>-node<N>/out/{summary.txt,result.json,run.log}`. The attrs divergence is
in `legs/PY-01-py3.13-node22/work/logs/0027-PY-01.det2-attrs-verify.log`. These are not committed (scratch). The tests
in `tests/test_review_p1_packages.py` reproduce every defect without them.

## Re-check D1-D3: PASS

Coordinator re-check round, 2026-11-20: PR #9, `claude/packages` @ 3a90d44 (one commit on f84dde7). Only the fixed tests
were re-run (founder rule). D4 is not re-checked here (PR #10, later).

- **Build as CI does it:** maturin manylinux_2_28 wheel from 3a90d44; the addon is unchanged (no `crates/` or `node/`
  change); `assemble.sh` → `fenvix-engine-0.1.0-rlocal.3a90d44-linux-x86_64.tar.gz`. As in the `python` job, the wheel
  was installed into a fresh venv per version with `_core` copied into `python/detpy`.
- **My tests, unchanged (`tests/test_review_p1_packages.py` as committed in 0119874), `-k "d1 or d2 or d3"`:**
  4 passed on CPython 3.12.13, 3.13.18 and 3.14.6 (D1 engine, D1 installer, D2, D3).
- **What the tests guard still holds (MEASURED, real interpreters, the artifact installed via `fetch.sh` + `install.sh`):**
  - D1:
    - `install.sh` exits 4 on a real CPython 3.15.0b4 and on 3.11, with one sentence.
    - A wheel forced into 3.15 refuses `pytest --det` with exit 4: "fenvix is not built or tested for CPython 3.15
      yet (the newest supported is 3.14)".
    - A 3.15 or 3.11 job venv reaching the image's `fenvix` through the new fallback is refused with exit 4, one
      line, no traceback. (A first 3.15 try gave exit 127 because my own forced install and uninstall had left a stray
      `detpy/` directory in that venv; a clean venv gives 4.)
  - D2: `fenvix version` from the installed image prints `artifact fenvix-engine 0.1.0 build rlocal.3a90d44 commit
    3a90d44fe7b4… (linux-x86_64, glibc 2.28+)`.
  - D3, through the real image path (`$FENVIX_HOME/python`, no checkout fallback):
    - Job venvs on 3.12, 3.13 and 3.14 hold itsdangerous with its test dependencies and no engine (`import detpy`
      fails there).
    - `$FENVIX_HOME/bin/fenvix python --det tests` twice: 297 passed each run, `fenvix verify` exit 0; plain pytest
      in the same venv also gives 297 passed.
- **Note (non-blocking):** the D2 `artifact` line reads `$FENVIX_HOME/VERSION.json`, so it names the image's artifact,
  not the build of the wheel actually imported. A job that pip-installs a wheel from another build into its own venv
  still sees the image's build and commit. Both carry version 0.1.0.

## Re-check D4: PASS

Coordinator re-check round, 2026-11-20: PR #10, `claude/p1-python-leaks` @ fdf6029 (contains trunk a996b68). Fix commit
0e5a47a: `plugin._plugin_rewrite_files()` adds the `.py` files of every installed pytest-plugin distribution (a
`pytest11` entry point) to the G-0168 pre-warm. The serial accounting is unchanged: a module still rewritten from
source in the test process remains the run input `bytecode … (cold rewrite cache: N)`. So the fix warms the modules;
it does not hide the input. (fdf6029 also zeroes the xdist controller's own cold count, under `-n`. That is P1
finding 11, outside D4, and was not reviewed here.)

- **Build:** wheel built from fdf6029 as CI builds it (maturin, manylinux_2_28). Fresh venv per version; `_core` copied
  into `python/detpy`, as in the `python` job.
- **My test, unchanged (`test_d4_…`, as committed in 0119874):** 1 passed on CPython 3.12.13, 3.13.18 and 3.14.6.
- **python-attrs/attrs@3dca08ce, fresh venv per version (PyPI reachable from here):**
  - Setup: `pip install --no-cache-dir -e . pytest hypothesis pytest-xdist` plus the fdf6029 wheel; exam arguments
    (`tests -p no:randomly --ignore=…mypy/pyright/hooks`).
  - `pytest --det` twice, then `fenvix verify`. Traces and logs were written outside the checkout.
  - Results:

    | | run 1 `bytecode` | `fenvix verify` | engine runs 1 and 2 = plain |
    |---|---|---|---|
    | 3.12 | `precompiled` | exit 0, IDENTICAL, 1330/1330 | 2 failed, 1322 passed, 6 skipped, 1 xfailed |
    | 3.13 | `precompiled` | exit 0, IDENTICAL, 1330/1330 | 2 failed, 1325 passed, 3 skipped, 1 xfailed |
    | 3.14 | `precompiled` | exit 0, IDENTICAL, 1330/1330 | 2 failed, 1321 passed, 3 skipped, 5 xfailed |

    The 2 failures are attrs' own; plain pytest in the same venv gives them too. Outcomes were compared by counts,
    not per test.
  - A first try had written the traces into the checkout root between the two runs. There 1 of 1330 tests diverged on
    `os.listdir(".")` (26 vs 28 entries) with run inputs identical: a real input change made by my command, correctly
    reported, not an engine defect.

**Result after the re-check rounds:** D1, D2 and D3 are fixed on PR #9 (3a90d44) and D4 on PR #10 (fdf6029), each
re-checked against its own branch head. Neither PR is merged into the trunk yet, so the trunk itself was not
re-checked.

## Re-check #3 #4 #11: PASS

Coordinator re-check round, 2026-11-20. These are findings 3, 4 and 11 of the earlier review
`claude/review-p1-verifier`, all fixed by PR #10, re-checked on `claude/p1-python-leaks` @ fdf6029 with the same build
and venvs as the D4 re-check.

- **The tests are the originals:**
  - The three tests in `tests/test_review_p1_python_leaks.py` on fdf6029 are byte-identical to those in
    `claude/review-p1-verifier:tests/test_review_p1_verifier.py` (checked function by function with `ast`). The shared
    helpers differ only in the module docstring.
  - Finding 11's test, `tests/test_verifier_truth.py::test_parallel_trace_records_inputs`, is unchanged between
    a996b68 and fdf6029.
- **Run (`-p no:randomly`; pytest-xdist installed for #11):** 4 passed on CPython 3.12.13, 3.13.18 and 3.14.6.
  - #3: `test_f03_a_test_that_uses_threads_is_never_reported_identical`
  - #3, #4: `test_f03_no_test_whose_value_differs_is_reported_identical`
  - #4: `test_f01_det_result_does_not_depend_on_the_pid_or_os_entropy`
  - #11: `test_parallel_trace_records_inputs`
- **The fixes do not hide inputs (MEASURED on 3.13):**
  - **#4, os control:** the trace header records the os control as a run input: `os: virtual pid; temporary directory
    fenvix-det (fresh); /dev/urandom, /dev/random, /proc/uptime virtual; other files read, devices and OS
    measurements recorded`. Under `--det` the PID is 10000 and `tempfile.gettempdir()` is `/tmp/fenvix-det` in every
    run. A file outside the project read by a test is still an observed input: unchanged A/A gives IDENTICAL (exit 0);
    changed A→B gives DIVERGENT (exit 1), "fs.read @ tests/test_a.py:4 returned different values" naming the file.
  - **#3, threads alive before a test:** the re-run test itself asserts that a test using `_thread` threads or a pool
    started at import is never reported identical. It passes, so these tests are marked rather than called identical.
  - **#11, xdist controller cold count zeroed:** a cold rewrite in the workers is still recorded. Setup: a module
    registered with `pytest.register_assert_rewrite` outside the root, so neither the project walk nor the
    plugin-distribution pre-warm reaches it. `-n 2 --det` run 1 records `bytecode: precompiled; test modules rewritten
    from source in this run (cold rewrite cache: 1)`, run 2 `precompiled`, and `fenvix verify` says DIVERGENT 4 of 4
    (exit 1). Only the controller's own rewrites (xdist's modules; the controller runs no test) left the input.
- **Note (non-blocking, not re-checked further):** the "fresh" temporary directory has the fixed name `/tmp/fenvix-det`.
  Whether two `--det` runs at the same time on one machine (two jobs on one runner) can share it was not examined here.

## Re-check Node #1 #2 #6 #7: FAIL (4/4 tests pass; #1 is not fully fixed: N1)

Coordinator re-check round, 2026-11-21. These are Node findings 1, 2, 6 and 7 of `claude/review-p1-verifier`,
fixed by PR #8, re-checked on `claude/node` @ 888b2ca5 (contains trunk a996b68).

- **Build:** the napi addon (`cargo zigbuild … x86_64-unknown-linux-gnu.2.28`) and the wheel were built from 888b2ca5
  (both `crates/` and `python/detpy/fenvix_js.py` changed). Then, as in the CI `node` job: the addon copied to
  `node/`, the wheel in a CPython 3.13 venv first on `PATH`, and `npm ci` in `node/`.
- **The tests:** `node/test/review-p1-verifier.test.js` on 888b2ca5 is byte-identical to the reviewer's file.
- **Run** (`node --test --test-concurrency=1 test/review-p1-verifier.test.js`): 4 pass, 0 fail, 0 skipped on Node
  v22.23.5, v24.22.3 and v26.13.1.
  - #1: "F-03: no test whose observed value differs …"
  - #2: "F-03: a concurrent fs.readFile completion order …"
  - #7: "F-01: --det pins the time zone and the locale …"
  - #6: "F-02: fenvix repro works for a Vitest, Jest and node:test test"
- **Does a differing Node run show as DIVERGENT? Not in every case.** Probes under `node-test --det`, two runs each:
  - A worker returning `Math.random()` is diverged (reason `thread` on 22, `other` on 24/26); the CLI verdict is
    DIVERGENT, exit 1.
  - An environment variable `R050_PROBE=1` then `2` gives "run inputs: DIFFER", DIVERGENT, exit 1.
  - **A file outside the project read as "A" then "B": `fenvix verify` exit 0, "IDENTICAL: all 1 tests ran with the
    same inputs and observed the same events", on Node 22, 24 and 26.** Finding #1 named exactly this source ("`file`:
    a file outside the project, `A` vs `B`"), but its test has no such probe, so the test passes while the false
    IDENTICAL remains. Python records the same read and reports the same pair DIVERGENT (re-check #3 #4 #11 above).
- **N1 (blocking for finding #1, row F-03 Node; wrong result, a false "same"):**
  `node/test/review-r050-node-recheck.test.js`, committed on this branch. It FAILS on 888b2ca5 on Node 22, 24 and 26:
  "verify reported the test identical although it read "A" and then "B"". Its precondition (the two runs really read
  A and then B) is asserted. Fixed when the read of a file outside the project is an observed event (or the test is
  marked), as on the Python side.
- **Not measured:** #2's test asserts only when the observed completion orders differ (`if (orders.size > 1)`). I did
  not record whether the orders still differ on 888b2ca5, i.e. whether it passed by control or by detection.

## Re-check Node #1 (N1): PASS

Coordinator re-check round, 2026-11-21. N1 is fixed on `claude/node` @ 825aef2c (descends from 888b2ca5; fix commit
67f2eba, `node/src/outside.js`). Reads of files outside the project are recorded as the event `fs.read.outside` (path
and content digest).

- **Build:** no `crates/` change since 888b2ca5, so the 888b2ca5 napi addon is current.
  - `verify` is computed in the Rust core; the CLI checks used the 888b2ca5 wheel.
  - The Python files changed since then (the PR #10 merge) do not touch `verify`.
  - `node/package*.json` are unchanged, so the same `node_modules` was used.
- **The tests are unchanged:**
  - `node/test/review-r050-node-recheck.test.js` on 825aef2c is byte-identical to the N1 test on this branch (0411332).
  - `node/test/review-p1-verifier.test.js` is byte-identical to the reviewer's file.
- **Run** (`node --test --test-concurrency=1`, N1 and "F-03: no test whose observed value differs …", i.e. finding #1's
  test): 2 pass, 0 fail, 0 skipped on Node v22.23.5, v24.22.3 and v26.13.1.
- **Differing vs identical runs (CLI `fenvix verify`, `node-test --det`, two runs, a file outside the project):**

  | | contents A then B | contents A then A |
  |---|---|---|
  | Node 22 | DIVERGENT 1 of 1, exit 1 | IDENTICAL, exit 0 |
  | Node 24 | DIVERGENT 1 of 1, exit 1 | IDENTICAL, exit 0 |
  | Node 26 | DIVERGENT 1 of 1, exit 1 | IDENTICAL, exit 0 |

  Run inputs are "identical in every run" in both cases. The difference is named as a test event, not hidden in the
  run header, and unchanged files do not cause false divergence.

## Re-check PR #5: FAIL (its 13 regression cases pass; P2: a real failure is reported passed under --det-cache)

Coordinator re-check round, 2026-11-21. PR #5 is `claude/py-cache` @ 2a7f0d1e (contains trunk cec096c). The wheel was
built from 2a7f0d1e (its `crates/detpy-py` changed). A fresh venv per version held pytest, pytest-xdist and the wheel,
with `_core` copied into `python/detpy` as in the CI `python` job; strace was present.

- **The fixes' regression tests** (named in `sessions/2026-11-20-py-cache/REPORT.md`, all in `tests/test_py_cache.py`):
  13 passed, 0 skipped, on CPython 3.12.13, 3.13.18 and 3.14.6.
  - PYTHONPATH outside the root: `test_g0164_module_outside_the_root_in_a_files_child_is_an_input` [default,
    default-n2, fenvix-python].
  - Import-time side effect: `test_import_time_code_of_another_test_module_is_an_input` [in-process, default,
    default-n2].
  - Order-dependent pair and `--det-isolate` defaults: `test_order_dependent_pair_has_the_serial_verdict` [-n 2, -n 4,
    --det-isolate, --det-cache -n 2].
  - Placement replay: `test_a_failure_only_the_per_file_isolation_causes_is_reported_not_the_result`.
  - Custom reporter: `test_g0412_cache_summary_is_written_when_a_project_reporter_swallows_it` [project, none].
- **Do the fixes hide nothing?**
  - **Outside-root module and import-time effect:** the tests themselves change the module or effect after the cache
    is warm, and assert the hit is not reused (and that the import-time case fails like a plain run). Both pass, so a
    change still invalidates.
  - **Placement replay with a real failure everywhere (P1, guard):** a test that fails in its child and in one process
    after the earlier files stays failed, exit 1, no finding, on both runs. PASS on 3.12, 3.13 and 3.14.
  - **P2, a real failure hidden (blocking; wrong result):** an earlier test file changes shared state, so the user's
    normal run fails a later file's test.
    - Plain `pytest` and `pytest --det` both report `1 failed, 1 passed`.
    - `pytest --det --det-cache=DIR` and `fenvix python --det --det-cache=DIR` on a fresh cache, with the real defaults
      (no `DETPY_CACHE_IN_PROCESS`), report "detpy --det-isolate: 2 tests in forked children … 0 children failed",
      `2 passed`, exit 0, and no placement finding.
    - The same on 3.12, 3.13 and 3.14 (MEASURED).
    - Cause: PR #5 makes "one child per test file" the default under `--det-cache` (1b6179d). The placement replay
      (b23026c) replays only tests that *fail* in their child; a test that *passes* only because its file was
      isolated from an earlier polluter is reported as the result.
    - The trunk code (fdf6029 build) reports the failure for the same command (`1 failed, 1 passed`). So this
      regression comes from PR #5.
  - Test: `tests/test_review_r050_pycache.py::test_p2_a_failure_an_earlier_file_causes_in_the_normal_run_is_not_reported_passed`
    on this branch. It FAILS on 2a7f0d1e (3.12, 3.13, 3.14) and passes on fdf6029. It asserts its preconditions
    (plain and `--det` fail the victim). It passes once the victim is reported failed, or reported with a placement
    finding.
