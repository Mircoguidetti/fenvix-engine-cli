# All runners, builder node-a: `node --test` and Mocha

Branch `ar-node-a` (based on `claude/node-cache-proof`). Labels: **MEASURED** (this container, Node 22.23.5, 4
CPUs shared with other agents: every timing is NOISY), **ESTIMATED**, **DECLARED**, **UNKNOWN**. Runner documents:
[node-test.md](node-test.md), [mocha.md](mocha.md).

## `node --test` (`detjs node-test`)

| item | result |
|---|---|
| support | **det + skip**: `--det`, `--det-seed`, `--det-cache` (unit = test file, process per file), `--det-cache-verify`, receipts, summary, trace; `--test-isolation=none` (one process under `--det`; one process per file under `--det-cache`); reporters, patterns, shards, `--import`/`--require`/`--env-file`/`--conditions`, type stripping, tsx, ts-node, `mock.module`, snapshots |
| control tests | `node/test/runner-node-test.test.js`, 6 of 6 pass (MEASURED): two `--det` runs identical fingerprints and order (27 tests, 3 files); seed 11 twice identical, seed 12 another order; virtual clock at the epoch, seeded `Math.random`, closed network inside the test processes (and the clock test fails without detjs); isolation=none vs per-file processes: 1 test whose outcome changes (`b sees a`), counted; verify mode; every file reused = exit 0 with the junit reporter still writing; reporter locations point at the test file |
| adversarial tests | 45 of 45 pass (MEASURED). r021: content, F1a size, F1b realpath, F1c lstat, F2a recursive readdir, F2b withFileTypes, existence, F3a openAsBlob, F3b loadEnvFile, F3c sqlite, F4 cpSync, F5 ESM + CJS optional modules, F8 outside dir via an INFRA library after await, held: after() hook, held: globSync. Environment/processes/R-009/R-017: env read, env name `constructor`, env enumeration, TZ, child process, loopback socket, file written by another test file, mtime, `wx` create, non-recursive mkdir, read in `process.on('exit')`, `.git` read, sqlite `file:` URI, unwrapped `fs` reference from a NODE_OPTIONS preload, real clocks (uptime, timeOrigin, Intl of now), `/dev/shm`, `process.binding`. Runner: `--require` setup, `--import` setup, `--test-name-pattern` selection, `--env-file`, `--conditions`, loader package in node_modules, type stripping, tsx + tsconfig paths, ts-node, `mock.module()`, snapshot file, new test file |
| fail on a naive adapter (MEASURED, by swapping the piece out) | naive node-test adapter (capture closed in an ordinary `exit` listener; NODE_OPTIONS untouched; flag values only in the digest; name patterns treated as selection): **4 fail**: interpreter shutdown, unwrapped read, `--test-name-pattern`, `--env-file`. Base shared capture (`claude/node-cache-proof`, f1c7caf): **4 fail**: `wx` create, non-recursive mkdir, sqlite `file:` URI (single-argument `DatabaseSync` broken by the capture), `process.binding`. New flags by construction (no base run): real clocks, env name `constructor` (crashed the recording on yargs) |
| walk specs | `harness/node_cache/specs/commander.json` (tj/commander.js, `node --test`, process per file, 109 files / 1,430 tests), `simple-statistics.json` (`--experimental-test-isolation=none test/*.test.js`, 83 files / 378 tests); 31 consecutive first-parent commits each (`commits/*-commits.json`, a9bcfdb907..a5a7dc084d and d3e92a67b3..551ad9eebe). Plain runner checked locally: 1,430 / 378 pass |
| local mini-walk | see "Local mini-walks" below |
| not covered, and why | tests that never begin (declared skipped, filtered) are not in trace/receipts (node:test runs no hook for them); `--test-global-setup` runs uncached (outside the capture); Node < 22.15: no facade (fixed order only); bare optional module probes from project code stay not cacheable (shared rule, R-021 F5) |

## Mocha (`detjs mocha`)

