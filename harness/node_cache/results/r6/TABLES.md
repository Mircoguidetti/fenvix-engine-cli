| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| docusaurus | 50 | 85% / 70% | 92% | 129295 | 0 | 0 | 27% / 56% (50 transitions) | 0 |
| lexical | 10 | 0% / 0% | 0% | 1528 | 0 | 0 | 75% / 62% (10 transitions) | 27 |
| react-native | 9 | 0% / 1% | 0% | 22330 | 0 | 0 | 98% / 87% (9 transitions) | 0 |
| tanstack-query | 50 | 92% / 62% | 94% | 158515 | 0 | 0 | 92% / 69% (50 transitions) | 0 |
| vue-core | 50 | 26% / 32% | 46% | 85112 | 0 | 0 | 27% / 29% (50 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| docusaurus | 0 (cold) | 41.11 | 87.47 | 98.41 | 15.59 (188/205) | 1.102 |
| docusaurus | 10 | 39.0 | 82.62 | 95.7 | 14.62 (188/205) | 0.903 |
| docusaurus | 20 | 39.56 | 83.27 | 102.61 | 15.99 (188/205) | 0.847 |
| docusaurus | 35 | 47.15 | 100.59 | 118.64 | 18.74 (189/206) | 0.992 |
| docusaurus | 45 | 47.72 | 101.01 | 115.44 | 19.36 (189/207) | 0.965 |
| lexical | 40 (cold) | 795.27 | 1502.77 | 1537.53 | 1557.43 (6/982) | 1.394 |
| react-native | 0 (cold) | 76.28 | 2133.97 | 2150.03 | 2096.3 (231/284) | 0.8 |
| react-native | 17 (cold) | 69.89 | 2114.8 | 2126.72 | 2089.73 (231/284) | 0.619 |
| react-native | 34 (cold) | 77.6 | 2134.17 | 2148.13 | 2095.32 (231/284) | 0.76 |
| tanstack-query | 0 (cold) | 75.89 | 133.64 | 146.4 | 40.39 (161/179) | 1.645 |
| tanstack-query | 10 | 72.8 | 133.85 | 151.46 | 40.36 (162/180) | 1.162 |
| tanstack-query | 27 | 107.51 | 195.9 | 226.69 | 57.86 (162/180) | 2.521 |
| tanstack-query | 44 | 73.97 | 137.46 | 156.67 | 41.22 (162/180) | 1.526 |
| vue-core | 0 (cold) | 44.28 | 92.72 | 101.84 | 1.92 (184/184) | 0.363 |
| vue-core | 10 | 41.11 | 84.12 | 90.63 | 1.77 (184/184) | 0.254 |
| vue-core | 20 | 40.78 | 85.04 | 92.39 | 1.73 (184/184) | 0.255 |
| vue-core | 35 | 40.32 | 84.31 | 90.71 | 1.74 (184/184) | 0.306 |
| vue-core | 45 | 41.46 | 86.91 | 94.47 | 1.77 (185/185) | 0.329 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| docusaurus | 107 | 22 | 0.20 |
| lexical | 1478 | 1493 | 1.01 |
| react-native | 2151 | 2129 | 0.99 |
| tanstack-query | 156 | 62 | 0.40 |
| vue-core | 92 | 63 | 0.68 |
