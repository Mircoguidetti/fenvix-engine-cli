DONE

# rust-hotpaths, round 2c: review R-017b (FIX 2) and review R-019b N5 fixed

Branch `claude/rust-hotpaths-2`. Reviews: `claude/review-r017b` (`sessions/2026-11-19-review-rust-r2/REPORT-2.md`,
failing tests `tests/test_review_r017b.py`, merged unchanged at 35ba3a8) and `claude/review-r019b`
(`sessions/2026-11-19-review-exact-culprit/REPORT-2.md` §2 N5, case
`harness/culprit/review_r019b/test_wrong_culprits_r2.py::test_det_replay_runs_the_checked_out_source_not_stale_bytecode`).

Labels: **MEASURED** (a named run, data committed unless said otherwise), **ESTIMATED** (derived). "pre" = the engine
before these fixes (35ba3a8, the same engine as 0599e28 / REPORT-R2b), "r017b" = with them (a3bdcf1).
Environment: CPython 3.13.18, pytest 9.2.0, `maturin develop --release` into fresh virtualenvs (one per engine).

## Commits

| commit | what |
|---|---|
| 35ba3a8 | merge of `claude/review-r017b` (fast-forward): `tests/test_review_r017b.py` and the review report, unchanged |
| 6946e52 | **F1**: rewritten-test pycs keyed on the rewriter *as loaded* (`plugin.py`) |
| 78553a1 | **F2**: sqlite databases opened through a `file:` URI (and with `ATTACH`) are inputs; bytes-exact `%XX` (`capture.rs`, `sqlcap.rs`, `proofcache.py`, the Python reference) |
| d1730be | **N5**: hash-checked project bytecode under `--det` without the bytecode control (`precompile.rs`: `HashCheckedPycs`; `plugin.py`: the importlib interface) + `tests/test_det_stale_bytecode.py` (the ported case) |
| 9bfa03e | `tests/test_r017b_fixes.py`: cases beyond the reviewer's (a conftest that patches the rewriter, digest stable across runs, `ATTACH`, bytes-exact names) |
| 62be5f5, a3bdcf1 | F1 follow-up found by the profile: the digest had the install path in it (below) |

## Findings: finding -> fix -> test before / after

### F1: the rewritten-pyc key ignored plugins and conftests that patch a method of `AssertionRewriter`

**Finding (confirmed).** `_cache_rewritten_tests` refused to cache only when `rewrite_asserts` or
`AssertionRewriter` was *another object*. A plugin doing `AssertionRewriter.run = …` keeps both, and the key (pass
hook, optimize, `rewrite.py` hash) did not see it, so `--det -p plugin` ran code an earlier run wrote without the
plugin (and the reverse), and `--det-cache` recorded that result.

**Fix (6946e52, 62be5f5, a3bdcf1; `plugin.py:_rewrite_key`, `_rewriter_digest`, `_rewriter_snapshot`).** The key
now also holds a digest of the rewriter as loaded:
* every value of `rewrite.py`'s namespace and of `AssertionRewriter`'s, by name, and `rewrite_asserts`;
* a function is its code (bytecode, constants, names, argument counts and flags, recursively into nested code; not
  file names or line numbers), its defaults, its closure cells and the globals its code names. Functions are
  followed wherever they are defined (the plugin's replacement *and* the original it wraps through its closure);
  a function's globals are followed within its own module (a plugin's helpers), other modules' objects are named;
