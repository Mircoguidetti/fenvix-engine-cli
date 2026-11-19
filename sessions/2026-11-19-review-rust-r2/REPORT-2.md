FIX 2

# Review R-017b (last round): claude/rust-hotpaths-2 after REPORT-R2b

Target: `claude/rust-hotpaths-2` at 0599e28. Its report is `sessions/2026-11-18-rust-hotpaths/REPORT-R2b.md`. The
first review is `claude/review-r017` (dc8e70d), `sessions/2026-11-19-review-rust-r2/REPORT.md`. Failing tests for
this round are in `tests/test_review_r017b.py` on `claude/review-r017b`.

Environment: Python 3.13, pytest 9.2.0, `maturin develop --release` of 0599e28 in a fresh venv.

## Verdict in short

* **H1 is fixed for the cases it names**: the pass-hook option, `-O` vs `-OO`, a patched `rewrite.py`, and
  `DETPY_REWRITE_CACHE=0`. But the key does not cover a plugin or conftest that patches a *method* of
  `AssertionRewriter`. The same stale-code reuse then comes back, including a result recorded by `--det-cache`
  (**F1**).
* **H2 is fixed.** The author is right that the copied `test_h2` is defective: that is my error from round 1
  (details below).
* **H3 is fixed for env names.** Env values, argv option values and bytes paths that are not valid UTF-8 are keyed
  correctly. But a sqlite database opened through a `file:` URI is not an input at all, so its content can change
  and the old result is reused. For `%FF` / `%FE` the decoded name is also lossy (**F2**, pre-existing).
* **Numbers**: every headline number of REPORT-R2b re-derives exactly from the committed data, and the labels are
  right. One count is labelled MEASURED without committed data (observation 2).
* **Speed**: round 2b's speed is kept. Pre vs r017 are within the spread of the rounds on every project, and
  home-assistant `--det` is 1.095x.

## 1. Review tests and suites

* `git diff origin/claude/review-r017 HEAD -- tests/test_review_r017.py`: **empty**, so the file is unchanged.
* `pytest tests` (0599e28, before `test_review_r017b.py` was added): **518 passed, 8 skipped, 1 failed**. The
  failure is `test_review_r017.py::test_h2_…`, as the report says.
* `cargo test --workspace --release`: **detpy-core 61 passed**; detpy-py has 0 Rust tests.
* `test_review_r017.py`: H1 ×2 and H3 pass.

**The H2 test failure is a defect in my round-1 test, not in the fix.**
* p8 `B:*` rows carry `"not_cached": null`, so `.get("not_cached", {})` returns `None` and line 108 raises
  `AttributeError`. It fails the same way on any report.
* Checked with a scratch copy that changes that one expression to
  `((x.get("cache") or {}).get("not_cached") or {})`:
  * It **fails** on the REPORT-R2 of ac0110b with the intended message, and lists `C:r2` / `W:r2` from round index 1
    and the other engines from index 2.
  * It **passes** on 0599e28.
* The author's corrections to my round-1 text are also right: `B:r2` fails from round 3, not round 2.
* The H2 fix is accepted. That one test should be amended on `claude/review-r017` (one expression); the author
  correctly did not change it.

## 2. H1: trying to break the new rewritten-pyc key

