| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tanstack-query | 50 | 0% / 41% | 0% | 102973 | 0 | 0 | 92% / 69% (50 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| tanstack-query | 0 (cold) | 77.59 | 134.33 | 145.63 | 40.48 (161/179) | 1.633 |
| tanstack-query | 10 | 73.17 | 136.58 | 154.56 | 40.7 (162/180) | 1.2 |
| tanstack-query | 27 | 110.72 | 201.92 | 227.85 | 58.83 (162/180) | 2.267 |
| tanstack-query | 44 | 111.75 | 204.94 | 232.02 | 60.55 (162/180) | 2.953 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| tanstack-query | 227 | 64 | 0.28 |
