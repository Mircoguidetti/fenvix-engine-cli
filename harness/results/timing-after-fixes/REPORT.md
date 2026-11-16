# detpy Level 0: measurement report (`timing-after-fixes`)

Generated 2026-11-16 19:08 UTC with detpy 0.1.0. Per repository: 10 baseline runs (random order from pytest-randomly with a different seed per run, pytest-xdist `-n 2` where the suite supports it) interleaved with 10 `--det` runs (fixed order, serial); then, for every test unstable in the baseline, exploration with `--det-seed=1..20` and 10/10 confirmation of the seed that makes it fail. Executor: GitHub Actions matrix, one repository per ubuntu-latest runner (run https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43933691030). Labels: MEASURED (by this harness), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host.

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

Quiet timing pass: 10 repositories, one per GitHub-hosted runner, one repository per runner, 3 serial fixed-order normal runs vs 3 `--det` runs interleaved on the same machine; median per repository. Every ratio compares two runs on the same runner, but the runners differ: 4 CPU models — AMD EPYC 7763 64-Core Processor (5 repositories); AMD EPYC 9V74 80-Core Processor (2 repositories); AMD EPYC 9V45 96-Core Processor (2 repositories); INTEL(R) XEON(R) PLATINUM 8573C (1 repository); 4 vCPUs, ubuntu26 20261111.196.1. Labelled **DECLARED-NOISY**: hosted runners are virtual machines on shared hardware.

**Slowdown of `--det` (MEASURED, DECLARED-NOISY): median 25.0%**, min -5.7%, max 202.1%.

* Without the suites that run in under 1 s (idoft-centreon-sdk-python, idoft-crom): median 16.3% over 8 repositories (MEASURED, DECLARED-NOISY).
* Absolute extra time of `--det` per suite run: median 1.72 s (MEASURED, DECLARED-NOISY). Fixed start-up cost: not measured in this pass (UNKNOWN).

| repo | tests | runner CPU | normal serial s (median) | --det s (median) | slowdown % | start-up cost s | precompile s (per run) |
|---|---:|---|---:|---:|---:|---:|---|
| attrs | 1412 | AMD EPYC 9V74 80-Core Processor | 7.56 | 9.61 | 27.1 | n/a | 6.33, 0.31, 0.31 |
| idoft-centreon-sdk-python | 44 | INTEL(R) XEON(R) PLATINUM 8573C | 0.41 | 1.10 | 171.8 | n/a | 1.48, 0.48, 0.49 |
| idoft-cloudnetpy | 439 | AMD EPYC 9V74 80-Core Processor | 6.97 | 7.24 | 3.8 | n/a | 2.93, 0.86, 0.84 |
| idoft-crom | 84 | AMD EPYC 7763 64-Core Processor | 0.38 | 1.14 | 202.1 | n/a | 1.42, 0.52, 0.51 |
| idoft-easypy | 212 | AMD EPYC 9V45 96-Core Processor | 11.04 | 10.42 | -5.7 | n/a | 0.81, 0.22, 0.21 |
| idoft-eppy | 218 | AMD EPYC 7763 64-Core Processor | 6.88 | 8.46 | 22.9 | n/a | 1.95, 0.80, 0.76 |
| networkx | 10191 | AMD EPYC 9V45 96-Core Processor | 82.58 | 89.88 | 8.8 | n/a | 7.20, 0.36, 0.35 |
| pygments | 5346 | AMD EPYC 7763 64-Core Processor | 19.14 | 21.02 | 9.8 | n/a | 6.84, 0.63, 0.58 |
| rich | 981 | AMD EPYC 7763 64-Core Processor | 5.64 | 7.59 | 34.7 | n/a | 8.66, 0.57, 0.57 |
| werkzeug | 1016 | AMD EPYC 7763 64-Core Processor | 10.30 | 21.52 | 108.9 | n/a | 7.96, 0.48, 0.47 |

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
| idoft-crom |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-easypy |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-cloudnetpy |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| attrs |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-centreon-sdk-python |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| idoft-eppy |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| werkzeug |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| rich |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| networkx |  | round: no-result | the matrix job produced no summary (job timeout or crash) |
| pygments |  | round: no-result | the matrix job produced no summary (job timeout or crash) |

## Reproduction

```bash
gh workflow run harness.yml -f runs=10 -f seeds=20 -f confirm=10
```
Per-test details in `<repo>.csv`, per-run details in `<repo>_runs.csv`; columns in `docs/HARNESS.md`.

## Notes

* The FlaPy dataset (Gruber et al.) is published on Zenodo, which the development environment cannot reach (HTTP 403 from the network proxy): the 'flaky' pool uses the Python section of IDoFT, each project pinned at the commit where its flaky tests were detected.
* Selection: the first 25 candidates per pool (in harness/repos.json and harness/flaky_candidates.json order) that clone, install, collect and finish their first baseline run within 120 s; every rejected candidate is listed above.
