#!/usr/bin/env python3
"""Write REPORT-2.md from the committed walk results (aggregate2.py), the committed gate outputs
(tracks/all-runners-2/gates/summary.json) and the fixed text below. Rerun after the walks land:
`python3 sessions/2026-11-19-all-runners/make_report2.py`."""
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
AGG = os.path.join(HERE, "aggregate2.py")


def agg(set_name, as_json=True):
    args = [sys.executable, AGG, "--set", set_name] + (["--json"] if as_json else [])
    out = subprocess.check_output(args).decode()
    return json.loads(out) if as_json else out


GATES = json.load(open(os.path.join(ROOT, "tracks", "all-runners-2", "gates", "summary.json")))
SETS = {s: agg(s) for s in ("first", "second", "final")}
# the engine each run set ran (Python: the raw files' engine field; Node: the Actions run's head_sha, MEASURED from
# the Actions API) and the Actions runs (MEASURED)
RUNS = json.load(open(os.path.join(HERE, "runs.json")))
by = {r["repo"]: r for r in SETS["final"]}

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
    return f"{round(100 * statistics.median(xs))}% / {round(100 * statistics.mean(xs))}%" if xs else "—"


def walk(name, label=None):
    r = by.get(name)
    exp = EXPECTED[name]
    label = label or name.removeprefix("runner-")
    if r is None:
        PENDING.append(name)
        return f"{label}: NOT LANDED (0 of {exp} shards)"
    got = len(r["files"]) - r.get("unfinished", 0)
    tail = "" if got >= exp else f", PARTIAL ({got} of {exp} shards finished)"
    if got < exp:
        PENDING.append(name)
    s = (f"{label}: {r['transitions']} transitions, reuse by tests {mm(r['share_tests'])}"
         + (f", by time {mm(r['share_time'])}" if r["lang"] == "python" else "")
         + f", **{r['verified']}** tests verified against a fresh run, {r['mismatches']} mismatches, "
         f"**{r['wrong']} wrong**")
    if r["lang"] == "node":
        s += f" (engine --det-cache-verify: {r['engine_verified']} tests, {r['engine_mismatches']} differ)"
    return s + tail


def totals(rows):
    t = {"python": [0, 0, 0], "node": [0, 0, 0]}
    for r in rows:
        t[r["lang"]][0] += r["verified"]
        t[r["lang"]][1] += r["wrong"]
        t[r["lang"]][2] += r["mismatches"]
    return t


