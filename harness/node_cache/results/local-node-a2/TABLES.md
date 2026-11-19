| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hexo | 2 | 6% / 6% | 35% | 269 | 0 | 0 | n/a / n/a (0 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| hexo | 27 (cold) | 33.79 | 29.11 | 397.8 | 366.18 (20/120) | 0.882 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| hexo | 397 | 389 | 0.98 |
