FIX 8: the YES verdict does not hold. Four kinds of input make the finder name a wrong culprit with confidence (High), the ground truth behind 220 of the 303 cases cannot tell the finder from a trivial rule (High), and three labels overstate the result (Medium). Recommended verdict for P-029: **PARTIAL**.

# Review R-019: exact culprit (idea 2)

* Target: branch `claude/exact-culprit` at 3c2e796 (`harness/culprit/`), plus `review-input/REPORT.md`, `P-029-exact-culprit.md` and `IDEA-2.md`.
* Branch: `claude/review-r019`.
* How it was run: the engine was built with maturin into a fresh CPython 3.13.18 virtualenv, and the prototype finder (`harness/culprit/finder.py`) was used as it is, called the same way `run_code_cases.py` and `nocode.py` call it.
* Evidence committed on this branch, all in `harness/culprit/review_r019/`:
  * `test_wrong_culprits.py`: 4 failing tests (H1 to H4) and 1 passing control. It needs detpy installed in the interpreter that runs it, and takes about 40 s.
  * `test_ground_truth.py`: 4 failing checks over the committed result rows (H5, M6, M7, M8). No engine is needed.

  Command: `python -m pytest -p no:cacheprovider harness/culprit/review_r019`. Result here: 8 failed, 1 passed.

## 1. Re-deriving the numbers

Running `python3 harness/culprit/aggregate.py harness/culprit/results` gives exactly the committed `summary.json`. I also checked every figure in the "number that says yes" table and in the per-kind tables against the rows. They all match:

* 302/303 correct; executions median 3, mean 5.86, p90 17, max 30.
* Kinds a, b and c alone: median 3, p90 5, max 7.
* Kind a: 200/200 for both the finder and git bisect. Finder executions 3/5/7, git bisect median 5. Distances k: 84/57/31/28, median 28.5. The tables by k and by library match.
* Kind c: 40/40, 14/14 singles, git bisect 20/40. Rebuilds: 36 needed, 33 exact.
* Step 4: 62/63, executions 17/21/30 (polluter search 8, commit search 10). Git bisect: 548/630 wrong, 55 cases with most attempts wrong, 40 cases with all 10 wrong.
* Clean timing: finder 3.9 s and git bisect 1.3 s per case; 1.3 s per `--det` replay, 0.36 s per plain pytest step, 0.7 s for the key diff.

One small error: "19 distinct culprit commits" in step 4 is really **18 distinct true culprits**. The 19th is the commit the finder wrongly named for pykicad.

The labels are where the table goes wrong (M6, M7, M8 below). Every number is "MEASURED", but three of them measure something narrower than the criterion they are set against.

## 2. Is the ground truth honest?

* **Are the mutants realistic?** Yes. They are one-token changes inside function bodies, and the red test must fail under both plain pytest and `--det`. The finder never sees the mutation itself, only unit digests.
* **But the answer leaks through its position (H5).** The culprit sits in the same place in every case:
  * `mutants.build_chain` commits the mutant directly on the green commit;
  * `nocode.edit_tree_commits` commits the fixture edit right after the green commit.

  So in all 220 commit cases (kind a, plus the 20 fixture-edit cases of kind c), the culprit is the **oldest** commit of (green, red]. Everything after it is red by construction.

  In the rows, the finder made **622 candidate replays and none passed**. A rule that names the oldest candidate commit and runs nothing scores 220/220. For the same reason, the 200/200 for git bisect says nothing either.

  "Distance k" changes how many commits lie between the culprit and the red head, but never what comes before the culprit. A history that breaks, gets fixed, then breaks again (H4) cannot occur.
* **The red test always runs the mutated function**, because it is chosen from the tests the mutant kills. So pruning can never drop the culprit. That is fine as a design, but it is why pruning was never at risk of being wrong.
* **Selection bias.** When today's environment could not run an old green commit, the case was dropped and a nearer distance was used instead (see `generation-notes.txt`). That happened in 240 attempts: click 168, toolz 42, structlog 30. Arrow's 43 rejected mutants were dropped for clock reasons. Exactly the cases that would test the "old environment" criterion are missing (M8).
* **Are the baselines fair?**
  * Kind a: same test, plain pytest, `-p no:randomly`. Fair.
  * Kind c: git bisect cannot name an input, so the 20/40 is by design. That is fair as far as it goes, but the comparison is made against a tool that is not trying to answer the same question.
  * Step 4: the baseline runs the full suite in random order, while the finder runs a fixed deterministic order and identifies the polluter first. That matches CI practice, but a fixed-order `git bisect run` of the victim (`-p no:randomly`) was not measured. So the 87% shows that random-order bisect fails, not that bisect fails. I have no reproduction for this, so it is an observation, not a counted finding.
  * Step 4 truth and finder use the same oracle (the pair under `--det`). Only the "named commit edits the polluter or victim file" check is independent of it.

