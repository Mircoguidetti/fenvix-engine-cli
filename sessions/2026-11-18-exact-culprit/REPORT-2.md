PARTIAL: 500 of 533 culprits right (93.8%, under the 95% target) and 0 confident wrong answers among the 470 cases measured in round 2 (1 carried over from round 1). Median 5 test executions per case (target 3). 13 of 15 no-code reds right, 2 answered "unknown", none wrong.

# Exact culprit (idea 2): round 2, after review R-019

Session `2026-11-18-exact-culprit`, round 2. Prompt: fix the R-019 findings and measure again. Engine branch `claude/exact-culprit`; code and result rows are in `harness/culprit/`, and `harness/culprit/README.md` describes the layout. The engine itself (`python/`, `crates/`) is unchanged; all changes are in the harness and in the prototype finder.

* **Labels:** MEASURED (my runs in this session), DECLARED (a source), ESTIMATED (my arithmetic or judgement), UNKNOWN.
* **Machine:** one cloud container, 4 cores, CPython 3.13.18. The main runs had 4 to 9 jobs on 4 cores, so their wall times are NOISY. Clean timings come from a separate pass on an idle host.
* **Recompute:** `python3 harness/culprit/round2/aggregate2.py harness/culprit/results` prints every number below and writes `results/summary.json`. Round 1's rows moved unchanged to `results/round1/`, and `aggregate.py results/round1` still reproduces round 1.

## Against "the number that says yes" (P-029)

| criterion | target | round 2 | label |
|---|---|---|---|
| correct culprits | ≥ 95% over ≥ 300 cases | **500 / 533 = 93.8%** (round-2 cases alone: 438 / 470 = 93.2%) | MEASURED |
| confident wrong culprit | 0 (this prompt) | **0** in the 470 round-2 cases; **1** in the 63 carried-over step-4 cases (pykicad, round 1) | MEASURED |
| answered "unknown" | | 32 (all in round-2 cases); in 27 of them the withheld suspect was the truth | MEASURED |
| test executions per case | median ≤ 3 | **median 5** for the round-2 cases (p90 11); 6 including step 4 | MEASURED |
| no-code reds attributed to the right input | 14 of 14 | **13 of 15** single no-code changes; 2 "unknown", 0 wrong (6 mechanisms) | MEASURED |
| NO: correct share under 85% | | 93.8%: not triggered | MEASURED |
| NO: old environment not rebuildable in > 20% of cases | | **depends on age**, see "Rebuild". Green environment rebuilt from the key: not exact in 3 of 33 (9%). Old commits that no environment I could build would run: 81 of 125 revert attempts (65%), all years. Regression fixes since 2021: 16 of 143 (11%). | MEASURED |

**Why PARTIAL:**
* Correctness misses 95% only because of answers withheld as "unknown". Of the answers the finder did state, 500 of 501 are right, and the one wrong answer is round 1's step-4 case.
* Executions miss the target: every answer is now confirmed by replays (R-019 M7), and the median is 5.
* The no-code criterion is 13 of 15, not 14 of 14.
* The rebuild criterion holds for recent history but fails for history more than a few years old.

## 1. Finder fixes (R-019 H1 to H4)

The four reviewer tests (`harness/culprit/review_r019/`, copied unchanged from `claude/review-r019`) each failed before (MEASURED: 8 failed, 1 passed on the unchanged finder). After the fixes, all four wrong-culprit tests pass, and so does the control. Four more variants are in `round2/test_finder_round2.py` and pass:
* a break fixed by a different edit, then broken again;
* a mode change landing after a harmless commit;
* three inputs needed together;
* a green commit that is red when replayed.

What changed in `finder.py`:

