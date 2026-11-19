# Build summary: node-c (Bun `bun test`, Deno `deno test`)

Branch `ar-node-c` (worktree `/tmp/claude-0/wt-node-c`, based on `claude/node-cache-proof`). Local machine: 4 CPUs
shared with other agents, Node 22.23.5, Bun 1.4.4, Deno 2.9.8. Every timing below is **MEASURED, local, NOISY**.

## The hard questions, answered with a running test

| question | answer | evidence |
|---|---|---|
| Can Bun / Deno load the shared core? | **Yes, both.** The detpy-node Node-API addon and the detjs CommonJS modules load unchanged (Deno through `createRequire`). No proof logic is reimplemented: the test process runs the shared controls and capture, the main process (Node) runs `ProofSession`. | every test in `runner-bun.test.js` / `runner-deno.test.js` goes through it |
| Level 0 inside Bun / Deno | Shared controls work unchanged (Date, performance.now, timers, Math.random, crypto); added: `Bun.nanoseconds/sleep/sleepSync/randomUUIDv7`, closed `fetch`, `Bun.connect`, `Deno.connect(Tls)`, `Deno.resolveDns`, `WebSocket`, `Bun.dns`, node:http(s). Order: core shuffle of files, runner's own seeded shuffle (`--randomize --seed`, `--shuffle=`) inside a file with a core-derived seed | control tests below |
| Bun's / Deno's module loaders | Bun: import graph from Bun's own scanner (`Bun.Transpiler#scanImports`) resolved with Bun's resolver (an `onResolve` plugin misses extensionless specifiers, MEASURED). Deno: `deno info --json` graph after the run; non-literal `import()` not cached | adversarial: changed module, shadowing file, optional module appearing, tsconfig paths, import map, lockfile |
| APIs the capture cannot see | Bun: every `Bun.*` API not classified pure is wrapped to make the file not cacheable; non-replaceable properties (`Bun.env`, `import.meta.env`, `Bun.fetch`, `BunFile#lastModified`, `Bun.secrets`) by a source scan of every module loaded. Deno: same for the `Deno` namespace, plus **Deno's own permission audit** (`DENO_AUDIT_PERMISSIONS`) as a completeness check: an access the capture did not see makes the file not cacheable | `the audit cross-check alone catches reads the wrappers miss` |
| Unit of reuse | the test file, one runtime process per file under `--det` and `--det-cache` (bun: all files share one global object; deno: one process, shared env/cwd/files) | `isolation: ... (counted)` tests |

## bun test

