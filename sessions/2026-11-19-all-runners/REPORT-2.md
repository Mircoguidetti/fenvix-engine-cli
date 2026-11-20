PARTIAL

# All runners, round 2: the runner drivers on the Rust engine, R-032 and R-032b fixes, Node policy in Rust — report

Branch `claude/all-runners-2` (fenvix-engine-cli). Final engine: code **ed66b960**, walked at head **db0c8c56** (the same code plus run configuration). Started from `claude/parallel-proof-3` 74721a4. Merged: `claude/parallel-proof-3` 3471d45, 72100d3 (its R-032b F1-F3 engine fix c5f0e70 and `--det-isolate`), 19ba798 (F2-mtime, F3 for repository callers, temporary roots) and 0f45362 (time helpers); `claude/node-cache-proof` 8cd01e6; the R-032b tests of `claude/review-r032b`. Labels: **MEASURED** (Actions run id, raw file or local command), **ESTIMATED**, **DECLARED**, **UNKNOWN**. Every walk number is regenerated from the committed raw files by `sessions/2026-11-19-all-runners/aggregate2.py` (this report by `make_report2.py`; gate numbers from `tracks/all-runners-2/gates/summary.json` and the outputs next to it).

## Answer

* **PARTIAL only because a walk on the final engine had not landed when the round closed** (coordinator's scope decision: the runner work continues on `claude/runners-compat`, no new walks): ink (Actions runs 44692179684, 44692179670, 44692179449, 44692179649; no shard failed). Everything else is done: every gate passes and every landed transition has 0 wrong reuses.
* **Final engine (code ed66b960, head db0c8c56): 0 wrong reuses in 134,211 tests verified** (Python 30,968, Node 103,243; 0 mismatches before recheck; MEASURED, `aggregate2.py --set final`). Counted per TEST, never per file entry (R-032 F8), and re-derived test by test from the committed pairs `[id, reused outcome, fresh outcome]` (R-032b F7d).
* **What "fresh" means** (R-032b F7e): Python, run B = the runner under `--det` without cache on the same commit; Node, a separate run `detjs <runner> --det` without cache. Both are the engine under Level 0 without the cache, **not** the plain runner. The Node walks also keep the engine's own `--det-cache-verify` sample.
* Earlier, separate measurements (first set, engine **7510773**, before the parallel-proof-3 quarantine merge; runs cancelled after the landed shards were kept): 92,016 tests verified (Python 29,468, Node 62,548), 0 wrong (MEASURED, `aggregate2.py --set first`). They do not cover the final tree.
* Earlier, separate measurements (second set, engine **0f969116**, R-032b F4-F6 fixed, before the parallel-proof-3 F1-F3 engine fix; runs cancelled when that fix landed, landed shards kept): 92,654 tests verified (Python 30,313, Node 62,341), 0 wrong (MEASURED, `aggregate2.py --set second`). They do not cover the final tree.
* **Deno** on Actions is **2.9.8** (the raw files' `runtime`, the workflow's DENO_VERSION; MEASURED), locally 2.9.6 (2.9.8 is not on npm here). Bun 1.4.4 both.
* **One implementation.** The Python runner drivers (`python/detpy/runners/`) run on `claude/parallel-proof-3`'s Rust capture through one runner-neutral session (`_proof.py`, `_level0.py`) shared with the pytest plugin; `_statcap.py`'s Python interception is not on this branch. The Node session policy is Rust (`detpy_core::node_session`), checked equal to the JavaScript it replaced.

## Gates (final tree)

| gate | result | file |
|---|---|---|
| Python `pytest tests -p no:randomly` serial (MEASURED local) | **1098 passed, 52 skipped, 0 failed** (1 deselected: test_review_r017 `test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does`, pre-existing, a recorded results file lacks an entry; pytest-benchmark and pytest-django not installed) | gates/pytest-full.txt |
| `cargo test --release --workspace` (MEASURED local) | **138 passed, 0 failed** | gates/cargo-test.txt |
| Node `node --test test/*.test.js` (MEASURED local; Node 22, Bun 1.4.4, Deno 2.9.6) | **682 tests, 681 passed, 1 skipped, 0 failed** | gates/node-suite-summary.txt |
| Bun/Deno runner + R-032 + R-032b + F6/F7 files on Actions (Bun 1.4.4, **Deno 2.9.8**; MEASURED, run 44692179649 (job 136140705108)) | **151 passed, 0 failed** | job log |
| R-032b Python, every runner (tests/review_r032b, MEASURED local) | **20 passed, 0 failed** | gates/r032b-python.txt (also in pytest-full.txt) |

## R-032 findings

| # | finding | fix on this branch | test (unchanged unless noted) | result (MEASURED local) |
|---|---|---|---|---|
| F1 | namespace package gains `__init__.py` | parallel-proof-3's `CaptureCore.lookup` / `proof::import_probe` (Rust); lookups keyed per (directory, name) `j:` | tests/review_r032 `test_p2_namespace_package_gains_init`, `test_x_pytest_plugin[namespace_init]` | pass |
| F2 | zipimport member changes | parallel-proof-3's capture (archive read kept) | `test_p3_zipimport_member_changes`, `[zipimport]` | pass |
| F3 | `ctypes.CDLL` of a project `.so` | `ctypes.dlopen` audit arm (Rust) | `test_p4_ctypes_dlopen`, `[ctypes_dlopen]` | pass |
| F4 | memoised answers across tests | carried-set rule (record.rs); runner framework modules are infrastructure in it (`Plan::infra_modules`), `unittest.mock` is not | `test_p5_*`, `test_p6_*`, `x_nose2[lru_prefix]`, `[lru_prefix, module_dict_prefix]` | pass |
| F5 | `.pth` file appears | `runtime_with_paths` (Rust) used by every runner (`ProofSession.open`) | `test_p11_pth_file_appears` | pass |
| F6 | nested `package.json` appears (Node) | node-cache-proof de10518 merged | review-r032.test.js N3, review-r032-runners-b.test.js N3 (tap: cached agrees with fresh), all-runners-2-f6f7.test.js (Bun, Deno) | pass, every Node runner |
| F7 | WebCrypto / ECDH keygen not entropy | node-cache-proof de10518 (`keygen`) merged | review-r032 N8b, B9, D7; all-runners-2-f6f7.test.js under tap, AVA, Jasmine, uvu, Bun, Deno | pass, every Node runner |
| F8 | 153,483 counted file entries | counts are per test (aggregate2.py; Node `verified_tests`) | — | this report counts tests only |
| claim 3 | Node session policy duplicated Rust | `detpy_core::node_session`; `proof.js` gathers inputs | node/test/policy-equivalence.test.js: old JS (test-only `legacy-proof-policy.js`) vs Rust on real node --test / Mocha sessions and 500 seeded inputs | 5/5 pass |

## R-032b findings

| # | finding | fix | test | result |
|---|---|---|---|---|
| F1 | state left by an earlier test with no static-import edge (leaked `mock.patch('consts.V')`, `importlib`/`__import__` + setattr, `builtins`, `os.environ`) | parallel-proof-3 c5f0e70 (merged): a repository file whose text reaches modules by name is connected to the library node; a context reaching it is carried into every later test of its process, a test reaching it carries every earlier context. Combined here with the runner infrastructure list (`reference_closure_with(.., dynamic, infra)`) | tests/review_r032b W1 (unittest, nose2, pytest plugin), W2, W3, W4, W12 (zope), W13 (Django), W14 (ward), W15 (xdist loadgroup/loadfile); tests/test_r032b_engine.py | pass (MEASURED local) |
| F2 | `os.DirEntry.stat()` (scandir) size unkeyed; then (coordinator) time reads | parallel-proof-3 c5f0e70 / 6cfae24 / 97e61ac / 89971a3 (merged). On this branch: `os.stat`, `os.lstat`, `os.access`, `os.readlink` key the path's metadata (`q`/`Q`: size, mode, kind; the `_statcap.py` probe set); user code's `os.scandir` entries are wrapped (`stat()` like `os.stat`, `is_file`/`is_dir`/`is_symlink` kinds); **one rule for times, as parallel-proof-3**: a time read by user code (a stat result's `st_mtime`/`st_ctime`/`st_atime`, indices 7-9, unpacking; `os.path.getmtime`/`getctime`/`getatime`) refuses the test (`mtime`). detpy's own stats never count (a detpy frame stops the caller walk: found by this port, the reference flagged its own reads) | W5, W6 (fstat, held); test_r032b_engine W5b, W6c, W6d, W6e and the detpy-frame test | pass |
| F3 | libc called through ctypes unobserved | parallel-proof-3 c5f0e70 (merged): a C library from outside the repository (or `CDLL(None)`) loaded by user code flags `cdll`: not cached | W7 | pass |
| F4 | `module.findPackageJSON` absent probes unkeyed (Node ≥ 22.14) | capture.js wraps `findPackageJSON`: every probed `package.json` is keyed (absent ones too), a non-path specifier flags `runtime-api` | review-r032b E3 (node --test, Mocha, Deno) | pass (local; Deno 2.9.8 on Actions) |
| F5 | Deno `Temporal.Now` real clock | capture.js wraps `Temporal.Now.*` (not `timeZoneId`) as `clock-real` in any runtime that has it. **Bun checked**: Bun 1.4.4 has `Temporal` (MEASURED), same wrap; new test all-runners-2-f6f7 "R-032b F5 Temporal.Now" fails with the wrap removed (MEASURED) and passes with it | review-r032b D4; all-runners-2-f6f7 (Bun) | pass |
| F6 | Bun `Worker` reads a file | the global `Worker` flags `worker`, as `worker_threads` does | review-r032b B2 | pass |
| F7 | report accuracy | this report: regenerated at the final head; each walk set states its engine (7510773, 0f969116, db0c8c56); Deno 2.9.8 named; per-test fresh outcomes committed (`verify.pairs`, `compare.pairs`) and re-derived; "fresh" = `--det` without cache | `aggregate2.py` re-derivation column | done |
| nits | legacy-proof-policy.js header; object details | header states its `envDep` change and the two inputs the policies differ on; Rust writes object details inside array details as JavaScript does | policy-equivalence 5/5 | done |

## `_statcap.py` probes, against the Rust capture

| probe (`_statcap.py`) | on parallel-proof-3 | on this branch |
|---|---|---|
| `os.stat` metadata (size, mtime, mode) | size (`z:`); a time read refuses | **ported into Rust**: `stat_check(meta=True)` → `proof::probe_now` under probe keys (mode `q`); a time read by user code refuses (as parallel-proof-3) |
| `os.lstat`, `os.readlink` (link target) | lstat kind | **ported**: mode `Q` (target in the digest); `readlink` wrapped |
| `os.access` | kind | **ported**: metadata (mode bits) |
| `os.scandir` entries | `stat()` size, kind checks (c5f0e70) | `stat()` metadata (`q`/`Q`), kind checks |
| `exists` / `isfile` / `isdir` / `islink` / `lexists` | kind | kind (`s:` / `l:`), through the unwrapped stat |
| `find_spec` misses | `CaptureCore.lookup` | same; keyed per name (`j:`), compacted to `i:` (`compact_lookups`) |
| `rmtree` dir-fd writes, in-tree `*.egg-info` | — / counted as a distribution | all-runners' rules kept (`under_dir_fd`, `identity.rs`) |

## Python runners

### `unittest`

| support | control tests | adversarial tests | walks (MEASURED, final set, run 44692179684) | not covered |
|---|---|---|---|---|
| det + skip; unit = the `TestCase` class; carried-set rule with unittest's loader/loop as infrastructure | tests/test_runners_unittest.py (in the full suite: 0 failed) | shared cases of tests/runners_cases.py (`sqlite_real_clock` expects reuse: SQLite's clock is virtual on this engine) + runner cases; R-032 P1-P11 (tests/review_r032); R-032b W1-W11 (tests/review_r032b) | unittest-jc: 20 transitions, reuse by tests 0% / 10%, by time 0% / 9%, **2901** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>unittest-icecream: 20 transitions, reuse by tests 0% / 10%, by time 0% / 10%, **98** tests verified against a fresh run, 0 mismatches, **0 wrong** | import-time side effects of a module on another module's tests (as under pytest) |

### Django

| support | control tests | adversarial tests | walks (MEASURED, final set, run 44692179684) | not covered |
|---|---|---|---|---|
| det + skip; DiscoverRunner groups; `--parallel` 1 under --det; cached template loader re-read (`_django.py`) | tests/test_runners_django.py, tests/test_django_pytest_cache.py (in the full suite: 0 failed) | shared cases + settings, migration, JSON fixture, template through the cached loader; R-032b W13 | django-debug-toolbar: 20 transitions, reuse by tests 34% / 26%, by time 22% / 17%, **1939** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>django-healthchecks: 20 transitions, reuse by tests 11% / 15%, by time 15% / 16%, **4804** tests verified against a fresh run, 0 mismatches, **0 wrong** | every test depends on the whole environment (wsgiref at import); pytest-django not installed locally (its test skips) |

### nose2

| support | control tests | adversarial tests | walks (MEASURED, final set, run 44692179684) | not covered |
|---|---|---|---|---|
| det + skip | tests/test_runners_nose2.py (in the full suite: 0 failed) | shared + config file, plugin change, mp refused; R-032 x_nose2; R-032b W1 | nose2-nose2: 20 transitions, reuse by tests 27% / 15%, by time 2% / 1%, **1018** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>nose2-howdoi: 120 transitions, reuse by tests 0% / 0%, by time 0% / 0%, **0** tests verified against a fresh run, 0 mismatches, **0 wrong** | `layers`, `mp` plugins refused; howdoi's 2021 commits (shard 0) do not run on Python 3.13 (its one test errors at every commit) |

### `python -m doctest`

| support | control tests | adversarial tests | walks (MEASURED, final set, run 44692179684) | not covered |
|---|---|---|---|---|
| det + skip (one test per docstring / text file) | tests/test_runners_doctest.py (in the full suite: 0 failed) | shared + text file, docstring, option change; R-032b W11 | doctest-autopep8: 120 transitions, reuse by tests 100% / 57%, by time 100% / 57%, **68** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>doctest-nameparser: 200 transitions, reuse by tests 0% / 31%, by time 0% / 31%, **62** tests verified against a fresh run, 0 mismatches, **0 wrong** | — |

### zope.testrunner

| support | control tests | adversarial tests | walks (MEASURED, final set, run 44692179684) | not covered |
|---|---|---|---|---|
| det + skip; layers as fixture contexts; -j 1 | tests/test_runners_zope.py (in the full suite: 0 failed) | shared + layer set-up read, `test_suite` reads, -j forced; R-032b W12 | zope-datetime: 20 transitions, reuse by tests 0% / 10%, by time 0% / 10%, **106** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>zope-irclog2html: 20 transitions, reuse by tests 0% / 14%, by time 0% / 13%, **252** tests verified against a fresh run, 0 mismatches, **0 wrong** | layers resumed in a subprocess (run, never reused); a reuse withdrawn at its turn under a layer that was not set up runs without it (a false failure, never a wrong pass) |

### ward

| support | control tests | adversarial tests | walks (MEASURED, final set, run 44692179684) | not covered |
|---|---|---|---|---|
| det + skip; rich Live auto-refresh off under --det (its timer moved the virtual clock: MEASURED 5.75 s vs 6.0 s after sleep(3)) | tests/test_runners_ward.py (in the full suite: 0 failed) | shared + module/global fixture reads; R-032b W14 | ward-ward: 3 transitions, reuse by tests 0% / 0%, by time 0% / 0%, **0** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>ward-thoughtspot-tml: 20 transitions, reuse by tests 0% / 0%, by time 0% / 0%, **0** tests verified against a fresh run, 0 mismatches, **0 wrong** | **no reuse across commits**: ward's CLI probes `pyproject.toml` at start-up (`click.Path`), a metadata probe (its mtime changes at every checkout): 0 reuses, sound, coarse |

### Hypothesis (every runner + pytest)

| support | control tests | adversarial tests | walks (MEASURED, final set, run 44692179684) | not covered |
|---|---|---|---|---|
| seed from the test id, no example database / storage / local constants; GC-time accounting off under --det (its gc callback read the clock at collection time: MEASURED different fingerprints alone vs after another test) | test_hypothesis_is_seeded_per_test_and_has_no_database (unittest) (in the full suite: 0 failed) | — | hypothesis-attrs: 20 transitions, reuse by tests 90% / 70%, by time 99% / 75%, **19720** tests verified against a fresh run, 0 mismatches, **0 wrong** | example database off under --det (saved failures not replayed) |

## Node/JS/TS runners

Shared Node tests (every runner): the cache/r021/r021b/controls suites, R-032 files, R-032b files, all-runners-2-f6f7, policy-equivalence: all in the Node gate above (0 failed, MEASURED local).

### `node --test`

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | test/runner-node-test.test.js, runner-mocha.test.js; review-r032b E1-E3 | commander: 30 transitions, reuse by tests 98% / 59%, **20623** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 20623 tests, 0 differ)<br>simple-statistics: 30 transitions, reuse by tests 0% / 23%, **2632** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 2632 tests, 0 differ) | — |

