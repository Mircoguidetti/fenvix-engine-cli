| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hexo | 30 | 6% / 6% | 32% | 3686 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| ink | 30 | 22% / 21% | 25% | 15371 | 0 | 0 | n/a / n/a (0 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| hexo | 0 (cold) | 28.51 | 27.63 | 364.96 | 345.74 (20/119) | 0.236 |
| hexo | 10 | 27.65 | 26.83 | 360.69 | 323.91 (20/119) | 0.174 |
| hexo | 25 | 24.17 | 23.05 | 288.74 | 256.19 (20/120) | 0.151 |
| ink | 0 (cold) | 173.72 | 180.03 | 179.35 | 120.4 (43/101) | 0.244 |
| ink | 10 | 168.49 | 184.05 | 183.08 | 122.72 (44/104) | 0.156 |
| ink | 25 | 138.49 | 151.39 | 150.65 | 114.7 (42/106) | 0.13 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| hexo | 329 | 307 | 0.93 |
| ink | 167 | 133 | 0.80 |
