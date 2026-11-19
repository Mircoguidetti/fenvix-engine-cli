| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tanstack-query | 34 | 92% / 66% | 94% | 113442 | 0 | 0 | 92% / 74% (34 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| tanstack-query | 0 (cold) | 78.42 | 136.19 | 145.25 | 41.18 (161/179) | 1.68 |
| tanstack-query | 10 | 72.58 | 134.44 | 149.49 | 39.85 (162/180) | 1.16 |
| tanstack-query | 27 | 95.17 | 173.65 | 198.19 | 53.57 (162/180) | 1.619 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| tanstack-query | 176 | 56 | 0.32 |