### Mocha

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | (with node --test above) | dependency-cruiser: 30 transitions, reuse by tests 64% / 44%, **26004** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 26004 tests, 0 differ)<br>yargs: 30 transitions, reuse by tests 29% / 29%, **7207** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 7207 tests, 0 differ) | — |

### tap

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | test/runner-tap.test.js | tap-minimatch: 25 transitions, reuse by tests 0% / 20%, **670** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 670 tests, 0 differ)<br>tap-dotenv: 25 transitions, reuse by tests 0% / 21%, **698** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 698 tests, 0 differ) | — |

### AVA

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | test/runner-ava.test.js | ava-globby: 25 transitions, reuse by tests 0% / 4%, **227** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 227 tests, 0 differ)<br>ava-shelljs: 25 transitions, reuse by tests 0% / 3%, **452** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 452 tests, 0 differ) | — |

### Jasmine

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | test/runner-jasmine.test.js | jasmine-cordova-android: 25 transitions, reuse by tests 82% / 66%, **5500** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 5500 tests, 0 differ)<br>jasmine-xregexp: 20 transitions, reuse by tests 0% / 25%, **2101** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 2101 tests, 0 differ) | — |

### uvu

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | test/runner-uvu.test.js | uvu-autoprefixer: 25 transitions, reuse by tests 24% / 26%, **1695** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 1695 tests, 0 differ)<br>uvu-browserslist: 25 transitions, reuse by tests 1% / 13%, **1084** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 1084 tests, 0 differ) | — |

