# detpy Level 0: measurement report (`timing-startup`)

Generated 2026-11-16 21:40 UTC with detpy 0.1.0. Per repository: 10 baseline runs (random order from pytest-randomly with a different seed per run, pytest-xdist `-n 2` where the suite supports it) interleaved with 10 `--det` runs (fixed order, serial); then, for every test unstable in the baseline, exploration with `--det-seed=1..20` and 10/10 confirmation of the seed that makes it fail. Executor: GitHub Actions matrix, one repository per ubuntu-latest runner (run https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43946234291). Labels: MEASURED (by this harness), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host.

## Main metric

**Baseline-unstable tests made reproducible: 0/0 = n/a** (MEASURED). Tests whose id changes between runs (ids built from time or random values: 0) are not flaky tests and are excluded; including them the figure was 0/0. A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass; a test that fails under every `--det` configuration is broken by Level 0, not reproduced.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

Tests with unstable ids (excluded above, MEASURED): 0.

## Tests that do not run under --det

A test that runs in every baseline run but in no `--det` run is worse than a false failure. **0 tests** (MEASURED). Tests present only under `--det` (an id that differs between modes): 0.

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). These are false failures. **0 tests** (MEASURED), of which 0 fail in every `--det` run.

## Timing

Quiet timing pass: 10 repositories, one per GitHub-hosted runner, 3 serial fixed-order normal runs vs 3 `--det` runs interleaved on the same machine; median per repository. Every ratio compares two runs on the same runner, but the runners differ: 6 CPU models — AMD EPYC 7763 64-Core Processor (4 repositories); AMD EPYC 9V74 80-Core Processor (2 repositories); Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz (1 repository); Intel(R) Xeon(R) 6975P-C (1 repository); Intel(R) Xeon(R) 6973P-C (1 repository); AMD EPYC 9V45 96-Core Processor (1 repository); 4 vCPUs, ubuntu26 20261111.196.1. Labelled **DECLARED-NOISY**: hosted runners are virtual machines on shared hardware.

**Slowdown of `--det` (MEASURED, DECLARED-NOISY): median 16.8%**, min -2.8%, max 198.7%.

* Without the suites that run in under 1 s (idoft-centreon-sdk-python, idoft-crom): median 9.8% over 8 repositories (MEASURED, DECLARED-NOISY).
* Absolute extra time of `--det` per suite run: median 1.16 s (MEASURED, DECLARED-NOISY). Fixed start-up cost (one-test suite, same venv, warm caches): median 0.72 s, min 0.46 s, max 1.10 s (MEASURED, DECLARED-NOISY).

| repo | tests | runner CPU | normal serial s (median) | --det s (median) | slowdown % | start-up cost s | precompile s (per run) |
|---|---:|---|---:|---:|---:|---:|---|
| attrs | 1412 | Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz | 8.67 | 11.12 | 28.3 | 1.03 | 8.13, 0.34, 0.34 |
| idoft-centreon-sdk-python | 44 | AMD EPYC 9V74 80-Core Processor | 0.33 | 0.87 | 161.8 | 0.51 | 1.17, 0.36, 0.35 |
| idoft-cloudnetpy | 439 | Intel(R) Xeon(R) 6975P-C | 6.23 | 6.30 | 1.2 | 0.84 | 2.62, 0.67, 0.67 |
| idoft-crom | 84 | AMD EPYC 7763 64-Core Processor | 0.40 | 1.19 | 198.7 | 0.73 | 1.48, 0.52, 0.53 |
| idoft-easypy | 212 | Intel(R) Xeon(R) 6973P-C | 12.27 | 11.92 | -2.8 | 0.50 | 1.10, 0.37, 0.37 |
| idoft-eppy | 218 | AMD EPYC 9V45 96-Core Processor | 6.09 | 6.75 | 10.8 | 0.46 | 1.31, 0.38, 0.38 |
| networkx | 10191 | AMD EPYC 7763 64-Core Processor | 141.36 | 153.82 | 8.8 | 1.10 | 10.54, 0.72, 0.73 |
| pygments | 5346 | AMD EPYC 7763 64-Core Processor | 19.48 | 21.09 | 8.3 | 0.71 | 7.37, 0.59, 0.59 |
| rich | 981 | AMD EPYC 9V74 80-Core Processor | 4.95 | 6.49 | 31.1 | 0.64 | 8.62, 0.40, 0.41 |
| werkzeug | 1016 | AMD EPYC 7763 64-Core Processor | 9.35 | 11.49 | 22.8 | 0.73 | 7.08, 0.45, 0.46 |

* Round timings, serial `--det` vs the random-order xdist `-n 2` baseline: median n/a% — **NOT COMPARABLE** (different parallelism and order; reported only for completeness).
* Deterministic bytecode precompilation, first `--det` run of each repository: median n/a s, max n/a s; later runs (incremental check): median n/a s (MEASURED, NOISY).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 0; unstable in the baseline and stable under `--det`: 0
* stable in both modes but with a different majority outcome: 0
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 0 (n/a); not covered: 0

## Per repository (MEASURED)

| repo | pool | py | xdist | tests | unstable | reproduced | seeds explored | broken by det | not covered | IDoFT present / flaky / reproduced |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|

## Discarded candidates

| repo | pool | reason | detail |
|---|---|---|---|
| attrs |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-centreon-sdk-python |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-cloudnetpy |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-crom |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-easypy |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-eppy |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| networkx |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| pygments |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| rich |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| werkzeug |  | round: no-result | the matrix job produced no summary (job timeout or crash) |

## Reproduction

```bash
gh workflow run harness.yml -f runs=10 -f seeds=20 -f confirm=10
```
Per-test details in `<repo>.csv`, per-run details in `<repo>_runs.csv`; columns in `docs/HARNESS.md`.

## Notes

* The FlaPy dataset (Gruber et al.) is published on Zenodo, which the development environment cannot reach (HTTP 403 from the network proxy): the 'flaky' pool uses the Python section of IDoFT, each project pinned at the commit where its flaky tests were detected.
* Selection: the first 25 candidates per pool (in harness/repos.json and harness/flaky_candidates.json order) that clone, install, collect and finish their first baseline run within 120 s; every rejected candidate is listed above.
