# drydock: tests whose outcome changes without the engine (THEIRS)

Repository https://github.com/CodesWhat/drydock at ce562a6a84c91b7e101398766d7de560cd18e35f; engine verdicts from trunk ['bfaf70b4']. Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.

40 test(s).

## `agent/api/event.test.ts::agent API event::subscribeEvents::should set SSE headers and send ack`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/auth-lockout.test.ts::auth-lockout::a store fault during login is never counted as a failed attempt`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/auth-lockout.test.ts::auth-lockout::clearLoginLockout BlockStatement: persist fires only from the clear, not from a prior failure`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/auth-lockout.test.ts::auth-lockout::clearLoginLockout: no key does nothing (block not empty)`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/auth-lockout.test.ts::auth-lockout::clearLoginLockout: when key is undefined, no persist or gauge update`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/auth-lockout.test.ts::auth-lockout::clears lockout state after a successful authentication`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::global error handler logs an unexplained error, and only repeats an already explained one at debug`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::global error handler should default to 500 and generic message`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::global error handler should use err.status and keep message generic`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::real Express: GET /api/auth/methods is no longer registered and is answered by the removed-alias tombstone`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=failed, engine P1w4=failed, engine P2w2=failed, engine P2w4=failed, engine P3w2=failed, engine P3w4=passed, engine S1=passed, engine S2=failed, engine S3=failed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::real Express: UI paths return a JSON 404 explaining DD_SERVER_UI_ENABLED=false, while /api/v1 and /health are unaffected`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=failed, engine P1w4=failed, engine P2w2=failed, engine P2w4=passed, engine P3w2=failed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=failed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::real Express: a non-whitelisted /api/* request returns 410 JSON (not 404, not SPA HTML) when DD_COMPAT_WUDCARD is disabled`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=failed, engine P2w2=failed, engine P2w4=failed, engine P3w2=failed, engine P3w4=failed, engine S1=failed, engine S2=passed, engine S3=failed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::real Express: sendUiDisabledResponse lets unmatched API, health, and metrics paths fall through instead of returning the UI-disabled body`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=failed, engine S1=failed, engine S2=failed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::real Express: the legacy-alias usage tracker still records a hit for a request the tombstone answers with 410`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=failed, engine P3w2=failed, engine P3w4=failed, engine S1=failed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::real Express: whitelisted wud-card endpoints still serve via the compat router while a non-whitelisted /api route still 410s when DD_COMPAT_WUDCARD is enabled`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=failed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=failed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/index.test.ts::API Index::should skip mounting UI router when DD_SERVER_UI_ENABLED=false`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `api/portwing-ws.test.ts::version handshake::welcome config includes serverCompatLevel=1.4.0 and supportedProtocols=portwing/1.0`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-2.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `configuration/index.test.ts::getRegistryConfigurations should return empty object by default`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-2.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `log/buffer.test.ts::Ring Buffer::empty buffer::should return empty array when buffer is empty`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `log/buffer.test.ts::Ring Buffer::empty buffer::should return no components when buffer is empty`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `log/buffer.test.ts::Ring Buffer::getComponents::returns sorted unique component names from the buffer`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `registries/providers/custom/Custom.test.ts::authenticate should add basic auth`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `registries/providers/custom/Custom.test.ts::maskConfiguration should mask configuration secrets`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `registries/providers/custom/Custom.test.ts::match should return false when registry url is not from custom`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-2.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `registries/providers/ecr/Ecr.test.ts::fetchPrivateEcrAuthToken should construct the ECR client with configured credentials`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `registry/index.test.ts::reconcileComponentsWithConfiguration::a component that fails to re-register on change is reported, and ends up absent (no rollback)`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `registry/index.test.ts::reconcileComponentsWithConfiguration::registers components outside the request audit actor so armed timers stay actor-free`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=failed, engine P2w2=failed, engine P2w4=failed, engine P3w2=passed, engine P3w4=passed, engine S1=failed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `registry/index.test.ts::registerAuthentications should preserve unknown-provider error messages`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `release-notes/providers/GithubProvider.test.ts::release-notes/providers/GithubProvider::fetchRange::plain 403 with no token and no GHCR fallback: interrupted:true, no warn`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `store/audit.test.ts::retention configuration::defaults to 30 days when unset`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `store/index.test.ts::Store Module::should create directory if it does not exist`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `store/index.test.ts::Store Module::should initialize store successfully`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `store/mqtt-hass.test.ts::MQTT Hass store::hasRunHassIdentityTopicCleanup returns false before createCollections runs`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `store/mqtt-hass.test.ts::MQTT Hass store::markHassIdentityTopicCleanupComplete is a no-op before createCollections runs`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `triggers/providers/dockercompose/ComposeFileLockManager.test.ts::ComposeFileLockManager::withComposeFileLock should not reacquire lock when operation nests on the same file`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `triggers/providers/portainer/Portainer.test.ts::Portainer delegates tag lifecycle calls to the inherited implementation`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `triggers/providers/portainer/Portainer.test.ts::performContainerUpdate persists Portainer recovery state before target PUT`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `triggers/providers/portainer/Portainer.test.ts::runContainerUpdateLifecycle creates a durable operation before automatic work without a runtime operation id`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `triggers/providers/slack/Slack.test.ts::trigger should format text as expected`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `updates/request-update.test.ts::request-update::markAcceptedQueuedOperationFailed reclassification (issue #410 Part B)::keeps failed status for Docker 404 when only another agent has a recent same-name success`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:registries/providers/gar/Gar.js differs: "stat:missing" vs <not recorded>; also differ: file:registries/providers/gar/Gar.ts, file:registries/providers/gcr/Gcr.js, file:registries/providers/gcr/Gcr.ts, file:registries/providers/ghcr/Ghcr.js, file:registries/providers/ghcr/Ghcr.ts, file:registries/providers/lscr/Lscr.js, file:registries/providers/lscr/Lscr.ts, file:registries/providers/mau/Mau.js, file:registries/providers/mau/Mau.ts, file:registries/providers/ocir/Ocir.js, file:registries/providers/ocir/Ocir.ts
* first differing event: {"t": 0, "s": "other", "o": "input.file:registries/providers/gar/Gar.js", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/drydock/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/CodesWhat_drydock/app/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

