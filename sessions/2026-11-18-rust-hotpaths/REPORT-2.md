DONE

# rust-hotpaths, round 2: fixes for review R-015 (F1-F4)

Branch `claude/rust-hotpaths`. Review: `claude/review-r015`,
`sessions/2026-11-18-review-rust-hotpaths/REPORT.md` (verdict FIX 4). Its tests, `tests/test_review_r015.py`, are copied
unchanged (20ad9b3).
Labels: MEASURED (numbers from runs named here), ESTIMATED (derived or inferred), unmarked = description.

**Result.** All four findings are fixed. Every fix closes a way the cache could record a result under code that did not
produce it. None of them adds a reuse: each one either adds a refusal or makes bytecode validation stricter. The
re-profile (click, pygments, home-assistant 0/16; base 3d20406 vs the fixes, interleaved in the same jobs) shows
**no added overhead**:

* click and pygments are within noise;
* home-assistant `--det` is faster: 35.05 s -> 32.47 s (MEASURED).

The stores and warm-run decisions are identical to the base outside known noise, except for the bytecode files'
own bytes (below).

## Tests: fail before the fix, pass after (MEASURED, local)

`pytest tests/test_review_r015.py -k "F1 or F2 or F3 or F4"`, with the engine rebuilt at each commit:

| commit | F1 | F2 | F3 | F4 |
|---|---|---|---|---|
| 20ad9b3 (review tests on 3d20406) | fail | fail | fail | fail |
| c8798ee F2/F3: checked-hash bytecode | fail | **pass** | **pass** | fail |
| c7904e1 F1: code changed during the session | **pass** | pass | pass | fail |
| 4c4bcfd F4: report correction | pass | pass | pass | **pass** |

The review's fifth test, `test_record_session_matches_reference_with_wider_scopes`, passes throughout.

Suites at HEAD (MEASURED, local, Python 3.13):

* `pytest tests`: **164 passed, 6 skipped**, 0 failed.
* `cargo test -p detpy-core`: **49 passed**.

The review had 158 passed and 7 skipped plus its 4 failures, on its own machine. Here there is one test more
(`tests/test_r015_fixes.py`), and the skips depend on the environment: this container skipped 6 before the fixes too.

## F3 (regression from #2) and F2 (pre-existing): bytecode validated by content

**Cause.** A timestamp `.pyc` is valid for `(int(mtime), size)`.

* #11 dropped only project bytecode of sources with an mtime within 2 s of the precompile.
* #2 made venv libraries load from cached bytecode with no such check.
* A same-size edit whose mtime stays in the same second therefore ran the old code. Examples: restored commit
  times, another machine's clock, archive mtimes, a reinstalled library module.
* The run then recorded the result under the new content digest (F2) or the new runtime identity (F3).

**Fix (c8798ee).** The precompile now writes **checked-hash pycs** (PEP 552) for the stdlib, site-packages and the
project:

* The header holds a hash of the source that was compiled.
* Before using a `.pyc`, the import system reads the source and compares the hash. On a mismatch it compiles from
  source, under the same fixed seed.
* Stale bytecode cannot run, whatever the mtime, the size, or the clock that set them.

This keeps #2's gain, because libraries still load from bytecode, so #2 is not reverted.

Implementation details:

* **Own driver.** `compileall` recompiles every hash-based `.pyc` on every run, so the precompile uses its own
  driver, `python/detpy/_pycompile.py`. It is run as `python -c <its text>` in the child interpreter under the
  fixed seed and `PYTHONPYCACHEPREFIX`. The working directory is removed from `sys.path`.
* **Same file set as `compileall`.** It skips `__pycache__`, does not enter symlinked directories, and applies the
  same `-x` exclusions to the project only.
* **Skip rule.** It skips a module whose `.pyc` header already equals magic + checked flag + the hash of the
  current source. Anything else goes to `py_compile` (`CHECKED_HASH`), which hashes the bytes it compiles.
