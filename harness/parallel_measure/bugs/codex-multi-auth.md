# codex-multi-auth: tests whose outcome changes without the engine (THEIRS)

Repository https://github.com/ndycode/codex-multi-auth at b9886168aafcebd8581d4e344daf7abd19b510ce; engine verdicts from trunk ['bfaf70b4']. Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.

10 test(s).

## `test/codex-bin-wrapper.test.ts::codex bin wrapper::stress: metadata stays bounded across many launch/exit cycles`

* plain runs failed: plain serial 2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 3, plain shuffle-1, plain shuffle-2
* engine runs: engine P1w2=failed, engine P1w4=failed, engine P2w2=failed, engine P2w4=failed, engine P3w2=failed, engine P3w4=failed, engine S1=failed, engine S2=failed, engine S3=failed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce: failed only in a plain serial round of measure.py (command in results.jsonl)
* reproduces: yes (1 of 7 plain runs failed)

## `test/codex-manager-cli.test.ts::codex manager cli commands::reuses the queued refresh result across concurrent live best runs`

* plain runs failed: plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-1
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-2.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/repair-commands.test.ts::repair-commands direct deps coverage::runVerifyFlagged uses the injected identity resolver in the direct no-restore flow`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-1.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/runtime-transcription-proxy.test.ts::runtime transcription proxy::refuses a disabled selected transcription workspace without using a sibling`

* plain runs failed: plain shuffle-1; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3, plain shuffle-2
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-1.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (1 of 7 plain runs failed)

## `test/storage.test.ts::clearAccounts removes discovered backup artifacts as well as fixed slots`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-1.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/storage.test.ts::storage::import/export (TDD)::should export accounts to a file`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-1.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/storage.test.ts::storage::import/export (TDD)::should import accounts from a file and merge`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-1.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/storage.test.ts::storage::import/export (TDD)::should preserve distinct accountId plus email pairs during import`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-1.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/storage.test.ts::storage::import/export (TDD)::should preserve distinct shared-accountId imports when the imported row has no email`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-1.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `test/storage.test.ts::storage::import/export (TDD)::should preserve duplicate shared accountId entries when imported rows lack email`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [fs] before the test started: run input file:<tmp>/.codex/accounts.json differs: "stat:missing" vs <not recorded>; also differ: file:<tmp>/.codex/auth.json
* first differing event: {"t": 0, "s": "other", "o": "input.file:<tmp>/.codex/accounts.json", "at": "<run>", "v": "stat:missing"} vs null
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/final/codex-multi-auth/repro/shuffle-1.raw.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/568516dc-247a-56de-93e9-0fa8d2081b5c/scratchpad/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

