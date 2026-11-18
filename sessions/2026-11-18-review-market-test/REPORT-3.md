PASS

# R-010 · Round 2 (last) · market test fix check

Scope: only the two FIX items of round 1 (`review-input/R-010-REPORT.md`) against the fix delivery (`review-input/delivery-REPORT-2.md`).
* Before: `review-claude/market-test` @ 342fc11 (delivery e2107683 plus the two reviewer tests).
* After: `claude/market-test` @ 2b6cd84 (this branch's base).
* All runs are in this container. No GitHub Actions were used.

## Verdict in short

* **Fix 1 (`.git` reads enter the proof key): fixed.**
  * The reviewer test fails before and passes after.
  * The test file is unchanged between 342fc11 and 2b6cd84.
  * I found no other git-derived input that the harness still misses. Coverage limits are listed below as NOTES.
* **Fix 2 (no "flaky" without evidence): fixed.**
  * Without the re-check files, the new rule calls the 2 pydantic-ai items "wrong".
  * With the re-checks, they become "flaky". The re-check data supports that.
* **Headline recomputed independently from the raw shards: it holds.**
  * 7 of 10 in both views.
  * 0 wrong of 7,277 verified skips.

## Tests: before and after

Command: `python3 -m pytest -q harness/market_test/tests/` (MEASURED).

| commit | result |
|---|---|
| 342fc11 | 2 failed, 21 passed, 1 skipped. The 2 failures are exactly the two reviewer tests in `test_r010_market_review.py` |
| 2b6cd84 | 29 passed, 1 skipped (the docusaurus test needs a checkout) |

* `git diff 342fc11 2b6cd84 -- harness/market_test/tests/test_r010_market_review.py` is empty. So the tests were not weakened.

## Item 1: `.git` reads in the key

**The code (read in full):**
* `strace_deps.SKIP_PARTS` now drops only `/.git/objects/`.
* In `walk.normalize`:
  * a read-write `.git/*` file (the index refreshed by `git status`) is hashed as it is after the run;
  * any read or listing under `<src>/.git` records `deps["git"] = {head, paths}`.
* `decide()` adds the reason `git:HEAD` when the recorded HEAD differs from the current HEAD. The `.git` files themselves are compared like any other read.

**Extra probes I ran on 2b6cd84** (ad hoc tests in a scratch directory, built on the delivered `_walker` helper; both pass, MEASURED):
* *New tag, same HEAD.* A unit asserts on `git describe --tags`. A tag `v9.0` is then added at the same commit, and the fresh run fails. `decide()` reruns the unit, because the refs and packed-refs it read changed. This is the case the delivery gave for keying refs as well as HEAD.
* *Python reads `.git/HEAD` directly, without the git binary.* Example: a version helper that parses HEAD. The read is recorded as a git key, and the unit reruns at the next commit.
* The delivered guards also cover:
  * index-only changes (`git diff --cached`);
  * a unit that never reads `.git` keeps its skip.

**Other git-derived inputs. None missed inside the harness; limits as NOTES:**
* Every git command reads `.git/HEAD` when it finds the repository. In the harness's detached checkout, that file contains the commit itself. So any unit that runs git, or parses `.git`, reruns at every commit.
* Leaving out `.git/objects` is safe. The objects are addressed by commit, and HEAD and the index are in the key.
* Versions derived from git that reach tests through installed metadata, or through an ignored version file: already in the key (round 1). They cost skips (risk R3), not correctness.

**Re-verification data (MEASURED, from `results/r010/gitkey/*.json`):**
* prefect: the 3 recorded wrong hits on `test_dockerutils.py` now decide `git:HEAD`. At each case 18 test IDs differ in the fresh run, and the unit read `HEAD`, `config` and `packed-refs`.
* The prefect probes at 57e0a7c and 5e8ca11 find 2 units that read `.git`:
  * `tests/utilities/test_dockerutils.py`;
  * `tests/cli/test_shell.py`, which round 1's static scan missed.
* Probe counts:
  * esphome: 350 units probed, 0 read `.git`;
  * moto: 226 units, 0;
  * community.general: 247 units, 0.
* 0 capture errors in every probe.

**NOTES (none blocks):**
* N-a. The old walks are not re-decided. They are corrected by an overlay: `market.py --git-units` forces the probed git units to rerun.
  * The unit list comes from probes at 1 or 2 commits only.
  * Six repositories were not probed: airflow, integrations-core, pydantic-ai, litellm, transformers, mlflow (UNKNOWN).
  * Their verified samples show no mismatch from git, which supports that they have no such unit (MEASURED). But an unprobed git-reading unit would still be counted as a skip.
  * Cheapest test: one `gitkey.py --probe <head>` per repository.
* N-b. The trigger is a path prefix, `<src>/.git`. If the checkout were a `git worktree`, or `.git` were a gitdir file pointing outside the source root, the reads would fall outside the capture roots and would be missed.
  * The harness always clones, so this cannot happen in these walks.
  * It matters for the product on CI systems that use worktrees.
  * Test: a unit that runs `git rev-parse HEAD` in a worktree checkout must rerun at the next commit.

## Item 2: "flaky" only with evidence

**The rule (`aggregate.classify` at 2b6cd84):**
* A matching re-check verdict in `FLAKY_VERDICTS` gives flaky.
* Otherwise:
  * an old item (no `rerun_codes`) with an empty `diff` is wrong, because its reruns were blind to the exit code;
  * a new item is flaky only if a rerun disagreed with the fresh run on (outcomes, exit code == 0), or matched the cached result;
  * otherwise it is wrong.
* `walk.compare` stores `cache_code`, `fresh_code` and `rerun_codes`, and compares on the exit code too.
* `recheck.py` compares on (tests, code == 0).

**The 2 pydantic-ai items:**
* Without the re-check files, the code at 2b6cd84 classifies both as **wrong**. With them, both are **flaky** (MEASURED: `classify()` with `_RECHECK` emptied, then restored).
* The re-check's "rec" commits are the unit's real last runs in the walk:
  * i = 14 (b5dcf1b, reason `read:installed`) before the verified skip at i = 15;
  * i = 37 (3d3b4d6, reason `py-source:source`) before i = 38.
* Every count in the delivery's table recomputes from the two JSON files (MEASURED):
  * plain runs: 6/6, 5/5, 4/6, 5/5 passed;
  * captured runs: 4/6, 3/5, 1/6, 4/5 passed;
  * totals: plain 20 of 22, captured 12 of 22.
* The 4 runs that passed every test and still ended with exit -9 (timeout) are all at the cached commit 3d3b4d6.
* At the two verified commits, 4b389e1 and 593b32d:
  * plain runs pass 5/5;
  * captured runs flip pass/fail through real test failures (2/5 and 1/5 fail).
* The walk's fresh run of a verified skip is a captured run. So the evidence shows the file's pass or fail is not stable at the same commit under the walk's conditions, at all 4 commits. The "flaky" labels are supported.
* Limits, stated correctly in the delivery: the re-checks ran in this container, not on the walk's runner, and the walk's fresh exit code was not stored (that it was -9 is ESTIMATED).

**NOTE N-c (no block):**
* A new-style item is called flaky when any one rerun disagrees with the fresh run. That includes a rerun that only timed out.
* So a real code change on a unit that also times out under load would be labelled flaky.
* This is the rule round 1 proposed, so it is not a defect. It is a softer bar than "reproduces the cached result".
* Cheapest test: in `test_r010_fixes.py`, an item with `rerun_codes = [-9, 1]`, the fresh run failing, and the cached run passing. Decide whether it should be "wrong".

## Headline, recomputed from the raw shards

**Method:**
* My own script reads `results/m1, m3, m4, m5, m7/walk/*.json.gz` directly. It uses neither `aggregate.py` nor `market.py`.
* It applies the same rules:
  * cost = max(test, wall − 5th-percentile wall);
  * a commit counts only when all shards reached it;
  * env-ok drops the files that failed at baseline;
  * late and mid windows are merged by commit;
  * prefect's 2 `.git` units are forced to rerun.
* Separately, `market.py ... --git-units .../prefect.json --json` reproduces the committed `market-summary.json` byte for byte (MEASURED).

| repository | transitions | env-ok median / mean | all units median / mean | verified | mismatches |
|---|---:|---:|---:|---:|---:|
| esphome | 50 | 98.6 / 89.0 | 97.2 / 87.7 | 1,300 | 0 |
| moto | 50 | 98.2 / 76.2 | 98.0 / 76.1 | 688 | 0 |
| prefect | 50 | 98.1 / **73.2** | 98.1 / **73.2** | 147 (+3 moved out by the git rekey) | 0 |
| pydantic-ai | 50 | 87.2 / 68.5 | 74.1 / 58.2 | 641 | 2 (flaky, re-checked) |
| integrations-core | 50 | 73.8 / 65.0 | 56.8 / 50.1 | 2,899 | 1 (flaky) |
| community.general | 50 | 59.8 / 55.5 | 59.3 / 55.1 | 885 | 0 |
| airflow | 50 | 90.6 / 55.6 | 83.4 / 51.2 | 241 | 0 |
| litellm | 37 | 0.0 / 22.6 | 0.0 / 21.4 | 238 | 0 |
| transformers | 46 | 0.0 / 21.7 | 0.0 / 19.6 | 43 | 1 (flaky) |
| mlflow (CI) | 42 | 0.0 / 0.0 | 0.0 / 0.0 | 0 | 0 |
| mlflow (dev, outside the verdict) | 50 | 96.9 / 71.6 | 75.1 / 55.5 | 195 | 0 |

Shares in %, MEASURED.

**What the table shows:**
* **Count with a mean of at least 50%:** 7 of 10 env-ok, and 7 of 10 all units (MEASURED). The 7 are airflow, community.general, esphome, integrations-core, moto, prefect and pydantic-ai.
* **Verified skips:** 7,277 (MEASURED).
  * Wrong: 0.
  * Flaky: 4.
    * pydantic-ai 2, flaky with re-check evidence.
    * integrations-core 1 (`tls/tests/test_utils.py`) and transformers 1 (`smolvlm`): both reruns gave the cached outcomes back, so `rerun_matches_cache = 2`.
* Prefect before the fix (342fc11, MEASURED): mean 73.7% / 73.7%, 150 verified, 3 wrong. After: 73.2% / 73.2%, 147 verified, 0 wrong. This matches the delivery.
* Minutes saved per month, sum over the 10 with mlflow as CI: 375,536 (ESTIMATED, as in the delivery's "about 375,500"). prefect: 29,291.
* The integrations-core env-ok figure is 64.98%. Round 1 printed 64.9 by truncation; nothing changed.

**Wording (NOTE, no block):**
* The 7,277 includes mlflow developer mode (195), which is outside the 10-repository verdict. On the 10 alone it is 7,082 verified skips, 0 wrong.
* The shorter count is better wherever the sentence starts with "of 10 repositories".
* Round 1's points on the 7-of-10 noise (R1) and on the wording "large modular Python monorepos picked as targets" (R2) still apply; they were out of scope here.

## Links

* Delivery code: this branch, `harness/market_test/` (identical to `claude/market-test` @ 2b6cd84).
* Reviewer tests: `harness/market_test/tests/test_r010_market_review.py`.
* Data used: `harness/market_test/results/{m1,m3,m4,m5,m7}/walk/*`, `results/r010/gitkey/*.json`, `results/r010/recheck/*.json`.
