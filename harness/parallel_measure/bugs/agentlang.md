# agentlang: tests whose outcome changes without the engine (THEIRS)

Repository https://github.com/agentlang-ai/agentlang at f02e27199b193096c19985b7877ad1644974507a; engine verdicts from trunk ['bfaf70b4']. Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.

79 test(s).

## `test/api/http.test.ts::Between Relationship - Link (POST)::POST /Module/RelName links User 2 to Post 100`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Link (POST)::POST /Module/RelName links another pair`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Link (POST)::POST /Module/RelName links two entities`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Query (GET)::GET /Module/RelName returns all relationship entries`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Unlink (DELETE)::DELETE /Module/RelName unlinks two entities`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create - POST::POST /Module/Entity creates an entity and returns it`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create - POST::POST with duplicate @id should fail`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create with Inline Relationships::array inline relationship children are queryable`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create with Inline Relationships::array inline relationship links are queryable`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create with Inline Relationships::inline relationship link is queryable`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create with Inline Relationships::inline relationship link to existing entity is queryable`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Query - GET::GET /Module/Entity returns all entities`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Query - GET::GET /Module/Entity with query params filters results`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Query - GET::GET /Module/Entity/id returns a single entity`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::GET Pagination - @limit and @offset::@limit and @offset together paginate correctly`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-2.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::GET Pagination - @limit and @offset::@limit larger than total returns all results`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-2.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::GET Pagination - @limit and @offset::@limit returns at most N results`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-2.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::GET Pagination - @limit and @offset::@offset skips rows`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-2.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/mcp.test.ts::MCP over Streamable HTTP::tools/call evaluates the event and returns its result`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [time] event #26: [time] Date.now @ src/api/http.ts:101 = 16000  <>  [sched] sched.timer @ <deps>/@hono/node-server/dist/index.mjs:513 = 0/5:<deps>/@hono/node-server/dist/index.mjs:513#1
* first differing event: {"t": 0, "s": "time", "o": "Date.now", "at": "src/api/http.ts:101", "v": "16000"} vs {"t": 0, "s": "sched", "o": "sched.timer", "at": "<deps>/@hono/node-server/dist/index.mjs:513", "v": "0/5:<deps>/@hono/node-server/dist/index.mjs:513#1"}
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-2.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/mcp.test.ts::MCP over Streamable HTTP::workflow errors are returned as tool errors`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [sched] event #79: [sched] sched.timer @ <deps>/@hono/node-server/dist/index.mjs:513 = 0/7:<deps>/@hono/node-server/dist/index.mjs:513#1  <>  [time] performance.now @ wasm:/wasm/0002f80e:1 = 49000
* first differing event: {"t": 0, "s": "sched", "o": "sched.timer", "at": "<deps>/@hono/node-server/dist/index.mjs:513", "v": "0/7:<deps>/@hono/node-server/dist/index.mjs:513#1"} vs {"t": 0, "s": "time", "o": "performance.now", "at": "wasm:/wasm/0002f80e:1", "v": "49000"}
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-2.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Array, enum and oneof tests::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Basic CRUD tests::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] the test loaded a native extension whose own C code the engine has not reasoned about: not accounted for: native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node. Identical fingerprints are no evidence of an identical execution, so the verdict is NOT PROVEN and the test must be rerun
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Between operator test::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Between relationship query result shape::between relationship query with @into returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Between relationship query result shape::between relationship query with no results returns empty array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Between relationship query result shape::query via between relationship returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Between relationship query result shape::reverse between relationship query returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Built-in date functions::dateFns datetime inline attribute values`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Built-in date functions::dateFns functions as inline attribute values`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Built-in date functions::dateFns in between queries`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Built-in date functions::dateFns nested calls in between query with @into`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Catch test::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Composite unique attributes::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Contains relationship query result shape::contains query returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Contains relationship query result shape::contains query with @into returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Contains relationship query result shape::nested contains query with @into returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Default date-time test::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Destructuring::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Empty hint test::backward compat: inner @as propagates to parent env`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Empty hint test::empty does not fire when query returns results`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Empty hint test::empty with create fallback`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Empty hint test::new syntax: @empty fires, inner @as binds alias`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Empty hint test::new syntax: query succeeds, outer @as [E] destructures`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Empty hint test::no inner @as: outer @as applies normally`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Empty hint test::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Expression attributes::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Expression tests::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Inline function call as attribute value::function call in CRUD attribute value position`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Inline function call as attribute value::inline function call with arguments`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Instances as JS objects::JS obejct syntax for instances`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Join query result shape::@join with @where filter returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Join query result shape::@join with aggregates returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Join query result shape::@join with no matching rows returns empty array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Join query result shape::multiple @join (nested joins) returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Join query result shape::simple @join returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Map attribute tests::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Nested query-into tests::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Path reference tests::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Pre-Post trigger tests::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query result shape consistency::query always returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query result shape consistency::query-all returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query result shape consistency::read-for-update multiple results returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query result shape consistency::read-for-update no match returns empty array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query result shape consistency::read-for-update single result returns array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query with @empty and relationships::@empty on contains relationship query`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query with @empty and relationships::@empty on entity query with relationship setup`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query-all with relationships returns array::query-all with between relationship and @into`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Query-all with relationships returns array::query-all with no data returns empty array`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Return from Workflow::test01`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Self-reference column comparison in queries::mixed self-reference and literal filter`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Self-reference column comparison in queries::self-reference with dotted module name`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Self-reference column comparison in queries::x < y self-reference`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::Self-reference column comparison in queries::x > y self-reference`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::custom-defaults::custom default function`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::tracking-attrs::set tracking attributes in entity instances`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=failed, engine P1w4=failed, engine P2w2=failed, engine P2w4=failed, engine P3w2=failed, engine P3w4=failed, engine S1=failed, engine S2=failed, engine S3=failed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/basic.test.ts::write-only-attributes::queries must not return writeonly attributes`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/par4-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/expr-attr.test.ts::Expression attributes with helper functions - relationship param::related entity attribute accessed through relationship as function param`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-2.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/expr-attr.test.ts::Expression attributes with helper functions - relationship param::update recomputes @expr that references through relationship`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-2.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/rbac.test.ts::Basic RBAC checks::test01`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] the test loaded a native extension whose own C code the engine has not reasoned about: not accounted for: native:/home/user/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node. Identical fingerprints are no evidence of an identical execution, so the verdict is NOT PROVEN and the test must be rerun
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/agentlang/repro/shuffle-1.raw.json --reporter=/home/user/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

