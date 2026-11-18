# Market test (2026-11-17/18)

Does the buyer shape exist? Skip-with-proof (closure v3, `harness/skip_study2` v3.1) on 10 public Python repositories
picked as fenvix targets. Report: fenvix-brain-cli `sessions/2026-11-17-market-test/REPORT.md`.

* Code: a copy of `harness/skip_study2` (walk.py, strace_deps.py, pyhooks, nodehooks, aggregate.py, tests) plus
  `market.py` (tables), `ddenv.py` (integrations-core hatch environment), `hatchdeps.py`, and these walk.py options:
  `why_paths` (first-reason path of every rerun), `src_dir`, `db_inputs_always`, `ci_env`,
  `untracked_exists_are_outputs` (mlflow-dev only). The proof rule itself is unchanged.
* Specs: `specs/make_specs.py` writes `specs/*.json` (heads pinned 2026-11-17) and `specs/smoke/*.json`.
* Workflow: `.github/workflows/market-test.yml`, triggered by a push that changes `run.json`.
* Runs: m1 (all 11), m3 (transformers fixed, mlflow-dev), m4 (late windows: litellm, integrations-core),
  m5 (litellm middle window), m7 (mlflow-dev shard 1 without the hanging `tests/server/auth/test_auth.py`).
  smoke1, smoke2, m2 and m6 were cancelled before producing results.
* Tables: `python3 harness/market_test/market.py m1 m3 m4 m5 m7 --json harness/market_test/results/market-summary.json`
  (a later run replaces the same shard of an earlier one; `-mid` / `-late` windows merge into their repository).

## R-010 fixes (2026-11-18)

Review: fenvix-brain-cli `sessions/2026-11-18-review-market-test/REPORT.md` (FIX 2) and `REPORT-2.md` (the fixes).

1. **Reads under `.git/` enter the key.** `strace_deps.SKIP_PARTS` now drops only `.git/objects/`. A unit that read or
   listed anything under the checkout's `.git/` records the resolved HEAD (`deps["git"]["head"]`) and the `.git`
   files it read (HEAD, refs, packed-refs, index, config) like any other file. `decide()` reruns it when HEAD
   changed (reason `git:HEAD`) or when one of those files changed.
2. **A verification mismatch is wrong unless a rerun shows it flips.** `walk.compare` stores the exit codes of the
   two extra runs and matches a rerun on (test outcomes, exit code == 0). `aggregate.classify` calls a mismatch
   flaky only when a rerun disagrees with the fresh run, or when a re-check under `results/*/recheck/` shows the
   flip. An item written before the fix that differs in the exit code alone is wrong until a re-check exists.
   `recheck.py` compares the exit code too.

* Tests: `tests/test_r010_market_review.py` (the reviewer's two tests), `tests/test_r010_fixes.py` (guards).
* `gitkey.py`: which units of a repository read `.git` (one captured run per unit at a commit), and whether the fixed
  rule reruns a given unit between two commits. Output: `results/r010/gitkey/<repository>.json`.
* `market.py ... --git-units results/r010/gitkey/prefect.json`: applies fix 1 to the walks recorded before it. The
  listed units rerun at every transition and their verification items leave the verified skips (`rekeyed_verify`).
* Re-checks of the two pydantic-ai items: `results/r010/recheck/`.
* Tables after the fixes:
  `python3 harness/market_test/market.py m1 m3 m4 m5 m7 --git-units harness/market_test/results/r010/gitkey/prefect.json --json harness/market_test/results/market-summary.json`
