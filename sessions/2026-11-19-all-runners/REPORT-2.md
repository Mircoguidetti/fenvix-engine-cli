PARTIAL

# All runners, round 2: the runner drivers on the Rust engine, R-032 fixes, Node policy in Rust — report

Branch `claude/all-runners-2` (fenvix-engine-cli), started from `claude/parallel-proof-3` 74721a4; `claude/parallel-proof-3` 3471d45 and `claude/node-cache-proof` 8cd01e6 merged. Labels: **MEASURED** (Actions run id, raw file or local command), **ESTIMATED**, **DECLARED**, **UNKNOWN**. Walk numbers are regenerated from the committed raw files by `sessions/2026-11-19-all-runners/aggregate2.py` (this report by `make_report2.py`).

## Answer

* **PARTIAL only because walks are still queued/running on Actions**: runner-django-debug-toolbar, runner-nose2-nose2, runner-nose2-howdoi, runner-doctest-autopep8, runner-doctest-nameparser, commander, dependency-cruiser, yargs, ava-globby, jasmine-xregexp, uvu-browserslist, ink, hexo (runs 44656473683 Python, 44656473680 / 44656473679 / 44656473729 Node; no shard failed). Everything else is done.
* **0 wrong reuses in 74,893 tests verified** on the walks landed so far (Python 28,766, Node 46,127; MEASURED, aggregate2.py). Counted per TEST (never a file entry, R-032 F8). Python: each reused test against run B (the runner under --det without cache, a separate fresh run). Node: each reused test of the skip run against a **separate fresh run** `detjs <runner> --det` without cache (new in harness/node_cache/walk.py), plus the engine's own --det-cache-verify (tests only).
* **One implementation.** The Python runner drivers (`python/detpy/runners/`) run on `claude/parallel-proof-3`'s Rust capture through one runner-neutral session (`_proof.py`, `_level0.py`) shared with the pytest plugin; `_statcap.py`'s Python interception is not on this branch. The Node session policy is Rust (`detpy_core::node_session`), checked equal to the JavaScript it replaced.
* **Gates (MEASURED local, final tree):** Python full suite `pytest tests -p no:randomly` serial: **1031 passed, 55 skipped, 0 failed** (1 deselected: `test_h2_report…`, the pre-existing failure parallel-proof-3 also deselects; tracks/all-runners-2/gates/pytest-full.txt), including test_review_r023b.py, test_review_r023.py, test_absent_inputs_r019c.py, the R-020 and dep-verdict tests. `cargo test --release --workspace`: **138 passed, 0 failed** (gates/cargo-test.txt). Node `node --test test/*.test.js`: **642 tests, 641 passed, 1 skipped, 0 failed** (gates/node-suite-summary.txt; Node 22.23.5, Bun 1.4.4, Deno 2.9.6). Runner + R-032 Python files: 229 passed, 3 skipped (de_DE locale, pytest-django, Django TZ).

## R-032 findings

