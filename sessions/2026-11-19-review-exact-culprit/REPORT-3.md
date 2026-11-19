FIX 7: the shipped proof cache (`--det-cache`) reuses a stale pass when a later change adds a module that a failed `try: import` now finds (MEASURED, `test_e1*`), and also for a new `conftest.py`, a namespace package that gains an `__init__.py`, a module that shadows the stdlib, an existing-file check, a vendored zip, a ctypes library and a `.pth` file: 10 failing tests in `harness/culprit/review_r019c/test_cache_stale_reuse.py`. The ini-file change does not cause a wrong reuse. Key validity in the finder states a confident wrong culprit in 5 constructed histories with 0 red-side replays (`test_key_validity_attacks.py`). The same 5 histories are right with inference off. REPORT-4's numbers re-derive exactly, and a re-run of __SAMPLE_N__ population cases gives the same answer in __SAMPLE_SAME__ of __SAMPLE_N__.

# Review R-019c: exact culprit, round 4

* **Target:** branch `claude/exact-culprit` at a1ac749, report `sessions/2026-11-18-exact-culprit/REPORT-4.md`.
* **Branch:** `claude/review-r019c`, created from a1ac749.
* **Labels:**
  * MEASURED: my runs in this review.
  * ESTIMATED: my arithmetic.
  * DECLARED: a source.
  * UNKNOWN.
* **Machine:** one cloud container, 4 cores, CPython 3.13.18 (step 4: 3.9). The engine was built with `maturin develop --release` of a1ac749 into a fresh virtualenv. The population re-runs used a wheel built from the same commit.
* **Brain repository not read.** Attaching `Mircoguidetti/fenvix-brain-cli` to this session was refused by the session's permission policy. So I did not read CLAUDE.md, RULES.md, sessions/README.md or R-019's `REPORT.md`, and this report is not on the brain's `main`.
  * I read R-019b's `REPORT-2.md` from this repository, plus REPORT-4 and the code.
  * The report is on `claude/review-r019c` only. Copying it to the brain's `sessions/2026-11-19-review-exact-culprit/` is left to someone with access.
* **Evidence:** everything is in `harness/culprit/review_r019c/`:

| file | what |
|---|---|
| `test_cache_stale_reuse.py` | item 3: 15 engine tests (pytester, `--det-cache`). **10 fail** (a wrong reuse) and 5 pass. |
| `test_key_validity_attacks.py` | item 2: 6 histories × {round-4 finder, control with `infer_keys = False`}. **5 fail** (a confident wrong culprit) and 7 pass. |
| `rederive.py` | item 1: an independent recount from the committed rows. It recomputes correctness and does not use `aggregate4.py`. |
| `compare_sample.py`, `run_b_sample.sh`, `run_a_sample.sh`, `run_cd_sample.sh`, `sample-rows/` | item 4: re-run drivers (copies of the round-4 drivers with their own output directory), the re-run rows, and the comparison with the committed rows. |

* **Commands:**
  * `python -m pytest -p no:cacheprovider harness/culprit/review_r019c` gives **15 failed, 12 passed** (MEASURED, about 95 s). The 15 failures are this review's findings.
  * `python3 harness/culprit/review_r019c/rederive.py harness/culprit/results`
  * `python3 harness/culprit/review_r019c/compare_sample.py harness/culprit/results harness/culprit/review_r019c/sample-rows`

## Findings