## 3. Hunting wrong culprits

All four cases run the unchanged finder on small git repositories. Keys are recorded with `--det-cache-keys`, exactly as the harness records them. Each test asserts the right answer and fails today.

| # | case | truth | finder answer | finder executions | git bisect |
|---|---|---|---|---:|---|
| H1 | the red needs `APP_STRICT=1` **and** `APP_LEGACY_FORMAT=1`; `LOG_LEVEL` INFO→DEBUG also changed and is harmless | the two variables together | **`env:LOG_LEVEL`** (shown harmless alone) | 2 | cannot name an input |
| H2 | a commit drops the exec bit of `bin/deploy.sh` (100755→100644, same content); a later commit harmlessly refactors `script_path`, which the test runs | the mode commit | **the refactor** | **0** | right |
| H3 | flaky test (two `uuid4` ids assumed to sort in creation order), 3 harmless commits to `new_id` | no culprit: it is flaky at green too (12 replays: pass and fail) | **one of the three commits**, every run | 1-2 | n/a |
| H4 | C1 breaks `f`, C2 reverts C1, C3 breaks `f` again | C3 | **C1** | 1 | right (C3) |
| control | one break in the middle of 8 commits that all change `f` | c5 | c5 | 3 | |

What goes wrong in each case:

* **H1, interaction** (`finder.py` input split): the split applies one half of the candidates to the green environment. If that half passes, it keeps the *other* half. When neither culprit alone reproduces the red, the search walks away from both and ends on the decoy. The IDEA's risks section expects "two inputs together" to need "a slightly larger search"; instead the finder answers wrongly.
* **H2, input outside the key**:
  * `os.access` and `os.stat` are not recorded inputs;
  * `commit_candidates` compares blob contents, so a mode-only commit is never a candidate;
  * with a single candidate, the search costs 0 executions and nothing is checked.

  File permissions were one of the six change kinds named in P-029, and no case covered them (M6).
* **H3, flaky test:** the key already flags the test (it drew OS entropy without `--det-urandom`, so it is never cacheable). The finder ignores that flag, never re-runs the green side, and its binary search always returns `cands[hi]`. Whatever the outcomes, it names a commit.
* **H4, non-monotonic history:** the binary search over candidates assumes a monotonic history. Its first probe is the oldest candidate, C1, which is red, so it stops there. The report already notes this kind of miss for step 4 (pykicad). Kind a cannot contain it (H5). Plain git bisect gets this case right.

**Common cause:** the finder never confirms its answer (REPORT decision 2: "No confirmation run"). H1, H2 and H3 would each have been caught by one or two confirmation replays:

* H1: "the named input alone, applied to green, is red";
* H2: "the parent of the named commit passes";
* H3: "green, replayed, passes".

H4 needs a red-side check as well, for example searching from the red head backward, as step 4 does.

**Environment that cannot be rebuilt:** if a distribution cannot be installed, `EnvBuilder.venv_for` raises and the harness records an error instead of an answer. That is not a confident wrong answer, so it is not counted. However, when a rebuild is *inexact*, the finder still answers: the 3 toolz rows have `rebuilt_exactly: false` and still name a culprit. Nothing refuses an answer from an inexact environment.

## 4. The real-history gap: YES does not hold, PARTIAL is the honest verdict

The yes-number is "≥ 95% over ≥ 300 cases", and the plan names three sources of cases. The 303 cases break down like this:

* **200 (kind a):** synthetic. The culprit is always the oldest commit, and the history is monotonic by construction (H5).
* **40 (kind c):** 14 changes in three variants each:
  * 7 are fixture-edit commits, again placed first;
  * the 7 true no-code changes come from 4 mechanisms (PYTHONWARNINGS in 4 repositories, the pytest bump, rich appearing, NODE_ENV).
* **63 (step 4):** real defects, but only 18 distinct culprit commits and 24 polluters, judged with the finder's own oracle.
* **0 (kind b):** real regressions.

