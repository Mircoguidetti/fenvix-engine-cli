PARTIAL, leaning NO on correctness: **0 confident wrong answers on the measured populations** (535 cases, every population re-run with the fixed finder). But only **391 of 535 culprits are stated (73.1%)**. The other 144 are "unknown", and in 137 of those the withheld suspect is the truth. Median **10** test executions per case (7 without step 4). The NO criterion "correct share under 85%" is now triggered: the red-side check that closes N1 and N2 needs more replays than a budget of 6 allows on most real histories.

# Exact culprit (idea 2): fix round 3, after review R-019b

Session `2026-11-18-exact-culprit`, round 3. This is the last fix round, and the bar is the reviewer's own failing tests (`sessions/2026-11-19-review-exact-culprit/REPORT-2.md`, FIX 6).
* **Branch:** `claude/exact-culprit`, with `claude/review-r019b` merged.
* **What changed:** the engine (`python/`, `crates/`) is unchanged. All changes are in `harness/culprit/`: `finder.py`, `orderdep.py`, the drivers in `round3/` and the result rows.
* **Labels:** MEASURED (my runs in this session), DECLARED (a source), ESTIMATED (my arithmetic or judgement), UNKNOWN.
* **Machine:** one cloud container, 4 cores, CPython 3.13.18 (step 4: 3.9). The runs had 5 to 9 jobs on 4 cores, so wall times are NOISY. No clean timing pass was made this round, so executions are the cost measure.
* **Recompute:** `python3 harness/culprit/round2/aggregate2.py harness/culprit/results` prints every number below; `results/summary.json` is its output.
  * The round-2 rows moved to `results/round2/`.
  * Round 1's rows stay in `results/round1/`.

## Against "the number that says yes" (P-029)

| criterion | target | round 3 (round 2 in brackets) | label |
|---|---|---|---|
| correct culprits | ≥ 95% over ≥ 300 cases | **391 / 535 = 73.1%** (500 / 533 = 93.8%). Without step 4: 360 / 472 = 76.3% | MEASURED |
| confident wrong culprit | 0 | **0 on the measured populations**: a2 392, b 27, c no-code 38, c edit 15, step 4 63 (round 2: 1, step 4) | MEASURED |
| answered "unknown" | | **144** (32). The suspect is the truth in all 137 that have one (a2 87, b 18, step 4 32). The other 7 (kind c) have no suspect: flaky, `csock`, or an inexact rebuild. | MEASURED |
| test executions per case | median ≤ 3 | **median 10**, p90 27 (6, p90 14). Without step 4: median 7 (5) | MEASURED |
| no-code reds attributed to the right input | 14 of 14 | **13 of 16** single no-code changes; 3 "unknown", 0 wrong (7 mechanisms) | MEASURED |
| NO: correct share under 85% | | **73.1%: triggered** | MEASURED |
| NO: old environment not rebuildable in > 20% of cases | | Green environment rebuilt from the key: not exact in 2 of 32 (toolz). Old commits that no environment I could build would run: **81 of 200 revert attempts (41%)**; regression fixes since 2021: **16 of 159 attempts (10%)**; a2 windows: 0 unusable (8 of 400 rejected). | MEASURED |

**Reading the headline.**
* Every answer the finder states is right on these populations: 391 of 391.
* What fell is the share it is willing to state. Round 2 named a commit once its parent passed and it failed, and probed later commits only when they touched the culprit's own inputs.
* N1 showed this is not enough: a fix elsewhere (in a caller) followed by a newer break gives a confident wrong answer. The sound condition is that **every later footprint state fails**.
* Checking that costs one replay per distinct later state. With a budget of 6 (as in round 2), most real-history cases run out of budget.
* Read as "suspect or answer", **528 of 535 point at the truth** (ESTIMATED as a product figure: a product could show "probably X, N later changes unchecked").

## 1. Findings N1 to N5

Tests: `harness/culprit/review_r019b/test_wrong_culprits_r2.py`, unchanged (MEASURED, final run below).

