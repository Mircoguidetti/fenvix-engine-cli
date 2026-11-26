| repository | w | exit | wall s | hazards (by kind) | files re-run | proven / tests | proven % | vs previous point |
|---|---|---|---|---|---|---|---|---|
| agentlang | 2 (best) | 1 | 65.72 | 0 (-) | 0 | 0 / 439 | 0.0 | wall -11.8 %, proven +0.0 pp |
| agentlang | 4 | 1 | 66.62 | 0 (-) | 0 | 0 / 439 | 0.0 | wall -17.4 %, proven +0.0 pp |
| agentsys | 2 | 1 | 19.52 | 6 (list-write 2, read-write 4) | 7 | 1554 / 2224 | 69.9 | wall -19.0 %, proven +0.5 pp |
| agentsys | 4 (best) | 1 | 18.82 | 8 (list-write 2, read-write 6) | 9 | 1552 / 2224 | 69.8 | wall +0.6 %, proven +0.5 pp |
| alakajam | 2 | 1 | 92.13 | 122 (read-write 19, recursive-write 98, write-write 5) | 27 | 0 / 221 | 0.0 | wall -1.8 %, proven +0.0 pp |
| alakajam | 4 (best) | 1 | 76.52 | 183 (read-write 29, recursive-write 145, write-write 9) | 27 | 0 / 221 | 0.0 | wall +8.2 %, proven +0.0 pp |
| codex-multi-auth | 2 | 1 | 496.24 | 82 (recursive-write 82) | 83 | 0 / 8662 | 0.0 | wall +47.5 %, proven +0.0 pp |
| codex-multi-auth | 4 (best) | 1 | 474.75 | 120 (port 1, recursive-write 119) | 122 | 0 / 8662 | 0.0 | wall +64.5 %, proven +0.0 pp |
| drydock | 2 | 1 | 267.07 | 1 (list-write 1) | 2 | 0 / 21578 | 0.0 | wall -4.2 %, proven +0.0 pp |
| drydock | 4 (best) | 1 | 238.93 | 37 (list-write 1, recursive-write 36) | 38 | 0 / 21578 | 0.0 | wall +26.2 %, proven +0.0 pp |
| ironcurtain | 2 | 1 | 240.22 | 191 (list-write 6, port 1, read-write 17, recursive-write 167) | 105 | 0 / 7033 | 0.0 | wall +29.4 %, proven +0.0 pp |
| ironcurtain | 4 (best) | 1 | 221.74 | 278 (list-write 11, read-write 22, recursive-write 245) | 184 | 0 / 7033 | 0.0 | wall +120.1 %, proven +0.0 pp |
| lerna-lite | 2 | 0 | 1111.6 | 36 (write-write 36) | 12 | 0 / 107 | 0.0 | wall -2.2 %, proven +0.0 pp |
| lerna-lite | 4 (best) | 1 | 906.19 | 54 (write-write 54) | 12 | 0 / 107 | 0.0 | wall +0.1 %, proven +0.0 pp |
| nestjs-pino | 2 | 0 | 12.24 | 0 (-) | 0 | 258 / 269 | 95.9 | wall -5.6 %, proven +0.0 pp |
| nestjs-pino | 4 (best) | 0 | 8.01 | 0 (-) | 0 | 258 / 269 | 95.9 | wall -19.4 %, proven +0.0 pp |
| yalc | 2 | 1 | 128.81 | 3449 (list-write 31, read-write 2, recursive-write 2817, write-write 599) | 165 | 0 / 1483 | 0.0 | wall +15.7 %, proven +0.0 pp |
| yalc | 4 (best) | 1 | 119.4 | 5198 (list-write 43, read-write 6, recursive-write 4278, write-write 871) | 165 | 0 / 1483 | 0.0 | wall +36.0 %, proven +0.0 pp |

STOP RULE: codex-multi-auth: best-worker wall 288.57 s (w4) -> 474.75 s (w4), +64.5 %; drydock: best-worker wall 189.28 s (w4) -> 238.93 s (w4), +26.2 %; ironcurtain: best-worker wall 100.74 s (w4) -> 221.74 s (w4), +120.1 %; yalc: best-worker wall 87.8 s (w4) -> 119.4 s (w4), +36.0 %