| # | finding | fix on this branch | test (unchanged unless noted) | result (MEASURED local) |
|---|---|---|---|---|
| F1 | namespace package gains `__init__.py` | parallel-proof-3's `CaptureCore.lookup` / `proof::import_probe` (Rust); lookups now keyed per (directory, name) `j:` | tests/review_r032 `test_p2_namespace_package_gains_init`, `test_x_pytest_plugin[namespace_init]` | pass |
| F2 | zipimport member changes | parallel-proof-3's capture (archive read kept) | `test_p3_zipimport_member_changes`, `[zipimport]` | pass |
| F3 | `ctypes.CDLL` of a project `.so` | `ctypes.dlopen` audit arm (Rust) | `test_p4_ctypes_dlopen`, `[ctypes_dlopen]` | pass |
| F4 | memoised answers across tests | carried-set rule (record.rs); runner framework modules are infrastructure in it (`Plan::infra_modules`), `unittest.mock` is not | `test_p5_*`, `test_p6_*`, `x_nose2[lru_prefix]`, `[lru_prefix, module_dict_prefix]` | pass |
| F5 | `.pth` file appears | runtime identity with the site directories' `.pth` set (`runtime_with_paths`, Rust) now used by every runner (`ProofSession.open`) | `test_p11_pth_file_appears` | pass |
| F6 | nested `package.json` appears (Node) | node-cache-proof de10518 (absent `package.json` probes keyed) merged | node/test/review-r032.test.js N3, review-r032-runners-b.test.js N3 (tap: restated as cached-agrees-with-fresh, the review's n/a), new all-runners-2-f6f7.test.js (Bun, Deno) | pass, every Node runner |
| F7 | WebCrypto / ECDH keygen not entropy | node-cache-proof de10518 (`keygen` flag) merged | review-r032 N8b, B9, D7; new all-runners-2-f6f7.test.js: 3 forms under tap, AVA, Jasmine, uvu, 2 more under Bun and Deno | pass, every Node runner |
| F8 | 153,483 counted file entries | counts are per test: aggregate2.py; Node summary `verified_tests`; the Node walk compares tests only | — | this report counts tests only |
| claim 3 | Node session policy duplicated Rust | `detpy_core::node_session` (UNCACHEABLE, outcome rule, observation/entry composition, env dependencies, verified comparisons, receipts); `proof.js` gathers inputs | node/test/policy-equivalence.test.js: old JS (`legacy-proof-policy.js`, test-only) vs Rust on inputs dumped by real node --test and Mocha sessions and 500 seeded random inputs: identical stores, reasons, verified lists, receipts | 5/5 pass |

## `_statcap.py` probes, against the Rust capture

| probe (`_statcap.py`) | on parallel-proof-3 | on this branch |
|---|---|---|
| `os.stat` metadata (size, mtime, mode) | kind only (`s:`): a `getsize`/`getmtime` test was reusable after the file changed | **ported into Rust**: `stat_check(meta=True)` → `proof::probe_now` under probe keys (mode `q`); tests: runners_cases `stat_size` / `stat_mode` / `mtime` for every runner, test_capture_rust equivalence |
| `os.lstat`, `os.readlink` (link target) | lstat kind only, readlink not seen | **ported**: mode `Q` (target in the digest); `readlink` wrapped |
| `os.access` | kind only | **ported**: metadata (mode bits) |
| `exists` / `isfile` / `isdir` / `islink` / `lexists` | through the `os.stat` wrapper (kind) | kind (`s:` / `l:`), calling the unwrapped stat so they stay kind-only |
| `realpath` | via lstat (kind) | via lstat/readlink: link target keyed |
| `find_spec` / `_find_and_load` misses | `CaptureCore.lookup` (Rust, meta-path finder) | same; keyed per name (`j:`), compacted to `i:` when many names in a directory (proof.rs `compact_lookups`, test) |
| `rmtree` dir-fd writes | — | all-runners' `under_dir_fd` (Rust) kept |
| in-tree `*.egg-info` | counted as a distribution | all-runners' rule in `identity.rs` kept |

## Python runners

### `unittest`

| support | control tests | adversarial tests | walks (MEASURED, run 44656473683) | not covered |
|---|---|---|---|---|
| det + skip; unit = the `TestCase` class; carried-set rule with unittest's loader/loop as infrastructure | tests/test_runners_unittest.py: 42 passed (controls: 2 det runs identical, seeded shuffle, Level 0 inside tests, Hypothesis seeded per test) | shared cases of tests/runners_cases.py (28, `sqlite_real_clock` now expects reuse: SQLite's clock is virtual on this engine) + runner cases; R-032 P1-P11 (tests/review_r032) | unittest-jc: 20 transitions, reuse by tests 0% / 10%, by time 0% / 9%, **2913** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>unittest-icecream: 20 transitions, reuse by tests 0% / 10%, by time 0% / 10%, **98** tests verified against a fresh run, 0 mismatches, **0 wrong** | import-time side effects of a module on another module's tests (as under pytest) |

### Django