### `bun test`

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | test/runner-bun.test.js; review-r032b B1-B9; all-runners-2-f6f7 (F6, F7, Temporal.Now) | wouter: 20 transitions, reuse by tests 0% / 0%, **0** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 0 tests, 0 differ)<br>json-schema-faker: 20 transitions, reuse by tests 2% / 10%, **1180** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 1180 tests, 0 differ) | wouter: every file reads `performance.timeOrigin` (flag clock-real): 0 cacheable, sound, coarse |

### `deno test`

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | test/runner-deno.test.js; review-r032b D1-D7 | std: 20 transitions, reuse by tests 77% / 63%, **20666** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 20666 tests, 0 differ)<br>oak: 20 transitions, reuse by tests 33% / 37%, **1164** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 1164 tests, 0 differ) | the capture's load hook is off under Deno (it changed Deno's CommonJS detection; MEASURED): Deno's graph comes from `deno info` |

### TS loaders (tsx, ts-node)

| support | tests | walks (MEASURED, final set, runs 44692179670, 44692179449, 44692179649) | not covered |
|---|---|---|---|
| det + skip | through the runners above | ink: 15 transitions, reuse by tests 25% / 28%, **7756** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 7756 tests, 0 differ), PARTIAL (1 of 2 shards finished)<br>hexo: 30 transitions, reuse by tests 9% / 9%, **3584** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 3584 tests, 0 differ) | — |

