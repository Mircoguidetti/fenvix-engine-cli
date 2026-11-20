# ND1 notes: Node back-end part 1 (packaging, Node versions, module systems / TypeScript, runners + parallelism, package managers / monorepos)

Audited: `/home/user/audit/engine` (branch `claude/release-1`), installed detjs at `/home/user/audit/build/opt/node`.
Scratch: `/home/user/audit/work/ND1/` (projects, `gen.js`, `battery.sh`, `matrix.sh`, logs in `logs/`).
Gaps: `/home/user/audit/findings/ND1.gaps.jsonl` (86 entries; source `work/ND1/gaps.txt`, built by `work/ND1/build-gaps.js`).

**The run was cut short by a budget stop.** What was executed: packaging / CLI checks, the Node version x Vitest/Jest
matrix (28 batteries), nothing else. Everything in sections 3-5 that says "not checked" was prepared (projects exist in
the scratch folder) but never run. Entries with `how: READ` or `DOC` in the gaps file were not confirmed by a run.

Battery (one per cell, `work/ND1/battery.sh`): plain run; `--det` twice + `detjs verify`; `--det-seed=7` twice +
verify, `--det-seed=8`; `--det-cache` twice, then a change to `src/helper.js` and a third cache run. Project: 7 test
files / 25 tests (3 "basic" files: Date.now, new Date, Math.random, setTimeout 300 ms, fs.readdirSync, an order
dependency between two tests, an import of `src/helper` or `src/other`; `net`: http server on 127.0.0.1 + fetch;
`ord1..3`: a file each test file appends to and reads, i.e. an order dependency between files).

## 1. Node version x result (RAN)

"ok" = `--det` twice gives the same printed values and `detjs verify` says `covered by Level 0: 25 not covered: 0`;
seed 7 twice identical and different from the fixed order; cache: second run `reused 21 tests in 3 files` (the net
file and the 3 cross-file files are never cached, by rule), after the change of `src/helper.js` `reused 7 tests in 1
files` (only the file that does not import it).

