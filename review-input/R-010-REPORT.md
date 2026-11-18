FIX 2

# R-010 · Review of the market test

Delivery: `sessions/2026-11-17-market-test/REPORT.md` (PARTIAL). Engine: fenvix-engine-cli `claude/market-test` @ e2107683, `harness/market_test/`.
Reviewer tests: fenvix-engine-cli branch `review-claude/market-test` @ 342fc11, file `harness/market_test/tests/test_r010_market_review.py`. Both tests FAIL on e2107683.

## Verdict in short

* The numbers are right. Every median, mean, count and minutes figure recomputes from the raw shards with an independent script: exact for shares and counts, within 0.1% for minutes.
* **The decision holds with margin.** At least 5 of 10 is robust, with probability about 1.00 (env-ok) and 0.99 (all units) under a bootstrap over transitions (ESTIMATED).
* **"7 of 10" is a point count, not a stable number.** Airflow (env-ok) and integrations-core (all units) sit inside the noise around 50%.
* **Two proven errors:**
  1. The `.git` hole. A unit that reads the commit from git reuses a PASS at a commit where it FAILS.
  2. The verifier calls an exit-code-only mismatch "flaky" without evidence. So the headline "0 of 7,280 verified skips changed a pass or fail" is not proven. 2 verified skips (pydantic-ai) went from a passing file to a failing file. Their "flaky" label rests on reruns that cannot tell.

## Proven errors (each a failing test on e2107683)

### 1. `.git` is outside the key: the proof rule reuses a pass where the fresh run fails

Test: `test_unit_that_reads_the_commit_from_git_reruns_when_the_commit_changes`.

**What the test does:**
* It builds a test file with the shape of prefect's `tests/utilities/test_dockerutils.py`:
  * the IDs come from `git rev-parse --short=7 HEAD`;
  * the file also asserts on the commit subject.
* The next commit changes only a file the unit never reads (`README.md`) and has the subject "BROKEN release".
* The fresh run at that commit has other test IDs and exits 1.
* `decide()` returns `closure = None` (skip).

**Why it matters:** this is the pass/fail form of prefect's 3 strict wrong hits.
* `strace_deps.SKIP_PARTS` drops every read under `/.git/`.
* So any unit whose IDs or outcome come from the commit is reused with the old result.

**Effect on the numbers (MEASURED, recomputed):**
* If prefect's `test_dockerutils.py` reruns at every transition, prefect's mean goes from 73.7% to 73.2%.
* The headline does not move.

**Proposed fix (cheapest sound one):**
* If a unit executes `git` or reads anything under `.git/`, add the resolved HEAD commit to its key.
* Add the content hash of `.git/index` when it is read, because `git ls-files` and `git diff` read the index.
* Keep `.git/objects` out of the key.

**Can other projects hit the same class? Yes, in principle. In this sample, only prefect.**
* Static scan of every sampled test file at the pinned heads (ESTIMATED, a grep heuristic): 23 sampled files run git or name `.git`.
  * 22 work on a temporary repository or a mock: airflow 1, esphome 6, integrations-core 4, mlflow 4, pydantic-ai 5, transformers 1, prefect `tests/runner/test_storage.py`.
  * Only prefect's `test_dockerutils.py` reads the checkout's own git.
* Library code the tests load can read git too:
  * `mlflow/tracking/context/git_context.py` tags runs with the source commit;
  * also `prefect/_internal/git.py` and `prefect/_internal/versioning.py`, and `esphome/git.py`.
  * A test that asserts on such a value is in the class. Whether one exists in the full suites: UNKNOWN.
* Versions derived from git (DECLARED by each `pyproject.toml`):
  * prefect: versioningit, `{base}+{distance}.g{rev}`;
  * pydantic-ai: uv-dynamic-versioning, 5 packages;
  * integrations-core `ddev`: hatch-vcs.
  * These reach the tests through installed metadata or a written version file under the source root. Both are in the key: pydantic-ai reruns 215 units at each reinstall. So they cost skips but do not cause wrong hits. See risk R3 for the cost side.