| finding | cause | fix (`finder.py`) | reviewer's test now |
|---|---|---|---|
| N1, fix in another unit, then a new break | after confirming C, only later commits that touch C's own inputs or undo C's lines were probed | **Red-side check.** Commits between candidates keep the footprint state of the candidate before them, so C is the newest transition only if every later candidate's state fails. States already replayed (or equal to the green or red state) are inferred with no execution. The rest are probed in this order: commits that undo C, then those that re-touch C's inputs, then every other later candidate, newest first. Up to 6 probes beyond the undo commits; a pass restarts the search above it; an unprobed rest withholds the answer, with the suspect recorded. | names C3 (the truth) |
| N2, fallback search names a reverted break | `_bisect_all` (after a failed confirmation, and when the key shows no difference) had no non-monotonic check | the same red-side rule over every commit after the answer (no footprint, so no inference), newest first, up to 6. A pass restarts above it; an unprobed rest gives "unknown" | names C4 (the truth) |
| N3, flaky child process | `spawn` was not an uncontrolled flag. **Also (MEASURED here): a child that the engine follows (strace present) is not flagged at all.** Its `getrandom` draws are counted session-wide, not per test, so the key carried no flag for the reviewer's case. | `spawn` joins the uncontrolled flags. A followed child is detected from the key itself: the dynamic loader's reads (`/etc/ld.so.cache`, `/etc/ld.so.preload`) or a program under a `bin` directory. In-process code reads neither during a test (checked on a plain test). Green is then replayed 5 times (any fail: "unknown: flaky"), red 5 times (any pass: "unknown: flaky"), and every confirmation 5 times (all pass at the parent, all fail at the culprit) | "unknown: flaky" in 8 of 8 runs |
| N4, masked input blamed | the named input was confirmed only on the green side | **Both sides.** S is named only if S applied alone to green fails, **and** the red environment without S passes. If it still fails, ddmin over the other inputs finds the next set, which is checked the same way. A set found twice ("several inputs break it independently") gives "unknown" | names `env:OUTPUT` (the truth) |
| N5, engine stale bytecode under `--det` | engine (`.pyc` validated by mtime and size) | not fixed here: it is fixed on `claude/rust-hotpaths-2` by another session. The test is unchanged. `review_r019b/conftest.py` marks it as a **non-strict** expected failure, so it still runs in full and reports XPASS once the engine fix lands; the mark should then be removed | XFAIL (fails 5 of 5, as reported) |

The attack the reviewer tried that the finder handled (a reverted break, then a data file read only by a child) still passes. It now takes the child-process path: repeated green and red, then repeated confirmations.

Not addressed:
* The input search still does not check that its replays run in an exactly rebuilt environment. The reviewer noted this from reading the code and did not count it.
* The answer is withheld only at the end, when any green-environment replay was inexact.

## 2. Step 4 (R-019b M6)

1. **Re-run with fresh stamps, step-4 finder unchanged:** all 63 carried-over rows were re-run with the round-2 checkout, so every checkout gives the files it rewrote a strictly increasing mtime and a stale `.pyc` cannot match. Result, MEASURED: **all 63 rows give the same verdict at every step, the same polluter, the same answer and the same truth** (truth-scan length and tail identical). So no step-4 verdict had flipped under the stale-bytecode condition. The rows are kept in `results/round1/d-rerun-fresh-stamps.jsonl`.
2. **The step-4 finder had no red-side check**, so pykicad stayed a confident wrong answer (62 of 63). `orderdep.py` now applies the same rule as the main finder:
   * the footprint is the repository files the pair imports (`-X importtime`, which works on the Python 3.9 environments where proof keys cannot be written), plus both test files, every conftest and the pytest configuration, measured at red and at the named commit;
   * every later footprint state must fail;
   * states where a test file of the pair changes are probed first (a missing test passes);
   * the budget is 8 probes; a pass restarts the bisection above it.

   If the import report comes back empty, every Python file counts as the footprint.
3. **Final step-4 rows** (`results/d.jsonl`, re-run with fresh stamps and the red-side check), MEASURED:
   * **31 right, 0 wrong, 32 unknown** (the suspect is the truth in all 32);
   * median 26 executions, including the polluter search (round 1: 17);
   * pykicad is now "unknown" with the right suspect, after one restart.

`review_r019b/stale-d.jsonl` was regenerated from these rows with `stale_d.py`:
* 63 of 63 reconstruct and all carry fresh stamps, so 0 rows are exposed;
* the 133 raw same-size pairs under 1 s are kept in a `_raw` field;
* `stale_d.py` gained two things: rows with fresh stamps count as not exposed, and the reconstruction compares against the answer before the red-side check (`finder_first`).

`test_carried_over.py` is unchanged and passes.

## 3. Populations, re-run with the round-3 finder

Each population was re-run, not re-scored. The truth and the git bisect baseline of each committed row are kept, because neither depends on the finder.
* **a2:** the round-2 histories were rebuilt commit for commit (392 of 392 rebuilt ids equal the recorded ones), and the keys were written again.
* **b:** reverts use the same commits and the period environment rebuilt with the same resolver cut-off. Fix cases are replayed with the fix's tests overlaid; 27 of 27 rebuilt ids are equal.
* **c no-code:** the committed scans' green and red commits; for the head-to-head scenarios, the same seeded placement (15 of 15 data-edit truths are equal).
* **d:** as in §2.

Green/red key outcomes are unchanged in every a2 row.

| kind | cases | right | wrong | unknown (suspect = truth) | executions, median (p90) | round 2: right / unknown, median |
|---|---:|---:|---:|---|---|---|
| a2 placed | 196 | 135 | 0 | 61 (61) | 9 (23) | 183 / 13, — |
| a2 reland | 196 | 170 | 0 | 26 (26) | 7.5 (26) | 187 / 9, — |
| a2 total | 392 | 305 | 0 | 87 (87) | 8 (25) | 370 / 22, 6 |
| b real history | 27 | 9 | 0 | 18 (18) | 11 (17) | 22 / 5, 10 |
| c no-code | 38 | 31 | 0 | 7 (no suspect) | 4 (21) | 31 / 5, — |
| c data edit | 15 | 15 | 0 | 0 | 4 (6) | 15 / 0, — |
| d step 4 | 63 | 31 | 0 | 32 (32) | 26 (31) | 62 / 0 (1 wrong), 17 |
| **all** | **535** | **391** | **0** | **144 (137)** | **10 (27)** | 500 / 32 (1 wrong), 6 |

