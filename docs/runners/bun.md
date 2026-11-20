# `bun test` under detjs (`detjs bun-test`)

```bash
detjs bun-test [bun test args]                                   # bun test, unchanged
detjs bun-test --det [--det-seed=N] [bun test args]              # Level 0 (determinism)
detjs bun-test --det --det-cache=DIR|URL [--det-cache-verify] [bun test args]   # + skip with proof
```

Support: **det + skip**. Bun 1.4.4 measured (`bun test` is the runner of 6.2% of 1,999 popular JS/TS repositories,
MEASURED, `sessions/2026-11-19-all-runners/INTERMEDIATE-1.md`).

## The shared core in Bun

Bun loads the detpy-node Node-API addon (`crates/detpy-node`) and the detjs CommonJS modules unchanged (MEASURED:
`native.digest`, `Recorder`, `ProofCache` work in Bun 1.4.4; `node/test/runner-bun.test.js` runs every test through
it). So nothing is reimplemented: the test process runs the shared Level 0 controls (`src/controls.js`: clock,
timers, seeded `Math.random` / `crypto`, fs order, closed network) and the shared capture (`src/cache/capture.js`:
node:fs, process.env, os, child_process, net, dgram, dlopen); the main process (Node) runs `ProofSession`
(`src/cache/proof.js`): decision, records, receipts, summary, trace merge. Files: `src/runners/bun.js` (main side),
`bun-preload.js` (test process), `bun-runtime.js` (Bun's own APIs), `bracket.js` and `common.js` (shared with Deno).

## Process model and order

* One `bun test` process per test file, in detjs' order: sorted paths, or the core's reproducible shuffle
  (`shuffleIndices`) with `--det-seed`. Inside a file: declaration order, or Bun's own `--randomize --seed=S` with
  `S = deriveSeed(seed, file)` from the core. `--max-concurrency=1`.
* Why one process per file, also under `--det` without cache: `bun test` runs every file in one process with one
  global object (MEASURED: a global set by file A is visible in file B). A file reused from the cache would leave the
  next file in a context the reference run never had (docs/ALL-RUNNERS.md). The change is counted:
  `isolation: ... (counted)` in runner-bun.test.js shows a test that passes under plain `bun test` and fails alone; on
  the walk repositories the plain run's outcomes are recorded next to detjs' per commit (`plain.outcomes`).
* Discovery is Bun's own: a `bun test` with the same filters and a preload whose loader hook returns an empty module
  for every file and records its path (no test code runs). The file list is exactly what `bun test` would run.
* bunfig.toml: Bun loads bunfig's preloads before any `--preload` (MEASURED), so their reads would escape the capture.
  detjs passes a copy of the configuration without preloads (`--config=`, parsed by Bun's own TOML parser) and passes
  them after its own preload.
* Refused with `--det`: `--watch`, `--hot`, `--randomize`, `--seed` (use `--det-seed`); `--det-record` (Bun's native
  connections are not recorded). `--concurrent` / `--max-concurrency` are replaced by `--max-concurrency=1`.
* JUnit output (`--reporter=junit --reporter-outfile=F`) is merged from the per-file reports.

## Hooks used

| need | Bun hook |
|---|---|
| test start | a runner-wide `beforeEach` registered by the preload (runs before the file's own hooks, MEASURED order: global, file, describe, body, describe, file, global) |
| test id and outcome | `bun:test`'s `test` / `it` / `describe` (and `.each`, `.if`, `.skip`, `.only`, `.todo`, `.failing`, `.concurrent`, ...) wrapped in the preload: the module namespace is mutable and test files get the wrapped functions (MEASURED); ids `<file>::<describe>::<name>`, `#n` for duplicates, `[k]` for the k-th row of `.each`; the body's throw / rejection / `done(err)` is the outcome |
| test end | a runner-wide `afterEach` (after the file's hooks) |
| file end | a runner-wide `afterAll` (after the file's own; `process.on('exit')` does not fire in `bun test`, MEASURED) |
| file outcome | the process exit status: a failed hook, a timeout, an unhandled error or any failure the wrapper did not see makes the file failed (never reused) |
| fake timers | `jest/vi.useFakeTimers` and `setSystemTime` put Bun's native timers / Date back while they are on |

## What is captured (on top of the shared Node capture)

| Bun API | key |
|---|---|
| `Bun.file(path)` (+ `text/json/bytes/arrayBuffer/stream/formData/slice/exists`, native consumers such as `new Response(file)` and `Bun.write(dst, file)`) | content `f:` (size and existence included) |
| `BunFile#stat()` | kind; fields as for `fs.stat` (`size`, `mode` keyed; times, inode, owner: not cached) |
| `Bun.write`, `BunFile#write/writer/delete` | outputs (a read of another file's output: not cached) |
| `Bun.mmap` | content |
| `Bun.Glob#scan/scanSync` | recursive typed listing of the scanned directory (`t:`); `followSymlinks`: not cached |
| `bun:sqlite` `Database(path)` | the database file and its `-wal/-journal/-shm` (read-only opens), else also an output; URIs, ATTACH, VACUUM INTO, extensions: not cached |
| `node:sqlite` (Bun implements it; its ES bindings cannot be re-pointed) | not cached |
| modules (Bun's loader is native) | import graph of the file: from the test file, the preloads and Bun's CommonJS registry, every import of every module (`Bun.Transpiler#scanImports`: static, literal dynamic, require) resolved with Bun's resolver (import and require conditions): project modules by content + stem listing + nearest package.json (`cap.module`), misses by what would make them resolve (`cap.resolveFailed`, which now also keys a missing parent directory); `import()`/`require()` of a non-literal specifier in a project module: not cached. (A `Bun.plugin` onResolve hook alone is not enough: Bun does not call it for extensionless specifiers, found or not, MEASURED) |
| `mock.module(spec, factory)` | the target the specifier resolves to (or its miss); the factory is test code |
| snapshot files (`toMatchSnapshot` reads `__snapshots__/<file>.snap` natively) | content (or `missing`) of the file's snapshot file |
| `.env`, `.env.*` (Bun loads them itself), bunfig.toml, `~/.bunfig.toml`, `--env-file`, `--tsconfig-override`, `BUN_*`, `NODE_ENV`, `TZ` | configuration digest; plus the shared configuration files (tsconfig, package.json, ...) and the runtime identity (node_modules, TZ, locale, ...) |
| `Bun.env` / `import.meta.env` (Bun does not let either be replaced, MEASURED) | a module whose source uses them (or uses `Bun` as a value) keys the whole environment |
| `Bun.spawn/spawnSync/$`, `openInEditor`, `Terminal` | not cached (process) |
| `Bun.serve/listen/connect`, `fetch` to loopback, `WebSocket`, `Bun.dns.*`, `sql/SQL/postgres/redis/RedisClient/s3/S3Client` | not cached (socket); non-local hosts are closed by Level 0 |
| `Bun.udpSocket` | not cached |
| `Bun.password.hash`, `Bun.CSRF.generate` | not cached (OS entropy) |
| `Bun.resolve/resolveSync` | the result (module) or the miss |
| `Bun.fetch`, `BunFile#lastModified`, `Bun.secrets`, `Bun.WebView`, `Bun.ModuleGraph` (not replaceable) | source scan: not cached when used |
| every other `Bun.*` function or namespace not on the PURE list | not cached (`runtime-api`): an API added by a later Bun is refused until it is classified |

## Level 0 in Bun

Shared controls (MEASURED working in Bun: `Date`, `performance.now`, timers, `Math.random`, `crypto.getRandomValues`,
`crypto.randomUUID`, node:net, node:dns), plus: `Bun.nanoseconds` (virtual), `Bun.sleep` (virtual timer),
`Bun.sleepSync` (advances the virtual clock), `Bun.randomUUIDv7` (virtual time + seeded bytes); closed network for
`fetch`, `Bun.connect`, `WebSocket`, `Bun.dns.*`, `node:http(s).request/get` (Bun's HTTP client does not use
net.Socket). Not closed: `Bun.fetch` (not replaceable; a use makes the file not cached and is a note), Bun's
built-in database clients (`Bun.sql`, `Bun.redis`, S3: not cached).

## Not covered, and why

* A library in `node_modules` that reads `BunFile#lastModified` without mentioning `Bun.file` / `BunFile` in its
  source, or reaches `Bun.env` through an alias the scan does not match (`const B = globalThis[name]`): the getter and
  the env object cannot be wrapped in Bun 1.4.4. Project modules are scanned strictly.
* A failed resolution of a non-literal specifier inside an installed package (runtime identity covers the package
  itself, not what its computed `require()` would find in the project).
* `--det-record` / cassette replay of Bun's native connections.
* Per-test outcome: the trace takes the body's outcome; a failure only Bun sees (`expect.assertions`, a failing
  afterEach) fails the file through the exit status (never reused), but the trace can say `passed` for that test.

Evidence: `node/test/runner-bun.test.js` (41 tests); walk specs `harness/node_cache/specs/{wouter,json-schema-faker}.json`.
