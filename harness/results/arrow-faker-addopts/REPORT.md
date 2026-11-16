# detpy Level 0: measurement report (`arrow-faker-addopts`)

Generated 2026-11-16 21:45 UTC with detpy 0.1.0. Per repository: 10 baseline runs (random order from pytest-randomly with a different seed per run, pytest-xdist `-n 2` where the suite supports it) interleaved with 10 `--det` runs (fixed order, serial); then, for every test unstable in the baseline, exploration with `--det-seed=1..20` and 10/10 confirmation of the seed that makes it fail. Executor: GitHub Actions matrix, one repository per ubuntu-latest runner (run https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43946215518). Labels: MEASURED (by this harness), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host.

## Main metric

**Baseline-unstable tests made reproducible: 2/2 = 100.0%** (MEASURED). Tests whose id changes between runs (ids built from time or random values: 0) are not flaky tests and are excluded; including them the figure was 2/2. A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass; a test that fails under every `--det` configuration is broken by Level 0, not reproduced.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| popular | 2 | 4374 | 2 | 2 | 100.0% | 0 | 0 | 0 |
| total | 2 | 4374 | 2 | 2 | 100.0% | 0 | 0 | 0 |

Tests with unstable ids (excluded above, MEASURED): 0.

**Reproduced share by IDoFT category** (MEASURED). Most IDoFT flaky tests are order-dependent and were found by order shuffling, so reproducing them with a seeded order is the easy part; the NOD/NIO rows and the popular pool are the hard part.

| category | unstable in baseline | reproduced | % |
|---|---:|---:|---:|
| popular pool (no IDoFT label) | 2 | 2 | 100.0% |

**Reproduced tests by first diverging source** (passing vs failing `--det` fingerprint, MEASURED): `random` 2 (100.0%).

**(a, b) Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 2-5: 2; median 2.

**(c) First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `random` 2.

## Tests that do not run under --det

A test that runs in every baseline run but in no `--det` run is worse than a false failure. **0 tests** (MEASURED). Tests present only under `--det` (an id that differs between modes): 0.

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). These are false failures. **0 tests** (MEASURED), of which 0 fail in every `--det` run.

## Timing

Quiet timing pass: 2 repositories, one per GitHub-hosted runner, 3 serial fixed-order normal runs vs 3 `--det` runs interleaved on the same machine; median per repository. Every ratio compares two runs on the same runner, but the runners differ: 2 CPU models — AMD EPYC 9V74 80-Core Processor (1 repository); INTEL(R) XEON(R) PLATINUM 8573C (1 repository); 4 vCPUs, ubuntu26 20261111.196.1. Labelled **DECLARED-NOISY**: hosted runners are virtual machines on shared hardware.

**Slowdown of `--det` (MEASURED, DECLARED-NOISY): median 35.4%**, min -11.0%, max 81.9%.

* Without the suites that run in under 1 s (none): median 35.4% over 2 repositories (MEASURED, DECLARED-NOISY).
* Absolute extra time of `--det` per suite run: median 0.45 s (MEASURED, DECLARED-NOISY). Fixed start-up cost (one-test suite, same venv, warm caches): median 0.85 s, min 0.65 s, max 1.05 s (MEASURED, DECLARED-NOISY).

| repo | tests | runner CPU | normal serial s (median) | --det s (median) | slowdown % | start-up cost s | precompile s (per run) |
|---|---:|---|---:|---:|---:|---:|---|
| arrow | 1904 | AMD EPYC 9V74 80-Core Processor | 6.31 | 11.48 | 81.9 | 0.65 | 6.64, 0.38, 0.39 |
| faker | 2470 | INTEL(R) XEON(R) PLATINUM 8573C | 38.83 | 34.56 | -11.0 | 1.05 | 12.44, 0.72, 0.75 |

* Round timings, serial `--det` vs the random-order xdist `-n 2` baseline: median 67.5% — **NOT COMPARABLE** (different parallelism and order; reported only for completeness).
* Deterministic bytecode precompilation, first `--det` run of each repository: median 7.22 s, max 8.19 s; later runs (incremental check): median 0.56 s (MEASURED, NOISY).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 0; unstable in the baseline and stable under `--det`: 2
* stable in both modes but with a different majority outcome: 4
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 4374 (100.0%); not covered: 0

## Per repository (MEASURED)

| repo | pool | py | xdist | tests | unstable | reproduced | seeds explored | broken by det | not covered | IDoFT present / flaky / reproduced |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [arrow](https://github.com/arrow-py/arrow) | popular | 3.13 | yes | 1904 | 2 | 2 | 2 | 0 | 0 |  |
| [faker](https://github.com/joke2k/faker) | popular | 3.13 | yes | 2470 | 0 | 0 | 0 | 0 | 0 |  |

## Reproduction

```bash
gh workflow run harness.yml -f runs=10 -f seeds=20 -f confirm=10
```
Per-test details in `<repo>.csv`, per-run details in `<repo>_runs.csv`; columns in `docs/HARNESS.md`.

## Notes

* The FlaPy dataset (Gruber et al.) is published on Zenodo, which the development environment cannot reach (HTTP 403 from the network proxy): the 'flaky' pool uses the Python section of IDoFT, each project pinned at the commit where its flaky tests were detected.
* Selection: the first 25 candidates per pool (in harness/repos.json and harness/flaky_candidates.json order) that clone, install, collect and finish their first baseline run within 120 s; every rejected candidate is listed above.