PY_RUNNERS = [
    ("`unittest`", "det + skip; unit = the `TestCase` class; carried-set rule with unittest's loader/loop as infrastructure",
     "tests/test_runners_unittest.py", "shared cases of tests/runners_cases.py (`sqlite_real_clock` expects reuse: SQLite's clock is virtual on this engine) + runner cases; R-032 P1-P11 (tests/review_r032); R-032b W1-W11 (tests/review_r032b)",
     ["runner-unittest-jc", "runner-unittest-icecream"],
     "import-time side effects of a module on another module's tests (as under pytest)"),
    ("Django", "det + skip; DiscoverRunner groups; `--parallel` 1 under --det; cached template loader re-read (`_django.py`)",
     "tests/test_runners_django.py, tests/test_django_pytest_cache.py",
     "shared cases + settings, migration, JSON fixture, template through the cached loader; R-032b W13",
     ["runner-django-debug-toolbar", "runner-django-healthchecks"],
     "every test depends on the whole environment (wsgiref at import); pytest-django not installed locally (its test skips)"),
    ("nose2", "det + skip", "tests/test_runners_nose2.py", "shared + config file, plugin change, mp refused; R-032 x_nose2; R-032b W1",
     ["runner-nose2-nose2", "runner-nose2-howdoi"],
     "`layers`, `mp` plugins refused; howdoi's 2021 commits (shard 0) do not run on Python 3.13 (its one test errors at every commit)"),
    ("`python -m doctest`", "det + skip (one test per docstring / text file)", "tests/test_runners_doctest.py",
     "shared + text file, docstring, option change; R-032b W11", ["runner-doctest-autopep8", "runner-doctest-nameparser"], "—"),
    ("zope.testrunner", "det + skip; layers as fixture contexts; -j 1", "tests/test_runners_zope.py",
     "shared + layer set-up read, `test_suite` reads, -j forced; R-032b W12", ["runner-zope-datetime", "runner-zope-irclog2html"],
     "layers resumed in a subprocess (run, never reused); a reuse withdrawn at its turn under a layer that was not set up runs without it (a false failure, never a wrong pass)"),
    ("ward", "det + skip; rich Live auto-refresh off under --det (its timer moved the virtual clock: MEASURED 5.75 s vs 6.0 s after sleep(3))",
     "tests/test_runners_ward.py", "shared + module/global fixture reads; R-032b W14", ["runner-ward-ward", "runner-ward-thoughtspot-tml"],
     "**no reuse across commits**: ward's CLI probes `pyproject.toml` at start-up (`click.Path`), a metadata probe (its mtime changes at every checkout): 0 reuses, sound, coarse"),
    ("Hypothesis (every runner + pytest)", "seed from the test id, no example database / storage / local constants; GC-time accounting off under --det (its gc callback read the clock at collection time: MEASURED different fingerprints alone vs after another test)",
     "test_hypothesis_is_seeded_per_test_and_has_no_database (unittest)", "—", ["runner-hypothesis-attrs"],
     "example database off under --det (saved failures not replayed)"),
]
NODE_RUNNERS = [
    ("`node --test`", "test/runner-node-test.test.js, runner-mocha.test.js; review-r032b E1-E3", ["commander", "simple-statistics"]),
    ("Mocha", "(with node --test above)", ["dependency-cruiser", "yargs"]),
    ("tap", "test/runner-tap.test.js", ["tap-minimatch", "tap-dotenv"]),
    ("AVA", "test/runner-ava.test.js", ["ava-globby", "ava-shelljs"]),
    ("Jasmine", "test/runner-jasmine.test.js", ["jasmine-cordova-android", "jasmine-xregexp"]),
    ("uvu", "test/runner-uvu.test.js", ["uvu-autoprefixer", "uvu-browserslist"]),
    ("`bun test`", "test/runner-bun.test.js; review-r032b B1-B9; all-runners-2-f6f7 (F6, F7, Temporal.Now)", ["wouter", "json-schema-faker"]),
    ("`deno test`", "test/runner-deno.test.js; review-r032b D1-D7", ["std", "oak"]),
    ("TS loaders (tsx, ts-node)", "through the runners above", ["ink", "hexo"]),
]

# walk each runner's repositories once so PENDING is known before the answer
for _, _, _, _, ws, _ in PY_RUNNERS:
    for x in ws:
        walk(x)
for _, _, ws in NODE_RUNNERS:
    for x in ws:
        walk(x)
PENDING_NOW = sorted(set(PENDING))
PENDING.clear()
G = GATES
gates_ok = all(G[k]["failed"] == 0 for k in ("pytest", "cargo", "node")) and G["ci_runtimes"]["failed"] == 0
first = "DONE" if not PENDING_NOW and gates_ok else "PARTIAL"

out = []
w = out.append
w(first)
w("")
w("# All runners, round 2: the runner drivers on the Rust engine, R-032 and R-032b fixes, Node policy in Rust — report")
w("")
w(f"Branch `claude/all-runners-2` (fenvix-engine-cli). Final engine: code **ed66b960**, walked at head "
  f"**{RUNS['final']['engine']}** (the same code plus run configuration). Started from `claude/parallel-proof-3` 74721a4. "
  "Merged: `claude/parallel-proof-3` 3471d45, 72100d3 (its R-032b F1-F3 engine fix c5f0e70 and `--det-isolate`), "
  "19ba798 (F2-mtime, F3 for repository callers, temporary roots) and 0f45362 (time helpers); "
  "`claude/node-cache-proof` 8cd01e6; the R-032b tests of `claude/review-r032b`. Labels: **MEASURED** (Actions run "
  "id, raw file or local command), **ESTIMATED**, "
  "**DECLARED**, **UNKNOWN**. Every walk number is regenerated from the committed raw files by "
  "`sessions/2026-11-19-all-runners/aggregate2.py` (this report by `make_report2.py`; gate numbers from "
  "`tracks/all-runners-2/gates/summary.json` and the outputs next to it).")
w("")
w("## Answer")
w("")
if PENDING_NOW:
    w(f"* **PARTIAL because walks on the final engine have not all landed**: {', '.join(PENDING_NOW)} "
      f"(Actions runs {', '.join(str(x) for x in RUNS['final']['runs'].values())}).")
