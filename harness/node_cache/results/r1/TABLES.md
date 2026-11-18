| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| docusaurus | 50 | 88% / 73% | 94% | 132108 | 0 | 0 | 26% / 56% (50 transitions) | 0 |
| vue-core | 50 | 26% / 32% | 46% | 85112 | 0 | 0 | 28% / 29% (50 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| docusaurus | 0 (cold) | 53.55 | 107.46 | 120.57 | 122.19 (0/205) | 1.238 |
| docusaurus | 10 | 53.13 | 109.2 | 124.38 | 124.0 (0/205) | 0.956 |
| docusaurus | 20 | 52.47 | 110.15 | 124.57 | 128.42 (0/205) | 0.971 |
| docusaurus | 35 | 40.69 | 85.63 | 95.87 | 95.86 (0/206) | 0.659 |
| docusaurus | 45 | 41.49 | 86.06 | 96.91 | 96.93 (0/207) | 0.67 |
| vue-core | 0 (cold) | 26.19 | 52.74 | 56.7 | 1.33 (184/184) | 0.259 |
| vue-core | 10 | 24.53 | 50.93 | 55.81 | 1.25 (184/184) | 0.185 |
| vue-core | 20 | 25.56 | 49.71 | 52.81 | 1.21 (184/184) | 0.183 |
| vue-core | 35 | 40.98 | 85.72 | 90.83 | 1.76 (184/184) | 0.308 |
| vue-core | 45 | 41.7 | 88.11 | 93.43 | 1.77 (185/185) | 0.314 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| docusaurus | 114 | 114 | 1.00 |
| vue-core | 76 | 40 | 0.52 |
