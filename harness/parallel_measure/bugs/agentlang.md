# agentlang: tests whose outcome changes without the engine (THEIRS)

Repository https://github.com/agentlang-ai/agentlang at f02e27199b193096c19985b7877ad1644974507a; engine verdicts from trunk ['0071cbb9']. Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.

38 test(s).

## `example/knowledge/test/core.test.ts::Entity CRUD::Connection: create with required fields and verify defaults`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::Entity CRUD::KnowledgeDocument: create with defaults`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::Relationships::ConnectionDocument contains: documents linked to connection via connectionId`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::Relationships::TopicDocumentLink between: link topic to document via TopicDocument`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::processChangelog workflow::processes added entries: creates KnowledgeDocument and DocumentVersion`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::processChangelog workflow::processes deleted entries: soft-deletes KnowledgeDocument`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::processChangelog workflow::processes modified entries: bumps document version`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::syncConnection workflow::detects deleted files: creates deleted changelog entry`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::syncConnection workflow::detects modified files: creates modified changelog entry`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::syncConnection workflow::happy path: creates SyncJob, detects added file, processes changelog`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::syncConnection workflow::sync failure: SyncJob marked failed and Connection syncErrorCount incremented`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::syncTick workflow::prunes stale in_progress jobs: marks failed and bumps syncErrorCount`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::syncTick workflow::skips connection when in_progress job already exists`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::syncTick workflow::skips disabled connections: no new SyncJob created`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `example/knowledge/test/core.test.ts::syncTick workflow::triggers sync for ready connections with no in_progress job`

* plain runs failed: plain par4-1; passed: plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --maxWorkers=4 --fileParallelism --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/par4-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Link (POST)::POST /Module/RelName links User 2 to Post 100`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Link (POST)::POST /Module/RelName links another pair`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Link (POST)::POST /Module/RelName links two entities`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Query (GET)::GET /Module/RelName returns all relationship entries`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Between Relationship - Unlink (DELETE)::DELETE /Module/RelName unlinks two entities`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create - POST::POST /Module/Entity creates an entity and returns it`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create - POST::POST with duplicate @id should fail`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create with Inline Relationships::array inline relationship children are queryable`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create with Inline Relationships::array inline relationship links are queryable`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create with Inline Relationships::inline relationship link is queryable`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Create with Inline Relationships::inline relationship link to existing entity is queryable`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Query - GET::GET /Module/Entity returns all entities`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Query - GET::GET /Module/Entity with query params filters results`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::Entity Query - GET::GET /Module/Entity/id returns a single entity`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/api/http.test.ts::GET Pagination - @limit and @offset::@limit and @offset together paginate correctly`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-2.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::GET Pagination - @limit and @offset::@limit larger than total returns all results`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-2.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::GET Pagination - @limit and @offset::@limit returns at most N results`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-2.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/http.test.ts::GET Pagination - @limit and @offset::@offset skips rows`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-2.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/mcp.test.ts::MCP over Streamable HTTP::tools/call evaluates the event and returns its result`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [time] event #18: [time] setTimeout @ <deps>/@hono/node-server/dist/index.mjs:513 = schedule:1000000  <>  [time] performance.now @ wasm:/wasm/0002f80e:1 = 11000
* first differing event: {"t": 0, "s": "time", "o": "setTimeout", "at": "<deps>/@hono/node-server/dist/index.mjs:513", "v": "schedule:1000000"} vs {"t": 0, "s": "time", "o": "performance.now", "at": "wasm:/wasm/0002f80e:1", "v": "11000"}
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-2.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/api/mcp.test.ts::MCP over Streamable HTTP::workflow errors are returned as tool errors`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [sched] event #28: [sched] sched.timer @ <deps>/@hono/node-server/dist/index.mjs:513 = 0/5:<deps>/@hono/node-server/dist/index.mjs:513#1  <>  [time] Date.now @ src/api/http.ts:101 = 16000
* first differing event: {"t": 0, "s": "sched", "o": "sched.timer", "at": "<deps>/@hono/node-server/dist/index.mjs:513", "v": "0/5:<deps>/@hono/node-server/dist/index.mjs:513#1"} vs {"t": 0, "s": "time", "o": "Date.now", "at": "src/api/http.ts:101", "v": "16000"}
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-2.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/expr-attr.test.ts::Expression attributes with helper functions - relationship param::related entity attribute accessed through relationship as function param`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-2.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/expr-attr.test.ts::Expression attributes with helper functions - relationship param::update recomputes @expr that references through relationship`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] outside any test the run read sources that are not controlled (native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node): every test may have observed them, so identical fingerprints are no evidence of an identical execution
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-2.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/runtime/rbac.test.ts::Basic RBAC checks::test01`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [native] the test loaded a native extension whose own C code the engine has not reasoned about: not accounted for: native:/tmp/pm/repos/agentlang/node_modules/.pnpm/better-sqlite3@12.6.2/node_modules/better-sqlite3/build/Release/better_sqlite3.node. Identical fingerprints are no evidence of an identical execution, so the verdict is NOT PROVEN and the test must be rerun
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/pm/lane-a/agentlang/repro/shuffle-1.raw.json --reporter=/tmp/pm/repos/agentlang/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

