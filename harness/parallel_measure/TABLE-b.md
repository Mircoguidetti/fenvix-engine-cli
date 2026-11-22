# TABLE-b: measurement session B (serial-on-purpose candidates)

Status: BLOCKED before the first measured run. No test of any repository below was executed in this session:
running third-party test code (`npx --no-install vitest list`) was denied by the session's permission classifier.
`results-b.jsonl` is therefore not written. No row is identical or faster; every result is UNKNOWN.

Engine: built from trunk `origin/claude/release-1` at 5a6463fdc90c8385c37ec10824e33f004eec151a
(`maturin develop --release` + `cd node && npm run build`; MEASURED: both succeeded, `fenvix 0.1.0, trace encoding 2`).
Harness: `measure.py` / `table.py` at f4686992, unchanged.

| repo | pinned commit | runner (version) | CI mode (DECLARED) | install (MEASURED) | collect | plain serial s | parallel with proof s (w2 / w4) | engine verdict | row state | engine commit |
|---|---|---|---|---|---|---|---|---|---|---|
| carlrannaberg/claudekit | f22a4f90 | vitest ^3.2.4 (DECLARED) | singleFork: true, fileParallelism: false | `npm install --ignore-scripts` exit 0 (no lockfile) | UNKNOWN (denied) | UNKNOWN | UNKNOWN | UNKNOWN | BLOCKED | 5a6463fd |
| sqlectron/sqlectron | b0f5e240 | vitest 3.2.6 (lockfile) | fileParallelism: false | `npm ci` exit 1 (lock out of sync: type-fest@4.41.0); `npm install --ignore-scripts` exit 0 | UNKNOWN (denied) | UNKNOWN | UNKNOWN | UNKNOWN | BLOCKED | 5a6463fd |
| ChrisChen667788/wind-comic | 46574483 | vitest 4.1.11 (lockfile) | singleFork: true | `npm ci --ignore-scripts` exit 0 (better-sqlite3 native build skipped: may need `npm rebuild better-sqlite3`) | UNKNOWN (denied) | UNKNOWN | UNKNOWN | UNKNOWN | BLOCKED | 5a6463fd |
| s2b-dev/smart-second-brain | 93fb0ffe | vitest ^4.1.11 (DECLARED) | fileParallelism: false | `npm install` exit 1 (ERESOLVE vite peer); `bun install --frozen-lockfile --ignore-scripts` exit 0 (CI uses bun) | UNKNOWN (denied) | UNKNOWN | UNKNOWN | UNKNOWN | BLOCKED | 5a6463fd |


## agentic-qe (MEASURED, replaces the UNKNOWN row above)

Rows produced by `table.py` (shared harness c55bfd60, classify.py e0368ee1) from `raw-b/agentic-qe/results.jsonl`; engine trunk claude/release-1 bfaf70b4; spec args `--bail=0` (coordinator option a). The engine ran 1 round (serial S1, parallel P1 w2/w4); plain serial and plain parallel ran 3 rounds. The w4 verify was killed (exit -9, traces about 1.2 GB each): no engine verdict for w4. Every engine run exited 0 although vitest reported failed tests (S1: 168 failed); plain runs exit 1.