| support | control tests | adversarial tests | walks (MEASURED, run 44656473683) | not covered |
|---|---|---|---|---|
| det + skip; DiscoverRunner groups; `--parallel` 1 under --det; cached template loader re-read (`_django.py`) | tests/test_runners_django.py: 33 passed, 1 skipped (TZ: Django sets it from settings) | shared cases + settings, migration, JSON fixture (expectation: Other carries Fix's inputs, carried-set rule), template through the cached loader; tests/test_django_pytest_cache.py 1 passed, 1 skipped (pytest-django not installed here) | django-debug-toolbar: PENDING (0 of 1 shards landed)<br>django-healthchecks: 20 transitions, reuse by tests 11% / 15%, by time 15% / 16%, **4876** tests verified against a fresh run, 0 mismatches, **0 wrong** | every test depends on the whole environment (wsgiref at import) |

### nose2

| support | control tests | adversarial tests | walks (MEASURED, run 44656473683) | not covered |
|---|---|---|---|---|
| det + skip | tests/test_runners_nose2.py: 33 passed | shared + config file, plugin change, mp refused; R-032 x_nose2 | nose2-nose2: 9 transitions, reuse by tests 5% / 13%, by time 0% / 1%, **381** tests verified against a fresh run, 0 mismatches, **0 wrong**, PARTIAL (0 of 1 shards finished)<br>nose2-howdoi: 60 transitions, reuse by tests 0% / 0%, by time 0% / 0%, **0** tests verified against a fresh run, 0 mismatches, **0 wrong**, PARTIAL (1 of 2 shards finished) | `layers`, `mp` plugins refused; howdoi's 2021 commits (shard 0) do not run on Python 3.13 (its one test errors at every commit) |

### `python -m doctest`

| support | control tests | adversarial tests | walks (MEASURED, run 44656473683) | not covered |
|---|---|---|---|---|
| det + skip (one test per docstring / text file) | tests/test_runners_doctest.py: 33 passed | shared + text file, docstring, option change | doctest-autopep8: 60 transitions, reuse by tests 100% / 57%, by time 100% / 57%, **34** tests verified against a fresh run, 0 mismatches, **0 wrong**, PARTIAL (1 of 2 shards finished)<br>doctest-nameparser: PENDING (0 of 2 shards landed) | — |

### zope.testrunner

| support | control tests | adversarial tests | walks (MEASURED, run 44656473683) | not covered |
|---|---|---|---|---|
| det + skip; layers as fixture contexts; -j 1 | tests/test_runners_zope.py: 33 passed | shared + layer set-up read, `test_suite` reads, -j forced | zope-datetime: 20 transitions, reuse by tests 0% / 10%, by time 0% / 10%, **106** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>zope-irclog2html: 20 transitions, reuse by tests 0% / 35%, by time 0% / 35%, **623** tests verified against a fresh run, 0 mismatches, **0 wrong** | layers resumed in a subprocess (run, never reused); a reuse withdrawn at its turn under a layer that was not set up runs without it (a false failure, never a wrong pass) |

### ward

| support | control tests | adversarial tests | walks (MEASURED, run 44656473683) | not covered |
|---|---|---|---|---|
| det + skip; rich Live auto-refresh off under --det (its timer moved the virtual clock: MEASURED 5.75 s vs 6.0 s after sleep(3)) | tests/test_runners_ward.py: 32 passed (12/12 identical fingerprints under load after the fix) | shared + module/global fixture reads (expectation: carried-set rule) | ward-ward: 3 transitions, reuse by tests 0% / 0%, by time 0% / 0%, **0** tests verified against a fresh run, 0 mismatches, **0 wrong**<br>ward-thoughtspot-tml: 20 transitions, reuse by tests 0% / 0%, by time 0% / 0%, **0** tests verified against a fresh run, 0 mismatches, **0 wrong** | **no reuse across commits**: ward's CLI probes `pyproject.toml` at start-up (`click.Path`), now a metadata probe (mtime changes at every checkout): 0 reuses, sound, coarse |

### Hypothesis (every runner + pytest)

| support | control tests | adversarial tests | walks (MEASURED, run 44656473683) | not covered |
|---|---|---|---|---|
| seed from the test id, no example database / storage / local constants; GC-time accounting off under --det (its gc callback read the clock at collection time: MEASURED different fingerprints alone vs after another test) | test_hypothesis_is_seeded_per_test_and_has_no_database (unittest) passes | — | hypothesis-attrs: 20 transitions, reuse by tests 90% / 70%, by time 99% / 75%, **19735** tests verified against a fresh run, 0 mismatches, **0 wrong** | example database off under --det (saved failures not replayed) |

## Node/JS/TS runners

Shared Node tests (every runner): core cache/r021/r021b/controls 202 (201 passed, 1 skipped), R-032 files 57/57, all-runners-2-f6f7 18/18, policy-equivalence 5/5 (MEASURED local).

### `node --test`

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | test/runner-node-test.test.js + runner-mocha.test.js: 98 passed together | commander: PENDING (0 of 1 shards landed)<br>simple-statistics: 30 transitions, reuse by tests 0% / 23%, **2632** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 2632 tests, 0 differ) | — |