if not gates_ok:
    w("* **PARTIAL because a gate failed**: see Gates.")
tf = totals(SETS["final"])
w(f"* **Final engine (code ed66b960, head {RUNS['final']['engine']}): {tf['python'][1] + tf['node'][1]} wrong reuses in {tf['python'][0] + tf['node'][0]:,} tests verified** "
  f"(Python {tf['python'][0]:,}, Node {tf['node'][0]:,}; {tf['python'][2] + tf['node'][2]} mismatches before recheck; "
  "MEASURED, `aggregate2.py --set final`). Counted per TEST, never per file entry (R-032 F8), and re-derived test by "
  "test from the committed pairs `[id, reused outcome, fresh outcome]` (R-032b F7d).")
w("* **What \"fresh\" means** (R-032b F7e): Python, run B = the runner under `--det` without cache on the same "
  "commit; Node, a separate run `detjs <runner> --det` without cache. Both are the engine under Level 0 without the "
  "cache, **not** the plain runner. The Node walks also keep the engine's own `--det-cache-verify` sample.")
for s, label in (("first", "first"), ("second", "second")):
    t = totals(SETS[s])
    w(f"* Earlier, separate measurements ({label} set, engine **{RUNS[s]['engine']}**, {RUNS[s]['note']}): "
      f"{t['python'][0] + t['node'][0]:,} tests verified (Python {t['python'][0]:,}, Node {t['node'][0]:,}), "
      f"{t['python'][1] + t['node'][1]} wrong (MEASURED, `aggregate2.py --set {s}`). They do not cover the final tree.")
w("* **Deno** on Actions is **2.9.8** (the raw files' `runtime`, the workflow's DENO_VERSION; MEASURED), locally "
  "2.9.6 (2.9.8 is not on npm here). Bun 1.4.4 both.")
w("* **One implementation.** The Python runner drivers (`python/detpy/runners/`) run on `claude/parallel-proof-3`'s "
  "Rust capture through one runner-neutral session (`_proof.py`, `_level0.py`) shared with the pytest plugin; "
  "`_statcap.py`'s Python interception is not on this branch. The Node session policy is Rust "
  "(`detpy_core::node_session`), checked equal to the JavaScript it replaced.")
w("")
w("## Gates (final tree)")
w("")
w("| gate | result | file |")
w("|---|---|---|")
w(f"| Python `pytest tests -p no:randomly` serial (MEASURED local) | **{G['pytest']['passed']} passed, {G['pytest']['skipped']} skipped, "
  f"{G['pytest']['failed']} failed**{G['pytest'].get('note', '')} | gates/pytest-full.txt |")
w(f"| `cargo test --release --workspace` (MEASURED local) | **{G['cargo']['passed']} passed, {G['cargo']['failed']} failed** | gates/cargo-test.txt |")
w(f"| Node `node --test test/*.test.js` (MEASURED local; Node 22, Bun 1.4.4, Deno 2.9.6) | **{G['node']['tests']} tests, {G['node']['passed']} passed, "
  f"{G['node']['skipped']} skipped, {G['node']['failed']} failed** | gates/node-suite-summary.txt |")
w(f"| Bun/Deno runner + R-032 + R-032b + F6/F7 files on Actions (Bun 1.4.4, **Deno 2.9.8**; MEASURED, run {G['ci_runtimes']['run']}) | "
  f"**{G['ci_runtimes']['passed']} passed, {G['ci_runtimes']['failed']} failed** | job log |")
