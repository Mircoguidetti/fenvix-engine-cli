DONE: after making key validity sound (review R-019c, F-1), **491 of 533 measured cases have a stated culprit (92.1%), with 0 confident wrong**. The reviewer's 5 attacks now pass. Of the 42 unknowns, 37 carry a suspect, and the suspect is the truth in 37 of 37. Cost: median 15 test executions per case (p90 60), median wall 13.2 s per case (p90 54 s). Round 3 on the same footing stated 391 of 533 (73.4%).

# Exact culprit (idea 2): fix round 5, after review R-019c

Session `2026-11-18-exact-culprit`, last fix round. Review: `claude/review-r019c`, `sessions/2026-11-19-review-exact-culprit/REPORT-3.md` (FIX 7).

* **Branch:** `claude/exact-culprit`.
* **Labels:**
  * MEASURED: my runs in this session.
  * ESTIMATED: my arithmetic, a simulation, or a model over measured parts.
  * DECLARED: a source.
  * UNKNOWN.
* **Machine:** as in REPORT-4: 4 cores, 5 lanes during the re-run, so wall times are NOISY.
* **Recompute:**
  * `python3 harness/culprit/round4/aggregate4.py harness/culprit/results` (output: `results/summary5.json`).
  * Round 4's rows and summary moved to `results/round4/`; round 3's are in `results/round3/`.
  * The same script over `results/round4` and `results/round3` gives the comparison figures below.
* **REPORT-4 is superseded on soundness.** Its 97.2% came from an inference that states wrong culprits on constructed histories (F-1). The row data are kept in `results/round4/`.

## 1. F-1: key validity made sound (diff rule)

**Finding (reviewer, re-checked here, MEASURED).** On round 4's finder, the 5 histories in `review_r019c/test_key_validity_attacks.py` (F1–F5) each give a confident wrong culprit with 0 red-side replays:
* F1: a `try: import` from an unguarded `sys.path` directory;
* F2: a flag file checked with `exists`;
* F3: a namespace package gaining `__init__.py`;
* F4: a vendored zip replaced;
* F5: a ctypes `.so` rebuilt.

With inference off, all 5 are right.

**Cause.** The key does not record import probes, absences, stat checks or binary code (engine findings E-1 to E-4). Round 4 guarded only the places where I knew the key was silent.

**Fix (`finder.agrees`).** A commit j is inferred from a run R only if the trees of j and R's commit:
* have exactly the same set of paths (no addition, deletion or rename anywhere), and
* differ only in paths that R's key records as inputs, whatever their kind, binary or not.

Those recorded paths are then compared finely, as before: unit, skeleton and hooks digests, blob equality for data and content. Anything else means a replay.

This is the reviewer's "minimum" rule. The "better" rule (rely on the key once the engine records E-1 to E-4, on `claude/dep-verdict-abjcfw`) is not used, because that work has not merged here.

**Tests.** `harness/culprit/review_r019c/test_key_validity_attacks.py`, copied unchanged from the reviewer's branch: **12 passed** (F1–F5 with key validity, their controls, F6). MEASURED.

**Residual: untracked files.** The rule sees only git trees. A file that is untracked or ignored, and generated at install time, is equal at every replay of one copy of the repository. So it cannot differ between j and R in these replays. A generated file that the install would regenerate differently per commit is not modelled: such an install is not re-run per replay. This was already true in rounds 2 to 4. UNKNOWN impact.

**Effect on inference.** Under the diff rule, key validity decides almost nothing on real histories:
* a2 + b: **120 later commits inferred, 6,403 replayed** (round 4: 3,907 and 3,618). MEASURED.
* Nearly every real commit adds, deletes or changes some path that the failing run did not record (tests, docs, configuration).
* The coverage now comes from the larger budget and the parallel replays, not from inference.

## 2. Re-run of the populations (MEASURED)

* a2, b, c no-code and c data edit were re-run with the round-5 finder (`round5/run_{a,b,c}5.sh`).
* Step 4 (d) is carried over from round 4: `orderdep.py` does not use key validity and is byte-identical to round 4 (checked with `git diff`).

| kind | cases | stated = right | wrong | unknown (suspect = truth) | executions median (p90) | wall s median (p90) | round 4 stated | round 3 stated |
|---|---:|---:|---:|---|---|---|---:|---:|
| a2 placed | 196 | 179 | 0 | 17 (17) | 18.5 (66) | 15.5 (56) | 190 | 135 |
| a2 reland | 196 | 188 | 0 | 8 (8) | 12 (45) | 12.6 (54) | 196 | 170 |
| b real history | 27 | 20 | 0 | 7 (7) | 52 (71) | 44.5 (101) | 27 | 9 |
| c no-code | 36 | 31 | 0 | 5 (no suspect) | 4 (26) | 9.2 (35) | 31 of 35 | 31 of 36 |
| c data edit | 15 | 15 | 0 | 0 | 6 (8) | 9.0 (15) | 15 | 15 |
| d step 4 (carried over) | 63 | 58 | 0 | 5 (5) | 29 (67) | 14.1 (34) | 58 | 31 |
| **all** | **533** | **491 (92.1%)** | **0** | **42 (37)** | **15 (60)** | **13.2 (54)** | 517 of 532 | 391 of 533 (73.4%) |

