| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| docusaurus | 20 | 89% / 89% | 94% | 64522 | 0 | 0 | 26% / 59% (20 transitions) | 0 |
| tanstack-query | 20 | 86% / 60% | 91% | 61653 | 0 | 0 | 92% / 70% (20 transitions) | 0 |
| vue-core | 20 | 27% / 36% | 46% | 43498 | 0 | 0 | 28% / 32% (20 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| docusaurus | 0 (cold) | 40.59 | 84.62 | 93.75 | 11.46 (192/205) | 0.585 |
| docusaurus | 10 | 39.62 | 83.63 | 94.76 | 11.42 (192/205) | 0.315 |
| docusaurus | 20 | 39.55 | 83.71 | 94.4 | 11.67 (192/205) | 0.277 |
| tanstack-query | 0 (cold) | 112.88 | 194.63 | 209.3 | 55.87 (161/179) | 0.058 |
| tanstack-query | 10 | 108.37 | 198.38 | 221.14 | 56.26 (162/180) | 0.058 |
| tanstack-query | 20 | 109.17 | 199.78 | 222.89 | 55.88 (162/180) | 0.056 |
| vue-core | 0 (cold) | 28.07 | 57.33 | 60.18 | 0.97 (184/184) | 0.041 |
| vue-core | 10 | 27.51 | 58.32 | 62.06 | 1.0 (184/184) | 0.042 |
| vue-core | 20 | 27.15 | 57.49 | 61.07 | 0.98 (184/184) | 0.041 |

| project | commit | detjs --det s (runs) | cold capture, before s (runs) | cold capture, after s (runs) | overhead before | overhead after |
|---|---|---:|---:|---:|---:|---:|
| docusaurus | 0 | 84.4 (84.9/83.9) | 96.3 (97.2/95.5) | 95.1 (96.8/93.4) | +14.1% | +12.6% |
| docusaurus | 10 | 83.5 (83.5/83.4) | 93.8 (93.9/93.7) | 92.2 (92.3/92.0) | +12.4% | +10.5% |
| docusaurus | 20 | 83.3 (83.5/83.2) | 93.9 (94.0/93.9) | 92.2 (92.5/92.0) | +12.7% | +10.6% |
| tanstack-query | 0 | 194.9 (195.0/194.8) | 213.7 (213.8/213.6) | 209.0 (209.2/208.8) | +9.7% | +7.3% |
| tanstack-query | 10 | 198.4 (198.5/198.4) | 217.7 (218.2/217.2) | 212.6 (212.4/212.8) | +9.7% | +7.1% |
| tanstack-query | 20 | 199.2 (199.2/199.2) | 218.5 (218.7/218.4) | 213.8 (214.1/213.6) | +9.7% | +7.4% |
| vue-core | 0 | 57.6 (57.7/57.4) | 61.8 (61.6/61.9) | 60.7 (60.7/60.6) | +7.3% | +5.4% |
| vue-core | 10 | 58.3 (58.8/57.9) | 62.7 (63.4/62.0) | 61.6 (62.1/61.0) | +7.5% | +5.6% |
| vue-core | 20 | 57.7 (57.8/57.5) | 61.7 (62.0/61.5) | 60.7 (60.7/60.6) | +7.0% | +5.2% |

| project | commits | overhead before: range (median) | overhead after: range (median) |
|---|---:|---:|---:|
| docusaurus | 3 | +12.4% to +14.1% (+12.7%) | +10.5% to +12.6% (+10.6%) |
| tanstack-query | 3 | +9.7% to +9.7% (+9.7%) | +7.1% to +7.4% (+7.3%) |
| vue-core | 3 | +7.0% to +7.5% (+7.3%) | +5.2% to +5.6% (+5.4%) |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| docusaurus | 95 | 15 | 0.16 |
| tanstack-query | 221 | 71 | 0.32 |
| vue-core | 62 | 42 | 0.68 |