## Reuse share, final engine vs the second set (0f969116, before the R-032b F1-F3 engine rules)

Median / mean share of tests reused per transition (MEASURED, aggregate2.py). The final engine refuses more: a context that reaches a library or a by-name marker is carried into every later test of its process (F1), a C library called through ctypes and a time read refuse (F3, F2). Where the second set has no row, its run was cancelled before that walk landed. The F1-F3 rules are Python's: the Node capture did not change between the two sets, and the Node rows differ only where the second set has fewer shards (yargs: 1 of 2).

| repository | second set | final |
|---|---|---|
| django-debug-toolbar | 100% / 75% | 34% / 26% |
| django-healthchecks | — | 11% / 15% |
| doctest-autopep8 | 100% / 57% | 100% / 57% |
| doctest-nameparser | 0% / 31% | 0% / 31% |
| hypothesis-attrs | 90% / 70% | 90% / 70% |
| nose2-howdoi | 0% / 0% | 0% / 0% |
| nose2-nose2 | 27% / 15% | 27% / 15% |
| unittest-icecream | 0% / 10% | 0% / 10% |
| unittest-jc | 0% / 10% | 0% / 10% |
| ward-thoughtspot-tml | 0% / 0% | 0% / 0% |
| ward-ward | 0% / 0% | 0% / 0% |
| zope-datetime | 0% / 10% | 0% / 10% |
| zope-irclog2html | 0% / 35% | 0% / 14% |
| commander | 97% / 57% | 98% / 59% |
| dependency-cruiser | 63% / 39% | 64% / 44% |
| hexo | — | 9% / 9% |
| ink | — | 25% / 28% |
| simple-statistics | 0% / 23% | 0% / 23% |
| yargs | 3% / 27% | 29% / 29% |
| ava-globby | — | 0% / 4% |
| ava-shelljs | 0% / 2% | 0% / 3% |
| jasmine-cordova-android | 82% / 66% | 82% / 66% |
| jasmine-xregexp | 0% / 25% | 0% / 25% |
| tap-dotenv | 0% / 21% | 0% / 21% |
| tap-minimatch | 0% / 20% | 0% / 20% |
| uvu-autoprefixer | — | 24% / 26% |
| uvu-browserslist | 1% / 13% | 1% / 13% |
| json-schema-faker | 2% / 10% | 2% / 10% |
| oak | 33% / 37% | 33% / 37% |
| std | 77% / 63% | 77% / 63% |
| wouter | 0% / 0% | 0% / 0% |

