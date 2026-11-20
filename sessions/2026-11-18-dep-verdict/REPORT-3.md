PARTIAL: mean share of test time reused with proof on dependency-only commits 36.0% with per-distribution identity on the Rust engine (the engine's default 19.1%), over the same 130 pairs; mean of repository means 26.5%, pooled test time 12.3%; 0 wrong over 13,950 verified reuses, 2 of which could have exposed a wrong reuse; historically broken tests UNKNOWN. Base: claude/parallel-proof-3 bac3317; engine ee1d06c. Cost of the prefix rule on ordinary commits: click 30.1% to 18.5%, pygments 21.8% to 17.9% (MEASURED unless marked)

# Dependency-update verdict, third report: R-020b and R-019c fixed, rebased onto the Rust engine, measurement re-run

Follows `REPORT-2.md` (PARTIAL 39.9%) and review R-020b (`claude/review-r020b`,
`sessions/2026-11-19-review-dep-verdict/REPORT-2.md`, FIX 3). This is the last fix round. It closes on the
reviewers' own failing tests. During the round the coordinator widened it in three steps:
- review R-019c (`claude/review-r019c`): 10 wrong reuses in the shipped `--det-cache`;
- review R-023b's absent-input tests (`test_3_*`) as extra gates;
- the founder decision of 2026-11-18 (all non-interface engine logic in Rust): this branch's engine was still the
  Python capture. The dependency-verdict work is now on the Rust engine of `claude/parallel-proof-3`.

**Base: `claude/parallel-proof-3` at bac3317** (first merged at de41574 in fb8d246, then bac3317 in 4a62a89).
**Engine measured: ee1d06c** (branch `claude/dep-verdict-abjcfw`); after the measurement, 9b20f6a fixes a cost bug the rows showed (below). New non-interface logic is in Rust:
- `crates/detpy-core/src/record.rs`: the prefix rule, compaction at record time;
- `proof.rs`: kinds, tree and importable digests, `lstat` kinds;
- `distfiles.rs`: the distribution file index;
- `crates/detpy-py/src/capture.rs`: the capture rules.

The Python side keeps the interpreter hooks: the `stat`/`lstat`/`access` wrappers, the module-lookup finder, the
`importlib.metadata` wrappers and the per-distribution tracker's bookkeeping (`distid.Tracker`).

## Verdict against the bar (P-028)

| criterion | bar | result | label |
|---|---|---|---|
| mean share of test time reused with proof, dependency-only commits | YES ≥ 50%, NO < 25% | **36.0%** mean over 130 pairs; 26.5% mean of the 10 repository means; 12.3% of all pooled test time. With the site-packages lookup fix found in these rows (9b20f6a, below): at most **37.9%** / 27.7% (ESTIMATED) | MEASURED |
| same with the engine's default (one digest of the whole environment) | (comparison) | 19.1% over pairs; 14.3% mean of repository means; 9.0% pooled | MEASURED |
| wrong reuses | 0 over ≥ 5,000 verified | **0 wrong, 0 flaky over 13,950** verified per-distribution reuses (the default identity: 0 over 5,224). **2 informative cases**: the moto `6e705a82e3` boto3 tests, which reran because they depend on `d/boto3` | MEASURED |
| historically broken tests inside the affected set | 100% | **UNKNOWN**, as in REPORT-2: the projects' own CI logs are not readable | UNKNOWN |
| cost of the prefix rule (R-020 O1) on ordinary commits (R-020b M1) | (comparison) | **click 30.6% → 20.6%, pygments 21.8% → 17.8%** (the reviewer's walks, Python engine). On the Rust engine, this branch against its base: **click 30.1% → 18.5%, pygments 21.8% → 17.9%**. Cannot be narrowed soundly while tests share a process (below). | MEASURED (2 projects) |

Why PARTIAL: the per-pair mean (36.0%) sits between the NO line (25%) and the YES line (50%), as in REPORT-2 (39.9%).
The mean of repository means (26.5%) is near the NO line, and the pooled share (12.3%) is under it. Five repositories stay
near 0% for reasons unrelated to dependencies (airflow, mlflow, prefect, transformers; pydantic-ai at 5%).

What the 0-wrong row is worth: a rule that reuses every recorded result, whatever changed, would make 19,947 reuses
in these rows with 2 wrong (0.010%). As in REPORT-2, the 0 is evidence that the sample did not break the rule; the
evidence for the rule itself is the reviewers' tests and this branch's (all pass, each failing on the engine before
its fix).

## Review R-020b (`--det-cache-dists`): N1–N3, O2

`tests/test_review_r020b_dep_verdict.py` is unchanged; all 7 tests pass on the Rust engine.

| # | wrong reuse | fix (Rust engine) | tests (fail before, pass now) |
|---|---|---|---|
| N1 | a file two distributions install maps to one owner | `distfiles.rs`: a path maps to every distribution whose RECORD lists it, plus a claim group (`c/` identity file: the distributions installing anything in its top-level entry or directory, and the paths of it several of them install). A distribution that starts claiming the file changes the group. | review: `test_file_installed_by_two_distributions`; mine: `test_distribution_starts_claiming_a_file[False/True]` |
| N2 | a library a wheel installs into `<prefix>/lib` is skipped | every mapped library and loaded module goes through the RECORDs, inside or outside site-packages | review: `test_native_library_installed_outside_site_packages` |
| N3 | `shutil.which` / `os.path.exists` of a file a bump adds | existence checks by user code are inputs: the path's kind (`s:<kind>`, `l:<kind>` for `lstat`). With the flag, this includes paths under site directories. | review: `test_console_script_added_by_a_bump`; mine: `test_optional_plugin_module_added_by_a_second_distribution`, `test_existence_check_keeps_the_content_dependency`, `test_existence_check_of_a_path_the_session_created_is_not_an_input` |
| O2 | the same on a repository file, in the default cache | same rule, both modes | review: `test_repository_file_existence_check` |

What O2 is: a wrong reuse of the engine's default cache, pre-existing. It is the same class as R-019c E-3, below.

How `--det-cache-dists` runs on the Rust capture:
- **Site-packages reads.** The capture hands reads, listings and existence checks under a site directory to
  `distid.Tracker` (`CaptureCore.set_dist_read`).
- **Identity keys.** Each identity key a context depends on is recorded at once as an ordinary data read of its
  identity file (`CaptureCore.read`), so the Rust record step (prefix rule included) and the checker need no
  special case.
- **Loaded code.** Modules and mapped libraries are scanned after every test, and their keys attributed to that
  test's context.

## Review R-019c: wrong reuses in the shipped `--det-cache`

`harness/culprit/review_r019c/test_cache_stale_reuse.py` is unchanged. 10 of its 15 tests failed at 32ebfbb; all 15
pass now.

| # | finding | test (reviewer) | fix |
|---|---|---|---|
| E-1 | a failed `try: import` a new module satisfies (test code) | `test_e1_try_import_now_finds_a_new_module` | **module lookups**: a finder in front of `sys.meta_path` records, for each searched directory outside site-packages and the standard library, one dependency on that directory's **importable entries**. Those are identifier-named directories and `<identifier>.<py,pyc,pyw,so,pyd>` files, with kinds (`i:`; Rust `proof::importable_digest`). Inside an existing package directory, its `__init__` files are checked one by one. The search stops at the first regular module or package. |
| E-1 | same, in library code | `test_e1b_try_import_in_library_code` | same |
| E-1 | `ns/__init__.py` turns a namespace package into a regular one | `test_e4_init_turns_namespace_into_package` | same |
| E-1 | a new top-level module shadows a stdlib module | `test_e6_stdlib_shadowed_by_new_module` | same (the root is searched before the standard library) |
| E-1 | a `.pth` file added to site-packages | `test_e9_pth_file_added_to_site_packages` | the runtime identity holds the `.pth` files (name, content) and `sys.path` |
| E-2 | a new `conftest.py` next to the test / at the root | `test_e3_new_conftest_in_subdir`, `test_e3b_new_root_conftest` | every test depends on the kinds of `conftest.py` and `__init__.py` from the root down to its file |
| E-3 | `os.path.exists` of a file that does not exist yet | `test_e5b_data_file_existence_check` | existence checks (N3/O2) |
| E-4 | a module from a vendored zip on `sys.path` | `test_e7_vendored_zip_changes` | the import system reading a non-source file (zipimport) records its content |
| E-4 | a library loaded with `ctypes.CDLL` | `test_e8_native_library_changes` | files newly mapped into the process (`/proc/self/maps`, read at every context switch) are inputs by content |
| held | ini change, custom ini option, glob, plugin entry point, changed conftest | 5 tests | unchanged |

The parallel round ported most of these rules onto the Rust capture before this branch was rebased. This branch
adds the importable digest, compaction, `lstat` kinds, A1–A4 and the prefix rule. The parallel round's own R-023b
fixes (`ctypes.dlopen` names and the loader cache, process-state reads) are in the base.

Variants (`tests/test_proofcache_import_lookups.py`). Each runs serially and under `-n 2`. Each records a run,
makes one change, and requires every reused result to equal a fresh run. Variants added in this round:
- `importlib.util.find_spec`;
- `pkgutil.iter_modules` (already held before);
- a package that extends its `__path__`;
- a custom `sys.meta_path` finder;
- a library a root conftest loads before the capture starts;
- A1–A4 below.

R-023b's 9 absent-input tests (`tests/test_review_r023b.py`, `test_3_*`) pass serially and under `-n 2`.

### Not seen by a Python-level recorder: refused instead (`docs/LIMITS.md`, section 9)

| # | input | handling | test (serial and `-n 2`; fails on de41574) |
|---|---|---|---|
| A1 | a file the repository's native code stats or reads from C (S1) | a context in which a library from the project root is mapped or opened through `ctypes` is **not cached** ("native code from the repository"), unless a distribution's RECORD lists the library | `test_stat_from_c_code_of_the_repository` |
| A2 | a library `dlopen()`ed and `dlclose()`d within one context | the `ctypes.dlopen` event names it: refused as A1 | `test_library_loaded_and_unloaded_within_one_test` |
| A3 | `os.stat` bound before the session (`from os import stat` in a `-p` plugin) | rebound to the recording wrapper at capture start | `test_stat_bound_before_the_session` |
| A4 | `lexists`/`islink` of a dangling symlink | `os.lstat` records the kind without following the link (`l:link`) | `test_dangling_symlink_that_goes_away` |

These were K1–K4 in the coordinator's messages. They are named A1–A4 because the base's `LIMITS.md` already has
K1–K4 (real-clock limits). What stays out of reach is S1 as before: C code installed as a dependency (its reads)
and references held in closures or C code (S3).

## The prefix rule on the Rust engine (R-020 H1/O1)

The rule was in the pre-Rust Python record step of this branch (REPORT-2); the base did not have it, so the R-020
wrong reuses O1 and H1 were open in the base's default cache. It is now in `record.rs`. Everything a test, fixture
or collection that ran before a test in the same process depended on is an input of that test, in order of first
activation (`Plan.first_order`, from the capture's timeline). R-020's tests and this branch's prefix-rule tests
(`tests/test_dep_verdict_r020_fixes.py`) pass.

Two refinements made on the Rust engine, both measured below:
- **Incremental base.** The carried reads are one sorted base, extended as contexts are carried. Rebuilding it per
  test made recording quadratic: pygments recorded in 25.4 s instead of 6.8 s.
- **A context's own outputs are not carried.** What a context recorded about a file outside the repository that
  it wrote itself (a temporary file, an output a child process read back) describes its own output. That output is
  a function of the context's other inputs, which are carried. Carried, it tied every later test to a file the
  earlier test rewrites in each session, and the base's earlier-writer withdrawal then reran them: 558 of 5,344
  pygments tests on an unchanged rerun. Files in the repository stay carried.

The equivalence references (`tests/rust_hotpaths_ref`: the Python record loop, the Python capture) follow both
rules; Python and Rust give the same stores, receipts and summaries.

Tests whose fixtures put cacheable tests after refused ones (or after code or clock readers) were reordered, or
their counts adjusted. Each change keeps the original check and says why.

### R-020b M1: can the prefix rule be narrowed?

No, not soundly, while tests share a process. The candidate narrowings and why each fails:
- **Carry only between tests that executed code in the same files.** State flows through objects, not files: an
  earlier test can fill `other_module.REGISTRY` through an argument without running a line of it.
- **Carry data only, or test contexts only.** The code and import-time forms of the same hole are real
  (REPORT-2's tests).
- **Do not carry refusals.** A subprocess or socket result can be memoised, and a pooled connection outlives its
  test.
- **Isolate each test in a fork.** That would make the rule unnecessary, but it changes behaviour for tests that
  depend on earlier tests (LIMITS O4). It is an execution-model change, not a narrowing.

The parallel round decided (coordinator, 2026-11-19) to key the carried contribution under `-n` by what a test
actually consumed. That is the parallel round's change; see "Open" below.

## What the round costs on ordinary commits (walks)

The click and pygments walks of R-020b: 51 commits each, `mode: suite`, the same harness
(`harness/cache_proof/walk.py`), in this container, 2–4 walks in parallel. The rows are in `report3/walks-rust/`
(Rust engine) and `report3/walks/` (pre-Rust engines). `report3/cmp_walks_rust.py` reprints this table.

| project | engine | mean reused share | pooled | verified reuses (wrong) | cache run A / full run B, median | record, median |
|---|---|---|---|---|---|---|
| click (43 transitions) | 96f4bd1, Python, before the prefix rule | 30.6% | 30.3% | 28,699 (0) | 11.0 / 6.5 s | 3.4 s |
| | 9019c6d, Python, prefix rule (REPORT-2) | 20.6% | 20.9% | 19,342 (0) | 11.8 / 6.2 s | 4.6 s |
| | **bac3317, Rust (base)** | **30.1%** | 30.5% | 28,695 (0) | 7.8 / 5.4 s | 1.4 s |
| | **ee1d06c, Rust (this report)** | **18.5%** | 18.8% | 17,773 (0) | 7.6 / 4.9 s | 0.8 s |
| pygments (50 transitions) | 96f4bd1 | 21.8% | 22.0% | 58,131 (0) | 17.0 / 13.8 s | 1.3 s |
| | 9019c6d | 17.8% | 18.1% | 47,345 (0) | 22.8 / 13.9 s | 6.4 s |
| | **bac3317** | **21.8%** | 21.9% | 58,131 (0) | 26.4 / 14.9 s | 6.8 s |
| | **ee1d06c** | **17.9%** | 17.6% | 47,345 (0) | 25.8 / 14.2 s | 8.2 s |

Reading the table:
- **Reuse.** The loss against the base is the prefix rule (as on the Python engine: −10 points on click, −4 on
  pygments there), plus on click −2 points from module lookups. Click `7925a3410d` turns `tests/test_utils.py`
  into a package `tests/test_utils/`: the name now resolves to another file, and every test that looked it up
  reruns (77% → 0%). The per-directory importable digest is coarser than per-name checks: adding or removing any
  module in a searched directory reruns the tests whose imports searched it. The walks show that once, at a
  commit where it is also a real change.
- **Time.** The cache run is no slower than the base's on either project (click 7.6 vs 7.8 s, pygments 25.8 vs
  26.4 s). Pygments, full suite, same checkout, two runs each:
  - record run 22.5 s (base) / 23.1 s (this report);
  - fully reused run 9.1 s / 7.0 s, smaller entries: median 502 inputs per test against 1,428, with compaction;
  - the store 203 MB / 292 MB.
- **Wrong reuses:** 0 in every walk.

Intermediate engines are kept for the record:
- `walks-rust/*-new-a5c90e2.json.gz`: before the record-step fixes. There pygments' record was 25.4 s and
  click's reuse 17.8%.
- `walks/*-r3*.json.gz`: the pre-Rust engines of this round.

## Re-measurement: the same 130 pairs

Same 130 pairs and sampled test files as REPORT-2 (replayed with `pairs.py --plan
harness/dep_verdict/plan-report2.json`), the same verification (every reuse compared with a fresh run; a mismatch run
once more to tell wrong from flaky). Actions run dv18 (44632313263), all 10 repositories, 56 jobs, engine ee1d06c
(dv8–dv17 were cancelled: engine changes before they produced rows; partial rows of dv17 are not used).

| repository | pairs measured / listed | env changed | tests per pair | share reused D (prototype), mean / median | share reused T (today), mean / median | D of cacheable time, mean | D of dependency-eligible time, mean | verified reuses D (wrong, flaky) |
|---|---|---|---|---|---|---|---|---|
| airflow | 4 / 30 | 1 | 319 | 0% / 0% | 0% / 0% | - | - | 0 (0, 0) |
| community-general | 20 / 20 | 5 | 246 | 38% / 35% | 42% / 35% | 77% | 91% | 2,534 (0, 0) |
| esphome | 23 / 30 | 23 | 399 | 79% / 92% | 0% / 0% | 79% | 82% | 8,007 (0, 0) |
| integrations-core | 7 / 30 | 1 | 29 | 34% / 36% | 34% / 36% | 70% | 80% | 32 (0, 0) |
| litellm | 7 / 30 | 4 | 181 | 38% / 0% | 0% / 0% | 67% | 75% | 511 (0, 0) |
| mlflow | 20 / 30 | 15 | 195 | 0% / 0% | 0% / 0% | - | - | 0 (0, 0) |
| moto | 21 / 30 | 7 | 192 | 72% / 95% | 63% / 93% | 76% | 76% | 2,726 (0, 0) |
| prefect | 4 / 30 | 2 | 311 | 0% / 0% | 0% / 0% | - | - | 0 (0, 0) |
| pydantic-ai | 21 / 28 | 15 | 238 | 5% / 0% | 5% / 0% | 6% | 14% | 140 (0, 0) |
| transformers | 3 / 30 | 0 | 915 | 0% / 0% | 0% / 0% | - | - | 0 (0, 0) |

REPORT-2 on the same pairs (Python engine 9e0d005): esphome 82%, moto 77%, community.general 62%, integrations-core 37%,
pydantic-ai 9%, transformers 1%, the other four 0%; 39.9% over pairs, 26.7% mean of repository means, 14.1% pooled;
T 20.7% / 15.6% / 10.1%.

Other cuts (re-derived with the reviewers' `rederive.py` on these rows; MEASURED):
- environment changed (73 pairs): D 31.4%, T 0%; unchanged (57 pairs): D 41.8%, T 43.6%;
- pairs where at least half of the test time is cacheable (72): D 61.0%, T 30.8%;
- tests that broke (passed at P, not OK at C): 7, all rerun (5 not recorded at P, 2 the boto3 cases above).

What moved against REPORT-2, by repository (checked in the rows):
- **community.general 62% → 38%** (the default identity 50% → 42%): two causes.
  - The runner: REPORT-2 ran this repository in the session container; on Actions, 1,339 of its test runs fail at
    P (not cacheable).
  - A bug of mine: a root conftest is imported between the capture's start and `pytest_configure`, so its module
    lookups keyed the importable entries of site-packages. Any bump that added or removed a module then reran
    every test (740 reruns, 4 pairs).
- **moto 77% → 72%**: the same bug (445 reruns, 1 pair) and the prefix rule.
- **The fix** (9b20f6a, with a test): the capture knows the site and standard-library directories at its start.
  - Counting every test whose only miss was that key as reused gives 37.9% over pairs and 27.7% mean of
    repository means, an upper bound: ESTIMATED, not re-run.
  - Those tests' fresh outcomes equal their recorded ones (0 wrong in the recount).
- **litellm 0% → 38%**:
  - REPORT-2's engine refused every litellm test on a `localhost` lookup. The base keys loopback names by the
    resolver files (R-023b N2).
  - A1 at work: `litellm/rust_bridge/_native.abi3.so`, an extension built in the repository, refuses 445 test runs
    ("native code from the repository").
- **pydantic-ai 9% → 5%**: its `tests/conftest.py` reads `/proc/sys/kernel/random/boot_id` at import. The base counts
  `/proc` reads at import time again (R-023b N1), so those tests are refused.
- **esphome 82% → 79%**: the prefix rule.

## Gates (Python 3.13, this container)

| gate | result |
|---|---|
| `tests/test_review_r020b_dep_verdict.py` (R-020b, unchanged) | 7 passed |
| `tests/test_review_r020_dep_verdict.py` (R-020, unchanged) | 5 passed |
| `harness/culprit/review_r019c/test_cache_stale_reuse.py` (R-019c, unchanged) | 15 passed (10 failed at 32ebfbb) |
| `tests/test_review_r023b.py` `test_3_*` (R-023b absent inputs) | 9 passed serially, 9 under `-n 2` |
| this round's tests: `test_dep_verdict_r020b_fixes.py`, `test_proofcache_import_lookups.py` (serial and `-n 2`), `test_dep_verdict_distid.py`, `test_dep_verdict_r020_fixes.py` | all pass |
| full suite `pytest tests harness/culprit/review_r019c/test_cache_stale_reuse.py` | 768 passed, 10 skipped, 7 failed (below) |
| `cargo test` | 111 + 1 passed |

The 7 failures:
- **6 in the parallel round's `-n` area:** two tests in `test_parallel_proof.py`, four in
  `test_parallel_proof_round3.py`. They test that serial and `-n` sessions take the same decisions, that the
  shared store serves another machine, and the P5 proof. Under the prefix rule, a test's key includes what ran
  before it in its own process, so a serial and a `-n` entry of the same test differ whenever the worker's prefix
  differs. The coordinator assigned this to the parallel round (a carried-set rule: the prefix contribution is
  what the test actually consumed). These 6 tests are left unchanged, as asked.
- **`test_review_r017.py::test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does`** fails on bac3317
  too in this container (`AttributeError: 'NoneType' object has no attribute 'get'`): environmental, not from
  this branch.

## Open

1. The 6 `-n` tests above: the parallel round's carried-set change. This branch is merged into
   `claude/parallel-proof-3` for it.
2. As in REPORT-2: order dependence through reuse (LIMITS O4); C code installed as a dependency (S1).
3. The importable digest's coarseness on commits that add or remove modules in a searched directory (measured
   once above). Per-name checks with per-directory compaction were the alternative: they were slower to record.

## Links

- Branch `claude/dep-verdict-abjcfw`:
  - rebase onto the Rust engine fb8d246 (tree of de41574) and 4a62a89 (merge of bac3317);
  - engine commits 78ebd9b, 129c3b9, ee1d06c (measured); 9b20f6a (site-packages lookup fix, after the rows);
  - pre-Rust commits of this round (superseded on the Rust engine): 8b5a1d8, 3e19642, 5bfbfeb, f22c353, 735571f,
    d972a3e, 8d47dcd, e4660e8, 905fb40.
- Rows: `harness/dep_verdict/results/dv18/` (Actions run 44632313263)
- Reproduce:
  - `sessions/2026-11-18-dep-verdict/report3/mkbase.sh` builds the layout for the reviewers' `rederive.py`;
  - `python3 harness/dep_verdict/analyze.py harness/dep_verdict/results/dv18 --commits harness/dep_verdict/commits.json`;
  - `python3 sessions/2026-11-18-dep-verdict/report3/cmp_walks_rust.py`.
