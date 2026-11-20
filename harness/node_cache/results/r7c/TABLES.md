| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| docusaurus | 20 | 89% / 89% | 94% | 64522 | 0 | 0 | 26% / 59% (20 transitions) | 0 |
| tanstack-query | 20 | 86% / 60% | 91% | 61653 | 0 | 0 | 92% / 70% (20 transitions) | 0 |
| vue-core | 20 | 26% / 36% | 46% | 43498 | 0 | 0 | 27% / 31% (20 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| docusaurus | 0 (cold) | 35.13 | 72.75 | 80.26 | 9.46 (192/205) | 0.345 |
| docusaurus | 10 | 34.24 | 71.99 | 82.26 | 9.68 (192/205) | 0.099 |
| docusaurus | 20 | 34.53 | 73.11 | 80.8 | 9.76 (192/205) | 0.105 |
| tanstack-query | 0 (cold) | 117.03 | 203.99 | 228.51 | 61.37 (161/179) | 0.057 |
| tanstack-query | 10 | 117.46 | 216.69 | 237.31 | 59.96 (162/180) | 0.056 |
| tanstack-query | 20 | 117.07 | 212.26 | 242.76 | 58.72 (162/180) | 0.059 |
| vue-core | 0 (cold) | 32.29 | 66.19 | 70.89 | 1.41 (184/184) | 0.054 |
| vue-core | 10 | 31.04 | 67.08 | 70.82 | 1.41 (184/184) | 0.045 |
| vue-core | 20 | 31.15 | 67.62 | 73.4 | 1.43 (184/184) | 0.045 |

| project | commit | detjs --det s (runs) | cold capture, before s (runs) | cold capture, after s (runs) | overhead before | overhead after |
|---|---|---:|---:|---:|---:|---:|
| docusaurus | 0 | 72.2 (71.9/72.5) | 81.0 (81.0/81.0) | 80.7 (80.9/80.4) | +12.2% | +11.7% |
| docusaurus | 10 | 72.4 (72.2/72.5) | 81.0 (81.1/81.0) | 79.5 (79.6/79.5) | +12.0% | +9.9% |
| docusaurus | 20 | 71.9 (72.2/71.5) | 81.4 (81.2/81.5) | 80.1 (80.6/79.6) | +13.2% | +11.4% |
| tanstack-query | 0 | 208.9 (209.8/208.0) | 224.1 (226.1/222.1) | 218.5 (220.2/216.9) | +7.3% | +4.6% |
| tanstack-query | 10 | 207.7 (208.7/206.8) | 231.3 (229.7/232.9) | 232.0 (233.8/230.2) | +11.3% | +11.7% |
| tanstack-query | 20 | 214.3 (215.0/213.7) | 233.8 (235.6/231.9) | 227.2 (228.7/225.7) | +9.1% | +6.0% |
| vue-core | 0 | 65.5 (64.5/66.4) | 69.3 (69.3/69.3) | 69.7 (69.8/69.6) | +5.9% | +6.5% |
| vue-core | 10 | 66.8 (67.1/66.5) | 71.2 (71.7/70.6) | 70.7 (70.0/71.3) | +6.6% | +5.8% |
| vue-core | 20 | 68.1 (68.4/67.9) | 73.0 (73.6/72.5) | 72.1 (71.7/72.4) | +7.2% | +5.8% |

| project | commits | overhead before: range (median) | overhead after: range (median) |
|---|---:|---:|---:|
| docusaurus | 3 | +12.0% to +13.2% (+12.2%) | +9.9% to +11.7% (+11.4%) |
| tanstack-query | 3 | +7.3% to +11.3% (+9.1%) | +4.6% to +11.7% (+6.0%) |
| vue-core | 3 | +5.9% to +7.2% (+6.6%) | +5.8% to +6.5% (+5.8%) |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| docusaurus | 82 | 13 | 0.15 |
| tanstack-query | 233 | 77 | 0.33 |
| vue-core | 71 | 49 | 0.69 |
