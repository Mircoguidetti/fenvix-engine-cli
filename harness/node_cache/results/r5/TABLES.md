| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tanstack-query | 17 | 89% / 59% | 91% | 50508 | 0 | 0 | 92% / 72% (17 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| tanstack-query | 0 (cold) | 67.63 | 111.89 | 123.05 | 36.43 (161/179) | 2.33 |
| tanstack-query | 10 | 61.44 | 110.06 | 128.08 | 35.67 (162/180) | 1.842 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| tanstack-query | 128 | 42 | 0.33 |
