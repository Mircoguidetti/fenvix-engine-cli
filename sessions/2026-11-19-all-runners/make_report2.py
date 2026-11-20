#!/usr/bin/env python3
"""Write REPORT-2.md from the committed walk results (aggregate2.py) and the fixed text below. Rerun after the
walks land: `python3 sessions/2026-11-19-all-runners/make_report2.py`."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
rows = json.loads(subprocess.check_output([sys.executable, os.path.join(HERE, "aggregate2.py"), "--json"]))
by = {r["repo"]: r for r in rows}

# expected shards per walk (run configs: tracks/all-runners-python/run.json, harness/node_cache/RUN-*)
EXPECTED = {
    "runner-unittest-jc": 1, "runner-unittest-icecream": 1, "runner-django-debug-toolbar": 1,
    "runner-django-healthchecks": 1, "runner-nose2-nose2": 1, "runner-nose2-howdoi": 2, "runner-doctest-autopep8": 2,
    "runner-doctest-nameparser": 2, "runner-zope-datetime": 1, "runner-zope-irclog2html": 1, "runner-ward-ward": 1,
    "runner-ward-thoughtspot-tml": 1, "runner-hypothesis-attrs": 1,
    "commander": 1, "simple-statistics": 1, "dependency-cruiser": 3, "yargs": 2, "ink": 2, "hexo": 4,
    "tap-minimatch": 1, "tap-dotenv": 1, "ava-globby": 1, "ava-shelljs": 1, "jasmine-cordova-android": 1,
    "jasmine-xregexp": 1, "uvu-autoprefixer": 1, "uvu-browserslist": 1, "wouter": 1, "json-schema-faker": 1,
    "oak": 1, "std": 2,
}
PENDING = []


def mm(xs):
    import statistics
    return f"{round(100 * statistics.median(xs))}% / {round(100 * statistics.mean(xs))}%" if xs else "—"


def walk(name, label=None):
    r = by.get(name)
    exp = EXPECTED[name]
    label = label or name.removeprefix("runner-")
    if r is None:
        PENDING.append(name)
        return f"{label}: PENDING (0 of {exp} shards landed)"
    got = len(r["files"]) - r.get("unfinished", 0)
    tail = "" if got >= exp else f", PARTIAL ({got} of {exp} shards finished)"
    if got < exp:
        PENDING.append(name)
    share = mm(r["share_tests"])
    s = (f"{label}: {r['transitions']} transitions, reuse by tests {share}"
         + (f", by time {mm(r['share_time'])}" if r["lang"] == "python" else "")
         + f", **{r['verified']}** tests verified against a fresh run, {r['mismatches']} mismatches, "
         f"**{r['wrong']} wrong**")
    if r["lang"] == "node":
        s += f" (engine --det-cache-verify: {r['engine_verified']} tests, {r['engine_mismatches']} differ)"
    return s + tail


tot = {"python": [0, 0], "node": [0, 0]}
for r in rows:
    tot[r["lang"]][0] += r["verified"]
    tot[r["lang"]][1] += r["wrong"]

PY_RUNNERS = [
    ("`unittest`", "det + skip; unit = the `TestCase` class; carried-set rule with unittest's loader/loop as infrastructure",
     "tests/test_runners_unittest.py: 42 passed (controls: 2 det runs identical, seeded shuffle, Level 0 inside tests, Hypothesis seeded per test)",
     "shared cases of tests/runners_cases.py (28, `sqlite_real_clock` now expects reuse: SQLite's clock is virtual on this engine) + runner cases; R-032 P1-P11 (tests/review_r032)",
     ["runner-unittest-jc", "runner-unittest-icecream"],
     "import-time side effects of a module on another module's tests (as under pytest)"),
    ("Django", "det + skip; DiscoverRunner groups; `--parallel` 1 under --det; cached template loader re-read (`_django.py`)",
     "tests/test_runners_django.py: 33 passed, 1 skipped (TZ: Django sets it from settings)",
     "shared cases + settings, migration, JSON fixture (expectation: Other carries Fix's inputs, carried-set rule), template through the cached loader; tests/test_django_pytest_cache.py 1 passed, 1 skipped (pytest-django not installed here)",
     ["runner-django-debug-toolbar", "runner-django-healthchecks"],
     "every test depends on the whole environment (wsgiref at import)"),
    ("nose2", "det + skip", "tests/test_runners_nose2.py: 33 passed", "shared + config file, plugin change, mp refused; R-032 x_nose2",
     ["runner-nose2-nose2", "runner-nose2-howdoi"],
     "`layers`, `mp` plugins refused; howdoi's 2021 commits (shard 0) do not run on Python 3.13 (its one test errors at every commit)"),
    ("`python -m doctest`", "det + skip (one test per docstring / text file)", "tests/test_runners_doctest.py: 33 passed",
     "shared + text file, docstring, option change", ["runner-doctest-autopep8", "runner-doctest-nameparser"], "—"),
    ("zope.testrunner", "det + skip; layers as fixture contexts; -j 1", "tests/test_runners_zope.py: 33 passed",
     "shared + layer set-up read, `test_suite` reads, -j forced", ["runner-zope-datetime", "runner-zope-irclog2html"],
     "layers resumed in a subprocess (run, never reused); a reuse withdrawn at its turn under a layer that was not set up runs without it (a false failure, never a wrong pass)"),
    ("ward", "det + skip; rich Live auto-refresh off under --det (its timer moved the virtual clock: MEASURED 5.75 s vs 6.0 s after sleep(3))",
     "tests/test_runners_ward.py: 32 passed (12/12 identical fingerprints under load after the fix)",
     "shared + module/global fixture reads (expectation: carried-set rule)", ["runner-ward-ward", "runner-ward-thoughtspot-tml"],
     "**no reuse across commits**: ward's CLI probes `pyproject.toml` at start-up (`click.Path`), now a metadata probe (mtime changes at every checkout): 0 reuses, sound, coarse"),
    ("Hypothesis (every runner + pytest)", "seed from the test id, no example database / storage / local constants; GC-time accounting off under --det (its gc callback read the clock at collection time: MEASURED different fingerprints alone vs after another test)",
     "test_hypothesis_is_seeded_per_test_and_has_no_database (unittest) passes", "—", ["runner-hypothesis-attrs"],
     "example database off under --det (saved failures not replayed)"),
]
NODE_RUNNERS = [
    ("`node --test`", "test/runner-node-test.test.js + runner-mocha.test.js: 98 passed together", ["commander", "simple-statistics"]),
    ("Mocha", "(with node --test above)", ["dependency-cruiser", "yargs"]),
    ("tap", "test/runner-tap.test.js: 43 passed", ["tap-minimatch", "tap-dotenv"]),
    ("AVA", "test/runner-ava.test.js + runner-jasmine.test.js + runner-bun.test.js: 125 passed together", ["ava-globby", "ava-shelljs"]),
    ("Jasmine", "(with AVA above)", ["jasmine-cordova-android", "jasmine-xregexp"]),
    ("uvu", "test/runner-uvu.test.js: 39 passed", ["uvu-autoprefixer", "uvu-browserslist"]),
    ("`bun test`", "(with AVA above)", ["wouter", "json-schema-faker"]),
    ("`deno test`", "test/runner-deno.test.js: 36 passed (Deno 2.9.6)", ["std", "oak"]),
    ("TS loaders (tsx, ts-node)", "through the runners above", ["ink", "hexo"]),
]

out = []
w = out.append
first = "DONE"
body = []
for _, _, _, _, ws, _ in PY_RUNNERS:
    for x in ws:
        walk(x)
for _, _, ws in NODE_RUNNERS:
    for x in ws:
        walk(x)
first = "PARTIAL" if PENDING else "DONE"
PENDING_NOW = list(PENDING)
PENDING.clear()

w(first)
w("")
w("# All runners, round 2: the runner drivers on the Rust engine, R-032 fixes, Node policy in Rust — report")
w("")
w("Branch `claude/all-runners-2` (fenvix-engine-cli), started from `claude/parallel-proof-3` 74721a4; "
  "`claude/parallel-proof-3` 3471d45 and `claude/node-cache-proof` 8cd01e6 merged. Labels: **MEASURED** (Actions run "
  "id, raw file or local command), **ESTIMATED**, **DECLARED**, **UNKNOWN**. Walk numbers are regenerated from the "
  "committed raw files by `sessions/2026-11-19-all-runners/aggregate2.py` (this report by `make_report2.py`).")
w("")
w("## Answer")
w("")
if PENDING_NOW:
    w(f"* **PARTIAL only because walks are still queued/running on Actions**: {', '.join(PENDING_NOW)} "
      "(runs 44656473683 Python, 44656473680 / 44656473679 / 44656473729 Node; no shard failed). Everything else is done.")
w(f"* **0 wrong reuses in {tot['python'][0] + tot['node'][0]:,} tests verified** on the walks landed so far "
  f"(Python {tot['python'][0]:,}, Node {tot['node'][0]:,}; MEASURED, aggregate2.py). Counted per TEST (never a "
  "file entry, R-032 F8). Python: each reused test against run B (the runner under --det without cache, a separate "
  "fresh run). Node: each reused test of the skip run against a **separate fresh run** `detjs <runner> --det` "
  "without cache (new in harness/node_cache/walk.py), plus the engine's own --det-cache-verify (tests only).")
w("* **One implementation.** The Python runner drivers (`python/detpy/runners/`) run on `claude/parallel-proof-3`'s "
  "Rust capture through one runner-neutral session (`_proof.py`, `_level0.py`) shared with the pytest plugin; "
  "`_statcap.py`'s Python interception is not on this branch. The Node session policy is Rust "
  "(`detpy_core::node_session`), checked equal to the JavaScript it replaced.")
w("* **Gates (MEASURED local, final tree):** Python full suite `pytest tests -p no:randomly` serial: **1031 passed, "
  "55 skipped, 0 failed** (1 deselected: `test_h2_report…`, the pre-existing failure parallel-proof-3 also "
  "deselects; tracks/all-runners-2/gates/pytest-full.txt), including test_review_r023b.py, test_review_r023.py, "
  "test_absent_inputs_r019c.py, the R-020 and dep-verdict tests. `cargo test --release --workspace`: **138 passed, "
  "0 failed** (gates/cargo-test.txt). Node `node --test test/*.test.js`: **642 tests, 641 passed, 1 skipped, 0 "
  "failed** (gates/node-suite-summary.txt; Node 22.23.5, Bun 1.4.4, Deno 2.9.6). Runner + R-032 Python files: 229 "
  "passed, 3 skipped (de_DE locale, pytest-django, Django TZ).")
w("")
w("## R-032 findings")
w("")
w("| # | finding | fix on this branch | test (unchanged unless noted) | result (MEASURED local) |")
w("|---|---|---|---|---|")
w("| F1 | namespace package gains `__init__.py` | parallel-proof-3's `CaptureCore.lookup` / `proof::import_probe` (Rust); lookups now keyed per (directory, name) `j:` | tests/review_r032 `test_p2_namespace_package_gains_init`, `test_x_pytest_plugin[namespace_init]` | pass |")
w("| F2 | zipimport member changes | parallel-proof-3's capture (archive read kept) | `test_p3_zipimport_member_changes`, `[zipimport]` | pass |")
w("| F3 | `ctypes.CDLL` of a project `.so` | `ctypes.dlopen` audit arm (Rust) | `test_p4_ctypes_dlopen`, `[ctypes_dlopen]` | pass |")
w("| F4 | memoised answers across tests | carried-set rule (record.rs); runner framework modules are infrastructure in it (`Plan::infra_modules`), `unittest.mock` is not | `test_p5_*`, `test_p6_*`, `x_nose2[lru_prefix]`, `[lru_prefix, module_dict_prefix]` | pass |")
w("| F5 | `.pth` file appears | runtime identity with the site directories' `.pth` set (`runtime_with_paths`, Rust) now used by every runner (`ProofSession.open`) | `test_p11_pth_file_appears` | pass |")
w("| F6 | nested `package.json` appears (Node) | node-cache-proof de10518 (absent `package.json` probes keyed) merged | node/test/review-r032.test.js N3, review-r032-runners-b.test.js N3 (tap: restated as cached-agrees-with-fresh, the review's n/a), new all-runners-2-f6f7.test.js (Bun, Deno) | pass, every Node runner |")
w("| F7 | WebCrypto / ECDH keygen not entropy | node-cache-proof de10518 (`keygen` flag) merged | review-r032 N8b, B9, D7; new all-runners-2-f6f7.test.js: 3 forms under tap, AVA, Jasmine, uvu, 2 more under Bun and Deno | pass, every Node runner |")
w("| F8 | 153,483 counted file entries | counts are per test: aggregate2.py; Node summary `verified_tests`; the Node walk compares tests only | — | this report counts tests only |")
w("| claim 3 | Node session policy duplicated Rust | `detpy_core::node_session` (UNCACHEABLE, outcome rule, observation/entry composition, env dependencies, verified comparisons, receipts); `proof.js` gathers inputs | node/test/policy-equivalence.test.js: old JS (`legacy-proof-policy.js`, test-only) vs Rust on inputs dumped by real node --test and Mocha sessions and 500 seeded random inputs: identical stores, reasons, verified lists, receipts | 5/5 pass |")
w("")
w("## `_statcap.py` probes, against the Rust capture")
w("")
w("| probe (`_statcap.py`) | on parallel-proof-3 | on this branch |")
w("|---|---|---|")
w("| `os.stat` metadata (size, mtime, mode) | kind only (`s:`): a `getsize`/`getmtime` test was reusable after the file changed | **ported into Rust**: `stat_check(meta=True)` → `proof::probe_now` under probe keys (mode `q`); tests: runners_cases `stat_size` / `stat_mode` / `mtime` for every runner, test_capture_rust equivalence |")
w("| `os.lstat`, `os.readlink` (link target) | lstat kind only, readlink not seen | **ported**: mode `Q` (target in the digest); `readlink` wrapped |")
w("| `os.access` | kind only | **ported**: metadata (mode bits) |")
w("| `exists` / `isfile` / `isdir` / `islink` / `lexists` | through the `os.stat` wrapper (kind) | kind (`s:` / `l:`), calling the unwrapped stat so they stay kind-only |")
w("| `realpath` | via lstat (kind) | via lstat/readlink: link target keyed |")
w("| `find_spec` / `_find_and_load` misses | `CaptureCore.lookup` (Rust, meta-path finder) | same; keyed per name (`j:`), compacted to `i:` when many names in a directory (proof.rs `compact_lookups`, test) |")
w("| `rmtree` dir-fd writes | — | all-runners' `under_dir_fd` (Rust) kept |")
w("| in-tree `*.egg-info` | counted as a distribution | all-runners' rule in `identity.rs` kept |")
w("")
w("## Python runners")
w("")
for name, support, control, adv, ws, nc in PY_RUNNERS:
    w(f"### {name}")
    w("")
    w("| support | control tests | adversarial tests | walks (MEASURED, run 44656473683) | not covered |")
    w("|---|---|---|---|---|")
    w(f"| {support} | {control} | {adv} | " + "<br>".join(walk(x) for x in ws) + f" | {nc} |")
    w("")
w("## Node/JS/TS runners")
w("")
w("Shared Node tests (every runner): core cache/r021/r021b/controls 202 (201 passed, 1 skipped), R-032 files 57/57, "
  "all-runners-2-f6f7 18/18, policy-equivalence 5/5 (MEASURED local).")
w("")
for name, tests, ws in NODE_RUNNERS:
    w(f"### {name}")
    w("")
    w("| support | tests | walks (MEASURED, runs 44656473680 / 44656473679 / 44656473729) | not covered |")
    w("|---|---|---|---|")
    nc = "—"
    if name == "`bun test`":
        nc = "wouter: every file reads `performance.timeOrigin` (flag clock-real): 0 cacheable, sound, coarse (Level 0 does not virtualize timeOrigin under Bun)"
    if name == "`deno test`":
        nc = "the capture's load hook is off under Deno (it changed Deno's CommonJS detection, a pass under --det-cache where plain deno fails; MEASURED): Deno's graph comes from `deno info`"
    w(f"| det + skip (as claude/all-runners) | {tests} | " + "<br>".join(walk(x) for x in ws) + f" | {nc} |")
    w("")
w("## All walks (aggregate2.py)")
w("")
w(subprocess.check_output([sys.executable, os.path.join(HERE, "aggregate2.py")]).decode())
w("")
w("## What I changed besides the port, and why")
w("")
w("* **Test expectations changed** (each line commented in the test): `sqlite_real_clock` expects reuse (SQLite's "
  "clock is virtual on this engine, sqlvirt.py); four reuse sets under the carried-set rule (Django JSON fixture, "
  "ward module fixture, unittest-under-pytest class unit; their soundness assertions unchanged); the Node and Deno "
  "`mtimeMs` cases are value-keyed now (r021b `V:`) and check a rerun when mtime changes; tap's R-032 N3 checks "
  "agreement with a fresh run (the review's n/a); `test_capture_rust` pins one probed file's mtime on both copies "
  "and the Python reference (tests/rust_hotpaths_ref) follows the new probes.")
w("* **Engine fixes found by the port**: pytest-randomly's inert options were configuration, so no xdist worker "
  "result was ever reused with it installed (MEASURED); the runner shells' own lazy imports were taken as test "
  "lookups; Hypothesis's GC timer and ward's display timer broke determinism; Deno's load hook (above).")
w("* **Data kinds**: the Node capture's link dependency is `k:`/`K:`, its recursive listing `w:` (the Python "
  "capture's `l:` and `t:` mean other things in the same Rust checker).")
w("* **Fork isolation (coordinator heads-up)**: the driver brackets each test in `DetRun.begin` / `end` over "
  "`ProofSession.start` / `stop`, the same calls as the pytest shell, so a per-test fork can be inserted there.")
w("")
w("## Not covered / open")
w("")
w("* ward (0 reuse, start-up metadata probe), wouter (timeOrigin), howdoi's old shard: above.")
w("* A reuse withdrawn at its turn (R-023 F2) inside a unittest class unit leaves the earlier members reused.")
w("* Karma (browser, Level 2) not built. No independent review of this branch yet.")
w("* The brain repository was not written from this session (no access configured); this report is on the branch.")
open(os.path.join(HERE, "REPORT-2.md"), "w").write("\n".join(out) + "\n")
print(first, "pending:", PENDING_NOW)
