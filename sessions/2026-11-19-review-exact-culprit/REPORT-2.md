FIX 6: the eight R-019 findings are fixed in substance, and the headline numbers re-derive exactly. But four new kinds of input still make the round-2 finder name a wrong culprit with confidence (High). The engine's stale-bytecode bug is reproducible and writes a false pass into the proof key (High). And 52 of the 63 carried-over step-4 rows were measured under that bug's trigger condition (Medium). Recommended verdict for P-029: **PARTIAL** stands, with "0 confident wrong" restricted to the measured populations.

# Review R-019b (last round): exact culprit, round 2

* **Target:** branch `claude/exact-culprit` at 13033d7, report `sessions/2026-11-18-exact-culprit/REPORT-2.md`. The first review is `claude/review-r019`, `sessions/2026-11-19-review-exact-culprit/REPORT.md`.
* **Branch:** `claude/review-r019b`, created from 13033d7.
* **How it was run:**
  * the engine was built with `maturin develop --release` into a fresh CPython 3.13.18 virtualenv;
  * the finder and harness were used unchanged;
  * new cases call `finder.Finder` exactly as `review_r019/test_wrong_culprits.py` does, with the same helpers, imported from it.
* **Evidence:** everything is in `harness/culprit/review_r019b/`:
  * `test_wrong_culprits_r2.py`: 6 cases. 5 fail, and 1 passes (a tried attack that the finder handles).
  * `test_carried_over.py`: 1 failing check over committed data. No engine is needed.
  * `stale_d.py` and `stale-d.jsonl`: the step-4 probe reconstruction for item 5.
  * `trivial_rules.py` and `trivial-rules.json`: the extra trivial rules for item 3.
* **Command:** `python -m pytest -p no:cacheprovider harness/culprit/review_r019 harness/culprit/round2/test_finder_round2.py harness/culprit/review_r019b`. Result here: **9 failed, 11 passed** (150 s).
  * 3 of the failures are R-019's stale M6/M7/M8 assertions; see §1.
  * The other 6 are this review's findings.

## 1. The eight R-019 findings

`git diff origin/claude/review-r019 HEAD -- harness/culprit/review_r019` is empty, so the reviewer tests are unchanged.