### 2. The verifier labels an exit-code-only mismatch "flaky" without evidence

Test: `test_reproducible_exit_code_change_on_a_verified_skip_is_wrong_not_flaky`.

**What the test does:** it runs the real `walk()` with `run_unit` and `decide` stubbed.
* The verified skip exits 0 at c0 and 1 at c1, with identical test outcomes. The exit code of 1 reproduces on every run.
* `walk.compare` reruns twice but compares only `outcome_summary` (test outcomes), never the exit code. So it records `rerun_matches_cache = rerun_matches_fresh = 2`.
* `aggregate.classify` returns `"flaky"`. The test expects `"wrong"`.

**The data has exactly this case (MEASURED):** pydantic-ai `tests/harness/pixeltable/test_video.py` at i = 15 (4b389e1ce) and i = 38 (593b32d58).
* Both items read `same: false, diff: [], rerun_matches_cache: 2, rerun_matches_fresh: 2`.
* The cached run had exit code 0 or 5, otherwise it would not have been skipped.
* At the next transitions (i = 16 and 39) the decision is `cached-failure`. So the fresh run of the verified skip exited non-zero.
* So these are 2 verified skips where the cached result says "file passes" and the fresh run says "file fails". The two extra runs never checked whether that reproduces.

**Is it probably flaky? ESTIMATED yes:**
* the same file verified `same` at i = 35 and 43;
* it passed again at i = 16 and 39.
* But the delivered method does not prove it.

**Correct wording until fixed:** "0 of 7,280 verified skips changed a test's outcome. 2 changed the file's exit code (pass to fail), verdict open."

**Proposed fix:**
* Store the exit code of the 2 extra runs.
* Call a mismatch flaky only if an extra run disagrees with the fresh run on (outcomes, exit code == 0).
* Re-check the 2 pydantic-ai items at their commits with 5 plain runs each, using `recheck.py`.

## The numbers, recomputed

**How I checked:**
* Re-ran `market.py m1 m3 m4 m5 m7 --json`: byte-identical to the committed `market-summary.json` (MEASURED).
* Then recomputed from the raw shards with my own script, without `aggregate.py` or `market.py`: same cost rule, same "all shards reached the commit" rule, same window merge by commit.
* Delivered tests: `pytest harness/market_test/tests/` gives 21 passed, 1 skipped (the docusaurus test needs a checkout) (MEASURED, this container).

| repository | transitions | env-ok median / mean | all units median / mean | rerun-everything commits | verified (mismatch) | min saved / month |
|---|---:|---:|---:|---:|---:|---:|
| esphome | 50 | 98.6 / 89.0 | 97.2 / 87.7 | 0 | 1,300 (0) | 3,556 |
| moto | 50 | 98.2 / 76.2 | 98.0 / 76.1 | 9 | 688 (0) | 2,216 |
| prefect | 50 | 98.8 / 73.7 | 98.8 / 73.7 | 10 | 150 (3) | 29,501 |
| pydantic-ai | 50 | 87.2 / 68.5 | 74.1 / 58.2 | 8 | 641 (2) | 32,686 |
| integrations-core | 50 | 73.7 / 64.9 | 56.8 / **50.1** | 6 | 2,899 (1) | 2,942 |
| airflow | 50 | 90.6 / **55.6** | 83.4 / **51.2** | 21 | 241 (0) | 69,034 |
| community.general | 50 | 59.8 / 55.5 | 59.3 / 55.1 | 1 | 885 (0) | 159 |
| litellm | 37 | 0.0 / 22.6 | 0.0 / 21.4 | 22 | 238 (0) | 201,351 |
| transformers | 46 | 0.0 / 21.7 | 0.0 / 19.6 | 27 | 43 (1) | 34,291 |
| mlflow (CI) | 42 | 0.0 / 0.0 | 0.0 / 0.0 | 42 | 0 | 0 |
| mlflow (dev) | 50 | 96.8 / 71.5 | 75.1 / 55.5 | 12 | 195 (0) | 29,724 |