## All walks, final engine (aggregate2.py --set final)

| lang | repository | runs | transitions | reuse share by tests (median / mean %) | by time (median / mean %) | tests verified (fresh run) | mismatches | wrong (confirmed) | engine verify (tests) |
|---|---|---|---:|---|---|---:|---:|---:|---:|
| python | runner-django-debug-toolbar | ar2-py-4 | 20 | 34 / 26 | 22 / 17 | 1939 | 0 | 0 | —; re-derived from pairs: 1939, 0 differ |
| python | runner-django-healthchecks | ar2-py-4 | 20 | 11 / 15 | 15 / 16 | 4804 | 0 | 0 | —; re-derived from pairs: 4804, 0 differ |
| python | runner-doctest-autopep8 | ar2-py-4 | 120 | 100 / 57 | 100 / 57 | 68 | 0 | 0 | —; re-derived from pairs: 68, 0 differ |
| python | runner-doctest-nameparser | ar2-py-4 | 200 | 0 / 31 | 0 / 31 | 62 | 0 | 0 | —; re-derived from pairs: 62, 0 differ |
| python | runner-hypothesis-attrs | ar2-py-4 | 20 | 90 / 70 | 99 / 75 | 19720 | 0 | 0 | —; re-derived from pairs: 19720, 0 differ |
| python | runner-nose2-howdoi | ar2-py-4 | 120 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | —; re-derived from pairs: 0, 0 differ |
| python | runner-nose2-nose2 | ar2-py-4 | 20 | 27 / 15 | 2 / 1 | 1018 | 0 | 0 | —; re-derived from pairs: 1018, 0 differ |
| python | runner-unittest-icecream | ar2-py-4 | 20 | 0 / 10 | 0 / 10 | 98 | 0 | 0 | —; re-derived from pairs: 98, 0 differ |
| python | runner-unittest-jc | ar2-py-4 | 20 | 0 / 10 | 0 / 9 | 2901 | 0 | 0 | —; re-derived from pairs: 2901, 0 differ |
| python | runner-ward-thoughtspot-tml | ar2-py-4 | 20 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | —; re-derived from pairs: 0, 0 differ |
| python | runner-ward-ward | ar2-py-4 | 3 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | —; re-derived from pairs: 0, 0 differ |
| python | runner-zope-datetime | ar2-py-4 | 20 | 0 / 10 | 0 / 10 | 106 | 0 | 0 | —; re-derived from pairs: 106, 0 differ |
| python | runner-zope-irclog2html | ar2-py-4 | 20 | 0 / 14 | 0 / 13 | 252 | 0 | 0 | —; re-derived from pairs: 252, 0 differ |
| node | commander | ar2-node-a4 | 30 | 98 / 59 | — | 20623 | 0 | 0 | 20623 (0 differ); re-derived from pairs: 20623, 0 differ |
| node | dependency-cruiser | ar2-node-a4 | 30 | 64 / 44 | — | 26004 | 0 | 0 | 26004 (0 differ); re-derived from pairs: 26004, 0 differ |
| node | hexo | ar2-node-a4 | 30 | 9 / 9 | — | 3584 | 0 | 0 | 3584 (0 differ); re-derived from pairs: 3584, 0 differ |
| node | ink | ar2-node-a4 | 15 | 25 / 28 | — | 7756 | 0 | 0 | 7756 (0 differ); re-derived from pairs: 7756, 0 differ |
| node | simple-statistics | ar2-node-a4 | 30 | 0 / 23 | — | 2632 | 0 | 0 | 2632 (0 differ); re-derived from pairs: 2632, 0 differ |
| node | yargs | ar2-node-a4 | 30 | 29 / 29 | — | 7207 | 0 | 0 | 7207 (0 differ); re-derived from pairs: 7207, 0 differ |
| node | ava-globby | ar2-node-b4 | 25 | 0 / 4 | — | 227 | 0 | 0 | 227 (0 differ); re-derived from pairs: 227, 0 differ |
| node | ava-shelljs | ar2-node-b4 | 25 | 0 / 3 | — | 452 | 0 | 0 | 452 (0 differ); re-derived from pairs: 452, 0 differ |
| node | jasmine-cordova-android | ar2-node-b4 | 25 | 82 / 66 | — | 5500 | 0 | 0 | 5500 (0 differ); re-derived from pairs: 5500, 0 differ |
| node | jasmine-xregexp | ar2-node-b4 | 20 | 0 / 25 | — | 2101 | 0 | 0 | 2101 (0 differ); re-derived from pairs: 2101, 0 differ |
| node | tap-dotenv | ar2-node-b4 | 25 | 0 / 21 | — | 698 | 0 | 0 | 698 (0 differ); re-derived from pairs: 698, 0 differ |
| node | tap-minimatch | ar2-node-b4 | 25 | 0 / 20 | — | 670 | 0 | 0 | 670 (0 differ); re-derived from pairs: 670, 0 differ |
| node | uvu-autoprefixer | ar2-node-b4 | 25 | 24 / 26 | — | 1695 | 0 | 0 | 1695 (0 differ); re-derived from pairs: 1695, 0 differ |
| node | uvu-browserslist | ar2-node-b4 | 25 | 1 / 13 | — | 1084 | 0 | 0 | 1084 (0 differ); re-derived from pairs: 1084, 0 differ |
| node | json-schema-faker | ar2-node-c4 | 20 | 2 / 10 | — | 1180 | 0 | 0 | 1180 (0 differ); re-derived from pairs: 1180, 0 differ |
| node | oak | ar2-node-c4 | 20 | 33 / 37 | — | 1164 | 0 | 0 | 1164 (0 differ); re-derived from pairs: 1164, 0 differ |
| node | std | ar2-node-c4 | 20 | 77 / 63 | — | 20666 | 0 | 0 | 20666 (0 differ); re-derived from pairs: 20666, 0 differ |
| node | wouter | ar2-node-c4 | 20 | 0 / 0 | — | 0 | 0 | 0 | 0 (0 differ); re-derived from pairs: 0, 0 differ |