| # | severity | finding | test(s) | result |
|---|---|---|---|---|
| E-1 | **High** (engine, shipped) | **Import resolution is not in the cache key.** A pass is reused after the change in four cases: a module now exists for a failed `try: import` (in a test or in library code); `ns/__init__.py` turns a namespace package into a regular one; a new top-level module shadows a stdlib module the test imports; a `.pth` file in site-packages adds a `sys.path` entry. | `test_e1_try_import_now_finds_a_new_module`, `test_e1b_try_import_in_library_code`, `test_e4_init_turns_namespace_into_package`, `test_e6_stdlib_shadowed_by_new_module`, `test_e9_pth_file_added_to_site_packages` | 5 fail: stale pass reused, plain pytest fails |
| E-2 | **High** (engine, shipped) | **A new `conftest.py` is not in the key.** This holds at the rootdir (no conftest before) and in the test's directory. A change to an *existing* conftest is caught. | `test_e3_new_conftest_in_subdir`, `test_e3b_new_root_conftest` (control `test_e3c_existing_conftest_gains_autouse_fixture` passes) | 2 fail |
| E-3 | Medium (engine, shipped) | **Existence checks are not inputs.** A pass is reused after the file that `os.path.exists` checks for is created. There is no audit event for `stat`. LIMITS K2 covers stat only as a clock source, not as a content input. | `test_e5b_data_file_existence_check` (control `test_e5_data_file_found_by_glob`, a listdir, passes) | 1 fails |
| E-4 | Medium (engine, shipped) | **Binary code inputs are not in the key:** a module imported from a zip archive on `sys.path` (zipimport) and a library loaded with `ctypes.CDLL` (`dlopen`). R2's `REPORT-2.md` DECLARES that zip code has no stat and no facts, but does not say it can be reused stale. | `test_e7_vendored_zip_changes`, `test_e8_native_library_changes` | 2 fail |
| F-1 | **High** (finder) | **Key validity is unsound for every input the key misses that sits outside the guarded directories.** Each history is: C breaks; L works around C through an unrecorded input; harmless; B undoes L. Truth is B. The finder confirms C and infers L, x and B as failing from the red key, with **0 red-side replays**. Four mechanisms: a `try: import` from a `sys.path` directory that holds no recorded input (REPORT-4 §6 lists this as UNKNOWN); a flag file checked with `exists` in such a directory; a namespace package that gains `__init__.py`; and a content change of a vendored zip or a `.so` in a guarded directory (names unchanged). | `test_f1`–`test_f5[key-validity]` | 5 fail: C named, confirmed |
| F-2 | control | The same 5 histories with `infer_keys = False` are right (B, or unknown). So the wrong answer comes from the inference, not from the harness. | `test_f1`–`test_f5[control-no-inference]` | 5 pass |
| F-3 | tried | A `pytest.ini` added next to the test is caught: `tests/` names are guarded. | `test_f6[*]` | 2 pass |
| R-1 | Low (report) | **§2.1 now has an answer.** "Whether the proof cache would reuse a stale result in that case was not tested": it does (E-1). The ini part does not: `filterwarnings = error` and a `getini` option both invalidate (`test_e2*` pass). | | |
| R-2 | Low (report) | **The round-3 denominator includes 2 rows that were never a pass→fail case.** In the committed round-3 rows, rich-home-none is green fail / red fail and rich-home-second is pass / pass. On the 533 valid round-3 cases, round 3 stated 391 / 533 = 73.4%, not 73.1% (ESTIMATED from the rows). Calling them "no longer produced" is accurate only for toolz-env-tz. They were not produced in round 3 either. This does not change any round-4 number. | `rederive.py` | |
| R-3 | Low (labels) | The "replay critical path" in §1 (median 9.2 s, p90 33 s) is arithmetic over measured replays, a model where a batch counts as its longest replay. By REPORT-4's own definitions that is ESTIMATED, not MEASURED. §4 says "without key validity each of those 3,907 would have needed a replay or stayed undecided", with no label and no measurement: UNKNOWN. Round 3's vector inference and same-commit memo would have decided part of them. | | |

**Severity of E-1/E-2:** these are wrong reuses in the shipped `--det-cache`, with plain pytest failing on the same tree. A pull request that adds `pkg/optional.py`, a `conftest.py` or `ns/__init__.py` can be reported green from the cache. They are not new to round 4. They are engine behaviour that REPORT-4 §2.1 came close to and left UNKNOWN. None of E-1 to E-4 is in `docs/LIMITS.md` §8.

## 1. Re-derivation of REPORT-4 (item 1)

`rederive.py` reads the committed rows (`results/*.jsonl` and `results/round3/*.jsonl`) and recomputes correctness as named == truth. It does not trust `finder_correct`. It uses `aggregate2.pct`'s percentile convention, `xs[round(q·(n−1))]`, and also prints nearest-rank. MEASURED from the rows:

| quantity | REPORT-4 | re-derived | match |
|---|---|---|---|
| cases / stated / wrong / unknown | 532 / 517 / 0 / 15 | 532 / 517 / 0 / 15 | yes |
| unknowns with a suspect / suspect = truth | 11 / 11 | 11 / 11 | yes |
| per kind (cases, stated, unknown): a2 placed, a2 reland, b, c no-code, c data edit, d | 196/190/6, 196/196/0, 27/27/0, 35/31/4, 15/15/0, 63/58/5 | same | yes |
| executions median / p90 / max | 11 / 39 / 96 | 11 / 39 / 96 | yes |
| wall per case median / p90 / max | 10.1 / 37 / 239 s | 10.1 / 37.3 / 239 s | yes |
| per-kind executions and wall | table §1 | same (b: p90 45 executions, 53.4 s) | yes |
| round 3: stated / cases, median / p90 / max executions | 391 / 535, 10 / 27 / 43 | 391 / 535, 10 / 27 / 43 | yes (but see R-2) |
| transitions a2 (s→s, u→s, u→u), b (s→s, u→s) | 305, 81, 6; 9, 18 | 305, 81, 6; 9, 18 | yes |
| red-side inferred / replayed (a2 + b) | 3,907 / 3,618 | 3,907 / 3,618 | yes |
| red-side replays median / p90 / max: a2, b, d | 3/23/64, 19/39/46, 9/44/64 | same | yes |
| budget curve 0…64 | 160, 335, 375, 444, 469, 487, 512, 517 | same | yes |
| clean timing w4 / w1: right, median, p90, max, total, executions | 27, 16.2, 38.7, 50.6, 488, 30 (692); 27, 30.7, 66.2, 103.3, 920, 29 (663) | same | yes |
| speedup median / max, same answers | 1.74× / 2.32×, 27 / 27 | 1.74× / 2.32×, 27 / 27 | yes |

* **`finder_correct`:** the field agrees with the recomputed correctness on every row.
* **Case ids:** the round-4 and round-3 sets are identical per kind (no id only in one round).
* **The 3 dropped cases:** they are rows with `skip` set ("no red test that only the change breaks" for toolz-env-tz; "no test that --det and plain pytest agree" for rich-home ×2). They are excluded from 532 and counted in round 3's 535. See R-2 for the two rich-home rows.

## 2. Key validity under attack (item 2)

Each history uses the round-4 harness helpers (`round4/test_finder_round4._find`, `_truth`) unchanged. The truth is the newest transition from a plain walk. MEASURED:

| case | mechanism (what the key does not see) | guard that should apply | finder | with `infer_keys=False` |
|---|---|---|---|---|
| F1 | `sys.path.insert(0, 'extras')` and `try: import fastpath`. L adds `extras/fastpath.py`. | none: `extras/` holds no recorded input, and root names are unchanged because `extras/README` always exists | **C, confirmed**, 2 executions | B |
| F2 | `os.path.exists('flags/compat')`. L adds the file. | none (same reason) | **C, confirmed** | B |
| F3 | `import compat` (namespace package). L adds `compat/__init__.py`. | none: no recorded input inside `compat/` | **C, confirmed** | B |
| F4 | `vendor/lib.zip` on `sys.path`. L replaces the zip, same name. | none: the zip is not an input, and directory names are unchanged | **C, confirmed** | B |
| F5 | `pkg/_native.so` through ctypes. L rebuilds it, same name. | `pkg/` names guarded but unchanged; the `.so` is not an input | **C, confirmed** | B |
| F6 | `tests/pytest.ini` added next to the test | `tests/` names | right (not wrong) | right |
| — | plugin entry point, `.pth`, environment-dependent path | n/a for commit ranges: replays share one environment per side, and pyproject.toml is guarded at the root | not attacked as history; E-1 (`.pth`) and `test_e10` (entry point, caught) cover the cache | |

**Why the guards miss these.** The directory-names guard checks only directories on the path of a *recorded* input, plus the root. An import that failed, a stat that found nothing, or a namespace package leaves nothing recorded, so its directory is never guarded. And a binary input that is not recorded passes "same names" by construction.

**Suggested fix (not implemented; its cost on the population is UNKNOWN):**
* No inference across a commit pair whose tree diff (`git diff --name-status R.sha j`) adds, deletes or renames any path, or changes a path that is not a recorded input and is not a `.py`/text file.
* Better, once E-1 to E-4 are fixed in the engine, rely on the key itself.

## 3. Engine: the proof cache (item 3)

`test_cache_stale_reuse.py` writes commit 1 and runs `--det --det-cache`. It then applies only the change and checks two things: that plain pytest (`-p no:detpy`) now fails, and whether run 2 reused the test.

