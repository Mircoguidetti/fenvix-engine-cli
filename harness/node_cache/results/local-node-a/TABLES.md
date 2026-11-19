| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| commander | 4 | 91% / 68% | 98% | 3774 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| dependency-cruiser | 3 | 0% / 6% | 0% | 1477 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| simple-statistics | 4 | 0% / 25% | 0% | 459 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| yargs | 4 | 34% / 26% | 56% | 1449 | 0 | 0 | n/a / n/a (0 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| commander | 26 (cold) | 13.81 | 20.46 | 21.46 | 1.54 (107/109) | 0.291 |
| dependency-cruiser | 27 (cold) | 11.68 | 14.73 | 190.25 | 112.52 (144/217) | 0.962 |
| simple-statistics | 26 (cold) | 0.75 | 3.08 | 20.94 | 0.83 (83/83) | 0.803 |
| yargs | 26 (cold) | 9.44 | 8.77 | 16.81 | 10.11 (11/14) | 0.793 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| commander | 21 | 2 | 0.08 |
| dependency-cruiser | 121 | 120 | 0.99 |
| simple-statistics | 21 | 21 | 1.02 |
| yargs | 16 | 10 | 0.61 |
