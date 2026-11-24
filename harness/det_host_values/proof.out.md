| repository | engine | engine commit | tests run | proven identical | NOT PROVEN | not identical | input differs | failed (par) | exit (par) | wall s (par) | wall s (serial) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nestjs-pino | trunk | f67be4a31f1a | 269 | 223 | 8 | 38 | 0 | 0 | 0 | 8.51 | 25.45 |
| nestjs-pino | branch | 702bf4890c4b | 269 | 222 | 7 | 40 | 0 | 0 | 0 | 8.57 | 21.22 |
| agentsys | trunk | f67be4a31f1a | 2224 | 0 | 1740 | 484 | 0 | 1 | 1 | 21.2 | 19.79 |
| agentsys | branch | 702bf4890c4b | 2224 | 0 | 1740 | 484 | 0 | 1 | 1 | 23.54 | 20.97 |
| claudekit | trunk | f67be4a31f1a | 814 | 555 | 230 | 29 | 0 | 0 | 0 | 20.89 | 26.65 |
| claudekit | branch | 702bf4890c4b | 814 | 555 | 230 | 29 | 0 | 0 | 0 | 21.38 | 21.25 |
| sqlectron | trunk | f67be4a31f1a | 43 | 0 | 38 | 5 | 0 | 0 | 0 | 15.73 | 32.48 |
| sqlectron | branch | 702bf4890c4b | 43 | 0 | 38 | 5 | 0 | 0 | 0 | 15.57 | 19.31 |
| ironcurtain | trunk | f67be4a31f1a | 7033 | 0 | 0 | 7033 | 0 | 408 | 1 | 175.38 | 225.89 |
| ironcurtain | branch | 702bf4890c4b | 7033 | 0 | 0 | 7033 | 0 | 385 | 1 | 110.59 | 233.14 |
| codex-multi-auth | trunk | f67be4a31f1a | 8662 | 0 | 0 | 8661 | 0 | 390 | 1 | 284.82 | 421.46 |
| codex-multi-auth | branch | 702bf4890c4b | 8662 | 0 | 4752 | 3909 | 0 | 425 | 1 | 309.79 | 440.68 |

## AC3 bounds

| repository | identical trunk / branch | allowed drop (0.5% of tests) | identical | exit trunk -> branch | wall par branch / trunk (<= 1.10) |
|---|---|---|---|---|---|
| nestjs-pino | 223 / 222 | 1.3 | met | 0 -> 0 | 1.007 met |
| agentsys | 0 / 0 | 11.1 | met | 1 -> 1 | 1.110 MISSED |
| claudekit | 555 / 555 | 4.1 | met | 0 -> 0 | 1.023 met |
| sqlectron | 0 / 0 | 0.2 | met | 0 -> 0 | 0.990 met |
| ironcurtain | 0 / 0 | 35.2 | met | 1 -> 1 | 0.631 met |
| codex-multi-auth | 0 / 0 | 43.3 | met | 1 -> 1 | 1.088 met |

### nestjs-pino: identical on the trunk, not on the branch (1); the reverse: 0

| test | branch status | reason | description |
|---|---|---|---|
| `__tests__/module.spec.ts::module initialization::ExpressAdapter::forRoot::should work properly with single value of `httpPino` property` | diverged | time | `event #48: [time] Date.now @ <deps>/pino-http/logger.js:170 = 42000  <>  [other] uncontrolled.io @ <deps>/sonic-boom/index.js:622 = concurrent I/O` |

### agentsys: identical on the trunk, not on the branch (0); the reverse: 0


### claudekit: identical on the trunk, not on the branch (1); the reverse: 1

| test | branch status | reason | description |
|---|---|---|---|
| `tests/lib/filesystem-conflict-integration.test.ts::File Conflict Detection - Integration Tests::copyFileWithBackup - real file operations::should not ` | diverged | fs | `event #19: fs.stat @ <node> returned different values: "<tmp>/source.txt|file size=14" vs "<tmp>/target.txt|file size=30"` |

### sqlectron: identical on the trunk, not on the branch (0); the reverse: 0


### ironcurtain: identical on the trunk, not on the branch (0); the reverse: 0


### codex-multi-auth: identical on the trunk, not on the branch (0); the reverse: 0