Shares in %, MEASURED. Minutes ESTIMATED, as in the report.

**What the table shows:**
* Counts:
  * 7 of 10 have a mean of at least 50% in both views (MEASURED);
  * 7,280 verified skips (MEASURED);
  * 7 mismatches: 3 prefect test-ID changes, 2 pydantic-ai exit-code changes (error 2), 1 integrations-core, 1 transformers.
* The integrations-core (`tls/tests/test_utils.py`) and transformers (`smolvlm`) mismatches are well labelled flaky. In both, the two plain reruns matched the cached result and not the fresh one.
* Minutes saved: my values differ from the report by at most 0.1% (pydantic-ai 32,686 vs 32,690; mlflow-dev 29,724 vs 29,752).
  * The sum over the 10, mlflow as CI, is about 375,700 serial test minutes per month (ESTIMATED). 54% of it is litellm, which fails the 50% rule.
  * So any total-minutes claim is driven by a repository below the line. Say so wherever a total is used.

**Is the env-ok view fair? Yes, as long as both views are printed. The report prints both.**
* Env-ok leaves out the files that fail at the first commit's plain run. That assumes they would skip at the same rate as the rest. All units assumes they never skip. The truth lies between.
* The gap matters only where many files fail at baseline:
  * integrations-core: 313 of 1,119 files (28%);
  * pydantic-ai: 29 of 245;
  * mlflow-dev: 20 of 85.
* The 7 of 10 holds in the all-units view as point estimates. integrations-core passes by 0.13 points (50.13%).

**How certain is the count? (ESTIMATED: bootstrap over transitions, 4,000 replicates, repositories independent)**
* Consecutive commits are correlated, so these intervals are, if anything, too narrow.
* Env-ok view:
  * airflow 55.6%, 90% interval [44.5, 66.7], P(mean < 50%) about 0.20;
  * every other one of the 7 is above 50% at the 90% level;
  * P(count ≥ 7) about 0.80; P(count ≥ 5) about 1.00.
* All-units view:
  * integrations-core 50.1% [45.6, 54.2], P(< 50%) about 0.45;
  * airflow 51.2% [40.8, 61.6], P(< 50%) about 0.43;
  * pydantic-ai 58.2% [50.8, 65.5];
  * P(count ≥ 7) about 0.30; P(count ≥ 5) about 0.99.
* File sampling adds little. A bootstrap over the sampled files gives airflow [54.6, 56.9], prefect [71.1, 76.1] and transformers [16.6, 26.7] (ESTIMATED). integrations-core and community.general are 100% samples.
* **Proposal:**
  * Describe the market as "at least 5 of 10 (the decision rule) with margin; 7 of 10 as measured".
  * Cheapest test that decides the 7: a second, disjoint 50-commit window for airflow and integrations-core, 4 shards each.

## Point 2: is the verification sample fair? Yes, with one hole (error 2) and one blind spot (R4)

* **Random per commit:** yes.
  * `random.Random(f"{name}-{shard}")` draws for each skipped unit with p = 0.08, before any run and independent of outcomes.
  * Effective rate per repository: 6.8% (transformers) to 8.5% (mlflow-dev) (MEASURED).
* **Fresh run at the same commit:** yes. Same checkout, under strace, in the same pool as the units that must run.
* **Independent of the cache:** yes. The fresh run does not read the cached record; only the verdict compares against it.
  * Blind spot R4: the tree is cleaned with `git clean -ffd` without `-x`. Ignored files (`__pycache__`, `*.egg-info`, ignored outputs) persist, and the cached and fresh runs share them.

## Point 4: sampling rules and low results

**Files:**
* The rule is `sha1("s2:" + path) < fraction`. It is fixed and does not depend on any outcome.
* The fractions were changed once, in 11b99f2 at the m1 launch (2026-11-17 19:50 UTC). That was before any measured walk and after local smoke checks only.

