DONE

# rust-hotpaths, round 2b: review R-017 (FIX 3) fixed

Branch `claude/rust-hotpaths-2`. Review: `claude/review-r017` (dc8e70d), `sessions/2026-11-19-review-rust-r2/REPORT.md`.
The failing tests are copied unchanged into `tests/test_review_r017.py` (b4e7412). Starting point: ac0110b, the
round-2 final code (same as a9981c5 / e2696ec; the later commits only add walk shards).

Labels: **MEASURED** (a named run), **ESTIMATED** (derived). "pre" = the engine before these fixes (ac0110b),
"r017" = with them.

## Commits (one per finding, for `claude/parallel-proof`)

| commit | what |
|---|---|
| b4e7412 | `tests/test_review_r017.py`, copied unchanged from `claude/review-r017` |
| a1fe27d | **H1**: rewritten-test pycs keyed on what the rewrite depends on (`plugin.py`) + `tests/test_rewrite_cache.py` |
| b3b5a78 | **H2**: REPORT-R2 corrected: CI p8 pygments `--det` runs failed (finding 2, note under the headline table) |
| 6595f99 | **H3**: an env name that is not valid UTF-8 refuses the test (`badenv`; `capture.rs`, `record.rs`, the Python reference) + tests |
| 89bc112 | measurements: CI profile run p9 (`run.json`), and `--clean-tmp` on the CI profile step |
| f762e4b | measurements: local profiles (`results/local-r017/`) |

The other commits on the branch in this period are merges of the CI walk/profile result commits.

## Findings: finding -> fix -> test before / after

### H1 (port regression): the rewritten-test pyc cache ignored the configuration the rewrite depends on

**Finding.** Since 264b183, `--det` keeps pytest's assertion-rewritten test modules in the deterministic bytecode
cache. pytest checks such a pyc only against the source hash, the magic number and its own version (`PYC_TAIL`).
But the rewritten code also depends on the `enable_assertion_pass_hook` ini option. So a `--det` run loaded code
written by an earlier run with another configuration, and with `--det-cache` it recorded results produced by that
code.

**Fix (a1fe27d, `plugin.py:_cache_rewritten_tests`, `_rewrite_key`).** Under `--det`, pytest now reads and detpy
writes these pycs under a name keyed on everything the rewrite depends on besides the source and the
interpreter/pytest version (`test_a.cpython-313-pytest-9.2.0.det-<key>.pyc`). Both the reader (`_read_pyc`) and the
writer (`_rewrite_test`) are redirected. The key is a digest of:
* `enable_assertion_pass_hook`, the one configuration value `AssertionRewriter` reads (audited in pytest 9.2:
  `AssertionRewriter.__init__` is the only use of `config` in the rewrite; `module_path` only names warnings);