Where the unknowns come from (MEASURED):
* **a2, b, d: all are "ambiguous"**, meaning the budget ran out before every later footprint state was replayed.
* Unreplayed states per unknown:

  | kind | median | max | 2 or fewer | 14 or fewer |
  |---|---:|---:|---:|---:|
  | a2 | 6 | 99 | 21 of 87 | 67 of 87 |
  | b | 14 | 31 | 0 of 18 | 10 of 18 |
  | d | 8 | 103 | 1 of 32 | 22 of 32 |

* So raising the budget buys stated answers at a near-linear cost in executions. ESTIMATED: with a budget of 20, about 67 more a2 cases and 10 more b cases would be stated, at up to 14 more executions each. I did not run this.
* Placed histories are monotonic. Their 61 unknowns are pure verification cost: git bisect is right in 196 of 196 there, with no check at all.
* **c no-code, 7 unknowns:**
  * toolz ×2: green environment not rebuilt exactly (as in round 2);
  * toolz ×1: "flaky", because a red replay passed once in 5 (child process);
  * httpx ×2: `csock` (as in round 2);
  * rich-home ×2: "flaky", failing at green. This is a new case: rich-home's test selection now finds a red test (round 2 skipped it), and the test runs a child process that fails at green 1 or 2 times in 5.
* **Child processes are common:** 60 of the 419 a2/b cases and 10 of 38 no-code cases have a followed child in the key. They are searched with repeated confirmations. That is part of the higher medians: pluggy and sqlparse need 19 to 26 executions.

Unchanged from round 2 (MEASURED): 803 of 1,476 candidate replays pass in a2, and the trivial rules stay at or below 31%. On reland histories git bisect is right in 100 of 196; the finder is right in 170 and wrong in none.

## 4. Label remarks from R-019b §4, corrected

* **Old environments, regression fixes:** **16 unusable of 159 attempts (10%)** (16 unusable + 133 rejected + 10 that gave cases). REPORT-2's "16 of 143" left the 16 out of the denominator.
* **Old environments, reverts:** "81 of 125" cannot be derived from the notes. The notes give **81 unusable + 117 rejected + 2 that gave cases = 200 attempts**, so 81 of 200 (41%).
* **Kind b distinct culprits:** `aggregate2.py` now reports both counts:
  * `distinct_culprits` = 25 replayed commits (every fix case replays its own history);
  * `distinct_original_culprits` = **12** original commits, from each fix case's `truth_original` (a revert's culprit is the project's own commit);
  * `sources` = 12 (2 reverts + 10 fixes).

  So "12 distinct culprits" is now derived from the rows, not assumed.
* **a2 dropped attempts:** 8 of 400 were **rejected** (the walk or `--det` disagreed at the truth), not unusable. Unusable = 0 for every a2 project.
* **"0 confident wrong"** means **on the measured populations** (the 535 cases above). It is not a general claim. §1 shows four reproducible classes that produced confident wrong answers before this round. Others may exist (UNKNOWN). The reviewer's untested path (input search without an exactness check) is still open.

## 5. Gates (MEASURED)

`python -m pytest -p no:cacheprovider harness/culprit/review_r019 harness/culprit/round2/test_finder_round2.py harness/culprit/review_r019b` gives **3 failed, 16 passed, 1 xfailed** (118 s).
* **The 3 failures** are R-019's stale count assertions, which the reviewer says to exclude:
  * M6: 16 singles, not 14;
  * M7: 493 rows, not 303;
  * M8: round 2's 97 unusable old-commit attempts.
* **The xfail** is N5 (engine).
* **Everything else passes:**
  * `review_r019b`: N1, N2, N3, N4, the tried case and `test_carried_over`;
  * `round2/test_finder_round2.py`;
  * R-019's H1 to H5 and the control.

## 6. What this means for P-029

* **Confidence holds.**
  * 0 confident wrong on 535 measured cases (MEASURED).
  * The four new attack classes are closed by construction, not by tuning: the red-side rule, the two-sided input rule and repeats for child processes.
  * The only stale-bytecode exposure in the data, step 4, was re-measured and found unaffected.
* **Coverage does not.**
  * Stating an answer soundly costs one replay per later footprint state.
  * On real histories (kind b) and order-dependent cases (step 4), half or more of the cases need more than the budget.
  * The right share is 73%, below the 85% NO line, and the median is 10 executions against a target of 3.
* **Two ways forward, both ESTIMATED.** Either could be measured next.
  * Report the suspect as a product answer ("probably X; N later changes unchecked"): right in 528 of 535.
  * Raise the budget per case where CI time allows.
