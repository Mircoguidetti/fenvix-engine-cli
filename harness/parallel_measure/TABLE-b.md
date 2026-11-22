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
| proffesor-for-testing/agentic-qe | 9a42d9eb | vitest 5.0.5 (lockfile) | fileParallelism: false | `npm ci --ignore-scripts` exit 0 | UNKNOWN (denied) | UNKNOWN | UNKNOWN | UNKNOWN (Vitest 5: expect diverged [deps] on 5a6463fd, `.vitest-cache` bug; re-measure after the trunk fix) | BLOCKED | 5a6463fd |
| s2b-dev/smart-second-brain | 93fb0ffe | vitest ^4.1.11 (DECLARED) | fileParallelism: false | `npm install` exit 1 (ERESOLVE vite peer); `bun install --frozen-lockfile --ignore-scripts` exit 0 (CI uses bun) | UNKNOWN (denied) | UNKNOWN | UNKNOWN | UNKNOWN | BLOCKED | 5a6463fd |

Rows "outcome identical, verdict identical, faster": 0 (nothing measured).

To unblock: allow this session to run the repositories' test commands, then from the checkout:
`PM_WORK=<work dir> python3 harness/parallel_measure/measure.py --spec harness/parallel_measure/specs.json --name <repo> --reps 3 --workers 2,4 --out <out>`
then `table.py <out>/results.jsonl specs.json`.