**Transitions:**
* 51 consecutive first-parent commits up to heads pinned on 2026-11-17.
* The extra windows (litellm mid and late, integrations-core late, mlflow-dev late) start where the early window stopped and end where the budget ran out. Their boundaries are mechanical, not chosen from results.
* mlflow-dev dropped `tests/server/auth/test_auth.py` from its sample after it hung (R5).

**Low results:** reported as plainly as the high ones, in the answer, the table and the causes section.
* litellm 0% / 23%, transformers 0% / 22%, mlflow 0% (MEASURED).
* mlflow developer mode is reported but kept out of the verdict. That is correct.

## Risks (my opinion; none blocks), each with the cheapest test

* **R1. The 7 of 10 count is inside the noise** (above). Test: a second 50-commit window for airflow and integrations-core.
* **R2. The headline over-generalises.**
  * The 10 were picked because they look like the target: modular monorepos.
  * The excluded candidates were excluded for predicted low skip: sympy, scikit-learn, pandas, Django apps.
  * "7 of 10 large Python repositories" should read "7 of 10 large modular Python monorepos picked as targets".
  * No test needed, wording only.
* **R3. Version strings in installed metadata can erase pydantic-ai's skip in a CI that rebuilds the project at every commit.**
  * At all 4 reinstall transitions pydantic-ai skips 0% (MEASURED).
  * The first reason is its own `pydantic_ai_slim-<version>+<commit>.dist-info`, for 215 units.
  * The harness reinstalls only when `uv.lock` or `pyproject.toml` change.
  * A fresh venv without the uv build cache gets a new version at every commit, and then pydantic-ai would be near 0% (ESTIMATED).
  * pydantic-ai's own CI uses `setup-uv` with `enable-cache: true` and no git `cache-keys` (DECLARED by its `ci.yml` and `pyproject.toml`). So it probably reuses the stale build, as the harness does. Whether a customer's runner does: UNKNOWN.
  * Test: walk 10 pydantic-ai commits with an install at every commit and an empty uv cache.
* **R4. The verifier cannot see state that survives `git clean -ffd`.**
  * Ignored files survive, for example stale `__pycache__` or egg-info.
  * Test: for one shard of one repository, rerun every verified skip in a `git clean -ffdx` checkout and compare.
* **R5. `untracked_exists_are_outputs` changes what enters the key** (mlflow-dev only).
  * The report says no addition changes the proof rule; this one does.
  * mlflow-dev also removed one hanging file from its sample after the fact, which raises its all-units 55% a little.
  * Outside the verdict. Test: add to `test_r002_fixes.py` a unit that branches on the existence of a file created by an earlier unit at the same commit.
* **R6. Wording errors in the report, no test needed:**
  * m6 is called "cancelled before any result", but it committed 4 shard files (mlflow-dev late). Shard 3 reached 1 commit, so 0 transitions were fully covered. Adding m6 to `market.py` changes no number (MEASURED).
  * "Warm-up transitions lower the mean" is unsupported. A window's first transition compares against a full fresh run, like any other transition.

## Links

* fenvix-engine-cli `review-claude/market-test` @ 342fc11: `harness/market_test/tests/test_r010_market_review.py`.
* Run it with `python3 -m pytest -q harness/market_test/tests/test_r010_market_review.py`. It needs git, strace and uv. Result: 2 failed (MEASURED).
* Delivery: `claude/market-test` @ e2107683, `harness/market_test/results/market-summary.json`.

## Errors or gaps in this brain

* No task prompt for the market test exists in `prompts/`, so there is no written "Done means".
  * "The decision rule needs 5" and the 50% threshold cannot be checked against a contract.
  * I took them from the delivery report and from R-010.
* `NOW.md` still says "Market test: intermediate 1 only". The final report is in.
* `NUMBERS.md`, "Skip with proof", should say that `.git` reads are outside the key (as the delivery also notes). It should also say that a verified mismatch is judged on test outcomes only until error 2 is fixed.
