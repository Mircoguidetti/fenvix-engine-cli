# detpy Level 0: measurement report (`idoft-crom,idoft-cloudnetpy,idoft-flask-multi-redis,idoft-freezegun,idoft-krllint,idoft-django-beam`)

Generated 2026-11-16 17:37 UTC with detpy 0.1.0. Per repository: 10 baseline runs (random order from pytest-randomly with a different seed per run, pytest-xdist `-n 2` where the suite supports it) interleaved with 10 `--det` runs (fixed order, serial); then, for every test unstable in the baseline, exploration with `--det-seed=1..20` and 10/10 confirmation of the seed that makes it fail. Executor: local container (4 CPUs), serial baseline check. Labels: MEASURED (by this harness), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host.

## Main metric

**Baseline-unstable tests made reproducible: 95/104 = 91.3%** (MEASURED). Tests whose id changes between runs (ids built from time or random values: 0) are not flaky tests and are excluded; including them the figure was 95/104. A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass; a test that fails under every `--det` configuration is broken by Level 0, not reproduced.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IDoFT dataset | 6 | 764 | 104 | 95 | 91.3% | 8 | 1 | 0 |
| total | 6 | 764 | 104 | 95 | 91.3% | 8 | 1 | 0 |

Tests with unstable ids (excluded above, MEASURED): 0.

**Reproduced share by IDoFT category** (MEASURED). Most IDoFT flaky tests are order-dependent and were found by order shuffling, so reproducing them with a seeded order is the easy part; the NOD/NIO rows and the popular pool are the hard part.

| category | unstable in baseline | reproduced | % |
|---|---:|---:|---:|
| NOD | 11 | 11 | 100.0% |
| OD-Brit | 3 | 3 | 100.0% |
| OD-Vic | 85 | 80 | 94.1% |
| not in IDoFT | 5 | 1 | 20.0% |

**Reproduced tests by first diverging source** (passing vs failing `--det` fingerprint, MEASURED): `random` 71 (74.7%), `entropy` 20 (21.1%), `time` 3 (3.2%), `fs` 1 (1.1%).

**(a, b) Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 0 (fixed order): 2, 1: 24, 2-5: 52, 6-10: 15, 11-20: 2; median 3.

**(c) First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `random` 71, `entropy` 20, `time` 3, `fs` 1.

## IDoFT known flaky tests (MEASURED)

| known flaky tests (IDoFT, measured projects) | present in the collected suite | flaky in our baseline | reproduced |
|---:|---:|---:|---:|
| 151 | 151 | 99 | 94 |

## Tests that do not run under --det

A test that runs in every baseline run but in no `--det` run is worse than a false failure. **0 tests** (MEASURED). Tests present only under `--det` (an id that differs between modes): 0.

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). These are false failures. **0 tests** (MEASURED), of which 0 fail in every `--det` run.

## Timing

Quiet timing pass: not run yet (UNKNOWN).

* Round timings, serial `--det` vs the random-order xdist `-n 2` baseline: median 123.6% — **NOT COMPARABLE** (different parallelism and order; reported only for completeness).
* Deterministic bytecode precompilation, first `--det` run of each repository: median 1.11 s, max 4.04 s; later runs (incremental check): median 0.70 s (MEASURED, NOISY).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 0; unstable in the baseline and stable under `--det`: 104
* stable in both modes but with a different majority outcome: 1
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 717 (93.8%); not covered: 47 (`entropy` 47)

## Per repository (MEASURED)

| repo | pool | py | xdist | tests | unstable | reproduced | seeds explored | broken by det | not covered | IDoFT present / flaky / reproduced |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [idoft-crom](https://github.com/thegetty/crom) | flaky | 3.9 | no | 84 | 22 | 17 | 20 | 0 | 21 | 38 / 22 / 17 |
| [idoft-cloudnetpy](https://github.com/tukiains/cloudnetpy) | flaky | 3.9 | no | 439 | 28 | 28 | 5 | 0 | 1 | 52 / 28 / 28 |
| [idoft-flask-multi-redis](https://github.com/max-k/flask-multi-redis) | flaky | 3.9 | no | 33 | 27 | 26 | 20 | 0 | 0 | 26 / 26 / 26 |
| [idoft-freezegun](https://github.com/spulec/freezegun) | flaky | 3.9 | no | 112 | 14 | 11 | 20 | 0 | 0 | 15 / 10 / 10 |
| [idoft-krllint](https://github.com/d4nuu8/krllint) | flaky | 3.9 | no | 16 | 2 | 2 | 20 | 0 | 0 | 9 / 2 / 2 |
| [idoft-django-beam](https://github.com/django-beam/django-beam) | flaky | 3.9 | no | 80 | 11 | 11 | 1 | 0 | 25 | 11 / 11 / 11 |

## Reproduction

```bash
python harness/detpy_harness.py --set idoft-crom,idoft-cloudnetpy,idoft-flask-multi-redis,idoft-freezegun,idoft-krllint,idoft-django-beam --no-xdist --runs 10 --seeds 20 --confirm 10 --jobs 3 --wheel .harness-work/dist-new/detpy-0.1.0-cp39-abi3-linux_x86_64.whl --work /tmp/claude-0/-home-user-fenvix-engine-cli/72c438ee-1ad0-5631-91e5-b623fff4772c/scratchpad/idoft/work --out harness/results/idoft-serial-baseline --executor local container (4 CPUs), serial baseline check --max-first-run 100000
```
Per-test details in `<repo>.csv`, per-run details in `<repo>_runs.csv`; columns in `docs/HARNESS.md`.

## Notes

* The FlaPy dataset (Gruber et al.) is published on Zenodo, which the development environment cannot reach (HTTP 403 from the network proxy): the 'flaky' pool uses the Python section of IDoFT, each project pinned at the commit where its flaky tests were detected.
