| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| json-schema-faker | 20 | 1% / 15% | 2% | 1284 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| oak | 20 | 34% / 38% | 28% | 1151 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| std | 20 | 65% / 54% | 75% | 22787 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| wouter | 20 | 25% / 47% | 24% | 2602 | 0 | 0 | n/a / n/a (0 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| json-schema-faker | 0 (cold) | 0.92 | 1.6 | 4.36 | 0.94 (14/16) | 2.168 |
| json-schema-faker | 10 | 0.7 | 1.73 | 2.41 | 0.97 (16/18) | 0.056 |
| json-schema-faker | 20 | 0.93 | 2.31 | 3.12 | 1.02 (20/22) | 0.058 |
| oak | 0 (cold) | 1.75 | 18.44 | 11.3 | 9.3 (5/5) | 0.168 |
| oak | 10 | 1.77 | 2.88 | 4.11 | 1.32 (15/21) | 0.035 |
| oak | 20 | 1.73 | 2.87 | 4.01 | 1.31 (15/21) | 0.035 |
| std | 0 (cold) | 14.61 | 256.42 | 51.69 | 11.56 (164/203) | 0.148 |
| std | 10 | 14.27 | 38.3 | 52.27 | 11.76 (164/203) | 0.069 |
| std | 20 | 11.62 | 38.25 | 52.39 | 11.87 (164/203) | 0.069 |
| wouter | 0 (cold) | 0.59 | 6.87 | 14.35 | 0.75 (21/22) | 2.989 |
| wouter | 10 | 0.55 | 6.75 | 11.46 | 0.74 (21/22) | 0.133 |
| wouter | 20 | 0.53 | 6.99 | 11.97 | 0.77 (22/23) | 0.134 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| json-schema-faker | 2 | 2 | 0.94 |
| oak | 4 | 4 | 1.01 |
| std | 52 | 12 | 0.23 |
| wouter | 11 | 9 | 0.75 |