TOTAL python: tests verified 30968, mismatches 0, confirmed wrong 0

TOTAL node: tests verified 103243, mismatches 0, confirmed wrong 0

TOTAL: tests verified 134211, confirmed wrong 0

## Earlier measurement: second set, engine 0f969116 (R-032b F4-F6 fixed, before the parallel-proof-3 F1-F3 engine fix; runs cancelled when that fix landed, landed shards kept)

| lang | repository | runs | transitions | reuse share by tests (median / mean %) | by time (median / mean %) | tests verified (fresh run) | mismatches | wrong (confirmed) | engine verify (tests) |
|---|---|---|---:|---|---|---:|---:|---:|---:|
| python | runner-django-debug-toolbar | ar2-py-2 | 20 | 100 / 75 | 100 / 75 | 5690 | 0 | 0 | —; re-derived from pairs: 5690, 0 differ |
| python | runner-doctest-autopep8 | ar2-py-2 | 120 | 100 / 57 | 100 / 57 | 68 | 0 | 0 | —; re-derived from pairs: 68, 0 differ |
| python | runner-doctest-nameparser | ar2-py-2 | 200 | 0 / 31 | 0 / 31 | 62 | 0 | 0 | —; re-derived from pairs: 62, 0 differ |
| python | runner-hypothesis-attrs | ar2-py-2 | 20 | 90 / 70 | 99 / 75 | 19735 | 0 | 0 | —; re-derived from pairs: 19735, 0 differ |
| python | runner-nose2-howdoi | ar2-py-2 | 120 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | —; re-derived from pairs: 0, 0 differ |
| python | runner-nose2-nose2 | ar2-py-2 | 20 | 27 / 15 | 2 / 1 | 1018 | 0 | 0 | —; re-derived from pairs: 1018, 0 differ |
| python | runner-unittest-icecream | ar2-py-2 | 20 | 0 / 10 | 0 / 10 | 98 | 0 | 0 | —; re-derived from pairs: 98, 0 differ |
| python | runner-unittest-jc | ar2-py-2 | 20 | 0 / 10 | 0 / 9 | 2913 | 0 | 0 | —; re-derived from pairs: 2913, 0 differ |
| python | runner-ward-thoughtspot-tml | ar2-py-2 | 20 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | —; re-derived from pairs: 0, 0 differ |
| python | runner-ward-ward | ar2-py-2 | 3 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | —; re-derived from pairs: 0, 0 differ |
| python | runner-zope-datetime | ar2-py-2 | 20 | 0 / 10 | 0 / 10 | 106 | 0 | 0 | —; re-derived from pairs: 106, 0 differ |
| python | runner-zope-irclog2html | ar2-py-2 | 20 | 0 / 35 | 0 / 35 | 623 | 0 | 0 | —; re-derived from pairs: 623, 0 differ |
| node | commander | ar2-node-a2 | 24 | 97 / 57 | — | 15985 | 0 | 0 | 15985 (0 differ); re-derived from pairs: 15985, 0 differ |
| node | dependency-cruiser | ar2-node-a2 | 10 | 63 / 39 | — | 7571 | 0 | 0 | 7571 (0 differ); re-derived from pairs: 7571, 0 differ |
| node | hexo | ar2-node-a2 | 0 | None / None | — | 0 | 0 | 0 | 0 (0 differ) |
| node | simple-statistics | ar2-node-a2 | 30 | 0 / 23 | — | 2632 | 0 | 0 | 2632 (0 differ); re-derived from pairs: 2632, 0 differ |
| node | yargs | ar2-node-a2 | 15 | 3 / 27 | — | 3308 | 0 | 0 | 3308 (0 differ); re-derived from pairs: 3308, 0 differ |
| node | ava-shelljs | ar2-node-b2 | 16 | 0 / 2 | — | 224 | 0 | 0 | 224 (0 differ); re-derived from pairs: 224, 0 differ |
| node | jasmine-cordova-android | ar2-node-b2 | 25 | 82 / 66 | — | 5500 | 0 | 0 | 5500 (0 differ); re-derived from pairs: 5500, 0 differ |
| node | jasmine-xregexp | ar2-node-b2 | 20 | 0 / 25 | — | 2101 | 0 | 0 | 2101 (0 differ); re-derived from pairs: 2101, 0 differ |
| node | tap-dotenv | ar2-node-b2 | 10 | 0 / 21 | — | 256 | 0 | 0 | 256 (0 differ); re-derived from pairs: 256, 0 differ |
| node | tap-minimatch | ar2-node-b2 | 25 | 0 / 20 | — | 670 | 0 | 0 | 670 (0 differ); re-derived from pairs: 670, 0 differ |
| node | uvu-browserslist | ar2-node-b2 | 25 | 1 / 13 | — | 1084 | 0 | 0 | 1084 (0 differ); re-derived from pairs: 1084, 0 differ |
| node | json-schema-faker | ar2-node-c2 | 20 | 2 / 10 | — | 1180 | 0 | 0 | 1180 (0 differ); re-derived from pairs: 1180, 0 differ |
| node | oak | ar2-node-c2 | 20 | 33 / 37 | — | 1164 | 0 | 0 | 1164 (0 differ); re-derived from pairs: 1164, 0 differ |
| node | std | ar2-node-c2 | 20 | 77 / 63 | — | 20666 | 0 | 0 | 20666 (0 differ); re-derived from pairs: 20666, 0 differ |
| node | wouter | ar2-node-c2 | 20 | 0 / 0 | — | 0 | 0 | 0 | 0 (0 differ); re-derived from pairs: 0, 0 differ |

