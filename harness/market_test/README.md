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