| attempt | result |
|---|---|
| `enable_assertion_pass_hook` on/off/on (round-1 tests + author's `test_rewrite_cache.py`) | held |
| `python -O` / `-OO` / none, alternating, same pyc cache (a test that checks `__doc__` against `sys.flags.optimize`) | held: 5 runs, all pass |
| different pytest build at the same version | held by construction: `rewrite.py` is hashed into the key, and `AssertionRewriter` reads only `enable_assertion_pass_hook` from `config` (audited in 9.2: `rewrite.py:694` is the only config read in the rewrite; `:445` is a runtime read) |
| `python_files`, `register_assert_rewrite`, `--assert=plain` | not a content change: they decide *whether* a module is rewritten. A rewritten module and a plain one have different pyc names (`-pytest-9.2.0.det-<key>.pyc` vs `.cpython-313.pyc`) |
| `PYTHONDONTWRITEBYTECODE` set by the user | no effect: `--det` sets it anyway, and detpy writes with pytest's writer |
| two checkouts sharing `DETPY_PYC_CACHE` | held: `get_cache_dir` puts pycs under the prefix plus the source's absolute directory, so two checkouts at different paths never share a pyc. The same path with other content is caught by pytest's source-hash check |
| **a plugin or conftest that patches a method of `AssertionRewriter`** | **broken (F1)** |

### F1: the rewrite key ignores plugins that patch `AssertionRewriter` without replacing it

`_cache_rewritten_tests` refuses to cache only when `rw.rewrite_asserts` or `rw.AssertionRewriter` *is a different
object* (`plugin.py:399`). A plugin that does `AssertionRewriter.run = …` (or `visit_Assert`, `visit_Compare`, …)
keeps both identities, and the key (`_rewrite_key`: pass hook, optimize, `rewrite.py` hash) does not see it. So:

* `--det` without the plugin, then `--det -p plugin`: the second run executes the code the first one wrote. The
  reverse order fails too: in my first draft of the test, a run *without* the plugin picked up the plugin's code.
* With `--det-cache`: adding `-p plugin` changes the configuration digest, so the test re-runs. The re-run executes
  the stale code, and its result is recorded. This is exactly round 1's H1 scenario.
* REPORT-R2b says the key covers "everything the rewrite depends on besides the source and the interpreter/pytest
  version" and that a plugin-replaced rewriter is never cached. That holds only for wholesale replacement.

Tests (fail on 0599e28; the same tests pass with `DETPY_REWRITE_CACHE=0`):
* `test_f1_rewritten_pyc_ignores_plugin_that_patches_rewriter_method`
* `test_f1_cache_records_result_of_stale_rewrite`

Possible fix:
* Add to the key a digest of the rewriter *as loaded*: `marshal.dumps` of the `__code__` of every function in
  `vars(AssertionRewriter)` and of `rewrite_asserts`, plus the identity of anything else in that namespace that is
  not a plain function.
* Compute it at the first read. Re-check it cheaply at each read (a tuple of the dict's values, compared by
  identity), so a conftest loaded later that patches the class also turns the cache off.
* Or refuse to cache whenever that namespace differs from the one `rewrite.py` defines.

## 3. H3: other lossy or missing inputs in the Rust capture/record path

Swept `crates/detpy-py/src` for `from_utf8_lossy`, `.ok()` filters, `to_str`, and `surrogate*` codecs.

Probed end to end (two runs, the input changed in between, expecting `passed` then `failed`):

| input | result |
|---|---|
| env **value** not valid UTF-8 (`environb[b"R17V"]` = `\xff` then `\xfe`) | held |
| conftest option given on argv as non-UTF-8 bytes (`--val=\xff` then `\xfe`) | held |
| `sqlite3.connect(b"\xff.db")` (bytes path) | held |
| `sqlite3.connect("a.db")` (plain path) | held |
| **`sqlite3.connect("file:…", uri=True)`**, with UTF-8 or percent-encoded names | **wrong reuse (F2)** |

The other lossy sites are not keys:
* `sysmon.rs:374` decodes socket inode numbers, which are ASCII.
* `follow.rs:222` and `network.rs` parse numbers or host names and fall back safely.

### F2 (pre-existing, carried into Rust): a database opened through a `file:` URI is not an input

`capture.rs` (`"sqlite3.connect"` arm, about line 1034) returns early for any name that starts with `file:`. So
does the reference, `tests/rust_hotpaths_ref/_ref_proofcache.py:575`.

The skip exists so that detpy's own schema query (`_sql_schema_read` opens `file:…?mode=ro`) is not taken as the
test's read. But it also drops every user connection made through a URI. The recorded test has `"data": []`, and
after the database changes the old `passed` is reused (`reused 1 … ran 0`), although a fresh run fails.

Second-order problem for `%XX` names: `sqlcap.rs::unquote` mirrors `urllib.parse.unquote` with
`errors="replace"`. So `file:%FF.db` and `file:%FE.db` both name `�.db`, a file that does not exist, while
sqlite opens `\xff.db`. The schema clock check therefore looks at the wrong file, and a fix that just stops skipping
URIs would key the wrong path.

Test: `test_f2_sqlite_uri_database_is_an_input`, with 4 parameters (`file:r17b.db`, `?mode=ro`, `%FF`, `%FE`). All
fail on 0599e28 with `['passed', 'passed']`.

Possible fix:
* Exempt only detpy's own connection: the schema read already goes through `_sql_real_connect`, which is not the
  patched `connect`. A flag set around that call is enough.
* Resolve user URIs with `unquote_to_bytes`, so the result is a bytes path, which `badpath` handles when it is not
  valid UTF-8.
* Treat `mode=memory` and `:memory:` as no file.

## 4. Re-derived numbers (REPORT-R2b "Speed")

From the committed `walls`, `cache[*].exit` and `equivalence` of `tracks/rust-hotpaths/results/p9/*.json` (run
`p9`, engine sha 89bc112; `run.json` engines `pre` = ac0110b, `r017` = HEAD; runners 1000010496 / 98 / 500) and
`results/local-r017/profile-{click,pygments}.json`:

| row | cold pre → r017 | floor pre → r017 | `--det` pre → r017 | seconds cold / floor (pre; r017) | exits | store / receipt diffs (noise) |
|---|---|---|---|---|---|---|
| CI click | 1.117 → 1.127 | 0.544 → 0.547 | 0.836 → 0.838 | 9.39 / 4.58; 9.48 / 4.60 | all 0 | 0 / 0 (2 / 0) |
| CI pygments | 1.267 → 1.275 | 0.261 → 0.265 | 1.064 → 1.059 | 24.62 / 5.08; 24.77 / 5.15 | all 0 | 1 / 1 TNTLexer (11 / 11) |
| CI home-assistant 0/16 | 1.269 → 1.266 | 0.312 → 0.312 | 1.097 → 1.095 | 50.95 / 12.53; 50.86 / 12.51 | `W` 0, others 1 | 0 / 0 (444 / 444) |
| local click | 0.954 → 0.938 | 0.430 → 0.438 | 0.721 → 0.729 | 8.85 / 3.99; 8.70 / 4.07 | all 0 | 0 / 0 (2 / 0) |
| local pygments | 1.175 → 1.188 | 0.249 → 0.241 | 0.990 → 0.987 | 20.53 / 4.36; 20.75 / 4.20 | all 0 | 0 / 1 XQueryLexer (25 / 24) |

**Every value matches REPORT-R2b**, as do the quoted ranges (CI pygments floor pre 5.04-5.17 s, r017 5.09-5.20 s).
The labels are right: these are medians of named runs, so MEASURED. The ratios are not mixed across runs.

## 5. Did the fixes undo round 2b's speed?

No.

* **Within one run**, pre vs r017 differ by at most 0.016 in any ratio. Each difference is inside the
  round-to-round spread, and the differences go both ways. Example: the local pygments floor improves while the CI
  one worsens.
* **Against round 2's own CI run** (p8 `r2`, other runners): home-assistant 0/16 was cold 1.261, floor 0.332,
  `--det` 1.093; p9 r017 is 1.266 / 0.312 / 1.095.
* Click and pygments ratios moved between p8 and p9 *for both engines together*: click cold p8 r2 1.029, p9 pre
  1.117 and r017 1.127. That is the runner, not the fix, as the report says.
* The fix's added cost is one `rewrite.py` hash per run and a string rename per read.

## Observations (not findings)

1. **Label: the round-1 H2 test needs the one-expression amendment** (section 1). Until then the suite shows 1
   failure on any branch that carries `test_review_r017.py`.
2. **"r017 wrote and reused 44 keyed rewritten pycs on click and 37 on pygments" is labelled MEASURED from "local
   profile work directories", which are not committed.** I cannot re-derive it from `results/local-r017/`. It does
   not change any number in a table. Call it "observed, not committed", or add the counts to the profile JSON.
3. **No recorded provenance for the local `pre` wheel.** The local `pre` wheel's commit is stated in the report but
   not recorded in `local-r017/*.json` (`engine_sha` is empty). The CI `pre` is recorded (`run.json` ref ac0110b).
4. Agree with the author's observation 1 (import-time `random` in pygments' `test_basic_api`): it explains the one
   pygments store / receipt difference in both CI and local runs. It is not caused by the fixes.

## Files

* `tests/test_review_r017b.py`: F1 (2 tests) and F2 (4 parameters). All 6 fail on 0599e28. The F1 tests pass with
  `DETPY_REWRITE_CACHE=0`.
* This report.
