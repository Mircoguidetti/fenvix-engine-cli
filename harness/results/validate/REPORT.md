# detpy Level 0: measurement report (validate)

Generated 2026-11-16 13:54 UTC with detpy 0.1.0, Python 3.13.18, 10 normal + 10 `--det` runs per repository (interleaved), 3 repositories in parallel on 4 CPUs.

## Totals

* repositories measured: **4** (excluded: 1)
* tests: **1806**
* slowdown of `--det`: median **19.3%**, geometric mean 9.7%, min -29.0%, max 43.3%
* unstable tests (outcome differs between runs) without `--det`: **0**; with `--det`: **0**
* became stable with `--det`: **0**; became unstable: 0
* stable in both modes but with a different outcome under `--det` (behaviour changed by Level 0): **0**
* fingerprint identical in every `--det` run (covered by Level 0): **1806** (100.00%); not covered: **0**

## Per repository

| repo | tests | normal s | det s | slowdown % | unstable normal | unstable det | became stable | changed by det | not covered | reasons |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| [itsdangerous](https://github.com/pallets/itsdangerous) | 297 | 0.85 | 1.03 | 21.0 | 0 | 0 | 0 | 0 | 0 |  |
| [cachetools](https://github.com/tkem/cachetools) | 416 | 0.57 | 0.82 | 43.3 | 0 | 0 | 0 | 0 | 0 |  |
| [humanize](https://github.com/python-humanize/humanize) | 908 | 1.78 | 2.09 | 17.6 | 0 | 0 | 0 | 0 | 0 |  |
| [tenacity](https://github.com/jd/tenacity) | 185 | 2.59 | 1.84 | -29.0 | 0 | 0 | 0 | 0 | 0 |  |

## Examples of divergences and behaviour changes

## Excluded repositories

| repo | status | detail |
|---|---|---|
| filelock | too-slow | first normal run took 291s |

## Reproduction

```bash
python harness/detpy_harness.py --set validate --runs 10 --jobs 3
```
Per-test details are in `<repo>.csv`, per-run timings in `<repo>_runs.csv`. Column meanings are documented in `docs/HARNESS.md`.