### Mocha

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | (with node --test above) | dependency-cruiser: 10 transitions, reuse by tests 63% / 39%, **7571** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 7571 tests, 0 differ), PARTIAL (1 of 3 shards finished)<br>yargs: 15 transitions, reuse by tests 56% / 31%, **3899** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 3899 tests, 0 differ), PARTIAL (1 of 2 shards finished) | — |

### tap

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | test/runner-tap.test.js: 43 passed | tap-minimatch: 25 transitions, reuse by tests 0% / 20%, **670** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 670 tests, 0 differ)<br>tap-dotenv: 25 transitions, reuse by tests 0% / 21%, **698** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 698 tests, 0 differ) | — |

### AVA

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | test/runner-ava.test.js + runner-jasmine.test.js + runner-bun.test.js: 125 passed together | ava-globby: PENDING (0 of 1 shards landed)<br>ava-shelljs: 25 transitions, reuse by tests 0% / 3%, **452** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 452 tests, 0 differ) | — |

### Jasmine

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | (with AVA above) | jasmine-cordova-android: 25 transitions, reuse by tests 82% / 66%, **5500** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 5500 tests, 0 differ)<br>jasmine-xregexp: PENDING (0 of 1 shards landed) | — |

### uvu

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | test/runner-uvu.test.js: 39 passed | uvu-autoprefixer: 25 transitions, reuse by tests 24% / 26%, **1695** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 1695 tests, 0 differ)<br>uvu-browserslist: PENDING (0 of 1 shards landed) | — |

### `bun test`

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | (with AVA above) | wouter: 20 transitions, reuse by tests 0% / 0%, **0** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 0 tests, 0 differ)<br>json-schema-faker: 20 transitions, reuse by tests 2% / 10%, **1180** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 1180 tests, 0 differ) | wouter: every file reads `performance.timeOrigin` (flag clock-real): 0 cacheable, sound, coarse (Level 0 does not virtualize timeOrigin under Bun) |

### `deno test`

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | test/runner-deno.test.js: 36 passed (Deno 2.9.6) | std: 20 transitions, reuse by tests 77% / 63%, **20666** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 20666 tests, 0 differ)<br>oak: 20 transitions, reuse by tests 33% / 37%, **1164** tests verified against a fresh run, 0 mismatches, **0 wrong** (engine --det-cache-verify: 1164 tests, 0 differ) | the capture's load hook is off under Deno (it changed Deno's CommonJS detection, a pass under --det-cache where plain deno fails; MEASURED): Deno's graph comes from `deno info` |

### TS loaders (tsx, ts-node)

| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |
|---|---|---|---|
| det + skip (as claude/all-runners) | through the runners above | ink: PENDING (0 of 2 shards landed)<br>hexo: PENDING (0 of 4 shards landed) | — |

## All walks (aggregate2.py)

