| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| docusaurus | 10 | 85% / 59% | 93% | 22196 | 0 | 0 | 49% / 54% (10 transitions) | 0 |
| tanstack-query | 10 | 0% / 38% | 0% | 18745 | 0 | 0 | 89% / 63% (10 transitions) | 0 |
| vue-core | 10 | 60% / 53% | 67% | 24338 | 0 | 0 | 51% / 45% (10 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| docusaurus | 40 (cold) | 36.94 | 78.52 | 87.59 | 11.94 (194/206) | 1.124 |
| docusaurus | 50 | 36.83 | 79.16 | 86.32 | 11.25 (195/207) | 0.922 |
| tanstack-query | 40 (cold) | 96.24 | 162.22 | 174.73 | 47.33 (162/180) | 2.688 |
| tanstack-query | 50 | 89.49 | 169.72 | 187.88 | 52.53 (162/180) | 2.151 |
| vue-core | 40 (cold) | 29.41 | 61.03 | 64.8 | 1.15 (185/185) | 0.204 |
| vue-core | 50 | 28.7 | 60.94 | 64.42 | 1.15 (185/185) | 0.146 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| docusaurus | 88 | 18 | 0.20 |
| tanstack-query | 186 | 137 | 0.73 |
| vue-core | 64 | 25 | 0.38 |