* a class of `rewrite.py` (or of the referring function's module) is its name, bases and namespace; constants are
  their `repr`; modules their name; other objects their type;
* module metadata (`__file__`, `__cached__`, `__spec__`, `__loader__`, `__builtins__`) and detpy's own wrappers
  (`_read_pyc`, `_rewrite_test`, whose closure holds the memo) are left out, so the same pytest gives the same key
  in every install.

It is computed at the first read or write (1.7-3.7 ms, observed with `time.perf_counter` on this machine for the
first version of the digest, not committed; once per run)
and **re-checked at each read and write** by the identity of the two namespaces' values (a tuple compare, ~10 µs).
A conftest loaded after the first reads that patches the rewriter changes the key from then on. A replaced
`rewrite_asserts` / `AssertionRewriter` is still not cached at all; `DETPY_REWRITE_CACHE=0` still turns it off.

What it does not cover (documented in the docstring): a patch of a function in *another* module that the rewriter
calls (e.g. `ast.*`, `_pytest.assertion.util`), if made after the first read. Before the first read, such a patch
of an object the rewriter's namespace holds is seen; a deeper one in another pytest module is not. This is the same
boundary the reviewer proposed (`vars(AssertionRewriter)` + `rewrite_asserts`), widened to `rewrite.py`'s
namespace and to a patch's own helpers.

**Follow-up found while measuring (62be5f5, a3bdcf1).** The first version put the install path into the digest
(`rw.__file__`, then through `memo` in detpy's own closure and `__file__` named in `_rewrite_key`): the profile's
click and pygments venvs (same pytest) got different keys. Not a correctness problem (each install was stable
across its runs: one key per project over all profile runs), but it contradicted the intent. Fixed and
MEASURED: a dump of the digest's input from inside a `--det` collection in both venvs is now byte-identical.

**Tests.**

| test | before (pre) | after (r017b) |
|---|---|---|
| `test_review_r017b.py::test_f1_rewritten_pyc_ignores_plugin_that_patches_rewriter_method` | FAILED (the `-p` run loaded the pyc the no-plugin run wrote) | passed |
| `test_review_r017b.py::test_f1_cache_records_result_of_stale_rewrite` | FAILED (`'failed' == 'passed'`) | passed |
| `test_r017b_fixes.py::test_f1_conftest_patching_the_rewriter_gets_its_own_pycs` (new: a conftest patches when an env var is set; runs 0, 1, 0, 1) | FAILED | passed |
| `test_r017b_fixes.py::test_f1_digest_is_stable_across_runs` (new: one keyed pyc after two runs) | passed | passed |
| `test_rewrite_cache.py` (3), `test_review_r017.py` H1 ×2 | passed | passed |

### F2 (pre-existing, carried into Rust): a database opened through a `file:` URI was not an input

**Finding (confirmed).** `capture.rs` (`"sqlite3.connect"` arm) and the Python reference returned early for every
name starting with `file:`, to exempt detpy's own schema query. A test's `sqlite3.connect("file:…", uri=True)` was
recorded with no input, and the old result was reused after the database changed. `sqlcap.rs::unquote` also decoded
`%XX` as UTF-8 with `errors="replace"`, so `file:%FF.db` and `file:%FE.db` both named `�.db`.

**Fix (78553a1).**
* **Only detpy's own connection is exempt.** The `sqlite3.connect` audit event carries the name only, not `uri`. So
  the patched `sqlite3.connect` sets a per-thread *connect mode* around the real call (`_core.sql_connect_mode`,
  Rust thread-local): plain, URI, or detpy's own (`_sql_schema_read`, which goes through `_sql_real_connect`). The
  audit arm reads it:
  * own: nothing recorded;
  * URI: the file sqlite opens (`sqlite_file_str`: `//localhost/` hosts, `?`/`#` cut, `mode=memory` and
    `:memory:` = no file);
  * plain: the literal name (as before; a `file:` name is then a plain relative file name);
  * unknown (a direct `_sqlite3.connect`, no patched call around it): **both** the literal name and the URI's file.
    Conservative: an extra input can only cause a re-run.
* **Bytes-exact names.** `unquote` now percent-decodes `os.fsencode(name)` to bytes (as sqlite's URI parser does,
  stopping at a decoded NUL) and gives the path back as `os.fsdecode` would (surrogate escapes for bytes that are
  not UTF-8). A non-UTF-8 name then refuses the test through the existing `badpath` rule, and the schema-clock
  check stats the real file. `_sql_schema_read` now quotes `os.fsencode(path)`, so it can open such a file.
* **`ATTACH` (same class, not in the review).** An attached database had no audit event and was not an input
  either, only a schema source. It is now recorded like the main database (`CaptureCore::sql_database`, shared by
  both paths).
* The Python reference (`tests/rust_hotpaths_ref/_ref_proofcache.py`) has the same change, so
  `test_capture_rust.py` / `test_sqlcap_rust.py` keep comparing like with like (they pass).

**Tests.**

| test | before (pre) | after (r017b) |
|---|---|---|
| `test_review_r017b.py::test_f2_sqlite_uri_database_is_an_input[file:r17b.db]` | FAILED `['passed', 'passed']` | passed |
| `…[file:r17b.db?mode=ro]` | FAILED `['passed', 'passed']` | passed |
| `…[file:%FF.db?mode=ro]` | FAILED `['passed', 'passed']` | passed (refused: `badpath`) |
| `…[file:%FE.db]` | FAILED `['passed', 'passed']` | passed (refused: `badpath`) |
| `test_r017b_fixes.py::test_f2_attached_database_is_an_input` (new) | FAILED `['passed', 'passed']` | passed |
| `test_r017b_fixes.py::test_f2_uri_names_decode_bytes_exact` (new, 6 cases) | 3 FAILED (`%FF`, `%FE`, `%00`), 3 passed (`%C3%A9`, `%zz`, `mode=memory`) | 6 passed |
| `test_capture_rust.py`, `test_sqlcap_rust.py` (Rust vs reference) | passed | passed |

### N5 (review R-019b, engine): stale bytecode under `--det`, recorded as a false pass

**Finding: reproduced, but on this branch only without the bytecode control.** The reviewer's engine
(`claude/exact-culprit` at 13033d7) precompiled timestamp pycs. On this branch `--det` with its bytecode control
already reads only the precompile's checked-hash pycs (R-015), and the reviewer's own test, run unchanged against
this engine from a scratch copy of `harness/culprit`, **passes** (1 passed). But whenever `--det` runs *without*
the bytecode control, the import system uses the project's `__pycache__` timestamp pycs (`(int(mtime), size)`),
and the same-size, same-second checkout runs the previous version (MEASURED, pre engine):

| mode | green, bad (expected `passed`, `failed`) |
|---|---|
| `--det` (bytecode control on) | passed, failed |
| `--det --det-no-reexec` | passed, **passed** |
| `--det --det-disable=bytecode` | passed, **passed** |
| `PYTHONHASHSEED=0` preset | passed, failed |

The same holds whenever a re-exec is not possible (`reexec.can_reexec()` false). With `--det-cache`, the bad
version's run re-runs (its source digest changed) and records the old pass under the new digest.

**Fix (d1730be).** Under `--det` without the bytecode control, `SourceFileLoader.get_code` is patched (the
importlib interface, `plugin._hash_checked_imports`) for **project sources**: under the rootdir and not under one
of the precompile's excluded names (`.git`, `.tox`, `.venv`, `venv`, …), i.e. the precompile's own definition of
the project. The decision and the hash are in Rust (`_core.HashCheckedPycs`, `precompile.rs`): it reads the
source, computes `importlib.util.source_hash` (the existing SipHash) and returns the cached pyc only when it is a
hash-based pyc (PEP 552) of exactly this source and magic number. Otherwise the source is compiled and, when
bytecode may be written, cached as a *checked-hash* pyc, which plain Python then validates by hash too. Libraries
keep the import system's own check. If the Rust hash does not match the interpreter's (`_hash_variant()` None),
project pycs are never read. With the bytecode control on, nothing changes (the precompile's pycs are already
checked-hash, and the import system checks them).

**Tests** (`tests/test_det_stale_bytecode.py`: the reviewer's case, ported, 3 rounds instead of 5, in the three
modes; the same helpers as `harness/culprit/common.run_det`).

| test | before (pre) | after (r017b) |
|---|---|---|
| `test_det_runs_the_checked_out_source_not_stale_bytecode[default]` | passed | passed |
| `…[no-reexec]` | FAILED (`('pass', 'pass')`) | passed |
| `…[bytecode-disabled]` | FAILED (`('pass', 'pass')`) | passed |
| `test_det_cache_does_not_record_a_false_pass[default]` | passed | passed |
| `…[no-reexec]` | FAILED (recorded a false pass) | passed |
| `…[bytecode-disabled]` | FAILED (recorded a false pass) | passed |
| `test_pyc_written_without_bytecode_control_is_checked_hash` | FAILED (flags 0: timestamp pyc) | passed |
| the reviewer's original test, unchanged, against this engine | passed (pre) | passed |

The `[default]` rows pass before the fix: on this branch the bug is not in the default path. They are kept as
regression tests for it.

## Gates

| gate | result |
|---|---|
| `tests/test_review_r017b.py` (unchanged) | **6 passed** (pre: 6 failed) |
| `tests/test_review_r017.py` (unchanged) | 3 passed, 1 failed: `test_h2…` with the known defective expression (`AttributeError` at line 108), as in REPORT-R2b; the reviewer confirmed it is their test's defect (REPORT-2 §1) |
| full Python suite (`pytest tests`, a3bdcf1) | **540 passed, 8 skipped, 1 failed** (the `test_h2` above). REPORT-R2b had 518 passed: the 22 new are the 6 R-017b, 7 N5 and 9 extra tests |
| `cargo test --workspace --release` | detpy-core **61 passed**; detpy-py 0 Rust tests |

## Speed

### `--det` and `--det-cache` (the default path): kept

Local profile, `harness/rust_hotpaths/profile.py --reps 3 --no-probe --clean-tmp`, engines interleaved in each
round, wheels built here (pre = 35ba3a8, r017b = a3bdcf1). Medians of wall time divided by the plain-pytest (`P0`)
median of the same run. `B` = `--det`, `C` = cold `--det-cache`, `W` = fully reused ("floor"). MEASURED:
`tracks/rust-hotpaths/results/local-r017b/profile-{click,pygments}.json`.

| project | rounds | cold / plain pre → r017b | floor / plain pre → r017b | `--det` / plain pre → r017b | exits | store / receipt diffs outside noise (noise) |
|---|---|---|---|---|---|---|
| click | 3 | 1.028 → 0.971 | 0.499 → 0.477 | 0.798 → 0.761 | all 0 | 0 / 0 (2 / 0) |
| pygments | 3 | 1.328 → 1.339 | 0.265 → 0.279 | 1.062 → 1.075 | all 0 | 0 / 0 (12 / 12) |

In seconds (medians; the three rounds in brackets):

| | pre cold / floor / `--det` | r017b cold / floor / `--det` | plain |
|---|---|---|---|
| click | 9.65 / 4.68 / 7.48 (cold 9.49-10.05, floor 4.51-5.26) | 9.11 / 4.47 / 7.14 (cold 9.07-9.58, floor 4.24-4.71) | 9.38 |
| pygments | 23.39 / 4.66 / 18.70 (cold 23.22-23.73, floor 4.57-5.18) | 23.58 / 4.92 / 18.93 (cold 22.70-25.21, floor 4.44-5.27) | 17.62 |

Reading:
* Every pre → r017b change is inside the spread of the rounds, and the direction differs by project (click
  faster in all three columns, pygments slower in all three). No change is outside the spread.
* Two earlier profile runs of this session, with the intermediate F1 commits (6946e52-era wheel, then 62be5f5),
  went the other way on pygments (for example floor 0.255 → 0.250 and 0.274 → 0.268). Their JSON was overwritten
  by the final run, so those numbers are **observed, not committed**.
* What the fixes add on this path: the rewriter digest once per run (1.7-3.7 ms observed), a tuple identity check
  per rewritten-module read and write, and a thread-local set/reset around each `sqlite3.connect`. N5 adds nothing
  here: with the bytecode control on, `get_code` is not patched.
* The rewritten-module cache is kept: r017b wrote and reused 44 keyed pycs on click and 37 on pygments, under one
  key shared by both projects (`2e163c7d8db35fa0`), as pre did under its own key (MEASURED, counted in the work
  directories after the runs: `results/local-r017b/rewrite-pycs.json`; the directories are not committed).
* These ratios are not comparable with REPORT-R2b's local ones (another container: plain click 9.38 s here vs
  8.85 s there). The pre vs r017b columns of one row are.

### `--det --det-no-reexec` (the N5 path): what hash-checked project bytecode costs

`harness/rust_hotpaths/noreexec_timing.py` (new), on the profile's work directories: per block, install one wheel,
remove the checkout's `__pycache__` (each engine reads only pycs it wrote), one warm-up run, then 3 timed runs;
2 blocks per engine, alternating, and plain pytest timed the same way. MEASURED:
`results/local-r017b/noreexec-{click,pygments}.json`.

| project | `--det --det-no-reexec` / plain, pre → r017b | seconds pre → r017b (6 runs each) | exits |
|---|---|---|---|
| click | 0.709 → 0.742 | 7.32 (6.69-7.44) → 7.65 (7.25-7.82) | all 0 |
| pygments | 1.122 → 1.112 | 20.47 (18.79-21.72) → 20.29 (18.52-21.31) | all 0 |

* **click: +0.33 s (+4.5 %), MEASURED.** The ranges barely overlap, so I count it as a real cost. Its cause is
  not isolated. Hashing alone is unlikely to explain it (ESTIMATED: click has ~20 project modules outside the
  rewritten tests). The other candidate is the Python `get_code` wrapper, which now sits on every import, library
  ones included.
* **pygments: no measurable cost.** The spread between blocks (about 3 s) is larger than any difference.
* This path is the fallback, used only when `--det` cannot fix its bytecode. A run with the control on (the
  default, and every row above) is unaffected.

## Observations (not findings; not changed here)

1. **`test_h2` (round 1) still needs the reviewer's one-expression amendment** on `claude/review-r017`. Left
   unchanged here as instructed.
2. **Reviewer observation 2 (rewritten-pyc counts not committed) is addressed for this round:**
   `results/local-r017b/rewrite-pycs.json` holds the counts, read from the profile's work directories after the
   runs (the directories themselves are not committed).
3. **Reviewer observation 3 (no provenance of the local `pre` wheel):** the local `pre` here is 35ba3a8 (built from
   a worktree of that commit), r017b is a3bdcf1. `profile.py` still leaves `engine_sha` empty for local runs.
4. **Import-time randomness** (REPORT-R2b observation 1) is still the only source of the pygments store / receipt
   differences.
5. **The N5 fix leaves the bytecode control's own path as it was.** If a project module is *not* precompiled (for
   example a project under a directory named `venv`), it is compiled from source at every `--det` run (no pyc is
   written under the control), which is correct but not cached. Unchanged from before.
