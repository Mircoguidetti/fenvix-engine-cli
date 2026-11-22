# claudekit: tests whose outcome changes without the engine (THEIRS)

Repository https://github.com/carlrannaberg/claudekit at f22a4f9030520394bf1a517b46ad7585badf5130; engine verdicts from trunk ['5a6463fd']. Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.

2 test(s).

## `tests/unit/codebase-map.test.ts::CodebaseMapHook::execute::should handle large output buffers`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [None] None
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/claudekit/repro/shuffle-2.raw.json --reporter=/home/user/fenvix-engine-cli/harness/parallel_measure/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `tests/unit/codebase-map.test.ts::CodebaseMapHook::execute::should skip silently if codebase-map is not installed`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [None] None
* first differing event: null vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/claudekit/repro/shuffle-2.raw.json --reporter=/home/user/fenvix-engine-cli/harness/parallel_measure/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

