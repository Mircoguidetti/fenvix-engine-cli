| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tanstack-query | 50 | 91% / 61% | 94% | 158515 | 0 | 0 | 92% / 69% (50 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| tanstack-query | 0 (cold) | 67.63 | 111.89 | 123.05 | 36.43 (161/179) | 2.33 |
| tanstack-query | 10 | 61.44 | 110.06 | 128.08 | 35.67 (162/180) | 1.842 |
| tanstack-query | 27 | 71.95 | 136.98 | 152.22 | 40.46 (162/180) | 1.182 |
| tanstack-query | 44 | 71.67 | 133.4 | 152.94 | 41.35 (162/180) | 1.481 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| tanstack-query | 149 | 44 | 0.29 |
