| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| commander | 30 | 90% / 58% | 98% | 22548 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| dependency-cruiser | 30 | 17% / 12% | 64% | 28838 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| simple-statistics | 30 | 0% / 23% | 0% | 3213 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| yargs | 30 | 23% / 21% | 29% | 7428 | 0 | 0 | n/a / n/a (0 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| commander | 0 (cold) | 4.22 | 10.66 | 11.71 | 1.53 (107/109) | 0.098 |
| commander | 10 | 3.64 | 10.59 | 11.85 | 0.98 (107/109) | 0.078 |
| commander | 20 | 3.75 | 10.93 | 12.08 | 1.0 (107/109) | 0.08 |
| commander | 30 | 3.69 | 10.66 | 11.82 | 0.98 (107/109) | 0.079 |
| dependency-cruiser | 0 (cold) | 3.92 | 5.79 | 66.45 | 46.64 (140/212) | 0.111 |
| dependency-cruiser | 10 | 4.1 | 6.07 | 68.19 | 47.71 (140/212) | 0.086 |
| dependency-cruiser | 25 | 6.07 | 8.9 | 101.19 | 71.0 (144/217) | 0.132 |
| simple-statistics | 0 (cold) | 0.43 | 1.94 | 11.85 | 0.37 (80/80) | 0.221 |
| simple-statistics | 10 | 0.42 | 1.94 | 12.09 | 0.38 (80/80) | 0.123 |
| simple-statistics | 20 | 0.45 | 1.96 | 12.48 | 0.47 (83/83) | 0.216 |
| simple-statistics | 30 | 0.48 | 1.97 | 12.79 | 0.51 (83/83) | 0.232 |
| yargs | 0 (cold) | 10.45 | 10.2 | 14.68 | 10.89 (11/14) | 0.254 |
| yargs | 10 | 5.19 | 5.55 | 9.85 | 5.75 (11/14) | 0.188 |
| yargs | 20 | 5.07 | 5.56 | 9.89 | 5.89 (11/14) | 0.191 |
| yargs | 30 | 4.98 | 5.41 | 9.66 | 5.39 (11/14) | 0.141 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| commander | 12 | 1 | 0.09 |
| dependency-cruiser | 84 | 69 | 0.83 |
| simple-statistics | 12 | 12 | 0.99 |
| yargs | 10 | 7 | 0.73 |
