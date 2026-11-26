| repository | w | exit | wall s | hazards (by kind) | files re-run | proven / tests | proven % | vs previous point |
|---|---|---|---|---|---|---|---|---|
| agentlang | 2 | 1 | 80.59 | 0 (-) | 0 | 0 / 439 | 0.0 | wall +8.2 %, proven +0.0 pp |
| agentlang | 4 (best) | 1 | 78.7 | 0 (-) | 0 | 0 / 439 | 0.0 | wall -2.4 %, proven +0.0 pp |
| agentsys | 2 | 1 | 24.05 | 6 (list-write 2, read-write 4) | 7 | 1554 / 2224 | 69.9 | wall -0.2 %, proven +0.5 pp |
| agentsys | 4 (best) | 1 | 20.25 | 8 (list-write 2, read-write 6) | 9 | 1552 / 2224 | 69.8 | wall +8.3 %, proven +0.5 pp |
| alakajam | 2 | 1 | 96.05 | 32 (list-write 2, read-write 20, recursive-write 10) | 21 | 0 / 221 | 0.0 | wall +2.4 %, proven +0.0 pp |
| alakajam | 4 (best) | 1 | 86.34 | 46 (list-write 1, read-write 34, recursive-write 11) | 22 | 0 / 221 | 0.0 | wall +22.0 %, proven +0.0 pp |
| codex-multi-auth | 2 | 1 | 422.29 | 3 (shared-service 3) | 5 | 0 / 8662 | 0.0 | wall +25.5 %, proven +0.0 pp |
| codex-multi-auth | 4 (best) | 1 | 366.59 | 5 (port 1, shared-service 4) | 8 | 0 / 8662 | 0.0 | wall +27.0 %, proven +0.0 pp |
| drydock | 2 | 1 | 372.38 | 21 (list-write 1, shared-service 20) | 10 | 0 / 21578 | 0.0 | wall +33.6 %, proven +0.0 pp |
| drydock | 4 (best) | 1 | 252.24 | 32 (list-write 1, shared-service 31) | 12 | 0 / 21578 | 0.0 | wall +33.3 %, proven +0.0 pp |
| ironcurtain | 2 | 1 | 181.36 | 17 (list-write 4, port 1, read-write 1, recursive-write 10, shared-service 1) | 20 | 0 / 7033 | 0.0 | wall -2.3 %, proven +0.0 pp |
| ironcurtain | 4 (best) | 1 | 104.62 | 23 (list-write 9, read-write 1, recursive-write 12, shared-service 1) | 26 | 0 / 7033 | 0.0 | wall +3.9 %, proven +0.0 pp |
| lerna-lite | 2 | 0 | 1143.75 | 11 (read-write 6, recursive-write 4, write-write 1) | 12 | 0 / 107 | 0.0 | wall +0.6 %, proven +0.0 pp |
| lerna-lite | 4 (best) | 0 | 922.05 | 24 (read-write 10, recursive-write 11, write-write 3) | 12 | 0 / 107 | 0.0 | wall +1.9 %, proven +0.0 pp |
| nestjs-pino | 2 | 0 | 13.39 | 0 (-) | 0 | 258 / 269 | 95.9 | wall +3.3 %, proven +0.0 pp |
| nestjs-pino | 4 (best) | 0 | 9.2 | 0 (-) | 0 | 258 / 269 | 95.9 | wall -7.4 %, proven +0.0 pp |
| yalc | 2 | 1 | 87.38 | 78 (list-write 76, read-write 2) | 28 | 0 / 1483 | 0.0 | wall -21.5 %, proven +0.0 pp |
| yalc | 4 (best) | 1 | 77.55 | 121 (list-write 114, read-write 7) | 29 | 0 / 1483 | 0.0 | wall -11.7 %, proven +0.0 pp |

STOP RULE: codex-multi-auth: best-worker wall 288.57 s (w4) -> 366.59 s (w4), +27.0 %; drydock: best-worker wall 189.28 s (w4) -> 252.24 s (w4), +33.3 %