| item | result |
|---|---|
| support | **det + skip**: `--det` (Mocha's single process, `--parallel` off), `--det-seed` (files, suites, tests), `--det-cache` (one fresh process per spec file, events replayed into the user's reporter through Mocha's ParallelBufferedRunner), `--det-cache-verify`, receipts, summary, trace; `.mocharc*`, `package.json` `mocha`, `--config`, `MOCHA_OPTIONS`, `--require`, `--file`, root hook plugins, global fixtures, `--grep`, ESM + CJS specs, `--spec` globs, node flags via Mocha's own split; Mocha 11 and 12; ts-node, tsx, @swc-node, esbuild-register |
| control tests | `node/test/runner-mocha.test.js`, 6 of 6 pass (MEASURED): two `--det` runs identical (24 tests, ESM + CJS), seeds reproducible/different, per-file processes give the same tests and fingerprints; Level 0 inside tests; single vs per-file: 1 changed outcome counted; `.mocharc` `parallel: true` off; verify mode + `--fail-zero` with every file reused; global setup per file process, keyed |
| adversarial tests | 41 of 41 pass (MEASURED): the same r021 / R-009 / R-017 set as node-test (CJS and ESM specs), plus `--require` setup, `.mocharc` change, `package.json` `mocha` change, `--file` root hooks, `mochaHooks` plugin, `--grep` selection, new spec matching the glob, ts-node + tsconfig `strict`, tsx + tsconfig paths, @swc-node, esbuild-register |
| fail on a naive adapter (MEASURED) | **3 fail**: interpreter shutdown, unwrapped read (NODE_OPTIONS), `--grep` (selection treated as output). By construction (not run): a single shared process with skipped files changes other files' context (the isolation control shows the outcome change); global setup run in the driver would leak `process.env` it computes into every file process unkeyed |
| walk specs | `specs/dependency-cruiser.json` (sverweij/dependency-cruiser, Mocha 12, `.mocharc.cjs`, ESM, 217 spec files / 2,000 tests; 2 shards), `specs/yargs.json` (yargs/yargs, Mocha 11, `--require ./test/before.mjs`, `tsc` build per commit, 14 files / 844 tests); 31 consecutive first-parent commits each (9d53b95af1..b89a8456fb, 88f548c8c6..9588a76436). Plain runner checked locally: dependency-cruiser 1,997 pass / 3 fail (stdin and locale-dependent tests in this container), yargs 843 pass / 1 pending |
| local mini-walk | see below |
| not covered, and why | under `--det-cache` reporters Mocha refuses with `--parallel` (`progress`, `markdown`, `json-stream`) may misbehave; `--require` modules and global fixtures run once per spec file; test order differs between single process (top-level tests of every file first) and per-file mode; under `--det` Level 0's sorted directory listings fail 3 yargs `commandDir` tests that expect the file system's order (a determinism finding, like the Jest/Vitest shells) |

## Local mini-walks

FILLED_BY_MINIWALK

## Integration notes

* Shared files touched (generic, used by every runner): `node/src/cache/capture.js` (state-dependent write probes,
  `process.binding`, real clocks, sqlite arity, tool caches, tsx relay pipe, esbuild service thread, INFRA list:
  mocha, workerpool, typescript, ts-node, @swc-node, esbuild-register, pirates; `DETJS_DRIVER` includes the new
  shells), `node/src/cache/proof.js` (`captureFilter`, env names on `Object.prototype`, reasons `binding`,
  `clock-real`), `node/src/clock.js` (timeOrigin of other realms reported), `node/src/state.js` (`onRealClock`),
  `node/src/sites.js` (node:test internals are infrastructure; mocha in INFRA), `node/bin/detjs.js` (`node-test`,
  `mocha`), new `node/src/fileproc.js`. `node/package.json` devDependencies: mocha 11, tsx, ts-node, typescript 5,
  esbuild-register, @swc-node/register, @swc/core (fixtures of the tests).
* Suites of the base branch re-run with these changes: see the final message.
* Workflow: `.github/workflows/all-runners-node.yml`, triggered by a push to `claude/all-runners` that changes
  `harness/node_cache/RUN-all-runners` (JSON: `{"label": "...", "repos": ["commander", "simple-statistics",
  "dependency-cruiser", "yargs"], "tests": true, "shards": {"repo": n}, "windows": {"repo": [lo, hi]}}`); results to
  `harness/node_cache/results/<label>/`, tables with `python3 harness/node_cache/aggregate.py <label> --md`.