TOTAL python: tests verified 30313, mismatches 0, confirmed wrong 0

TOTAL node: tests verified 62341, mismatches 0, confirmed wrong 0

TOTAL: tests verified 92654, confirmed wrong 0

## Earlier measurement: first set, engine 7510773 (before the parallel-proof-3 quarantine merge; runs cancelled after the landed shards were kept)

| lang | repository | runs | transitions | reuse share by tests (median / mean %) | by time (median / mean %) | tests verified (fresh run) | mismatches | wrong (confirmed) | engine verify (tests) |
|---|---|---|---:|---|---|---:|---:|---:|---:|
| python | runner-django-healthchecks | ar2-py-1 | 20 | 11 / 15 | 15 / 16 | 4876 | 0 | 0 | — |
| python | runner-doctest-autopep8 | ar2-py-1 | 120 | 100 / 57 | 100 / 57 | 68 | 0 | 0 | — |
| python | runner-doctest-nameparser | ar2-py-1 | 100 | 0 / 31 | 0 / 31 | 31 | 0 | 0 | — |
| python | runner-hypothesis-attrs | ar2-py-1 | 20 | 90 / 70 | 99 / 75 | 19735 | 0 | 0 | — |
| python | runner-nose2-howdoi | ar2-py-1 | 60 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | — |
| python | runner-nose2-nose2 | ar2-py-1 | 20 | 27 / 15 | 2 / 1 | 1018 | 0 | 0 | — |
| python | runner-unittest-icecream | ar2-py-1 | 20 | 0 / 10 | 0 / 10 | 98 | 0 | 0 | — |
| python | runner-unittest-jc | ar2-py-1 | 20 | 0 / 10 | 0 / 9 | 2913 | 0 | 0 | — |
| python | runner-ward-thoughtspot-tml | ar2-py-1 | 20 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | — |
| python | runner-ward-ward | ar2-py-1 | 3 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | — |
| python | runner-zope-datetime | ar2-py-1 | 20 | 0 / 10 | 0 / 10 | 106 | 0 | 0 | — |
| python | runner-zope-irclog2html | ar2-py-1 | 20 | 0 / 35 | 0 / 35 | 623 | 0 | 0 | — |
| node | dependency-cruiser | ar2-node-a | 10 | 63 / 39 | — | 7571 | 0 | 0 | 7571 (0 differ) |
| node | ink | ar2-node-a | 24 | 25 / 28 | — | 12029 | 0 | 0 | 12029 (0 differ) |
| node | simple-statistics | ar2-node-a | 30 | 0 / 23 | — | 2632 | 0 | 0 | 2632 (0 differ) |
| node | yargs | ar2-node-a | 30 | 29 / 29 | — | 7207 | 0 | 0 | 7207 (0 differ) |
| node | ava-shelljs | ar2-node-b | 25 | 0 / 3 | — | 452 | 0 | 0 | 452 (0 differ) |
| node | jasmine-cordova-android | ar2-node-b | 25 | 82 / 66 | — | 5500 | 0 | 0 | 5500 (0 differ) |
| node | tap-dotenv | ar2-node-b | 25 | 0 / 21 | — | 698 | 0 | 0 | 698 (0 differ) |
| node | tap-minimatch | ar2-node-b | 25 | 0 / 20 | — | 670 | 0 | 0 | 670 (0 differ) |
| node | uvu-autoprefixer | ar2-node-b | 25 | 24 / 26 | — | 1695 | 0 | 0 | 1695 (0 differ) |
| node | uvu-browserslist | ar2-node-b | 25 | 1 / 13 | — | 1084 | 0 | 0 | 1084 (0 differ) |
| node | json-schema-faker | ar2-node-c | 20 | 2 / 10 | — | 1180 | 0 | 0 | 1180 (0 differ) |
| node | oak | ar2-node-c | 20 | 33 / 37 | — | 1164 | 0 | 0 | 1164 (0 differ) |
| node | std | ar2-node-c | 20 | 77 / 63 | — | 20666 | 0 | 0 | 20666 (0 differ) |
| node | wouter | ar2-node-c | 20 | 0 / 0 | — | 0 | 0 | 0 | 0 (0 differ) |