w(f"| R-032b Python, every runner (tests/review_r032b, MEASURED local) | **{G['r032b_py']['passed']} passed, {G['r032b_py']['failed']} failed** | gates/r032b-python.txt (also in pytest-full.txt) |")
w("")
w("## R-032 findings")
w("")
w("| # | finding | fix on this branch | test (unchanged unless noted) | result (MEASURED local) |")
w("|---|---|---|---|---|")
w("| F1 | namespace package gains `__init__.py` | parallel-proof-3's `CaptureCore.lookup` / `proof::import_probe` (Rust); lookups keyed per (directory, name) `j:` | tests/review_r032 `test_p2_namespace_package_gains_init`, `test_x_pytest_plugin[namespace_init]` | pass |")
w("| F2 | zipimport member changes | parallel-proof-3's capture (archive read kept) | `test_p3_zipimport_member_changes`, `[zipimport]` | pass |")
w("| F3 | `ctypes.CDLL` of a project `.so` | `ctypes.dlopen` audit arm (Rust) | `test_p4_ctypes_dlopen`, `[ctypes_dlopen]` | pass |")
w("| F4 | memoised answers across tests | carried-set rule (record.rs); runner framework modules are infrastructure in it (`Plan::infra_modules`), `unittest.mock` is not | `test_p5_*`, `test_p6_*`, `x_nose2[lru_prefix]`, `[lru_prefix, module_dict_prefix]` | pass |")
w("| F5 | `.pth` file appears | `runtime_with_paths` (Rust) used by every runner (`ProofSession.open`) | `test_p11_pth_file_appears` | pass |")
w("| F6 | nested `package.json` appears (Node) | node-cache-proof de10518 merged | review-r032.test.js N3, review-r032-runners-b.test.js N3 (tap: cached agrees with fresh), all-runners-2-f6f7.test.js (Bun, Deno) | pass, every Node runner |")
w("| F7 | WebCrypto / ECDH keygen not entropy | node-cache-proof de10518 (`keygen`) merged | review-r032 N8b, B9, D7; all-runners-2-f6f7.test.js under tap, AVA, Jasmine, uvu, Bun, Deno | pass, every Node runner |")
w("| F8 | 153,483 counted file entries | counts are per test (aggregate2.py; Node `verified_tests`) | — | this report counts tests only |")
w("| claim 3 | Node session policy duplicated Rust | `detpy_core::node_session`; `proof.js` gathers inputs | node/test/policy-equivalence.test.js: old JS (test-only `legacy-proof-policy.js`) vs Rust on real node --test / Mocha sessions and 500 seeded inputs | 5/5 pass |")
w("")
w("## R-032b findings")
w("")
w("| # | finding | fix | test | result |")
w("|---|---|---|---|---|")
w("| F1 | state left by an earlier test with no static-import edge (leaked `mock.patch('consts.V')`, `importlib`/`__import__` + setattr, `builtins`, `os.environ`) | parallel-proof-3 c5f0e70 (merged): a repository file whose text reaches modules by name is connected to the library node; a context reaching it is carried into every later test of its process, a test reaching it carries every earlier context. Combined here with the runner infrastructure list (`reference_closure_with(.., dynamic, infra)`) | tests/review_r032b W1 (unittest, nose2, pytest plugin), W2, W3, W4, W12 (zope), W13 (Django), W14 (ward), W15 (xdist loadgroup/loadfile); tests/test_r032b_engine.py | pass (MEASURED local) |")
w("| F2 | `os.DirEntry.stat()` (scandir) size unkeyed; then (coordinator) time reads | parallel-proof-3 c5f0e70 / 6cfae24 / 97e61ac / 89971a3 (merged). On this branch: `os.stat`, `os.lstat`, `os.access`, `os.readlink` key the path's metadata (`q`/`Q`: size, mode, kind; the `_statcap.py` probe set); user code's `os.scandir` entries are wrapped (`stat()` like `os.stat`, `is_file`/`is_dir`/`is_symlink` kinds); **one rule for times, as parallel-proof-3**: a time read by user code (a stat result's `st_mtime`/`st_ctime`/`st_atime`, indices 7-9, unpacking; `os.path.getmtime`/`getctime`/`getatime`) refuses the test (`mtime`). detpy's own stats never count (a detpy frame stops the caller walk: found by this port, the reference flagged its own reads) | W5, W6 (fstat, held); test_r032b_engine W5b, W6c, W6d, W6e and the detpy-frame test | pass |")
w("| F3 | libc called through ctypes unobserved | parallel-proof-3 c5f0e70 (merged): a C library from outside the repository (or `CDLL(None)`) loaded by user code flags `cdll`: not cached | W7 | pass |")
w("| F4 | `module.findPackageJSON` absent probes unkeyed (Node ≥ 22.14) | capture.js wraps `findPackageJSON`: every probed `package.json` is keyed (absent ones too), a non-path specifier flags `runtime-api` | review-r032b E3 (node --test, Mocha, Deno) | pass (local; Deno 2.9.8 on Actions) |")
w("| F5 | Deno `Temporal.Now` real clock | capture.js wraps `Temporal.Now.*` (not `timeZoneId`) as `clock-real` in any runtime that has it. **Bun checked**: Bun 1.4.4 has `Temporal` (MEASURED), same wrap; new test all-runners-2-f6f7 \"R-032b F5 Temporal.Now\" fails with the wrap removed (MEASURED) and passes with it | review-r032b D4; all-runners-2-f6f7 (Bun) | pass |")
w("| F6 | Bun `Worker` reads a file | the global `Worker` flags `worker`, as `worker_threads` does | review-r032b B2 | pass |")
w(f"| F7 | report accuracy | this report: regenerated at the final head; each walk set states its engine ({RUNS['first']['engine']}, {RUNS['second']['engine']}, {RUNS['final']['engine']}); Deno 2.9.8 named; per-test fresh outcomes committed (`verify.pairs`, `compare.pairs`) and re-derived; \"fresh\" = `--det` without cache | `aggregate2.py` re-derivation column | done |")
w("| nits | legacy-proof-policy.js header; object details | header states its `envDep` change and the two inputs the policies differ on; Rust writes object details inside array details as JavaScript does | policy-equivalence 5/5 | done |")
w("")
w("## `_statcap.py` probes, against the Rust capture")
w("")
w("| probe (`_statcap.py`) | on parallel-proof-3 | on this branch |")
w("|---|---|---|")
w("| `os.stat` metadata (size, mtime, mode) | size (`z:`); a time read refuses | **ported into Rust**: `stat_check(meta=True)` → `proof::probe_now` under probe keys (mode `q`); a time read by user code refuses (as parallel-proof-3) |")
w("| `os.lstat`, `os.readlink` (link target) | lstat kind | **ported**: mode `Q` (target in the digest); `readlink` wrapped |")
w("| `os.access` | kind | **ported**: metadata (mode bits) |")
w("| `os.scandir` entries | `stat()` size, kind checks (c5f0e70) | `stat()` metadata (`q`/`Q`), kind checks |")
w("| `exists` / `isfile` / `isdir` / `islink` / `lexists` | kind | kind (`s:` / `l:`), through the unwrapped stat |")
w("| `find_spec` misses | `CaptureCore.lookup` | same; keyed per name (`j:`), compacted to `i:` (`compact_lookups`) |")
w("| `rmtree` dir-fd writes, in-tree `*.egg-info` | — / counted as a distribution | all-runners' rules kept (`under_dir_fd`, `identity.rs`) |")
w("")
w("## Python runners")
w("")
for name, support, control, adv, ws, nc in PY_RUNNERS:
    w(f"### {name}")
    w("")
    w(f"| support | control tests | adversarial tests | walks (MEASURED, final set, run {RUNS['final']['runs'].get('python', '?')}) | not covered |")
    w("|---|---|---|---|---|")
    w(f"| {support} | {control} (in the full suite: 0 failed) | {adv} | " + "<br>".join(walk(x) for x in ws) + f" | {nc} |")
    w("")