| test | change | plain pytest | `--det-cache` run 2 |
|---|---|---|---|
| e1 | `pkg/optional.py` added (failed `try: from pkg import optional` in the test) | fails | **reused pass** |
| e1b | `pkg_speedups.py` added (failed optional import in `pkg/core.py`) | fails | **reused pass** |
| e2 | `pytest.ini` gains `filterwarnings = error` | fails | ran, fails (right) |
| e2b | `pytest.ini` sets a `getini` option a conftest reads | fails | ran, fails (right) |
| e3 | `tests/conftest.py` added with a failing autouse fixture | error | **reused pass** |
| e3b | `conftest.py` added at the rootdir (none before) | error | **reused pass** |
| e3c | existing `conftest.py` changed to the same fixture (control) | error | ran (right) |
| e4 | `ns/__init__.py` added | fails | **reused pass** |
| e5 | `data/b.txt` added, test globs `data/*.txt` (control) | fails | ran (right) |
| e5b | `LEGACY_MODE` file created, test checks `os.path.exists` | fails | **reused pass** |
| e6 | `colorsys.py` added at the rootdir | fails | **reused pass** |
| e7 | vendored zip's module changes | fails | **reused pass** |
| e8 | ctypes `.so` rebuilt with another return value | fails | **reused pass** |
| e9 | `.pth` in site-packages adds a directory with the optional module (environment change) | fails | **reused pass** |
| e10 | a `pytest11` entry-point plugin appears in site-packages | fails | ran (right) |

**What would close it (DECLARED, not implemented):**
* Record import resolution per test (module name → resolved origin or "absent", and the `sys.path` entries searched), as a key part.
* Record the set of `conftest.py` paths pytest could load for the test's directory chain.
* Record `stat`/`exists` results of repository paths.
* Hash archives on `sys.path` and libraries loaded through the `ctypes.dlopen` audit event.
* Put the resolved `sys.path` in the runtime digest.

## 4. Population re-run (item 4)

Drivers: copies of `round4/run_b4.sh` and `run_a4.sh`, plus the c and d lanes of `run_c4.sh` and `run_d4.sh`. They use the same budget (64), 4 workers and today's repository heads, and their output goes to a directory of their own. The comparison is `compare_sample.py`. MEASURED:

__SAMPLE_TABLE__

The machine was shared between up to 3 of these lanes, so the wall times are NOISY and are not compared.

## 5. Labels and cost (item 5)

* **Labels.** Every number in REPORT-4 §1 and §4 that I re-derived matches its label, apart from R-3.
  * The budget curve is correctly ESTIMATED. Its caveat (a restart inside a cut batch) is stated.
  * "Each guard is needed (MEASURED)" in §3 was not re-checked here (UNKNOWN to me). F1 to F5 show that the guards are not sufficient.
* **Cost.**
  * The executions and wall numbers re-derive (§1).
  * In the clean timing pass, the per-case speedup from 4 workers is 1.74× at the median (MEASURED from the rows), against an ideal of 4×. REPORT-4's explanation is consistent with the rows: 692 executions with 4 workers against 663 with 1.
  * The R-019 target of a median of 3 executions or fewer is still not met (11). REPORT-4 says so.
* **What a sound fix would cost:** the finder rule suggested in §2 would remove some of the 3,907 inferences (number UNKNOWN). The 97.2% stated share should be re-measured after any fix.

## 6. Verdict detail

* **On the measured populations:** "517 of 532 stated, 0 confident wrong" stands (MEASURED re-derivation; the re-run sample agrees).
* **As a method:** key validity is **not sound** for inputs the key does not record outside the guarded directories (F-1).
  * REPORT-4 §6 scopes "0 confident wrong" to the measured cases and names one of these shapes as UNKNOWN. That shape is now a confident wrong answer in 2 executions, and so are 4 more.
* **In the engine:** the shipped cache has 4 classes of wrong reuse (E-1 to E-4). E-1 and E-2 are High because a single common change (adding a module, adding a conftest) triggers them.

**To clear this review:** fix E-1 and E-2 in the engine, or make the cache refuse (not reuse) when the import or conftest set may differ. Fix or declare E-3 and E-4 in `docs/LIMITS.md`. Make F1 to F5 non-wrong, either through the engine fixes or through the tree-diff guard in §2. Then re-measure the stated share. Also correct R-1 to R-3.