No case contains a history that is not monotonic, a red caused by two inputs together, a flaky red, or an input outside the key. All four kinds are common in real CI, and all four produce confident wrong answers (H1 to H4).

Step 1b is exactly the part that would have exposed them. So without it the verdict cannot be YES. Even as PARTIAL, the result should be reported as:

> correct on synthetic, culprit-first cases (not discriminating); 62/63 on real order-dependent defects (18 distinct culprits); 0 real regressions measured; median executions 3 without any confirmation, 4 with one; four classes of wrong answer reproduced.

The proposed next test (project reverts in the 10 market-test repositories) is the right one. It should place no culprit by construction and should include the four cases above.

## Findings

High: a wrong answer stated with confidence, or a ground truth that carries the headline number. Medium: a label that overstates.

### H1. Two inputs needed together are blamed on an innocent third input
* Test: `test_wrong_culprits.py::test_two_inputs_together_are_not_blamed_on_a_third`
* Result: the finder names `env:LOG_LEVEL` in 2 executions; that variable alone leaves the test green.
* Fix: after the split, confirm that the named input alone turns green into red. If it does not, fall back to a ddmin-style search over pairs and complements.

### H2. Red from an input outside the proof key is blamed on a harmless commit, with 0 executions
* Test: `test_exec_bit_dropped_is_not_blamed_on_a_later_refactor`
* Cause: an exec-bit change is neither a key input nor a commit candidate, because pruning compares content only.
* Result: git bisect is right here; the finder is wrong without running anything.
* Fix:
  * always confirm that the named commit's parent passes;
  * make the mode part of the in-repo file value in pruning;
  * record `os.stat`/`os.access` (mode) as inputs.

### H3. A flaky test is blamed on a commit
* Test: `test_flaky_test_is_not_blamed_on_a_commit`
* Cause: the key's entropy flag (and `not_cached`) is ignored, and the green side is never replayed.
* Fix: refuse to answer, or switch to step-4 style repetition, when the red key carries an uncontrolled-entropy, network or real-clock flag, or when replaying green does not pass.

### H4. A non-monotonic history yields a commit whose breakage was already reverted
* Test: `test_non_monotonic_history_names_the_newest_transition`
* Result: the finder names C1; git bisect names C3, which is right.
* Fix: search from the red end, or check that the named commit's change still differs at red (here, C1's digest of `f` does not survive to red).

### H5. Ground truth in 220 of 303 cases cannot discriminate
* Test: `test_ground_truth.py::test_planted_culprit_is_not_always_the_first_commit_of_the_range`
* Evidence: 622 of 622 candidate replays were red, and "name the oldest candidate" is right 220/220 with 0 executions.
* Fix: plant the culprit at a random position in the range, and include break-fix-break and two-commit interaction cases.

### M6. "14 of 14 no-code reds" is 7 no-code reds and 7 commits
* Test: `test_fourteen_no_code_reds_are_no_code`
* Evidence:
  * the 7 fixture edits are commits, which git bisect also finds (7/7);
  * the true no-code reds are 7 cases from 4 mechanisms;
  * none of locale, time zone (except as a decoy), file permissions or runner image is ever the culprit. H2 shows that the file-permission kind fails.
* Fix: relabel the row as "7/7 no-code (4 mechanisms) + 7/7 data-edit commits".

### M7. "Median 3" holds only because answers are never confirmed
* Test: `test_median_executions_with_one_confirmation_replay`
* Evidence: with one confirmation replay per case, the median is 4. H1 to H3 show the confirmation is needed. The report's own estimate (+1 to +2) already puts the criterion at 4 to 5, above the target of 3.
* Fix: report the median with confirmation and compare that against the target.

### M8. The rebuild "NO" criterion is reported as passed but was not measured for old environments
* Test: `test_rebuild_criterion_includes_old_commits_that_could_not_run`
* Evidence:
  * the 3/36 figure covers only kind c, within one 8-commit window, rebuilt at the original path;
  * in kind a, today's environment could not run the green commit in 240 attempts (click, toolz, structlog), and those cases were replaced by nearer ones.

  The report body says "not tested here", but the table presents the criterion as met (8%).
* Fix: mark it UNKNOWN in the table, and count old green commits that cannot be run as rebuild failures in the next round.

### Not counted (no reproducible case, or Low)
* The step-4 baseline was not run in fixed order.
* Step 4 has 18 distinct culprits, not 19.
* The finder does not refuse when a rebuild is inexact.
* The overall median sits exactly on the threshold (3).