w("## Node/JS/TS runners")
w("")
w("Shared Node tests (every runner): the cache/r021/r021b/controls suites, R-032 files, R-032b files, "
  "all-runners-2-f6f7, policy-equivalence: all in the Node gate above (0 failed, MEASURED local).")
w("")
for name, tests, ws in NODE_RUNNERS:
    w(f"### {name}")
    w("")
    w(f"| support | tests | walks (MEASURED, final set, runs {', '.join(str(v) for k, v in RUNS['final']['runs'].items() if k != 'python')}) | not covered |")
    w("|---|---|---|---|")
    nc = "—"
    if name == "`bun test`":
        nc = "wouter: every file reads `performance.timeOrigin` (flag clock-real): 0 cacheable, sound, coarse"
    if name == "`deno test`":
        nc = "the capture's load hook is off under Deno (it changed Deno's CommonJS detection; MEASURED): Deno's graph comes from `deno info`"
    w(f"| det + skip | {tests} | " + "<br>".join(walk(x) for x in ws) + f" | {nc} |")
    w("")
w("## Reuse share, final engine vs the second set (0f969116, before the R-032b F1-F3 engine rules)")
w("")
w("Median / mean share of tests reused per transition (MEASURED, aggregate2.py). The final engine refuses more: a "
  "context that reaches a library or a by-name marker is carried into every later test of its process (F1), a C "
  "library called through ctypes and a time read refuse (F3, F2). Where the second set has no row, its run was "
  "cancelled before that walk landed. The F1-F3 rules are Python's: the Node capture did not change between the two "
  "sets, and the Node rows differ only where the second set has fewer shards (yargs: 1 of 2).")