| | |
|---|---|
| support | **det + skip** |
| control tests (runner-bun.test.js, `bun: Level 0 controls`) | `two --det runs give identical fingerprints; the controls are active inside bun test` (clock at the epoch, virtual `Bun.sleep`/timers/`performance.now`/`Bun.nanoseconds`, seeded `Math.random`/`crypto`/`Bun.randomUUIDv7` golden-compared, fetch / `Bun.connect` / node:http closed, loopback allowed); `seeded shuffle: same seed same order, another seed another order (files and tests)`; `isolation ... (counted)`: **3/3 pass** |
| adversarial tests (`bun: wrong reuse (--det-cache)`) | 38 tests: reuse works; content via `Bun.file().text()`, `new Response(Bun.file())`, named node:fs import; metadata size (`statSync`, `BunFile#size`), mode, mtime (`lastModified`: never cached); realpath retarget; lstat link→file; listing; recursive listing (`Bun.Glob`); existence (`Bun.file().exists()`); changed import; shadowing `m.tsx` before `m.ts`; optional module via `import()` and `require()`; tsconfig paths; `mock.module` factory target; env single read (process.env, `Bun.env`, `import.meta.env`), enumeration; `.env` loaded by Bun; `Bun.spawnSync`, `Bun.$` (never); `Bun.serve`+fetch (never); TZ; bunfig `[define]`; bunfig preload reads; CLI `--define`; loader (tsconfig jsx factory); file written by another test file (never); snapshot file; `bun:sqlite`; `node:sqlite` (never); unclassified API `Bun.which` (never); failure never reused; verify mode. **38/38 pass** |
| would fail on a naive adapter | run with `DETJS_RUNTIME_NAIVE=1` (shared Node capture only, no Bun wrappers / graph / scan / snapshot): **17 of 41 fail** — 10 WRONG REUSE (Bun.file text, Response(Bun.file), Bun.Glob, exists(), optional `import()`, optional `require()`, Bun.env, import.meta.env, snapshot, bun:sqlite), 6 reused although not keyed (lastModified, Bun.spawnSync, Bun.$, Bun.serve, node:sqlite, Bun.which), 1 no reuse at all (raw TAP: `/tmp/claude-0/scratch-node-c/final/naive-runner-bun.tap`) |
| walk specs | `wouter` (molefrog/wouter, 21 first-parent commits 330cf669..51b55c0, 2026-09-05..09-30, bunfig preload with happy-dom); `json-schema-faker` (21 commits 800c4ae1..92cc30b, 2026-04-07..11-08). Both: root `test` = `bun test` in every commit; no services (checked locally) |
| local mini-walk | json-schema-faker, commits [16:21] (5 commits, 4 transitions): would-reuse 2, 0, 20, 0 of 22 files; test time skipped 1%, 0%, 68%, 0%; **0 wrong** (verified 323 would-be reuses, 0 mismatches); skip run 2.1 s vs verify 6.3 s at the 68% transition. Zero-reuse transitions: a merge touching `src/` (code) and two version bumps of the root package.json (configuration). Raw: `harness/node_cache/results/node-c-local/json-schema-faker-mini.json.gz` |
| other local runs | wouter: cold `--det-cache` 22.2 s (plain `bun test` 1.9 s, one process), warm 1.5 s with 22 of 23 files reused (the 23rd has a non-literal `import()`); json-schema-faker: 20 of 22 reused on an unchanged second run. All MEASURED, local, NOISY |
| outcome changes vs plain `bun test` | wouter 0 (after fixing two Level 0 issues found there, below); json-schema-faker +1 failure (a remote `$ref` blocked by Level 0's closed network, not isolation) |
| not covered and why | see docs/runners/bun.md: a library reading `BunFile#lastModified` without naming `Bun.file`, `Bun.env` through an alias the scan misses (neither can be wrapped in Bun 1.4.4); computed `require()` misses inside installed packages; record/replay of Bun's native connections; per-test outcome of failures only Bun sees (file fails through the exit status) |

## deno test

| | |
|---|---|
| support | **det + skip** |
| control tests (runner-deno.test.js, `deno: Level 0 controls`) | identical fingerprints over two runs (clock, virtual timers, seeded random golden-compared, fetch / `Deno.connect` closed, loopback allowed); seeded shuffle same/different seed; isolation counted (`Deno.env.set` in one file, read in another). **3/3 pass** |
| adversarial tests (`deno: wrong reuse (--det-cache)`) | 33 tests: reuse works; content via `Deno.readTextFile`, `Deno.open`+readable, named node:fs import, `fetch(file:)`; size (`Deno.statSync`); mtime (never); realPath; lstat isSymlink; readDir with entry types; recursive walk; existence (NotFound); changed import; optional module appearing; non-literal `import()` (never); import map in deno.json; lockfile change (reruns); env `Deno.env.get`, process.env, `toObject`; `Deno.Command` (never); `Deno.serve`+fetch (never); TZ; deno.json compilerOptions (loader); CLI `--location`; file written by another test file (never); localStorage (never); node:sqlite (never); audit alone with wrappers off (never); `auditCheck` unit; failure never reused; sanitizer failure; verify mode. **33/33 pass** |
| would fail on a naive adapter | `DETJS_RUNTIME_NAIVE=1` (shared Node capture only: no Deno wrappers, graph or audit): **20 of 36 fail** — 12 WRONG REUSE (readTextFile, open, fetch(file:), statSync size, realPathSync, lstatSync, readDirSync, recursive walk, stat NotFound, optional `import()`, Deno.env.get, toObject), 8 reused although not keyed (mtime, non-literal import, Deno.Command, Deno.serve, written-by-another-file, localStorage, node:sqlite, audit case). Raw: `/tmp/claude-0/scratch-node-c/final/naive-runner-deno.tap` |
| walk specs | `oak` (oakserver/oak, 21 commits f5e53627..9e2ca3c, 2025-07-05..2026-11-03, its own `deno task test` flags); `std` (denoland/std, 21 commits d7afd1a1..f834d022, 2026-09-17..09-25, ten packages: collections semver text path encoding async fs dotenv ini csv, 203 files). No services (checked locally) |
| local mini-walk | oak, commits [17:21] (4 commits, 3 transitions): would-reuse 14, 15, 0 of 21 files; test time skipped 56%, 61%, 0%; **0 wrong** (verified 306 would-be reuses, 0 mismatches); skip 3.0 s vs verify 8.6 s at the 61% transition; the 0% transition is a release (version in deno.json: configuration). Raw: `harness/node_cache/results/node-c-local/oak-mini.json.gz` |
| other local runs | std subset (203 files): `deno test -A --parallel` 23 s; `--det` 75 s; cold `--det-cache` 83 s; warm 19.7 s with 164 of 203 files reused (not cached: Deno.Command 54, metadata times read by fs/ tests, files written by other test files, unobserved accesses 11, sockets 6). First run on a fresh machine 412 s (type check of every file in its own process). oak: cold 12 s, warm 4 s with 15 of 21 reused. All MEASURED, local, NOISY |
| outcome changes vs plain `deno test` | oak 0 (the same formData failure in both); std 2 of 3,021 tests (`deadline() throws DOMException`, `isGlob ... large number of open brackets`): both race a timer against work, which virtual time decides differently (Level 0, not isolation); 0 changes attributable to one process per file |
| not covered and why | see docs/runners/deno.md: a computed import of a project file from a remote/npm module; record/replay of Deno's native connections; per-test outcome of sanitizer failures (file fails through the exit status) |

## Found and fixed on the way (real repositories)

* wouter: test hooks ran outside the test bracket (real timers): tests now start at a runner-wide `beforeEach` and end
  at a runner-wide `afterEach` registered by the preload (bracket.js `pre`/`post`).
* wouter: a timer released to real time by the previous test (happy-dom's batched `hashchange`) was overtaken by fast
  virtual time: **shared clock change** (`src/clock.js` `Driver.fire` defers while a released timer is due, like the
  existing pending-`setImmediate` deferral). Node suites unchanged (controls 16/16, regressions 7/7, cache 45/45).
* oak: Deno without `--allow-env` throws on any unlisted variable: **shared capture change** (`installEnv` tolerates
  it); detjs' variables granted as `DETJS_*`.
* Optional module in a directory that does not exist yet: the stem listing was recorded as `missing` and stayed
  `missing` when the file appeared (wrong reuse, Bun test): **shared capture change** (`stemDep` also keys the missing
  directory and its missing parents). Would affect Node's `resolveFailed` the same way.

## Changes to shared files (all generic)

* `node/src/cache/capture.js`: `stemDep` keys missing parent directories; `installEnv` tolerates a guarded env.
* `node/src/clock.js`: released timers due in real time run before fast virtual timers.
* `node/src/cache/proof.js`: `configFiles(root, {extra})` (runner configuration files: bunfig.toml, deno.json(c),
  deno.lock, import maps); three UNCACHEABLE reasons (`runtime-api`, `dynamic-import`, `unobserved`).
* `node/bin/detjs.js`: `bun-test`, `deno-test` commands.
* `harness/node_cache/walk.py`: `RUNTIME_RUNNERS` dispatch (`detjs_cmd`, `report_args`, JUnit outcomes); Vitest/Jest
  paths unchanged.
* New: `node/src/runners/{common,bracket,bun,bun-preload,bun-runtime,deno,deno-preload.mjs,deno-setup,deno-runtime}.js`,
  `node/test/{runtime-helpers,runner-bun.test,runner-deno.test}.js`, specs and commit lists for wouter,
  json-schema-faker, oak, std, `.github/workflows/all-runners-node-c.yml`, `harness/node_cache/RUN-node-c`.