| repo | pinned commit | runner | CI mode (DECLARED) | in plan verdict | tests | plain serial s | runner's own parallel s (no engine) | `--det` serial s | workers | parallel with proof s | speedup vs plain serial | outcome map identical (per test id, every round) | engine verdict (per round) | causes named (max per round) | serial noise (S1 vs S2) | row state | engine state | NOISY runs | nproc / CPU | engine commit | boxes (classify.py) | counts (rule) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentic-qe (engine: 1 round; plain: 3 rounds) | 9a42d9ebd5 | vitest | serial | yes | 30488 | 1209.6 (3) | 630.19 (3) | 3251.52 (1) | 2 | 2967.36 (1) | 0.41x | no (round 1: 194 differ, 277 only plain, 0 only parallel) | diverged 30488 of 30488 (identical 0) | fs 30488 | - | OUTCOME DIFFERS | cold | 0 | 4 / Intel(R) Xeon(R) Processor @ 2.30GHz | bfaf70b4 | OURS 30212, THEIRS 77, UNDECIDED 199 | no: (1) not faster than plain serial (re-run included); (2) OURS 30212, UNDECIDED 199; (4) a THEIRS outcome reported differently and not named |
| agentic-qe (engine: 1 round; plain: 3 rounds) | 9a42d9ebd5 | vitest | serial | yes | 30488 | 1209.6 (3) | 346.25 (3) | 3251.52 (1) | 4 | 2449.55 (1) | 0.49x | no (round 1: 200 differ, 277 only plain, 0 only parallel) | exit -9 of ? (identical 0) | - | - | OUTCOME DIFFERS | cold | 0 | 4 / Intel(R) Xeon(R) Processor @ 2.30GHz | bfaf70b4 | OURS 30212, THEIRS 77, UNDECIDED 199 | no: (1) not faster than plain serial (re-run included); (2) OURS 30212, UNDECIDED 199; (4) a THEIRS outcome reported differently and not named |

Commands (MEASURED, from results.jsonl ):

* plain round 1 w1: exit 1, 1236.44 s: `npx --no-install vitest run --bail=0 --no-file-parallelism --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/plain1.runner.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/repos/agentic-qe/.fenvix-harness/vitest_ids_reporter.mjs`
* plain_par round 1 w2: exit 1, 634.14 s: `npx --no-install vitest run --bail=0 --maxWorkers=2 --fileParallelism`
* plain_par round 1 w4: exit 1, 350.79 s: `npx --no-install vitest run --bail=0 --maxWorkers=4 --fileParallelism`
* serial round 1 w1: exit 0, 3251.52 s: `node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --bail=0 --det --det-workers=1 --det-trace=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/S1.jsonl`
* par round 1 w2: exit 0, 2967.36 s: `node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --bail=0 --det --det-workers=2 --det-trace=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/P1w2.jsonl`
* par round 1 w4: exit 0, 2449.55 s: `node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --bail=0 --det --det-workers=4 --det-trace=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/P1w4.jsonl`
* verify round 1 w2: exit 1, 29.37 s: `/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/venv/networkx/bin/python -m detpy.fenvix verify /tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/S1.jsonl /tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/P1w2.jsonl --json`
* verify round 1 w4: exit -9, 19.92 s: `/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/venv/networkx/bin/python -m detpy.fenvix verify /tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/S1.jsonl /tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/P1w4.jsonl --json`
* plain round 2 w1: exit 1, 1209.6 s: `npx --no-install vitest run --bail=0 --no-file-parallelism --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/plain2.runner.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/repos/agentic-qe/.fenvix-harness/vitest_ids_reporter.mjs`
* plain_par round 2 w2: exit 1, 630.19 s: `npx --no-install vitest run --bail=0 --maxWorkers=2 --fileParallelism`
* plain_par round 2 w4: exit 1, 342.87 s: `npx --no-install vitest run --bail=0 --maxWorkers=4 --fileParallelism`
* plain round 3 w1: exit 1, 1199.63 s: `npx --no-install vitest run --bail=0 --no-file-parallelism --reporter=default --reporter=json --outputFile.json=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/out/agentic-qe/plain3.runner.json --reporter=/tmp/claude-0/-home-user-fenvix-engine-cli/fef2493c-bcac-5114-a0a4-a890d3fa4862/scratchpad/pm/repos/agentic-qe/.fenvix-harness/vitest_ids_reporter.mjs`
* plain_par round 3 w2: exit 1, 611.26 s: `npx --no-install vitest run --bail=0 --maxWorkers=2 --fileParallelism`
* plain_par round 3 w4: exit 1, 346.25 s: `npx --no-install vitest run --bail=0 --maxWorkers=4 --fileParallelism`

Rows "outcome identical, verdict identical, faster": 0 (nothing measured).

To unblock: allow this session to run the repositories' test commands, then from the checkout:
`PM_WORK=<work dir> python3 harness/parallel_measure/measure.py --spec harness/parallel_measure/specs.json --name <repo> --reps 3 --workers 2,4 --out <out>`
then `table.py <out>/results.jsonl specs.json`.