* **Parallelism.** Fork-context pool over chunks.
* **Removed.** `_drop_fresh_pycs` (#11) is no longer needed.
* **Migration.** `stamps-v3.json`: every library directory is checked once more, which converts existing timestamp
  pycs.

Cost (MEASURED, local container, 4 CPUs):

| what | timestamp pycs (before) | checked-hash pycs (now) |
|---|---|---|
| up-to-date check, all 5,367 `.py` under `/usr/local/lib/python3.13` (2 warm runs) | `compileall -j 0`: 0.55 s, 0.59 s | driver: 0.13 s, 0.11 s |
| first compile of the same tree | 3.8 s | 3.5 s |
| import of 3,000 synthetic modules (24 MB of source), median of 5 | 0.708 s | 0.770 s (about +20 us per module: the source read and hash) |
| the same modules compiled from source (what #2 replaced) | 5.6 s | 5.6 s |

* The project is checked on every run; that check is now cheaper than `compileall`'s timestamp check.
* Libraries are checked only when their directory stamp changes, as before.
* Import pays the hash check per module loaded.

On home-assistant the net effect is a faster `--det` (table below). ESTIMATED cause: the project's up-to-date check
(`compileall`'s per-file process pool plus #11's walk, against the driver). The precompile time is not broken out
in the profile results.

Tests:

* `tests/test_precompile_stamp.py::test_project_bytecode_is_checked_against_the_source_content` replaces #11's
  fresh-drop test. It checks the checked-hash header and that an unchanged source is not recompiled.
* The same test checks that a same-size, same-mtime edit runs the new code before the next precompile and gets a
  matching pyc after it.
* The review's F2 and F3 tests pass.

## F1 (pre-existing): a source edited during the session

**Cause.** A test's code digests were taken at the end of the session. An edit made after a module was loaded was
recorded as if the test had run the new code.

**Fix (c7904e1).** The capture takes a stat key, `(size, mtime_ns, ctime_ns, inode)`, of every repository code file
at one of two moments:

* in the `open` audit event, before the read, the first time its source is opened for reading (`.py` under the
  root). The import system (which now always reads the source to check its hash), pytest's assertion rewrite and
  `runpy` all open it this way;
* otherwise, when its module body first runs (the `exec` audit event), or at capture start for preloaded modules.

At record time, files whose key changed go to the plan as `changed`. `record_session` (Rust) refuses every test
whose code inputs include one:

* units in its contexts;
* global import-time units in scope;
* whole-content files (preloaded, unparsable);
* skeleton and hooks loaded before it.

The refusal reason is `why = "source changed during the session: <path>"`, and the test's previous entry is
dropped as for every other refusal. `ctime` cannot be set back by `utime`, so a restored mtime does not hide an
edit.

**Granularity.** The check is per file. By the existing design, a non-test module's import-time lines are inputs of
every test in scope. So editing such a module during the session refuses every test that ran after its import. A
test module serves only its own tests. This costs reuse, not correctness, and only in sessions with an edit during
the run.

Tests:

* the review's F1 test, which reproduces the scenario and passes;
* `tests/test_r015_fixes.py`: a test module edited during the session refuses only its own test. The next run
  reuses the untouched test and runs the edited one, which fails.

## F4: the report

`sessions/2026-11-18-rust-hotpaths/REPORT.md` was corrected (4c4bcfd), re-derived from the raw results:

* **p3 home-assistant shard 5 added.** Cold/plain is now **1.20-1.41x** (base 1.36-1.57x); `--det`/plain is
  1.08-1.25x.
* **Walk rows at the finished walks (3d20406).** I re-ran `compare_walks.py` against the base walk s1f from
  `claude/cache-proof-step1`:
  * home-assistant: 49 commits, 374,443 / 374,425 reused, 63.7% / 64.6% of test time, 15 commits differing by 1-2
    results;
  * pygments: 50 commits, 58,136 / 58,136.
* **Wrong reason fixed.** The stated reason for the earlier commit limit was wrong: it was w1 shard 4, not the
  base walk.
* **Labels.** Ratios of medians are labelled ESTIMATED. Where the median of per-round ratios differs by more than
  0.05, it is given in brackets. This replaces the claim that the base's cold run was faster than its `--det` run.
* **Bytecode section.** The section on the bytecode changes notes that this report supersedes it. `docs/LIMITS.md`
  (R2) describes the checked-hash precompile (bf5da84).

## Overhead after the fixes (MEASURED, GitHub Actions run `p5-r015`)

`harness/rust_hotpaths/profile.py`, same method as p2/p3: base = 3d20406 (the branch before these fixes),
new = b757657 (the fixes; later commits change no engine code), interleaved in one job per project. Results are in
`tracks/rust-hotpaths/results/p5-r015/`. Walls are MEASURED medians; ratios are ESTIMATED (ratio of medians,
median of per-round ratios in brackets where it differs by more than 0.01).

| project | rounds | plain | `--det` base / new | cold base / new | warm base / new | `--det` / plain base / new | cold / plain base / new |
|---|---|---|---|---|---|---|---|
| click | 5 | 8.00 s | 8.68 / 8.53 s | 10.84 / 10.76 s | 5.84 / 5.77 s | 1.08x / 1.07x | 1.35x / 1.35x |
| pygments | 5 | 19.48 s | 21.41 / 21.26 s | 25.20 / 24.95 s | 6.40 / 6.33 s | 1.10x / 1.09x | 1.29x / 1.28x |
| home-assistant 0/16 | 3 | 28.85 s | 35.05 / **32.47 s** | 38.19 / **36.65 s** | 11.59 / 10.83 s | 1.22x / **1.13x** | 1.32x (1.34x) / **1.27x** |

* The home-assistant `--det` gain is consistent across rounds: base 35.2 / 34.7 / 35.0 s, new 32.5 / 32.5 / 30.9 s.
* Cold over `--det` (the capture itself) is 1.09x / 1.13x (per-round 1.10x / 1.16x). The capture code is unchanged
  apart from F1's stat at the first open and at the end. So this is the faster `--det` run moving the
  denominator, not a costlier capture (ESTIMATED).
* Record phases on home-assistant are equal (MEASURED, per run): facts 1.40-1.46 s, assemble 0.39 s, save 0.21 s.
* Every home-assistant variant, plain pytest included, exits 1, as in p3. This is a failing test of the shard,
  not detpy.
* Single py-spy profiles per variant are also in the results; they are one run each and not wall-time evidence.
* Local supplement (MEASURED, this container, 3 rounds, trimmed result in
  `tracks/rust-hotpaths/results/local-r015/pygments-0of1.json`): pygments `--det` 1.11x / 1.11x, cold 1.30x /
  1.28x, warm 4.6 / 4.4 s.

Runner variance between jobs is 10-30 % (REPORT.md). Compare base and new within a row, not across runs: in this
run the base's home-assistant 0/16 cold/plain is 1.32x, against 1.28x in p3.

### Same decisions as the base (MEASURED, `profile.py` compare)

| project | entries | store differences | warm-decision differences | noise (same engine, two rounds) |
|---|---|---|---|---|
| click | 2,616 | **2** (see below) | **0** | 0 |
| pygments (CI / local) | 5,346 | **0** / **0** | **0** / **0** | 10 / 24 (`test_random_input[...]`) |
| home-assistant 0/16 | 444 | 0 outside noise | 0 outside noise | 444 of 444 |

* **The two click differences** (`test_light_imports`, `test_path_dash_no_byteswarning`) are data inputs only:
  30 `.pyc` files of the bytecode cache that a followed child process reads. Their bytes differ because they are
  now checked-hash pycs. Nothing else in the entries differs.
  * Consequence: such tests miss once after upgrading to this engine (their data inputs change), then reuse
    again. The same happens once per library upgrade, as before.
* **home-assistant.** As in p3, its global capture varies run to run in the base engine as well (REPORT.md
  finding 2). This comparison therefore shows only that there is no systematic difference. The written-paths maps
  are equal.
* **Probe.** The equivalence probe on home-assistant's environment: facts on 3,000 files and distribution identity
  on all 1,727 distributions are identical between the old and new paths.

## What is still open

* **F1, stat granularity.** A write after the stat is missed only if it leaves size, mtime_ns, ctime_ns and inode
  all unchanged. That needs a same-size, in-place write within the same filesystem timestamp tick (a few ms) as an
  earlier write that preceded the stat.
  * Code read with no `open` event and no module body run is not covered; I know of no such path for repository
    code.
  * Code imported from a zip archive inside the repository has no stat, and had no facts before either
    (pre-existing; it was never an input).
* **F2/F3, validation strength.** Validity is CPython's 64-bit SipHash-1-3 of the source bytes
  (`importlib.util.source_hash`). An accidental collision is about 2^-64 per changed file. It is not a
  cryptographic guarantee.
  * An interpreter started with `--check-hash-based-pycs never` would skip the check. detpy does not detect that
    flag.
* **One-time costs after upgrading.**
  * every library directory is checked again: first-compile cost, 3.5 s for the local stdlib + site-packages,
    more on home-assistant;
  * the tests above whose children read cached `.pyc` files miss once.
* **No new verification walk was run in this session.** The 0-wrong-reuse evidence for the unchanged parts remains
  the w1 walk (REPORT.md). These fixes only add refusals or make bytecode validation stricter. The decisions on
  click, pygments and home-assistant 0/16 are identical to the base, apart from the noise noted above.

## Commits (for the merge into `claude/rust-hotpaths-2`)

| commit | content |
|---|---|
| 20ad9b3 | `tests/test_review_r015.py`, unchanged from `claude/review-r015` |
| c8798ee | F2/F3: `python/detpy/_pycompile.py` (new), `python/detpy/reexec.py`, `tests/test_precompile_stamp.py` |
| c7904e1 | F1: `python/detpy/proofcache.py`, `crates/detpy-core/src/record.rs`, `tests/test_r015_fixes.py` |
| 4c4bcfd | F4: `sessions/2026-11-18-rust-hotpaths/REPORT.md` |
| bf5da84 | `docs/LIMITS.md` R2 |
| 1fb94c6, b757657 | `tracks/rust-hotpaths/run.json`: run `p5-r015`. The run id is not `p4` because round 2's run on `claude/rust-hotpaths-2` uses that id; 1fb94c6's run was cancelled before it started |
| ef2b2ec, dc4be99, 38f571b | results committed by the workflow |
| (this commit) | this report, `tracks/rust-hotpaths/results/local-r015/` |