| R-019 | test result now | verdict |
|---|---|---|
| H1 two inputs together | passes (names `{APP_LEGACY_FORMAT, APP_STRICT}`) | fixed |
| H2 exec bit outside the key | passes (mode commit named, confirmed) | fixed; mirror case in `round2/` also passes |
| H3 flaky test (entropy in-process) | passes ("unknown: flaky") | fixed **for in-process entropy only**; see N3 |
| H4 break, revert, break | passes (C3) | fixed **when the fix touches the culprit's own inputs**; see N1 and N2 |
| control | passes | the stale-bytecode harness fix works for the harness |
| H5 culprit always first | passes (803 of 1,476 candidate replays pass) | fixed; trivial rules fail (§3) |
| M6 "14 of 14 no-code" | fails on `len(singles) == 14` | fixed in substance: 15 singles, all no-code, data edits reported separately. The assertion's literal count is stale. |
| M7 median without confirmation | fails (asserts round 1's rows) | fixed in substance: medians now include every confirmation replay (5 for the round-2 cases) |
| M8 rebuild of old environments | fails (97 unusable attempts) | fixed in substance: reported per population, including the 97 (81 reverts + 16 fixes) |

The remaining M6/M7/M8 failures are the expected state of assertions written against round 1. They are not counted.

## 2. New adversarial cases (`test_wrong_culprits_r2.py`)

| # | case | truth (plain walk) | finder | executions | git bisect |
|---|---|---|---|---:|---|
| N1 | C1 breaks `f`; two harmless edits of `k`; C2 works around C1 **in the caller `g`**; C3 breaks `k` | C3 | **C1, confirmed** | 3 | wrong (C1) |
| N2 | C1 breaks `g`; C2 tidies `f`; C3 reverts C1; C4 breaks `f`. `g` is equal at green and red, so it is not in the key diff | C4 | **C1, confirmed** (via the fallback search) | 3 | wrong |
| (tried) | C1 breaks `g`, C2 reverts, C3 changes a data file that only a child process (`cat`) reads | C3 | C3, confirmed (child reads are in the key) | 2 | |
| N3 | randomness inside a **child process** (`python -c ... os.urandom`); 3 harmless commits; the test fails about half the time at every commit | no culprit | **a commit, confirmed**, in 6 of 8 runs (second full run: 3 of 8) | 2-4 | n/a |
| N4 | the job sets `APP_STRICT=1` with its shim `APP_COMPAT=1` (harmless together; strict alone breaks the test), plus `OUTPUT=json`, which breaks it. The red job without `OUTPUT` passes; without `APP_STRICT` it still fails | `env:OUTPUT` | **`env:APP_STRICT`, confirmed** | 3 | n/a |
| N5 | engine: reused workspace, plain `git checkout`, two same-size versions of `f` within one second, `--det` replay | bad version fails | **passes, 5 of 5**; the key records the *bad* version's `unit:pkg/m.py::f` digest with a pass | 1 | |

What goes wrong in each case:

* **N1 (`_search_commits`, re-touch check).** C1 is confirmed: its parent passes and C1 fails. The non-monotonic check then probes only two kinds of later commit:
  * candidates that change C1's own differing inputs (`ix`);
  * commits whose lines undo C1's lines.

  C2 fixes the red elsewhere, so it is never probed. REPORT-2 lists this under "Finder limits", as "no case in the data; UNKNOWN rate". It is now a three-function case that the finder answers with confidence in 3 executions.
* **N2 (`_bisect_all`).** When confirmation fails ("parent fails"), the finder searches every commit of the narrowed range. `_bisect_all` assumes a monotonic history and has no re-touch or undo check. It finds C1, a breakage of a unit that C3 reverted, and C1's own confirmation passes. The same function also serves the "no differing input in the key" path.
* **N3 (`NONDET_FLAGS`).** The finder treats only `rclock`, `connect`, `csock`, `dns`, `entropy` and `net` as uncontrolled sources. The engine flags a child process as `spawn` (`proofcache.py:549`, `:651-710`, including "[not followed …]" and "[reads …]" details). That flag is ignored, so a flaky child yields single-replay "proofs". The confirmation is just two more single replays, and it passes about 25% of the time per attempt.
* **N4 (`_search_inputs`).** The named input is confirmed only in the green-side direction: "applied alone to green, it fails". Nothing checks the red side, "the red job without it passes". When one change masks another (a flag with its compatibility shim), the finder blames an input whose removal leaves the job red. This is the "combined inputs" case R-019 asked for, in a form that ddmin's single-sided test cannot catch.
* **N5 (engine).** `.pyc` validation by mtime seconds and size runs the previous version's bytecode. The proof key is computed from the source, so it pairs the new digest with the old outcome. With `--det-cache`, that is a cached false pass. REPORT-2 calls the product impact UNKNOWN. It is reproducible on every try with one `git checkout` of a same-size edit in the same second (CI workspaces reused across commits, fast incremental checkouts).

Not attempted: an inexact environment rebuild that produces a wrong answer rather than "unknown". The rebuild needs a private or modified distribution. From reading the code, the input search (`_search_inputs`) passes no `expect_runtime`, so its replays are never checked for exactness. Only the "red code, green environment" step and commit probes are. This is not counted.

## 3. Ground truth: trivial rules (recomputed from committed rows)

From `aggregate2.py`, matching REPORT-2:

| rule | a2 placed (196) | a2 reland (196) | b (27) | c edit (15) |
|---|---:|---:|---:|---:|
| oldest commit in range | 14 | 0 | 2 | 3 |
| newest commit in range | 15 | 38 | 3 | 2 |
| oldest candidate | 42 | 0 | 7 | 8 |
| newest candidate | 44 | 76 | 3 | 6 |
| finder | 183 (13 unknown) | 187 (9 unknown) | 22 (5 unknown) | 15 |
| git bisect | 196 | 100 | 27 | 15 |

Extra rules (`trivial_rules.py`) were run against the upstream windows. The planted commit is the original commit at position p, plus one line. They cover the 276 a2 rows that record their green commit; 116 rows have no `green` field.

| rule | placed (138) | reland (138) |
|---|---:|---:|
| largest diff | 7 | 8 |
| newest commit touching the red test's file | 2 | 9 |
| oldest commit touching the red test's file | 2 | 2 |
| newest commit touching a non-test `.py` | 9 | 16 |

No trivial rule beats 31%, so the R-019 H5 leak is closed.

Two caveats:
* placed histories are monotonic, so plain git bisect is right 196 of 196 there;
* the discriminating set is the 196 reland cases plus 27 real cases.

## 4. Headline numbers and labels

`python3 harness/culprit/round2/aggregate2.py harness/culprit/results` reproduces the committed `summary.json` byte for byte. Every number in REPORT-2's table and in §§1-4 matches the rows:
* 500/533; 438/470; 0 and 1 confident wrong;
* 32 unknown, with the suspect equal to the truth in 27;
* median 5 (p90 11), and 6 with step 4;
* 13 of 15 singles; 30 of 33 exact rebuilds;
* the trivial-rule table; 803 of 1,476 candidate replays passing; the reland comparison (187 vs 100);
* kind b 22/0/5, median 10;
* the timing sample (9.3 s vs 5.1 s, 1.12 s per replay, 19 of 20 right).

The labels are right, with these remarks (none counted):
* **"Regression fixes since 2021: 16 of 143 (11%)".** `generation-notes.txt` gives 16 unusable, 133 rejected and 10 that produced cases, so 159 attempts, not 143. The denominator 143 leaves out the 16 unusable attempts themselves, and the share is 10%. "81 of 125" revert attempts cannot be derived from the notes (81 + 117 + 2 = 200 listed).
* **`aggregate2.py` reports `distinct_culprits: 25` for kind b.** That counts replayed SHAs, since every case rebuilds its own history. REPORT-2's "12" counts sources (2 reverts + 10 fixes), which is not the same claim: the rows do not show that the three cases of one fix share one original culprit.
* **"0 confident wrong" is MEASURED, and correct for the 470 cases.** Read with §2, though, it means "on the populations measured", not "in general". N1 to N4 are four reproducible classes that the populations contain none of.
* **"8 of 400 a2 attempts were dropped: the walk met a commit that could not run".** The notes record them as `rejected`, not `unusable` (unusable = 0 for every a2 project).

## 5. Open question: round-1 rows hit by stale bytecode

The trigger is a re-checkout within the same wall-clock second of a `.py` file whose new version has the same size, while a `.pyc` compiled from the old version is present.

* **Round-1 kind a (200 rows, now replaced by a2):** no answer could have been affected (MEASURED).
  * Every candidate contains the mutation and is truly red, so only a fail→pass flip could move an answer. 0 of 637 finder replays passed.
  * git bisect is right 200 of 200.
  * Case *selection* may have been affected: 144 of 200 bisect runs average under 1 s per execution, and a stale red key run would have dropped a case. That part is UNKNOWN.
* **Round-1 kind c (40) and b (5):** not exposed. Finder replays switch environments, not code, and 0 of 63 steps took under 1 s.
* **Step 4, the 63 rows carried into REPORT-2's 500/533:** exposed.
  * Round 1's `checkout` had no fresh stamps, and plain in-tree `__pycache__` follows the same mtime-and-size rule.
  * `stale_d.py` reconstructs every row's commit probes from its verdict sequence. All 63 replay exactly to the named commit. It then diffs consecutive probed commits.
  * MEASURED: **52 of 63 rows** have at least one consecutive probe pair where a `.py` blob changes with the same size and the first run took under 1 s (132 pairs). 410 of 483 probe pairs follow a run under 1 s, mostly fast "missing" verdicts.
  * ESTIMATED: assuming a uniform checkout phase, about **36 rows** would have at least one same-second pair. This is an upper bound, because import of the changed file was not checked.
  * Whether any verdict flipped is UNKNOWN. The step-4 truth uses the same pair oracle, so a flip could move the truth and the answer together, and the row would still look "correct".

## Findings

High: a reproducible confident wrong answer. Medium: a number in the headline that rests on an unverified measurement.

### N1. A fix in another unit is missed: an earlier, already-fixed commit is confirmed (High)
* **Test:** `test_break_worked_around_in_the_caller_then_broken_elsewhere`
* **Result:** C1 is named in 3 executions; the truth is C3. git bisect is also wrong.
* **Fix:** after confirming C, check the red end: re-apply only C's diff reverted at the red head, or probe the newest candidate's parent chain from the red side (step 4 searches backward from red). Otherwise withhold the answer when any later candidate exists that was not probed.

### N2. The fallback search confirms a breakage that was later reverted (High)
* **Test:** `test_fallback_search_does_not_name_a_breakage_that_was_already_reverted`
* **Cause:** `_bisect_all` has no non-monotonic check. It is used after a failed confirmation and when the key shows no difference.
* **Fix:** apply the same re-touch and undo checks there (over all commits, since no footprint is available), or answer "unknown" after a fallback whenever more than one transition is possible.

### N3. A flaky child process is blamed on a commit (High)
* **Test:** `test_flaky_child_process_is_not_blamed_on_a_commit`
* **Result:** 6 of 8 and 3 of 8 runs name a commit.
* **Fix:** add `spawn` (at least its "not followed", "reads /dev/urandom", network and clock variants) to `NONDET_FLAGS`, or repeat green whenever the key contains any flag that `--det` does not prove.

### N4. A masked input is blamed; the red comes from another (High)
* **Test:** `test_masked_input_is_not_blamed_when_the_red_comes_from_another`
* **Result:** `env:APP_STRICT` is named; the red job without it is still red.
* **Fix:** confirm on the red side as well: the red environment minus the named input (or set) must pass. If it does not, report "unknown" or continue with ddmin on the complement.

### N5. The engine runs stale bytecode under `--det` and records a false pass in the proof key (High)
* **Test:** `test_det_replay_runs_the_checked_out_source_not_stale_bytecode` (5 of 5 wrong). A manual run confirms that the key carries the bad source's `unit:` digest with a pass.
* **Label:** REPORT-2 calls the product impact UNKNOWN. It is a cache-poisoning false pass in any workspace that checks out a same-size edit within one second.
* **Fix:** validate cached bytecode by source hash (`--invalidation-mode checked-hash`, or the digest the engine already computes) in the shared prefix.

### M6. The 63 carried-over step-4 rows were measured under the stale-bytecode condition (Medium)
* **Test:** `test_carried_over.py`, over `stale-d.jsonl`.
* **Evidence:** 52 of 63 rows are exposed (132 qualifying probe pairs; about 36 rows expected to have at least one same-second pair). They account for 62 correct and the 1 wrong answer in 500/533, labeled MEASURED.
* **Fix:** rerun step 4 with the round-2 `checkout` (or with hash-checked bytecode) before quoting 62/63, or mark the step-4 row as "round 1, pre-fix, not re-verified" in the headline.

### Not counted
* The M6/M7/M8 assertions of R-019 still fail because they encode round 1's numbers; the substance is fixed.
* The rebuild denominators for fixes and reverts (§4).
* `distinct_culprits` in `aggregate2.py` counts replayed SHAs.
* The input search has no exactness check (code reading only).
