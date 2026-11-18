# detpy Level 0: measurement report (`after-fixes-easypy`)

Generated 2026-11-16 18:50 UTC with detpy 0.1.0. Per repository: 10 baseline runs (random order from pytest-randomly with a different seed per run, pytest-xdist `-n 2` where the suite supports it) interleaved with 10 `--det` runs (fixed order, serial); then, for every test unstable in the baseline, exploration with `--det-seed=1..20` and 10/10 confirmation of the seed that makes it fail. Executor: GitHub Actions matrix, one repository per ubuntu-latest runner (run https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43931114732). Labels: MEASURED (by this harness), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host.

## Main metric

**Baseline-unstable tests made reproducible: 43/44 = 97.7%** (MEASURED). Tests whose id changes between runs (ids built from time or random values: 0) are not flaky tests and are excluded; including them the figure was 43/44. A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass; a test that fails under every `--det` configuration is broken by Level 0, not reproduced.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IDoFT dataset | 1 | 212 | 44 | 43 | 97.7% | 0 | 1 | 0 |
| total | 1 | 212 | 44 | 43 | 97.7% | 0 | 1 | 0 |

Tests with unstable ids (excluded above, MEASURED): 0.

**Reproduced share by IDoFT category** (MEASURED). Most IDoFT flaky tests are order-dependent and were found by order shuffling, so reproducing them with a seeded order is the easy part; the NOD/NIO rows and the popular pool are the hard part.

| category | unstable in baseline | reproduced | % |
|---|---:|---:|---:|
| OD-Vic | 44 | 43 | 97.7% |

**Reproduced tests by first diverging source** (passing vs failing `--det` fingerprint, MEASURED): `time` 35 (81.4%), `thread` 6 (14.0%), `random` 2 (4.7%).

**(a, b) Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 0 (fixed order): 43; median 0.

**(c) First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `time` 35, `thread` 6, `random` 2.

## IDoFT known flaky tests (MEASURED)

| known flaky tests (IDoFT, measured projects) | present in the collected suite | flaky in our baseline | reproduced |
|---:|---:|---:|---:|
| 44 | 44 | 44 | 43 |

## Tests that do not run under --det

A test that runs in every baseline run but in no `--det` run is worse than a false failure. **0 tests** (MEASURED). Tests present only under `--det` (an id that differs between modes): 0.

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). These are false failures. **1 tests** (MEASURED), of which 1 fail in every `--det` run.

Cause: `fixed-order` = the test also fails in a serial fixed-order run *without* `--det` (the baseline hides it with random order and xdist: not a Level 0 failure); otherwise the controls whose `--det-disable` makes it pass again (one ablation run per control); `unexplained` = none does.

| cause (controls) &#124; exception | tests | examples |
|---|---:|---|
| `fixed-order (fails without --det too) | RecursionError` | 1 | idoft-easypy: tests/test_sync.py::test_logged_condition_exception: RecursionError: maximum recursion depth exceeded (first diverging source: time) |

## Timing

Quiet timing pass: not run yet (UNKNOWN).

* Round timings, serial `--det` vs the random-order xdist `-n 2` baseline: median 55.2% — **NOT COMPARABLE** (different parallelism and order; reported only for completeness).
* Deterministic bytecode precompilation, first `--det` run of each repository: median 1.44 s, max 1.44 s; later runs (incremental check): median 0.50 s (MEASURED, NOISY).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 0; unstable in the baseline and stable under `--det`: 44
* stable in both modes but with a different majority outcome: 0
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 183 (86.3%); not covered: 29 (`thread` 28, `entropy` 1)

## Per repository (MEASURED)

| repo | pool | py | xdist | tests | unstable | reproduced | seeds explored | broken by det | not covered | IDoFT present / flaky / reproduced |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [idoft-easypy](https://github.com/weka-io/easypy) | flaky | 3.9 | yes | 212 | 44 | 43 | 20 | 1 | 29 | 44 / 44 / 43 |

## Reproduction

```bash
gh workflow run harness.yml -f runs=10 -f seeds=20 -f confirm=10
```
Per-test details in `<repo>.csv`, per-run details in `<repo>_runs.csv`; columns in `docs/HARNESS.md`.

## Notes

* The FlaPy dataset (Gruber et al.) is published on Zenodo, which the development environment cannot reach (HTTP 403 from the network proxy): the 'flaky' pool uses the Python section of IDoFT, each project pinned at the commit where its flaky tests were detected.
* Selection: the first 25 candidates per pool (in harness/repos.json and harness/flaky_candidates.json order) that clone, install, collect and finish their first baseline run within 120 s; every rejected candidate is listed above.