| Node | addon loads (N-API reported) | Vitest | Jest |
|---|---|---|---|
| 16.20.2 | yes (napi 8) | 0.34.6: refused "no parseCLI (need vitest >= 1.4)" (ND1-021). 1.6.1: Vitest itself does not start on Node 16 | 29.7.0: ok. 27.5.1: ok. (1 of 25 fails with and without detjs: no global `fetch` on Node 16, my test.) 30.5.2: Jest itself does not run on 16 |
| 18.20.8 | yes (napi 9) | 3.2.7: ok. 1.6.1: **not checked** (plain run fails here: `--use-openssl-ca is not allowed in NODE_OPTIONS` for worker threads, an artifact of this container). 4.1.12: Vitest itself does not run on 18 | 30.5.2: ok. 29.7.0: ok |
| 20.20.2 | yes (napi 9) | 5.1.1: ok (outside Vitest's declared engines, ran anyway). 4.1.12: ok. 3.2.7: ok | 30.5.2: ok. 29.7.0: ok |
| 22.23.5 | yes (napi 10) | 5.1.1: ok. 4.1.12: ok. 3.2.7: ok. 2.1.9: ok. 1.6.1: ok. 0.34.6: refused (ND1-021) | 30.5.2: ok. 29.7.0: ok. 28.1.3: ok. 27.5.1: ok (1 of 25 fails with and without detjs: my fetch test under Jest 27) |
| 24.22.3 | yes (napi 10) | 5.1.1: ok. 4.1.12: ok | 30.5.2: ok. 29.7.0: ok. 27.5.1: ok (same 1 failure with and without detjs) |

Addon: built with napi-rs 3, feature `napi6` (`crates/detpy-node/Cargo.toml:15`); needs glibc >= 2.34 (ND1-011).
The printed values were identical across Node 18-24 and across Vitest 1-5 (digest `5762e15c`) and across Jest 28-30
(`5f19b41e`): the virtual clock, the seeds and the order do not depend on the Node or runner version on this project.
Not run on any Node version: Mocha, node:test, AVA, tap, uvu, Jasmine (other versions than 22 were never started for
them; on 22 they were not started either, see section 4).

## 2. Packaging and first use (RAN / READ)

| item | result | gap |
|---|---|---|
| npm package | none: `detjs`, `fenvix`, `@fenvix/detjs`, `@fenvix/cli`, `detpy`, `fenvix-detjs` all E404; names free | ND1-001, 002, 003 |
| package.json | name `detjs`, version 0.1.0, `private: true`, `bin: {detjs: bin/detjs.js}`, `main: src/index.js` (missing), no `engines`/`os`/`cpu`/`files`/`optionalDependencies` | ND1-004, 005, 006 |
| addon lookup | `$DETJS_NATIVE`, then `node/detjs.<platform>-<arch>.node`, then `../target/{release,debug}/libdetpy_node.so`; else "native core not found (run `npm run build` in node/)" | ND1-007..011 |
| platforms built | linux-x64 glibc only | ND1-007 (arm64), 008 (macOS), 009 (Windows), 010 (musl), 011 (old glibc) |
| CLI | `--help`/`-h`/`--version` => usage, rc 2; unknown runner => usage; errors as stack traces | ND1-012..015 |
| config | no config file, no package.json key; only `DETJS`, `DETJS_SEED`, `DETJS_CACHE_DIR` read from the environment by the wrapper | ND1-016 |
| plugin / reporter / environment integration | none; wrapper CLI only; `npm test -- --det` is rejected by Vitest ("Unknown option `--det`") and Jest ("Unrecognized option det") | ND1-017, 018 |
| CI gate | Linux x64, Node 22 only | ND1-019 |
| state | `.detjs/` in cwd, `node_modules/.detjs/` shim, `~/.cache/fenvix/runtime-memo-node-<uid>.json`; no .gitignore | ND1-020 |
| runner resolution | `createRequire(<cwd>/noop.js)`: the project's own vitest/jest/mocha from cwd upward; pnpm strict and Yarn PnP **not checked** | ND1-064 (READ) |

## 3. TypeScript toolchain x det / source map / cache: NOT RUN

Projects were generated (`work/ND1/tsj` Jest with ts-jest isolatedModules on/off, babel-jest + preset-typescript,
@swc/jest; `tsm` Mocha CJS with ts-node, tsx, @swc-node/register, esbuild-register; `tsme` Mocha ESM; `tsn` node:test;
`tsv` Vitest; `tsb` Bun; `tsd` Deno). `src/helper.ts` has 5 lines of types before the code, so the right site of the
clock read is `src/helper.ts:8`. None of them was executed.

| toolchain | `--det` works | site = original `.ts` path and line | cache sees .ts / tsconfig / babel / swc / paths / .env |
|---|---|---|---|
| tsc pre-compiled (dist/*.js + maps) | not checked | not checked | not checked |
| ts-node CJS (`-r ts-node/register`) | not checked (gate test `runner-mocha.test.js` "--require ts-node/register: tsconfig change" exists) | not checked | not checked |
| ts-node ESM loader | not checked | not checked | not checked |
| tsx | not checked (gate tests "--import tsx: tsconfig paths retargeted" for Mocha and node:test exist) | not checked | not checked |
| @swc/jest | not checked | not checked | not checked |
| @swc-node/register | not checked (gate test for Mocha exists) | not checked | not checked |
| esbuild-register | not checked (gate test for Mocha exists) | not checked | not checked |
| babel-jest + preset-typescript | not checked | not checked | not checked |
| ts-jest isolatedModules on / off | not checked | not checked | not checked |
| Vitest built-in esbuild / oxc | not checked | not checked | not checked |
| Node 22/24 type stripping | not checked (gate test "type stripping: a .ts test and the .ts module it imports" exists) | not checked | not checked |
| Bun native TS | not checked | not checked | not checked |
| Deno native TS | not checked | not checked | not checked |

Read only: sites come from the test realm's `Error` stack (`node/src/sites.js` `resolveFormatted`), "which Vitest
and Jest source-map"; for runners where nothing installs source-map support the site would be the executed file.
Configuration files (`tsconfig*`, babel, `.swcrc`, `.env*`, ...) are keyed by bytes for the whole tree below cwd
(`node/src/cache/proof.js:35,88-106`): coarse (ND1-086) and limited to cwd downward (see "Could not check").
Module systems (CJS, ESM `type: module`, .mjs/.cjs, dual packages): the Jest projects of the matrix are CommonJS, the
Vitest projects ESM (`type: module`); nothing else was run (Jest native ESM with `--experimental-vm-modules`, .mjs /
.cjs mixes, dual packages: not checked).

## 4. Runner x det / seed / cache / parallel (for ND2)

RAN = I ran it. READ = from the code. DOC = only the engine's docs say so. "not checked" = prepared, not run.

| runner (version) | `--det` twice identical | `--det-seed` | `--det-cache` reuse / invalidation | parallel under `--det` | `--det-cache` parallel | notes / gaps |
|---|---|---|---|---|---|---|
| Vitest 5.1.1 / 4.1.12 / 3.2.7 / 2.1.9 / 1.6.1 | RAN ok (Node 18-24, table 1) | RAN: files and tests shuffled, same seed = same order and fingerprints, seed printed in the header; replay command: none printed (ND1-038, READ) | RAN: reuse 21/25, change of an imported file reruns its importers only | **absent**: forced `fileParallelism: false`, `maxWorkers: 1`, `maxConcurrency: 1` (RAN header; ND1-022, 023) | **no** (RAN header; ND1-024) | vmThreads/vmForks not controlled (ND1-060 READ), isolate:false not cached (061), custom runner replaced (062), watch silently off (063). Pools threads/forks, `--shard`, workspaces/projects, fake timers: not checked |
| Vitest 0.34.6 | refused (RAN, ND1-021) | - | - | - | - | |
| Jest 30.5.2 / 29.7.0 / 28.1.3 / 27.5.1 | RAN ok (Node 16-24, table 1) | RAN: as Vitest | RAN: as Vitest | **absent**: forced `--runInBand --maxConcurrency=1` (RAN header; ND1-025, 026) | **no** (RAN; ND1-027) | `--forceExit` always added (ND1-028 RAN). setupFiles real globals (065), jest-jasmine2 (066), legacy fake timers (067), custom runner (068), globalSetup after decision (069): READ/DOC, not checked. `--shard`, projects, workerThreads, `--watch`, custom testEnvironment, `--detectOpenHandles`, fake timers: not checked |
| Mocha 12.0.3 (installed in `pm`) | not checked | not checked (READ: files, suites and tests shuffled) | not checked | **absent** (READ: `--parallel`/`--jobs` deleted, note printed; ND1-029) | no (READ: one fresh process per file, one at a time) | false failure under `--det-cache` for cross-file state (ND1-042 DOC), setup runs per file (048), reporters (049), two order digests (050) |
| node:test (Node 22.23.5) | not checked | not checked (READ: files; tests only on Node >= 22.15, ND1-058) | not checked | **absent** (READ: `--test-concurrency` ignored, concurrency 1; ND1-030) | no | isolation=none overridden under cache (047), watch refused / global setup uncacheable (059). `--test-shard` implemented (READ `nodetest/cli.js:154-159`), `mock.timers`: not checked |
| AVA 8.4.0 | not checked | not checked (READ: files + tasks shuffled) | not checked | **absent** (READ: `--concurrency=1 --serial`; ND1-031) | no | AVA <= 5 unsupported (054 DOC), shared workers / tsx first run not cached (055 DOC) |
| tap 21.8.1 | not checked | not checked (READ: file order only; no shuffle inside a file, ND1-051) | not checked | **absent** (READ: `--jobs=1`; ND1-032) | no | tap <= 16 refused (052), before/after scripts, coverage off (053) |
| uvu 0.5.6 | not checked | not checked (READ: files, suites, tests shuffled) | not checked | uvu has none; under cache one process per file (ND1-036) | no | false failure under cache (044 DOC), direct `node test.js` not covered (057) |
| Jasmine 7.0.0 | not checked | not checked (READ: `random` off, detjs shuffle through `orderChildren`) | not checked | **absent** (READ: `--parallel=` removed with a note; ND1-033) | no | false failure under cache (043 DOC), other jasmine-core builds keep declaration order (056) |
| Bun test 1.4.4 | not checked | not checked (READ: file order by detjs, inside a file Bun's `--randomize --seed=<derived>`; user `--seed`/`--randomize` refused) | not checked | **absent** (READ: one process per file, `--max-concurrency=1`; ND1-034) | no | false failure under `--det` for cross-file globals (045 DOC), no record/replay (070), per-test outcome in trace can be wrong (071 DOC). `--parallel`, `--isolate`, `--shard`, `--rerun-each`, `--bail`: not checked |
| Deno test 2.9.6 (installed with `npm i deno` in `pd`) | not checked | not checked (READ: Deno `--shuffle=<derived>`; user `--shuffle`/`--seed` refused) | not checked | **absent** (READ: `--parallel` refused; ND1-035) | no | false failure under `--det` (046 DOC), `--shard` unhandled (072 READ) |
| tape, QUnit | `detjs tape` / `detjs qunit` => usage rc 2 (RAN; ND1-073, 074) | missing | missing | missing | missing | |
| zora, Lab, Japa, Cucumber.js, Stryker, tsd / vitest typecheck | no shell (READ dispatch list; ND1-075..080) | missing | missing | missing | missing | |
| Playwright Test | `detjs playwright test` => usage rc 2 (RAN; ND1-081); measured-only preload J11 | missing | missing | missing | missing | FE agent covers the browser |
| Cypress, Karma, WebdriverIO | `detjs cypress run` => usage rc 2 (RAN); Karma / WebdriverIO: no shell (READ) | missing | missing | missing | missing | FE agent covers them |

How much slower serial is: only the 7-file project was timed (ND1-037: MEASURED, NOISY, machine load about 28): plain
vs `--det` wall time 1.9 s vs 4.7-5.5 s (Vitest 4, Node 22), 6.6 s vs 7.4-8.2 s (Vitest 5, Node 24), 2.7 s vs 4.4-4.5 s
(Jest 29, Node 22), 3.9 s vs 4.7-5.5 s (Jest 30, Node 24). The 40-file measurement the task asked for was not done.
Sharding across CI jobs: not checked for any runner (READ: Vitest and Jest keep the runner's own shard step and treat
`shard` as a selection key outside the configuration digest; node:test shard reimplemented; Deno unhandled).

## 5. Package manager / monorepo x result: NOT RUN

Prepared in the scratch folder, never executed: `mono-npm` (npm workspaces, Jest, `@m/app` depends on `@m/lib`, lib
depends on `is-number@6.0.0` with a test that fails if the major changes), `mono-pnpm` (pnpm workspace, Vitest, strict
symlinked store), `mono-yarn1` (Yarn classic workspaces), `mono-berry` (Yarn 4.18.1 Plug'n'Play, taken from the npm
package `@yarnpkg/cli-dist`; corepack download was refused by the proxy).

| tool | from the root | per package | through the task runner | cross-package source change seen | lockfile / node_modules as inputs (dependency bump) |
|---|---|---|---|---|---|
| npm workspaces | not checked | not checked | not checked | not checked | not checked |
| pnpm workspaces | not checked | not checked | not checked | not checked | not checked |
| Yarn classic workspaces | not checked | not checked | not checked | not checked | not checked |
| Yarn berry PnP | not checked | not checked | not checked | not checked | not checked (READ: `.yarn/cache` zips and `.pnp.cjs` are not keyed, ND1-084) |
| Nx (`nx test`, `nx affected`) | not checked | not checked | not checked | not checked | not checked |
| Turborepo (`turbo run test`) | not checked | not checked | not checked | not checked | not checked |
| Lerna | not checked | not checked | not checked | not checked | not checked |
| Rush | not checked | not checked | not checked | not checked | not checked |
| Bazel rules_js | not checked (not reasoned either) | | | | |
| Vitest workspace / `projects` | not checked (gate test `node/test/projects.test.js` exists) | | | | |
| Jest `projects` | not checked (gate test in `node/test/cache.test.js:508` exists) | | | | |

Read only: lockfiles are looked up in cwd only (ND1-085); every file under every `node_modules` of cwd and of its
ancestors is hashed into the runtime identity (`runtime-id.js` `packageRoots`), links leaving the project followed.

## Not covered (exact list, for the session that finishes this)

- **Node versions**: Mocha, node:test, AVA, tap, uvu, Jasmine on 16/18/20/24; Vitest 1.6.1 on Node 18 (blocked here by
  NODE_OPTIONS of the container: rerun with `NODE_OPTIONS=` cleared); Vitest 1.4-1.5, 2.0, 3.0-3.1, 4.0 point versions.
- **Module systems**: Jest native ESM (`--experimental-vm-modules`), `.mjs`/`.cjs` mixes, dual packages, Mocha ESM.
- **TypeScript**: every row of table 3 (det, source-mapped sites, cache inputs incl. tsconfig `paths`, babel config,
  `.swcrc`, `.env`).
- **Runners (never started under detjs)**: Mocha, node:test, AVA, tap, uvu, Jasmine, Bun test, Deno test (projects
  `pm pn pa pt pu pjas pb pd` are generated and installed); Jest 27/28 specifics (jest-jasmine2 default in 26);
  unsupported-runner messages for zora, Lab, Japa, Karma, WebdriverIO, Cucumber.js, Stryker, tsd (only read).
- **Parallel options (none executed)**: Vitest `--pool threads|forks|vmThreads|vmForks`, `poolOptions`,
  `fileParallelism`, `maxWorkers`, `--shard`, `sequence.concurrent`, `test.concurrent`, `describe.concurrent`,
  workspaces/projects; Jest `--maxWorkers`, `--shard`, `workerThreads`, `test.concurrent`, projects, `--watch`,
  jest-light-runner, jest-circus vs jest-jasmine2, custom `testEnvironment`, `globalSetup`, `setupFiles`,
  `--detectOpenHandles`, `jest.useFakeTimers` modern/legacy and `vi.useFakeTimers` on the virtual clock (projects `fv`
  and `fj` are written, incl. a "rendezvous" pair of concurrent tests that needs real concurrency: expected to time out
  under `maxConcurrency=1`, a possible false failure, NOT verified); Mocha `--parallel`/`--jobs`, root hooks,
  `.mocharc`; node:test `--test-concurrency`, `--test-shard`, `--test-isolation`, `describe`/`it` concurrency,
  `mock.timers`; AVA `--concurrency`, `--serial`, worker threads; tap `--jobs`; Jasmine `--parallel`, `random`/`seed`;
  Bun `--concurrent`, `--seed`, `--rerun-each`, `--bail`, `--parallel`, `--isolate`, `--shard`; Deno `--parallel`,
  `--shuffle`, `--shard`. The 40-file slowdown measurement.
- **Seeds**: behaviour on a failing test (what is printed, whether a usable replay command exists) was never run.
- **Package managers / monorepos**: every row of table 5; local install of detjs inside a project (`npm i -D <dir>`),
  pnpm strict resolution of the runner, Yarn PnP.

## Could not check (suspicions, not gaps)

- **Configuration above cwd (possible wrong reuse).** `configFiles()` scans from cwd downward
  (`node/src/cache/proof.js:88-106`). A per-package run in a monorepo whose behaviour depends on a root-level
  `tsconfig.base.json` (via `extends`), `babel.config.js` (`rootMode: upward`) or `.env` is keyed only if the capture
  sees the read some other way (in-band Babel reads under Jest probably are; Vite's own tsconfig reads in the main
  process "are not inputs" per docs/NODE-CACHE.md). Test to run: `packages/a/tsconfig.json` extends
  `../../tsconfig.base.json`, flip `useDefineForClassFields` there, class field test; expect a rerun.
- **Dependency bump in a workspace** (is-number 6.0.0 -> 7.0.0 in `mono-*`): must rerun `lib` and `app` tests; a reuse
  would be WRONG-RESULT. Not run.
- **Turborepo strict env mode**: `DETJS=1 turbo run test` probably never reaches the task (`DETJS*` not in
  `env`/`passThroughEnv`); and `.detjs/` written into each package is an untracked, un-ignored file that changes
  Turbo's and Nx's input hash every run. Not run.
- **Bun `--shard` / `--parallel` / `--isolate`**: `--shard` is passed to discovery and again to every one-file process
  (`bun.js` runOptions); `--parallel`/`--isolate` (Bun 1.4 flags) are in none of detjs' tables. Effect unknown.
- **Jest `--watch` under `--det`**: not refused in `jest/cli.js` (Mocha, node:test, Bun, Deno refuse it). Unknown.
- **Compiled-JS sites**: with tsc-precompiled tests the trace site is probably `dist/x.js:line`, against
  ARCHITECTURE.md ("never the compiled .js"). Not run.
- **Docker** (Alpine/musl, Debian 11 glibc 2.31 load errors): not tried; ND1-010 and ND1-011 are from `ldd`/`objdump`.
- **macOS / Windows**: no access; from code only.
- Yarn berry through corepack: download refused by the proxy (worked around with `@yarnpkg/cli-dist`).

## Things the lead should know

- `AI_AGENT` in this container's environment makes Jest 30 and Vitest 5 switch to a terse reporter (no console
  output of passing tests); the battery unsets it. Anyone comparing outputs here should do the same.
- npm 10.9.9 crashes ("Cannot read properties of null (reading 'edgesOut')") when vitest and jest are installed in one
  package.json here; separate projects were used.
- docs/NODE.md title and package.json description still say "for Vitest and Jest" while 10 runners are dispatched.
- The engine's own docs record the false failures of the per-file process model (Mocha/Jasmine/uvu under
  `--det-cache`, Bun/Deno under `--det`) as "limits" with a counting test; I listed each as DECIDE with severity
  WRONG-RESULT, `how: DOC` (not re-run).
- Background runs of mine were stopped (`pkill` of `matrix.sh`/`battery.sh`); nothing of mine is still running.

## Evidence appendix (commands and trimmed outputs)

- ND1-001/002/003: `npm view detjs name version` => `npm error 404 Not Found - GET https://registry.npmjs.org/detjs`;
  same for `fenvix`, `@fenvix/detjs`, `@fenvix/cli`, `detpy`, `fenvix-detjs`.
- ND1-004/005: `cat node/package.json`; `ls node/src/index.js` => No such file; `npm pack --dry-run` on a copy
  (`work/ND1/node-copy`, `private` removed) => `total files: 86`, `package size: 250.1 kB`, lists `test/*.test.js`.
- ND1-010/011: `ldd build/opt/node/detjs.linux-x64.node` => libgcc_s.so.1, libc.so.6, /lib64/ld-linux-x86-64.so.2;
  `objdump -T ... | grep -o 'GLIBC_[0-9.]*' | sort -V | tail -1` => `GLIBC_2.34`.
- ND1-012..015: `detjs --help|-h|--version|-v|help|playwright test|tape|cypress run|qunit` => the 3 usage lines, rc 2;
  `detjs vitest --det --det-foo` => `Error: detjs: unknown option --det-foo` + option list, rc 2;
  `detjs jest --det-seed=abc` => `Error: detjs: bad integer "abc"\n    at Object.int (.../src/config.js:18:43)`.
- ND1-017/018: in `pv`: `npm test -- --det` => `CACError: Unknown option \`--det\``; in `pj`: `Unrecognized option
  "det". Did you mean "e"?`; `DETJS=1 npx vitest run | grep -c detjs` => 0.
- ND1-021: `logs/matrix-n22-pv0.txt`, `logs/matrix-n16-pv0.txt`.
- ND1-022..028, 037, 039..041: `logs/matrix-n<node>-<project>.txt` (one line per step) and the full logs and traces
  in `logs/bat-n<node>-<project>/` (`base.log`, `det1.log`, `det2.log`, `seed7a.log`, `cache1..3.log`, `*.trace`).
  Example (`pv`, Vitest 5.1.1, Node 22): `[verify det1 det2] rc=0 ... covered by Level 0: 25 not covered: 0 missing: 0
  outcome-unstable: 0`; `[cache2] detjs cache: reused with proof 21 tests in 3 files ...; ran 4 files ... not cached:
  network connection 2, reads a file another test file or the start-up code wrote 6`; `[cache3 after change of
  src/helper.js] reused with proof 7 tests in 1 files; ran 6 files; recorded 14 tests`.
- Addon per Node: `nodes/n<v>/bin/node -e "require('/home/user/audit/build/opt/node/src/native.js')"` => 37 exports on
  v16.20.2 (napi 8), v18.20.8 (9), v20.20.2 (9), v22.23.5 (10), v24.22.3 (10).
- Trace sample (site format): `{"t":0,"s":"time","o":"Date.now","at":"src/helper.js:3","v":"3000"}` (`pv/.battery/det1.trace`).