* `sys.flags.optimize`, which `compile` in `_rewrite_test` uses (pytest's `PYC_EXT` only tells `-O` from no `-O`);
* the rewriter's own source (`_pytest/assertion/rewrite.py`, hashed once per run), for a patched or dev pytest
  under the same version.

What is no longer read:
* If a plugin has replaced `rewrite_asserts` or `AssertionRewriter` (checked at each read and write), nothing is
  read or written, and every module is rewritten fresh.
* pycs under pytest's own name, written by the earlier detpy or planted, are never read under `--det`.
* `DETPY_REWRITE_CACHE=0` now turns off both reads and writes. Before, it only turned off writes, so an existing
  stale pyc was still read.

Determinism: nothing else changes. The first run still executes the marshalled code, as later runs do.

**Tests.**

| test | before (ac0110b) | after |
|---|---|---|
| `test_review_r017.py::test_h1_rewritten_pyc_ignores_assertion_pass_hook_option` | FAILED: `assert 0 == 1` (hook never called: "ran rewritten code written by an earlier run without the option") | passed |
| `test_review_r017.py::test_h1_cache_records_result_of_other_configuration` | FAILED: `{'passed': 1, 'failed': 1}` (the hook-dependent test failed in the run with the hook on) | passed |
| `test_rewrite_cache.py::test_rewritten_pyc_is_keyed_on_the_rewrite_configuration` (new: on → off → on, and a planted pytest-named pyc with a matching source hash) | FAILED: the hook-off run loaded the hook-on pyc (`assert 1 == 0`) | passed |
| `test_rewrite_cache.py` (the two existing tests: cached and checked; can be turned off) | passed | passed |

The cache still works (MEASURED, local profile work directories): r017 wrote and reused 44 keyed rewritten pycs
on click and 37 on pygments, and no pytest-named ones. The pre wheel wrote the same 44 / 37 under pytest's name.

### H2 (report): "Fresh CI runners never see it" was contradicted by CI p8

**Finding.** REPORT-R2 finding 2 (deterministic temporary names run out, `TMP_MAX == 20`) said the problem was
local only. But in `results/p8/pygments-0of1.json`, every `--det` run fails from round 3 on, in every engine and in
`B`, `C` and `W`, while plain pytest passes. The pygments CI rows of the headline table are medians that include
those runs. (Exact rounds: rounds 3-5 everywhere, rounds 2-5 for `C:r2` / `W:r2`; `B:r2` fails from round 3, not
round 2 as the review says.)

**Fix (b3b5a78, REPORT-R2.md).**
* Finding 2 now says CI hits it too and gives the p8 rounds and exits.
* A note under the headline table says the pygments CI p8 medians (1.27x / 0.28x / 1.08x) are of 5 rounds of which
  3 (4 for `C:r2` / `W:r2`) exited 1. It also says the local pygments rows all exited 0 (checked in
  `results/local-final/profile-pygments.json` and `floor/final-pygments.json`).
* At the source: the CI profile step now passes `--clean-tmp` (89bc112). In p9, every pygments run exited 0
  (below).

**Test.** `test_review_r017.py::test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does`:

| | before (ac0110b) | after |
|---|---|---|
| the test as copied | FAILED: `AttributeError: 'NoneType' object has no attribute 'get'` (line 108) | **FAILED, same error** |
| the same test with that expression fixed (scratch copy, not committed) | FAILED: "REPORT-R2 finding 2 says CI never sees the temporary-name exhaustion; …" | passed |

**The copied test cannot pass on this data. This is a defect in the test, not in the fix.** Its precondition
reads `(x.get("cache") or {}).get("not_cached", {}).get("outcome")`. In p8, the `B:*` rows have
`"cache": {..., "not_cached": null}` (a `B` run has no cache). So `.get("not_cached", {})` returns `None`, and the
test crashes before it reaches the report check. It fails the same way before and after any change to the report.
The test file is copied unchanged as instructed. With `((x.get("cache") or {}).get("not_cached") or {})` instead
(one expression), the test fails before the fix with its intended message and passes after. I did not change the
p8 data: it is a measured record. **The reviewer should fix line 107-108 of the test.** Until then, the full suite
shows this one failure.

### H3 (pre-existing, carried into Rust): an env var with a non-UTF-8 name was not an input

**Finding.** `CaptureCore.fill_plan` built `plan.env` with `filter_map(|n| String::from_utf8(..).ok())`, and the
Python reference's `_plan` did the same (`_encodable`). A test reading `os.environb[b"R17\xff"]` was recorded
without that input, and its result was reused (`passed`) after the value changed.

**Fix (6595f99).** Such a name cannot be keyed in the store, whose JSON is UTF-8. So:
* `fill_plan` flags the context `badenv`.
* `detpy_core::record::uncacheable` refuses it: "reads an environment variable whose name is not valid UTF-8".
  This mirrors `badpath` for non-UTF-8 paths, which keeps precedence.
* The check is on the plan, so every way of reading a name is covered: `os.environb`, a surrogate-escaped `str`,
  `getenv`, `in`, `get`.
* The Python reference (`tests/rust_hotpaths_ref/_ref_proofcache.py`) gets the same fix, so the equivalence tests
  keep comparing like with like.

Tests that use only UTF-8 names are unaffected: 0 store / receipt differences on click and pygments outside the
known noise (below).

**Tests.**

| test | before (ac0110b) | after |
|---|---|---|
| `test_review_r017.py::test_h3_env_var_with_undecodable_name_is_an_input` (bytes name) | FAILED: `['passed', 'passed']` | passed |
| `test_proofcache.py::test_env_name_not_valid_utf8_refuses_the_test` (new: surrogate `str` name; reason text; a sibling test is still reused) | FAILED: `['passed', 'passed']` | passed |
| `record.rs::tests::test_badenv_is_uncacheable` (new; `badpath` keeps precedence) | (did not exist) | passed |

The "before" runs used the ac0110b wheel, built from a worktree and installed in its own venv.

## Test suites (after, this container: Python 3.13, pytest 9.2.0, `maturin develop --release`)

* `pytest tests` (every review test file included: r009, r009b, r015, r015b, r017, plus the rest): **518 passed,
  8 skipped, 1 failed**. The failure is `test_h2_…`, the test defect above.
* In an earlier full run, under load (two wheel builds and other test runs at the same time),
  `test_clock_rust.py::test_cache_matches_reference` failed once on the store byte comparison; its diff was not
  captured. It then passed 14 out of 14 reruns, with both wheels: 3 idle and 4 under 4 CPU-burning processes, per
  wheel. It also passed in the final full run above. I count it as a flake under load, not a regression. The
  review's observation that the virtual clock after a timed-out wait varies with real time is a likely cause.
* `cargo test --workspace --release`: **detpy-core 61 passed** (60 + the new `badenv` test); detpy-py has 0 Rust
  unit tests, as before.
* `tests/test_review_r017.py` alone: before, 4 failed. After, 3 passed and 1 failed (H2, the test defect).

## Speed: cold / floor before and after (MEASURED)

Medians of wall time divided by the plain-pytest (`P0`) median of the same run. "pre" (ac0110b) and "r017" are
interleaved in each run. `B` = `--det`, `C` = cold `--det-cache`, `W` = fully reused ("floor").

| project | where | rounds | cold / plain pre → r017 | floor / plain pre → r017 | `--det` / plain pre → r017 | exits | store / receipt diffs (outside noise) |
|---|---|---|---|---|---|---|---|
| click | CI p9 | 5 | 1.117 → 1.127 | 0.544 → 0.547 | 0.836 → 0.838 | all 0 | 0 / 0 |
| pygments | CI p9 (`--clean-tmp`) | 5 | 1.267 → 1.275 | 0.261 → 0.265 | 1.064 → 1.059 | **all 0** | 1 / 1 (see note) |
| home-assistant 0/16 | CI p9 | 3 | 1.269 → 1.266 | 0.312 → 0.312 | 1.097 → 1.095 | `W` 0; `P0`, `B`, `C` 1 in every round (the project's own failures, as in p8) | 0 / 0 (not informative: all 444 entries are round-to-round noise, as in p8) |
| click | local profile | 3 | 0.954 → 0.938 | 0.430 → 0.438 | 0.721 → 0.729 | all 0 | 0 / 0 |
| pygments | local profile (`--clean-tmp`) | 3 | 1.175 → 1.188 | 0.249 → 0.241 | 0.990 → 0.987 | all 0 | 0 / 1 (see note) |

Sources: `tracks/rust-hotpaths/results/p9/*.json` (CI, the run of 89bc112; engines `pre` = ac0110b wheel, `r017` =
that commit's wheel) and `tracks/rust-hotpaths/results/local-r017/profile-{click,pygments}.json`. The local runs
used `profile.py --reps 3 --no-probe --clean-tmp` with wheels built here.

In seconds (medians):

| | pre cold / floor | r017 cold / floor |
|---|---|---|
| CI click | 9.39 / 4.58 | 9.48 / 4.60 |
| CI pygments | 24.62 / 5.08 | 24.77 / 5.15 |
| CI home-assistant 0/16 | 50.95 / 12.53 | 50.86 / 12.51 |
| local click | 8.85 / 3.99 | 8.70 / 4.07 |
| local pygments | 20.53 / 4.36 | 20.75 / 4.20 |

Reading:
* Every pre → r017 change is within the spread of the rounds, both up and down. For example, CI pygments floor
  rounds were pre 5.04-5.17 s and r017 5.09-5.20 s. Local pygments floor went the other way, 4.36 → 4.20 s.
* The fixes add one hash of `rewrite.py` per run and a string rename per rewritten-module read.
* The rewritten-module cache, the largest floor gain of round 2, is kept: r017 loads its keyed pycs (counted
  above).
* The CI p9 ratios are not comparable with p8's (other runners, only two engines, and `--clean-tmp`, so pygments
  runs no longer fail). The pre vs r017 columns of one row are.

**Note on the one pygments difference.** The difference is `test_basic_api.py::test_random_input[…]` (XQueryLexer
locally, TNTLexer on CI): its executed units differ. This is not caused by the fixes, and it is noise in both
engines:
* `test_content` is built by a module-level `random.shuffle` at import, during collection.
* Under `--det --det-urandom` it differs on every run with **both** wheels. Probe: 3 runs per wheel, 3 different
  digests each, with pre also on a fresh bytecode cache.
* So these tests' stores vary from run to run (local, between two rounds of one engine: pre 7 tests, r017 21; CI
  noise 11). The harness counts most of them as noise. This one matched within each engine's two rounds by
  chance.

See observation 1.

## Observations (not R-017 findings; not changed here)

1. **Randomness drawn at collection (import time) is not controlled by `--det`.**
   * Level 0 reseeds `random` per test (README: "reseeded per test with `derive_seed(seed, nodeid)`"). A test
     module's import-time `random.shuffle` (pygments' `test_basic_api.test_content`) therefore differs on every
     run, even with `--det-urandom`.
   * With `--det-cache`, the tests that use it are reused although their input differs from run to run. They pass
     for every input here, but a test whose outcome depends on that input could be reused with an outcome its
     current run would not give.
   * Pre-existing, the same in both wheels. Worth its own look: seed `random` before collection, or flag
     collection-time entropy.
2. **The `test_h2` defect** (above) should go back to the reviewer.
3. **CI p9 home-assistant 0/16** (39 test files, 444 tests, 3 rounds):
   * `W` reused all 444 tests in both engines.
   * The engine comparison has no signal there, in p8 as now: every one of the 444 store entries differs between
     two rounds of the same engine, so the harness counts all of them as noise.
   * So on home-assistant, p9 measures speed only. The equivalence evidence for the fixes is the test suite and
     click / pygments.