w("")
w("| repository | second set | final |")
w("|---|---|---|")
_sec = {r["repo"]: r for r in SETS["second"]}
for r in SETS["final"]:
    o2 = _sec.get(r["repo"])
    w(f"| {r['repo'].removeprefix('runner-')} | {mm(o2['share_tests']) if o2 else '—'} | {mm(r['share_tests'])} |")
w("")
w("## All walks, final engine (aggregate2.py --set final)")
w("")
w(agg("final", False))
for s in ("second", "first"):
    w(f"## Earlier measurement: {s} set, engine {RUNS[s]['engine']} ({RUNS[s]['note']})")
    w("")
    w(agg(s, False))
w("## What I changed besides the port, and why")
w("")
w("* **Test expectations changed** (each commented in the test): `sqlite_real_clock` expects reuse (SQLite's clock "
  "is virtual on this engine, sqlvirt.py); four reuse sets under the carried-set rule (Django JSON fixture, ward "
  "module fixture, unittest-under-pytest class unit; soundness assertions unchanged); Node and Deno `mtimeMs` cases "
  "are value-keyed (r021b `V:`); tap's R-032 N3 checks agreement with a fresh run; `test_capture_rust` pins one "
  "probed file's mtime and the Python reference (tests/rust_hotpaths_ref) follows the new probes.")
w("* **Engine fixes found by the port**: pytest-randomly's inert options were configuration (no xdist worker result "
  "reused with it installed, MEASURED); the runner shells' own lazy imports were taken as test lookups; Hypothesis's "
  "GC timer and ward's display timer broke determinism; Deno's load hook.")
w("* **Merges of parallel-proof-3 72100d3, 19ba798, 0f45362**: `--det-isolate`'s session bookkeeping (`iso_*`, the shard merge) lives "
  "in the runner-neutral `ProofSession`, the pytest begin/end in the shell, Level 0's bracket in `_level0` "
  "(`plugin.level0_begin/_end` over it): a runner driver can insert a per-test fork at `DetRun.begin` / `end`. "
  "`tests/review_r032b/conftest.py` is not taken: it only skips the runner cases where the drivers are absent, and "
  "as a second module named `conftest` it broke the import of `tests/test_parallel_proof.py` in a full-suite run "
  "(MEASURED; parallel-proof-3 later moved that skip to tests/conftest.py). The reference capture "
  "(tests/rust_hotpaths_ref) follows this branch's stat rules and now deduplicates identical distribution parts as "
  "identity.rs does (this image has cryptography's dist-info and egg-info side by side: MEASURED).")
w("* **Data kinds**: the Node capture's link dependency is `k:`/`K:`, its recursive listing `w:` (the Python "
  "capture's `l:` and `t:` mean other things in the same Rust checker).")
w("")
w("## Not covered / open")
w("")
w("* ward (0 reuse, start-up metadata probe), wouter (timeOrigin), howdoi's old shard: above.")
w("* R-032b F1's rule is coarse by design: a test file that imports any library (or holds a by-name marker) carries "
  "every earlier context of its process; reuse falls where tests share a process (the final walks show the effect).")
w("* A tool that starts a process at pytest start-up (MEASURED: pytest-benchmark's `subprocess.Popen`) makes the "
  "first test of a `--det-isolate` child uncacheable (sound, coarse); parallel-proof-3's isolate tests assume it is not installed.")
w("* A reuse withdrawn at its turn (R-023 F2) inside a unittest class unit leaves the earlier members reused.")
w("* Karma (browser, Level 2) not built. No independent review of the merged head yet.")
w("* The brain repository was not written from this session (no access configured); this report is on the branch.")
open(os.path.join(HERE, "REPORT-2.md"), "w").write("\n".join(out) + "\n")
print(first, "pending:", PENDING_NOW, "gates_ok:", gates_ok)
