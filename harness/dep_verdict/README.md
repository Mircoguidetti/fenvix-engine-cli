# Dependency-update verdict validation (2026-11-18/19)

Measures, on dependency-only commits of the 10 market-test repositories, how much test time the cache with proof
reuses today (one digest of the whole environment) and with the per-distribution identity prototype
(`--det-cache-dists`, `python/detpy/distid.py`). Report: fenvix-brain-cli `sessions/2026-11-18-dep-verdict/REPORT.md`.

* `find_commits.py`: step 1, dependency-only commits (`commits.json`).
* `pairs.py`: steps 2, 3 and 5, one job per (repository, shard) in `.github/workflows/dep-verdict.yml`, triggered by
  a push that changes `run.json`. Specs in `specs/` are the market-test specs (install commands, units, sample),
  with Python 3.12 for mlflow (`--det-cache` needs sys.monitoring) and a cap on test files per pair.
* `ci_status.py`: step 4 input, the projects' own CI verdict on every pair (check runs, job logs).
* `analyze.py`: tables.
* `pyinstall.py`, `ddenv.py`, `hatchdeps.py`: copied from `harness/market_test` (branch `claude/market-test`).
