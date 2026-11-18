DONE

# R-010 fix round · market test

Answers `REPORT.md` in this folder (FIX 2). Both defects are fixed, each reviewer test fails before and passes after.

* Before: fenvix-engine-cli `review-claude/market-test` @ 342fc11 (the delivery e2107683 plus the reviewer's tests).
* After: fenvix-engine-cli `claude/market-test` @ 2b6cd84 (code fix 8dca1fb, results 2b6cd84).

## Short answer

* **The headline holds: 7 of 10** have a mean of at least 50% in both views (MEASURED, recomputed).
* **Only prefect's numbers move:** mean 73.7% to 73.2% (env-ok), 73.7% to 73.2% (all units) (MEASURED).
* **Verified skips: 0 wrong of 7,277** (MEASURED). 4 mismatches remain, all flaky with evidence.
  * The old count was 7,280. Prefect's 3 wrong hits are no longer skips: the fixed rule reruns that unit.
* **The 2 pydantic-ai cases are flaky, now with evidence** (MEASURED). The cause is a harness problem, see note N1.

## Tests against "fix both, failing before and passing after"

Command: `python3 -m pytest -q harness/market_test/tests/` (MEASURED, this container).

| commit | result |
|---|---|
| 342fc11 (before) | 2 failed, 21 passed, 1 skipped. The 2 failures are the reviewer's tests |
| 2b6cd84 (after) | 29 passed, 1 skipped |

* The 2 reviewer tests in `test_r010_market_review.py` pass unchanged.
* 6 new guard tests in `test_r010_fixes.py`.
* The skipped test is the docusaurus one, which needs a checkout (as in the review).

## Fix 1: reads under `.git/` enter the proof key

**What changed:**
* `strace_deps.SKIP_PARTS` now drops only `.git/objects/`, no longer all of `.git/`.
* A unit that read or listed anything under the checkout's `.git/` records two things:
  * the resolved HEAD commit (`deps["git"]["head"]`);
  * the `.git` files it read (HEAD, refs, packed-refs, index, config), hashed like any other file.
* `decide()` reruns the unit when HEAD changed (reason `git:HEAD`) or when one of those files changed.
* A unit that never reads `.git` is not affected. A guard test checks it still skips.

**Re-verified on prefect (MEASURED, real checkout, `gitkey.py`):**

| last real run | verified at | fixed rule | fresh run vs cached |
|---|---|---|---|
| 03af2c2 (i = 6) | c1bd949 (i = 14) | rerun, `git:HEAD` | 18 test IDs differ |
| 29241a3 (i = 19) | daeaa15 (i = 21) | rerun, `git:HEAD` | 18 test IDs differ |
| daeaa15 (i = 21) | 7633e3e (i = 27) | rerun, `git:HEAD` | 18 test IDs differ |

* These are the 3 wrong hits of `tests/utilities/test_dockerutils.py`. The unit read `HEAD`, `config` and `packed-refs`.

**Which prefect units read `.git` (MEASURED):** 2 of the 57 sampled units, at the first and the last commit of the window.
* `tests/utilities/test_dockerutils.py` (known from the review).
* `tests/cli/test_shell.py` (new: the review's static scan did not list it).
* 0 capture errors in both probes.

**Other repositories (MEASURED, one captured run per sampled unit at the pinned head):**

| repository | units probed | units that read `.git` |
|---|---:|---:|
| esphome | 350 | 0 |
| moto | 226 | 0 |
| community.general | 247 | 0 |

* airflow, integrations-core, pydantic-ai, litellm, transformers, mlflow: not probed, UNKNOWN.
  * The review's static scan found no unit there that reads the checkout's own git (ESTIMATED).
  * Cheapest test: one `gitkey.py --probe` job per repository in the market-test workflow.

## Fix 2: a mismatch is wrong unless a rerun shows it flips

**What changed:**
* `walk.compare` stores the exit codes of the 2 extra runs (`rerun_codes`, `cache_code`, `fresh_code`).
* A rerun now matches a result only if both the test outcomes and "exit code is 0" match.
* `aggregate.classify` calls a mismatch flaky only with evidence:
  * an extra run disagrees with the fresh run; or
  * a re-check file under `results/*/recheck/` shows the flip.
* Items written before the fix that differ in the exit code alone count as wrong until a re-check exists.
* `recheck.py` now compares the exit code too.

**Effect on the old data before any re-check (MEASURED):** the 2 pydantic-ai items moved from flaky to wrong.

**Re-check of the 2 pydantic-ai items (MEASURED, this container, `recheck.py --reps 5`):**

Unit: `tests/harness/pixeltable/test_video.py`. Each cell is passed / total runs.

| item | commit | plain runs | captured runs (1 alone + 4 in parallel) |
|---|---|---|---|
| i = 15 | b5dcf1b (cached result) | 6 / 6 | 4 / 6 (2 test failures) |
| i = 15 | 4b389e1 (verified) | 5 / 5 | 3 / 5 (2 test failures) |
| i = 38 | 3d3b4d6 (cached result) | 4 / 6 (2 test failures) | 1 / 6 (4 timeouts, 1 test failure) |
| i = 38 | 593b32d (verified) | 5 / 5 | 4 / 5 (1 test failure) |

* Totals: plain 20 passed of 22; captured 12 passed of 22.
* **The walk's exact symptom reproduced 4 times:** all tests pass, then the run is killed at the 900 s timeout (exit code -9).
  * That is "same test outcomes, non-zero exit code", as in both walk items.
* The other 8 failures are the test itself failing (`CalledProcessError`). 2 of them happened without capture.
* So the file's pass or fail flips between fresh runs at the same commit, at all 4 commits under capture.
* Verdicts written by `recheck.py`:
  * i = 15: `not-reproducible (load-sensitive)`;
  * i = 38: `flaky (plain runs disagree)`.
* Files: `harness/market_test/results/r010/recheck/pydantic-ai-4b389e1ce5.json` and `...-593b32d58d.json`.

**Limits of this evidence:**
* The runs are in this container, not on the GitHub runner of the walk.
* The walk did not store the exit code of the fresh run. That it was -9 is ESTIMATED, not MEASURED.

## The headline, recomputed

Command: `python3 harness/market_test/market.py m1 m3 m4 m5 m7 --git-units harness/market_test/results/r010/gitkey/prefect.json --json harness/market_test/results/market-summary.json`

**How fix 1 is applied to the old walks:** the recorded shards have no `.git` reads, so they cannot be re-decided.
* `market.py --git-units` forces the units that read `.git` (measured by `gitkey.py`) to rerun at every transition.
* Their verification items leave the verified skips and are counted apart (`rekeyed_verify`).
* Applied to prefect only. esphome, moto and community.general measured 0 such units.

| repository | env-ok median / mean | all units median / mean | verified (wrong, flaky) | min saved / month |
|---|---:|---:|---:|---:|
| prefect, delivered | 98.8 / 73.7 | 98.8 / 73.7 | 150 (3, 0) | 29,501 |
| prefect, fixed | 98.1 / 73.2 | 98.1 / 73.2 | 147 (0, 0) | 29,291 |
| pydantic-ai, delivered | 87.2 / 68.5 | 74.1 / 58.2 | 641 (0, 2) | 32,690 |
| pydantic-ai, fixed | 87.2 / 68.5 | 74.1 / 58.2 | 641 (0, 2) | 32,690 |

Shares in %, MEASURED. Minutes ESTIMATED, as in the delivery.

* Every other repository is identical to the delivered `market-summary.json` (MEASURED, field by field).
* **Count:** 7 of 10 with a mean of at least 50% in both views (MEASURED):
  airflow, community.general, esphome, integrations-core, moto, prefect, pydantic-ai.
* **Verified skips:** 7,277, mlflow developer mode included (MEASURED). Wrong: 0. Flaky: 4.
  * pydantic-ai 2 (re-checked above), integrations-core 1, transformers 1.
  * In the last two, both extra runs gave the cached outcomes back.
* **Wrong hits of the delivered rule:** 3, all prefect `test_dockerutils.py`. Closed by fix 1.
* Sum of minutes saved over the 10: about 375,500 per month (ESTIMATED), was 375,700.
* The review's bootstrap intervals were not recomputed. Prefect moved 0.5 points and stays far from 50%.

**Correct wording now:** "0 wrong of 7,277 verified skips. 4 mismatches, each shown to flip between runs at the same commit. The delivered rule had 3 wrong hits on one prefect file that reads the commit from git; the key now includes it."

## What I decided, and why

* **Key all of `.git` except `objects/`, plus the resolved HEAD.**
  * The review proposed HEAD plus the index. Refs, packed-refs and config are added because `git describe` and version tools read them.
  * A new tag changes a git-derived version without changing HEAD.
* **Trigger on reads under the checkout's `.git/`, not on "the unit executed git".**
  * 22 sampled files run git on a temporary repository. They would lose every skip for no reason.
  * A git command in the checkout always reads `.git/HEAD`, so the trigger does not miss it.
* **Old exit-code-only items are wrong until re-checked.** No evidence means no flaky label, as the review asked.
* **No new walk of the 10 repositories.** It would cost many runner hours. The overlay plus the probes answer the question.
* **Fix commits pushed to `claude/market-test`** as a fast-forward that includes the reviewer's test commit. `run.json` is untouched, so no workflow started.

## What is missing

* **N1. Capture makes this pydantic-ai file time out (new, not fixed here).**
  * The test starts a Postgres server (pixeltable) that outlives pytest. `strace -f` waits for it.
  * A captured pass took 69 to 733 s (median 341 s, 12 passes) against 13 to 21 s plain (MEASURED). The unit timeout is 900 s.
  * A timeout is stored as a failure, so it only costs skips. It cannot cause a wrong reuse.
  * Remedy: stop tracing when the test process exits, and end the processes it left behind.
  * Test to write: a unit that leaves a daemon running must finish in about its plain time with exit code 0.
* **N2. A unit that reads `.git` now reruns at every commit.** That is sound but coarse.
  * A finer key would hash the output of the git commands the unit ran. Not needed for these numbers.
* **N3. `harness/skip_study2` has the same two defects.** The market test is a copy of it. Not touched: outside this task.
* **N4. `.git` probes for 6 repositories** (listed above) are not done. UNKNOWN until probed.
* **N5.** prefect needs uv 0.13.4 or newer. This container had 0.11.32, so I used uv 0.13.9 from PyPI for prefect.
* The review's risks R1 to R6 are unchanged by this round.

## Links

* fenvix-engine-cli `claude/market-test` @ 2b6cd84. Draft PR: none opened.
* Code: `harness/market_test/strace_deps.py`, `walk.py`, `aggregate.py`, `recheck.py`, `market.py`, `gitkey.py` (new).
* Tests: `harness/market_test/tests/test_r010_market_review.py`, `tests/test_r010_fixes.py`.
* Results: `harness/market_test/results/r010/gitkey/*.json`, `results/r010/recheck/*.json`, `results/market-summary.json`.
* How to rerun: `harness/market_test/README.md`, section "R-010 fixes".

## Errors or gaps in this brain

* `NUMBERS.md` has no market test entry yet. When added: prefect 98.1% / 73.2%, 0 wrong of 7,277 verified skips, `.git` reads in the key.
* `NOW.md` still says "Market test: intermediate 1 only".
* No prompt file exists for this fix round. The task came as a chat message, so "Done means" is that message.
* This session was first pointed at `prompts/P-020-pricing-v2.md`. That task was not started: this fix round replaced it.