| finding | cause | fix | the reviewer's case now |
|---|---|---|---|
| H1, two inputs together | the split kept the other half whenever one half passed | the named input is confirmed alone; if it does not reproduce the red, ddmin over the candidates finds the smallest set that does | names `{APP_LEGACY_FORMAT, APP_STRICT}` together (8 executions) |
| H2, mode change outside the key | pruning compared blob contents only, so the mode commit was never a candidate, and nothing was checked | a commit that changes a file mode is always a candidate. Every named commit is confirmed (its parent passes, it fails). A failed confirmation falls back to a search over every commit of the range. | names the mode commit (2 executions) |
| H3, flaky test | the key's entropy flag was ignored | a key flagged with an uncontrolled source (entropy, network, real clock) means: replay green up to 5 times. Any fail gives "unknown". Entropy alone is then searched under `--det-urandom`; anything else is "unknown". | "unknown: flaky" (1 execution) |
| H4, non-monotonic history | the binary search stopped at the oldest red candidate | a candidate whose footprint state equals the green state is known green (no execution). After confirmation, later commits that undo the culprit's diff are always probed, and other later commits that change its inputs again are probed up to 6. If one passes, the search restarts above it. If more remain unprobed, the answer is withheld as "unknown (ambiguous)" with the suspect recorded. | names C3 (2 executions) |

Also changed:
* an answer from an inexactly rebuilt environment is withheld (it was stated in round 1);
* a red run that wrote no key (the session failed before the end) uses the green key plus the two job definitions.

**Harness bug found by the reviewer's own control case.** Here the control failed too: the finder named the wrong commit. The cause was stale bytecode. `.pyc` files are valid while the source's mtime (whole seconds) and size match. detpy keeps one shared bytecode directory, and two checkouts within one second of same-size versions (`x + 1 + 0 * 4` and `x * 3 + 0 * 8`) ran the older version's bytecode. The fix (`common.py`):
* every checkout gives the files it rewrote a strictly increasing mtime;
* plain pytest runs (baseline, truth walks) read and write no bytecode.

Round 1's rows were not re-checked for this. One-token mutations such as `==` → `!=` keep the size, so some round-1 replays may have been affected (UNKNOWN how many).

## 2. Ground truth: cases a trivial rule cannot solve