**Transitions from round 4, same case ids:**
* a2: 367 stated → stated; 19 stated → unknown; 6 unknown → unknown.
* b: 20 stated → stated; 7 stated → unknown.
* Every case that stays stated names the same commit (all right, 0 wrong). No case went from unknown to stated.

**The 42 unknowns:**
* **37 hit the red-side budget of 64.** The suspect is the truth in 37 of 37.
  * a2: 25, mostly placed culprits in 120 to 200-commit histories;
  * b: 7;
  * d: 5.
* **3 inexact rebuilds of the green environment** (toolz env, now including toolz-env-tz, which today's environment produces again as a case).
* **2 `csock`** (httpx).

**Stated share by red-side budget.** ESTIMATED: simulated from the recorded replays as in REPORT-4; only 64 is a run.

| budget | 0 | 4 | 8 | 16 | 24 | 32 | 48 | 64 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| stated / 533 | 112 | 259 | 316 | 395 | 425 | 447 | 473 | 490 |

The simulation gives 490 at 64, against 491 measured. The difference is one a2 case that used 65 replays: the budget is 64 plus the commits that undo C.

Without parallel replays, the same answers cost about 1.7× the wall time (REPORT-4 §4, MEASURED on kind b, not re-measured this round).

## 3. R-2 and R-3 (report corrections)

* **R-2:**
  * The round-3 denominator contained two rich-home rows that were never pass→fail. `aggregate4.py` now counts a no-code row only when its green run passed and its red run failed.
  * Round 3 recomputes to **391 of 533 = 73.4%** (REPORT-3 said 391 of 535, 73.1%). MEASURED from the rows.
  * REPORT-4's "3 cases no longer produced" was accurate only for toolz-env-tz, and that case is produced again in round 5.
* **R-3, critical path:**
  * The replay critical path (every replay in sequence, a parallel batch counted as its longest replay) is a model over measured replay times: **ESTIMATED**. Round 5: median 11.9 s, p90 47 s.
  * REPORT-4 labelled it MEASURED; that label was wrong.
  * The measured figures are the whole-finder wall times in the table, and the clean timing pass of REPORT-4 §4.
* **R-3, the "3,907 would have needed a replay" claim:**
  * The count of commits decided by key validity was MEASURED.
  * That each would otherwise have needed a replay was not measured: **UNKNOWN**. Round 3's vector inference and the same-commit memo would have decided part of them.
  * The question is moot after F-1: inference now decides 120 commits.

## 4. Gates (MEASURED)

`python -m pytest -p no:cacheprovider harness/culprit/review_r019 harness/culprit/round2/test_finder_round2.py harness/culprit/review_r019b harness/culprit/round4 harness/culprit/review_r019c` gives **38 passed, 3 failed** (266 s).
* **The 3 failures** are R-019's stale count assertions (M6, M7, M8), excluded by the reviewer, the same as in rounds 3 and 4.
* **Everything else passes:**
  * N1 to N5;
  * `test_carried_over`;
  * the 9 round-4 tests;
  * the 12 R-019c key-validity tests.

**Not in scope here: the engine findings E-1 to E-4.** These are stale reuse in `--det-cache` (`review_r019c/test_cache_stale_reuse.py`, 10 failing on the reviewer's branch). They belong to the dependency-verdict work on `claude/dep-verdict-abjcfw`. That file is not copied here, and they stay open.

## 5. What this means

* **Goal met with the sound rule.** The goal was at least 85–90% stated with 0 confident wrong. The result is 92.1% stated and 0 confident wrong on 533 measured cases, plus 0 on every adversarial test from R-019, R-019b, R-019c and round 4.
* **"0 confident wrong" holds on these cases, not in general.** The finder still trusts the key for the inputs of the files it compares. The diff rule removes the inference across every other kind of change.
* **Coverage now comes from replays, not inference.**
  * Median 15 executions per case (round 3: 10, round 4: 11).
  * Most of the cost goes to proving that no later commit fixed the test.
  * Parallel replays keep the median wall at 13 s.
* **Once the engine records import probes, absences, stats and binaries (E-1 to E-4),** the diff rule can be relaxed back to key validity. Round 4's 97% (ESTIMATED as an upper bound) would then be reachable at about 11 executions. This needs the reviewer's 5 attacks and the population re-run again.
* **Brain copy not made:** this session has no access to the brain repository. The report is on `claude/exact-culprit` only.