| lang | repository | runs | transitions | reuse share by tests (median / mean %) | by time (median / mean %) | tests verified (fresh run) | mismatches | wrong (confirmed) | engine verify (tests) |
|---|---|---|---:|---|---|---:|---:|---:|---:|
| python | runner-django-healthchecks | ar2-py-1 | 20 | 11 / 15 | 15 / 16 | 4876 | 0 | 0 | — |
| python | runner-doctest-autopep8 | ar2-py-1 | 60 | 100 / 57 | 100 / 57 | 34 | 0 | 0 | — |
| python | runner-hypothesis-attrs | ar2-py-1 | 20 | 90 / 70 | 99 / 75 | 19735 | 0 | 0 | — |
| python | runner-nose2-howdoi | ar2-py-1 | 60 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | — |
| python | runner-nose2-nose2 | ar2-py-1 | 9 | 5 / 13 | 0 / 1 | 381 | 0 | 0 | — |
| python | runner-unittest-icecream | ar2-py-1 | 20 | 0 / 10 | 0 / 10 | 98 | 0 | 0 | — |
| python | runner-unittest-jc | ar2-py-1 | 20 | 0 / 10 | 0 / 9 | 2913 | 0 | 0 | — |
| python | runner-ward-thoughtspot-tml | ar2-py-1 | 20 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | — |
| python | runner-ward-ward | ar2-py-1 | 3 | 0 / 0 | 0 / 0 | 0 | 0 | 0 | — |
| python | runner-zope-datetime | ar2-py-1 | 20 | 0 / 10 | 0 / 10 | 106 | 0 | 0 | — |
| python | runner-zope-irclog2html | ar2-py-1 | 20 | 0 / 35 | 0 / 35 | 623 | 0 | 0 | — |
| node | dependency-cruiser | ar2-node-a | 10 | 63 / 39 | — | 7571 | 0 | 0 | 7571 (0 differ) |
| node | simple-statistics | ar2-node-a | 30 | 0 / 23 | — | 2632 | 0 | 0 | 2632 (0 differ) |
| node | yargs | ar2-node-a | 15 | 56 / 31 | — | 3899 | 0 | 0 | 3899 (0 differ) |
| node | ava-shelljs | ar2-node-b | 25 | 0 / 3 | — | 452 | 0 | 0 | 452 (0 differ) |
| node | jasmine-cordova-android | ar2-node-b | 25 | 82 / 66 | — | 5500 | 0 | 0 | 5500 (0 differ) |
| node | tap-dotenv | ar2-node-b | 25 | 0 / 21 | — | 698 | 0 | 0 | 698 (0 differ) |
| node | tap-minimatch | ar2-node-b | 25 | 0 / 20 | — | 670 | 0 | 0 | 670 (0 differ) |
| node | uvu-autoprefixer | ar2-node-b | 25 | 24 / 26 | — | 1695 | 0 | 0 | 1695 (0 differ) |
| node | json-schema-faker | ar2-node-c | 20 | 2 / 10 | — | 1180 | 0 | 0 | 1180 (0 differ) |
| node | oak | ar2-node-c | 20 | 33 / 37 | — | 1164 | 0 | 0 | 1164 (0 differ) |
| node | std | ar2-node-c | 20 | 77 / 63 | — | 20666 | 0 | 0 | 20666 (0 differ) |
| node | wouter | ar2-node-c | 20 | 0 / 0 | — | 0 | 0 | 0 | 0 (0 differ) |

TOTAL python: tests verified 28766, mismatches 0, confirmed wrong 0

TOTAL node: tests verified 46127, mismatches 0, confirmed wrong 0

TOTAL: tests verified 74893, confirmed wrong 0


## What I changed besides the port, and why

* **Test expectations changed** (each line commented in the test): `sqlite_real_clock` expects reuse (SQLite's clock is virtual on this engine, sqlvirt.py); four reuse sets under the carried-set rule (Django JSON fixture, ward module fixture, unittest-under-pytest class unit; their soundness assertions unchanged); the Node and Deno `mtimeMs` cases are value-keyed now (r021b `V:`) and check a rerun when mtime changes; tap's R-032 N3 checks agreement with a fresh run (the review's n/a); `test_capture_rust` pins one probed file's mtime on both copies and the Python reference (tests/rust_hotpaths_ref) follows the new probes.
* **Engine fixes found by the port**: pytest-randomly's inert options were configuration, so no xdist worker result was ever reused with it installed (MEASURED); the runner shells' own lazy imports were taken as test lookups; Hypothesis's GC timer and ward's display timer broke determinism; Deno's load hook (above).
* **Data kinds**: the Node capture's link dependency is `k:`/`K:`, its recursive listing `w:` (the Python capture's `l:` and `t:` mean other things in the same Rust checker).
* **Fork isolation (coordinator heads-up)**: the driver brackets each test in `DetRun.begin` / `end` over `ProofSession.start` / `stop`, the same calls as the pytest shell, so a per-test fork can be inserted there.

## Not covered / open

* ward (0 reuse, start-up metadata probe), wouter (timeOrigin), howdoi's old shard: above.
* A reuse withdrawn at its turn (R-023 F2) inside a unittest class unit leaves the earlier members reused.
* Karma (browser, Level 2) not built. No independent review of this branch yet.
* The brain repository was not written from this session (no access configured); this report is on the branch.