TOTAL python: tests verified 29468, mismatches 0, confirmed wrong 0

TOTAL node: tests verified 62548, mismatches 0, confirmed wrong 0

TOTAL: tests verified 92016, confirmed wrong 0

## What I changed besides the port, and why

* **Test expectations changed** (each commented in the test): `sqlite_real_clock` expects reuse (SQLite's clock is virtual on this engine, sqlvirt.py); four reuse sets under the carried-set rule (Django JSON fixture, ward module fixture, unittest-under-pytest class unit; soundness assertions unchanged); Node and Deno `mtimeMs` cases are value-keyed (r021b `V:`); tap's R-032 N3 checks agreement with a fresh run; `test_capture_rust` pins one probed file's mtime and the Python reference (tests/rust_hotpaths_ref) follows the new probes.
* **Engine fixes found by the port**: pytest-randomly's inert options were configuration (no xdist worker result reused with it installed, MEASURED); the runner shells' own lazy imports were taken as test lookups; Hypothesis's GC timer and ward's display timer broke determinism; Deno's load hook.
* **Merges of parallel-proof-3 72100d3, 19ba798, 0f45362**: `--det-isolate`'s session bookkeeping (`iso_*`, the shard merge) lives in the runner-neutral `ProofSession`, the pytest begin/end in the shell, Level 0's bracket in `_level0` (`plugin.level0_begin/_end` over it): a runner driver can insert a per-test fork at `DetRun.begin` / `end`. `tests/review_r032b/conftest.py` is not taken: it only skips the runner cases where the drivers are absent, and as a second module named `conftest` it broke the import of `tests/test_parallel_proof.py` in a full-suite run (MEASURED; parallel-proof-3 later moved that skip to tests/conftest.py). The reference capture (tests/rust_hotpaths_ref) follows this branch's stat rules and now deduplicates identical distribution parts as identity.rs does (this image has cryptography's dist-info and egg-info side by side: MEASURED).
* **Data kinds**: the Node capture's link dependency is `k:`/`K:`, its recursive listing `w:` (the Python capture's `l:` and `t:` mean other things in the same Rust checker).

## Not covered / open

* ward (0 reuse, start-up metadata probe), wouter (timeOrigin), howdoi's old shard: above.
* R-032b F1's rule is coarse by design: a test file that imports any library (or holds a by-name marker) carries every earlier context of its process; reuse falls where tests share a process (the final walks show the effect).
* A tool that starts a process at pytest start-up (MEASURED: pytest-benchmark's `subprocess.Popen`) makes the first test of a `--det-isolate` child uncacheable (sound, coarse); parallel-proof-3's isolate tests assume it is not installed.
* A reuse withdrawn at its turn (R-023 F2) inside a unittest class unit leaves the earlier members reused.
* Karma (browser, Level 2) not built. No independent review of the merged head yet.
* The brain repository was not written from this session (no access configured); this report is on the branch.
* No pull request was opened (this session's instructions: no PR). The coordinator asked for one into `claude/release-1`; `claude/all-runners-2` is pushed and can be merged from there.
