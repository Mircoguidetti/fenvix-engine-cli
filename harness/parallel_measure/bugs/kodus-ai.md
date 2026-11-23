# kodus-ai: tests whose outcome changes without the engine (THEIRS)

Repository https://github.com/kodustech/kodus-ai at 8bc021d805313e2d23a4bb4e5fdcd7a6e1eb3fd1; engine verdicts from trunk ['bfaf70b4']. Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.

2 test(s).

## `src/__tests__/worktree-e2e.test.ts::Worktree E2E — hook commands::reports the hook as installed from inside the worktree`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [env] the test read a CI-volatile or proxy environment variable: its value (uncontrolled.env @ src/__tests__/worktree-e2e.test.ts:30) is not controlled by this release, so identical fingerprints are no evidence of an identical execution (uncontrolled: child, env)
* first differing event: {"t": 0, "s": "other", "o": "uncontrolled.env", "at": "src/__tests__/worktree-e2e.test.ts:30", "v": "*"} vs {"t": 0, "s": "other", "o": "uncontrolled.env", "at": "src/__tests__/worktree-e2e.test.ts:30", "v": "*"}
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/kodus-ai/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/kodustech_kodus-ai/apps/cli/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

## `src/__tests__/worktree-e2e.test.ts::Worktree E2E — hook commands::resolves the hooks dir from a nested subdirectory`

* plain runs failed: plain shuffle-1, plain shuffle-2; passed: plain par4-1, plain par4-2, plain serial 1, plain serial 2, plain serial 3
* engine runs: engine P1w2=passed, engine P1w4=passed, engine P2w2=passed, engine P2w4=passed, engine P3w2=passed, engine P3w4=passed, engine S1=passed, engine S2=passed, engine S3=passed
* engine cause (verify1w2.json): [env] the test read a CI-volatile or proxy environment variable: its value (uncontrolled.env @ src/__tests__/worktree-e2e.test.ts:30) is not controlled by this release, so identical fingerprints are no evidence of an identical execution (uncontrolled: child, env)
* first differing event: {"t": 0, "s": "other", "o": "uncontrolled.env", "at": "src/__tests__/worktree-e2e.test.ts:30", "v": "*"} vs {"t": 0, "s": "other", "o": "uncontrolled.env", "at": "src/__tests__/worktree-e2e.test.ts:30", "v": "*"}
* reproduce (plain runner, no engine): `cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=1 --reporter=default --reporter=json --outputFile.json=/home/user/pm/out-c-d13/kodus-ai/repro/shuffle-1.raw.json --reporter=/home/user/pm/fr/kodustech_kodus-ai/apps/cli/.fenvix-harness/vitest_ids_reporter.mjs`
* reproduces: yes (2 of 7 plain runs failed)

