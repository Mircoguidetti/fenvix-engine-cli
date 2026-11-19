| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ava-globby | 25 | 0% / 1% | 0% | 235 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| ava-shelljs | 25 | 0% / 1% | 0% | 456 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| jasmine-cordova-android | 25 | 86% / 69% | 82% | 5860 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| jasmine-xregexp | 20 | 0% / 25% | 0% | 2126 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| tap-dotenv | 25 | 0% / 7% | 0% | 750 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| tap-minimatch | 25 | 2% / 20% | 0% | 854 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| uvu-autoprefixer | 25 | 15% / 21% | 24% | 1844 | 0 | 0 | n/a / n/a (0 transitions) | 0 |
| uvu-browserslist | 25 | 1% / 11% | 1% | 1222 | 0 | 0 | n/a / n/a (0 transitions) | 0 |

| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |
|---|---|---:|---:|---:|---:|---:|
| ava-globby | 0 (cold) | 2.18 | 3.22 | 4.28 | 8.37 (2/6) | 0.197 |
| ava-globby | 10 | 1.67 | 3.16 | 5.16 | 5.37 (0/6) | 0.16 |
| ava-globby | 20 | 2.36 | 5.57 | 7.46 | 6.8 (1/9) | 0.159 |
| ava-shelljs | 0 (cold) | 15.56 | 17.17 | 23.13 | 16.72 (19/38) | 0.152 |
| ava-shelljs | 10 | 14.93 | 15.21 | 23.24 | 16.23 (20/38) | 0.123 |
| ava-shelljs | 20 | 15.37 | 15.9 | 22.18 | 15.58 (20/38) | 0.118 |
| jasmine-cordova-android | 0 (cold) | 1.37 | 1.19 | 9.2 | 1.09 (18/20) | 2.578 |
| jasmine-cordova-android | 10 | 1.07 | 1.11 | 6.43 | 1.04 (18/20) | 0.082 |
| jasmine-cordova-android | 20 | 1.07 | 1.15 | 6.57 | 1.06 (18/20) | 0.082 |
| jasmine-xregexp | 0 (cold) | 0.37 | 0.1 | 1.78 | 0.43 (0/0) | 1.671 |
| jasmine-xregexp | 10 | 0.65 | 0.66 | 1.82 | 0.49 (5/5) | 0.329 |
| jasmine-xregexp | 20 | 0.68 | 0.68 | 2.08 | 0.73 (5/5) | 0.56 |
| tap-dotenv | 0 (cold) | 10.99 | 20.25 | 21.36 | 16.96 (5/10) | 0.281 |
| tap-dotenv | 10 | 12.65 | 22.17 | 23.15 | 18.99 (5/10) | 0.209 |
| tap-dotenv | 20 | 12.91 | 23.52 | 24.17 | 19.61 (5/10) | 0.202 |
| tap-minimatch | 0 (cold) | 22.87 | 41.97 | 35.3 | 0.44 (33/33) | 0.222 |
| tap-minimatch | 10 | 22.36 | 42.32 | 37.3 | 0.46 (35/35) | 0.165 |
| tap-minimatch | 20 | 27.01 | 50.82 | 43.35 | 4.0 (36/37) | 0.167 |
| uvu-autoprefixer | 0 (cold) | 1.11 | 1.27 | 3.63 | 0.25 (15/15) | 0.176 |
| uvu-autoprefixer | 10 | 1.1 | 1.35 | 3.7 | 0.26 (15/15) | 0.092 |
| uvu-autoprefixer | 20 | 1.21 | 1.37 | 3.81 | 0.27 (15/15) | 0.091 |
| uvu-browserslist | 0 (cold) | 2.01 | 2.18 | 7.14 | 2.09 (32/36) | 0.232 |
| uvu-browserslist | 10 | 2.02 | 2.2 | 6.86 | 1.94 (32/36) | 0.155 |
| uvu-browserslist | 20 | 1.94 | 2.1 | 6.73 | 1.88 (32/36) | 0.235 |

| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |
|---|---:|---:|---:|
| ava-globby | 5 | 5 | 0.99 |
| ava-shelljs | 22 | 22 | 1.00 |
| jasmine-cordova-android | 7 | 1 | 0.16 |
| jasmine-xregexp | 2 | 2 | 0.99 |
| tap-dotenv | 23 | 21 | 0.92 |
| tap-minimatch | 37 | 37 | 0.99 |
| uvu-autoprefixer | 4 | 3 | 0.79 |
| uvu-browserslist | 7 | 7 | 0.99 |