| kind | source | cases | culprit position |
|---|---|---:|---|
| a2 placed | each of round 1's 200 mutations, folded into a **real commit at a random position** of a k-commit window (k = 4 to 200); commits before it are the originals | 196 | first commit of the range in 14 of 196 |
| a2 reland | the same mutation lands at p1, is undone inside a later real commit p2, and lands again at p3 (revert and reland) | 196 | never first; the older transition p1 is a trap |
| b, real history | commits the project reverted (2 reverts) and regressions the project fixed (10 fixes, the fix's test backported onto the history before it) in 8 projects | 27 (12 distinct real culprits) | first in 2 of 27 |
| c no-code | 6 head-to-head scenarios (rerun with the new finder) and 6 scenarios found by scanning 24 real suites, each alone and with a decoy | 36 (15 single) | not a commit |
| c data edit | 5 head-to-head data edits, folded into a random later commit (round 1: always first) | 15 | first in 3 of 15 |
| d step 4 | **carried over from round 1 unchanged** (`orderdep.py` not changed) | 63 (18 distinct culprits) | real history |

**Truth is independent of the finder.** In kinds a2 and b, the truth comes from a plain-pytest walk back from the red head to the first pass. That is the newest transition, so for relands it is p3, not p1. `--det` must agree with plain pytest at the truth and at its parent, else the case is dropped. 8 of 400 a2 attempts were dropped: the walk met a commit that could not run.

**The trivial rules now fail** (MEASURED, kind a2, 392 cases):

| rule | right |
|---|---:|
| name the oldest commit in range (round 1: 220 / 220) | 14 |
| name the newest commit in range | 53 |
| name the oldest candidate after pruning | 42 |
| name the newest candidate | 120 |
| **finder** | **370** (0 wrong, 22 unknown) |
| git bisect | 296 (placed 196/196; reland **100/196**) |

* In round 1, 0 of 622 candidate replays passed. In round 2, 803 of 1,476 passed: the ground truth now exercises the search.
* **Where git bisect fails:** on revert-and-reland histories it names a wrong commit in 96 of 196 cases (its probes land in the already-fixed first breakage). The finder names the truth in 187, withholds 9 and is wrong in none.

**Real history (kind b).** The reviewer proposed project reverts. Results (MEASURED):
* **Reverts:** 247 reverts with both commits on the first-parent chain, across the 41 cloned projects. 62 change no source module. In 81 of 125 attempted, the old commits could not be run by today's environment. I also tried a date-resolved environment (`uv --exclude-newer`, Python 3.12, the oldest that `--det-cache` supports): 8 of 83 installed, and 2 of those ran. Of the reverts that ran, few broke a test locally. **2 reverts gave cases** (faker, click), and in all 4 cases the walk's truth is the reverted commit.
* **Regression fixes** (a second source, added because reverts are thin): commits since 2021 whose message says regression and that change test files. The fix's test files are overlaid on the history before it; the walk finds where that test turns red. 10 fixes gave 23 cases (pytest 2, pyparsing 2, attrs 2, click, filelock, markdown, jsonschema). The bug, the culprit and the history are the project's own; only the test file is backported.

| kind b (27 cases, 12 distinct culprits, 8 projects) | right | wrong | unknown | executions, median | git bisect |
|---|---:|---:|---:|---:|---:|
| finder | 22 | 0 | 5 (suspect = truth in all 5) | 10 | 27 right, median 5 |

The 5 unknowns are pytest (2) and pyparsing (3). In each, later commits change the culprit's function again beyond the probe budget.

## 3. Labels corrected (R-019 M6, M7, M8)

* **M6, "14 of 14 no-code reds".** Round 1's row was **7 of 7 no-code reds from 4 mechanisms, plus 7 of 7 data-edit commits**. Round 2 reports them separately:
  * **No-code, single change, 15 cases:** 13 right, 2 unknown (toolz: green environment rebuilt inexactly; httpx: the test opens a socket in C, which `--det` does not control).
  * **Mechanisms:** package bump (pytest), a package appearing (rich), `PYTHONWARNINGS=error` (4 projects), `PYTHONOPTIMIZE=1` (5 projects; the whole session turns red through a pytest configuration warning), `PYTHONDEVMODE=1` (2), `COLUMNS=40` (2).
  * **Not covered:** time zone, locale, file permissions and runner image. I scanned 24 real suites under `TZ`, `LC_ALL`, `LANG`, `LANGUAGE`, `NO_COLOR`, `FORCE_COLOR`, `TERM`, `CI`, `PYTHONIOENCODING` and `HOME=/nonexistent`, and found no test whose red `--det` and plain pytest agree on (`round2/nocode2.py`, `results/scans/nocode-*.json`). H2 is the only file-permission case (synthetic, now right).
  * **With decoys:** 31 of 36 right, 0 wrong.
  * **Data-edit commits:** 15 of 15 (git bisect also 15 of 15).
* **M7, "median 3".** Round 1's 3 had no confirmation. Round 2's medians include every confirmation replay:

  | kind | finder median / p90 | git bisect median |
  |---|---|---|
  | a2 | 6 / 11 | 5 |
  | b | 10 / 11 | 5 |
  | c no-code | 3 / 4 | names a commit, always wrong |
  | c edit | 3 / 4 | 3 |
  | d | 17 / 21 | 4 (round 1) |

  On deterministic code regressions, **the finder now needs more executions than git bisect** (6 vs 5 on a2), because confirmation and the non-monotonic check cost 2 to 4 replays. It gains correctness on reland histories (187 vs 100 of 196) and names inputs, which bisect cannot.
* **M8, rebuild criterion.** Reported per population:
  * green environment rebuilt from the green key at the CI path: **30 of 33 exact (9% not exact)**. The 3 misses are toolz again: its own `egg-info`, as in round 1, and the finder now withholds those answers;
  * old commits: **81 of 125 revert attempts (65%)** could not be run by any environment I could build. They span 2012 to 2026, and `--det-cache` needs Python 3.12 or newer;
  * regression fixes since 2021: **16 of 143 (11%)**;
  * a2 windows (up to 200 commits back): **8 of 400 (2%)**.

  So "old environment cannot be rebuilt in more than 20% of cases" is **met (a NO) for history older than about 3 years** (ESTIMATED from the dates), and not met for recent history.

## 4. Clean timing (idle host, 20 kind-a2 cases, one at a time; MEASURED)

* **Per case:** finder median **9.3 s**, git bisect **5.1 s**.
* **Per replay:** one `--det` replay (re-exec, Level 0, key dump) median **1.1 s**.
* **Executions in this sample:** finder 6, bisect 5.
* **Correct:** finder 19 of 20 (1 unknown).
* Round 1's 3.9 s was without confirmation.

## What I decided, and why

1. **Withhold rather than guess.** Wherever a check is incomplete, the finder says "unknown" and records the suspect: a later commit touching the same inputs was not replayed, the environment rebuild was inexact, or the test reads an uncontrolled source. The prompt ranks a confident wrong culprit as worse than none. The cost is 32 unknowns, 27 of them with the right suspect. A product could show "probably commit X (not confirmed: N later changes to the same function unchecked)". Counted as a stated answer, that would make 527 of 533 right (ESTIMATED).
2. **Re-touch budget of 6** (plus every commit whose diff undoes the culprit's): with 4 and no undo detection, 2 reland cases were confidently wrong in an early pass (cachetools). A larger budget trades executions for fewer unknowns; I did not measure other budgets.
3. **Step 4 was not rerun.** It uses its own finder (`orderdep.py`), unchanged, on Python 3.9 environments. Its 62 of 63 and its one confident wrong answer (pykicad, non-monotonic) are round 1's. The same confirmation would probably turn that miss into "unknown" (ESTIMATED).
4. **Synthetic placement keeps the round-1 mutations.** Each round-1 mutation is reused with a new placement, so the same 200 one-token defects appear twice (placed, reland). The windows were rebuilt from today's first-parent chain because one structlog head of round 1 no longer exists upstream.

## Reviewer checks on the final rows (`review_r019/test_ground_truth.py`)

* **H5** (a candidate replay passes): **passes**.
* **M6** fails on `assert len(singles) == 14`. There are 15 singles now, all no-code; the check's second condition holds.
* **M7** asserts round 1's 303 rows and median 3. It cannot pass on any confirmed run: with one confirmation replay, the median is above the target by construction. Round 2's median is 5.
* **M8** fails because 97 attempts at old commits could not run (`generation-notes.txt`), which is the true state reported above.

## Errors or gaps found (for the coordinator)

1. **Engine:** the shared bytecode cache validates by mtime seconds and size. A CI workspace reused across commits (incremental checkout, the same second, same-size files) would run stale bytecode under `--det`. Found through the harness; the product impact is UNKNOWN.
2. **Finder limits** that remain:
   * a non-monotonic history whose fix does not touch the culprit's inputs is not detected (no case in the data; UNKNOWN rate);
   * an interaction between a commit and an input is reported as "unknown", not resolved;
   * a runner-image change (Python version) cannot be replayed by the input search (no real case found).
3. **Real-history scarcity:** most project reverts are not reproducible as test reds, and old commits cannot run on Python 3.12 or newer. Real culprits measured: 12 (round 2) plus 18 (step 4, round 1).

## Links

* Engine branch `claude/exact-culprit`:
  * `harness/culprit/finder.py`;
  * `harness/culprit/round2/` (`placed.py`, `realrevert.py`, `realfix.py`, `nocode2.py`, `refind.py`, `timing2.py`, `aggregate2.py`, `assemble.sh`, `test_finder_round2.py`);
  * `harness/culprit/review_r019/` (unchanged);
  * `harness/culprit/results/` (rows, `cases/`, `scans/`, `generation-notes.txt`, `summary.json`, `timing-a2.jsonl`).
* Review R-019: branch `claude/review-r019`, `sessions/2026-11-19-review-exact-culprit/REPORT.md`.
* Round 1 report: `review-input/REPORT.md` on that branch.
