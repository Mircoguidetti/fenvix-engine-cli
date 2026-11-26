| repository | w | exit | wall s | hazards (by kind) | files re-run | proven / tests | proven % | vs previous point |
|---|---|---|---|---|---|---|---|---|
| agentlang | 2 (best) | 1 | 55.93 | 0 (-) | 0 | 0 / 439 | 0.0 | wall -24.9 %, proven +0.0 pp |
| agentlang | 4 | 1 | 60.37 | 0 (-) | 0 | 0 / 439 | 0.0 | wall -25.2 %, proven +0.0 pp |
| agentsys | 2 | 1 | 18.25 | 6 (list-write 2, read-write 4) | 7 | 1554 / 2224 | 69.9 | wall -24.3 %, proven +0.5 pp |
| agentsys | 4 (best) | 1 | 16.4 | 8 (list-write 2, read-write 6) | 9 | 1552 / 2224 | 69.8 | wall -12.3 %, proven +0.5 pp |
| alakajam | 2 | 1 | 75.84 | 34 (read-write 19, recursive-write 10, write-write 5) | 21 | 0 / 221 | 0.0 | wall -19.1 %, proven +0.0 pp |
| alakajam | 4 (best) | 1 | 70.65 | 60 (read-write 30, recursive-write 22, write-write 8) | 27 | 0 / 221 | 0.0 | wall -0.1 %, proven +0.0 pp |
| codex-multi-auth | 2 | 1 | 471.11 | 72 (read-write 1, recursive-write 71) | 73 | 0 / 8662 | 0.0 | wall +40.0 %, proven +0.0 pp |
| codex-multi-auth | 4 (best) | 1 | 455.34 | 106 (port 1, read-write 1, recursive-write 104) | 108 | 0 / 8662 | 0.0 | wall +57.8 %, proven +0.0 pp |
| drydock | 2 | 1 | 249.19 | 1 (list-write 1) | 2 | 0 / 21578 | 0.0 | wall -10.6 %, proven +0.0 pp |
| drydock | 4 (best) | 1 | 178.06 | 1 (list-write 1) | 2 | 0 / 21578 | 0.0 | wall -5.9 %, proven +0.0 pp |
| ironcurtain | 2 | 1 | 164.29 | 117 (list-write 6, port 1, read-write 34, recursive-write 76) | 104 | 0 / 7033 | 0.0 | wall -11.5 %, proven +0.0 pp |
| ironcurtain | 4 (best) | 1 | 156.07 | 158 (list-write 12, port 1, read-write 42, recursive-write 103) | 137 | 0 / 7033 | 0.0 | wall +54.9 %, proven +0.0 pp |
| lerna-lite | 2 | 0 | 1109.9 | 36 (write-write 36) | 12 | 0 / 107 | 0.0 | wall -2.4 %, proven +0.0 pp |
| lerna-lite | 4 (best) | 0 | 889.46 | 54 (write-write 54) | 12 | 0 / 107 | 0.0 | wall -1.7 %, proven +0.0 pp |
| nestjs-pino | 2 | 0 | 10.55 | 0 (-) | 0 | 258 / 269 | 95.9 | wall -18.6 %, proven +0.0 pp |
| nestjs-pino | 4 (best) | 0 | 6.77 | 0 (-) | 0 | 258 / 269 | 95.9 | wall -31.9 %, proven +0.0 pp |
| yalc | 2 | 1 | 91.27 | 646 (list-write 45, read-write 2, write-write 599) | 62 | 0 / 1483 | 0.0 | wall -18.0 %, proven +0.0 pp |
| yalc | 4 (best) | 1 | 78.2 | 944 (list-write 66, read-write 7, write-write 871) | 62 | 0 / 1483 | 0.0 | wall -10.9 %, proven +0.0 pp |

STOP RULE: codex-multi-auth: best-worker wall 288.57 s (w4) -> 455.34 s (w4), +57.8 %; ironcurtain: best-worker wall 100.74 s (w4) -> 156.07 s (w4), +54.9 %
