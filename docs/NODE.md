# detjs — Level 0 for Node / TypeScript (Vitest and Jest)

`detjs` is the Node counterpart of `detpy`: the same Rust core
(`crates/detpy-core`), exposed to Node with napi-rs (`crates/detpy-node`),
and a thin shell for Vitest and Jest (`node/`). Traces and cassettes have the
same format as the Python ones: `detjs verify`, `detpy verify` and the
harness verifier read both.

```bash
cd node && npm run build                     # cargo build -p detpy-node + copy the addon
detjs vitest run --det                       # or: DETJS=1 detjs vitest run
detjs jest --det --det-seed=7                # reproducible shuffle (exploration)
detjs vitest run --det --det-record          # allow the network once, record it
detjs vitest run --det                       # later runs replay .detjs/cassette.json
detjs verify .detjs/run1.jsonl .detjs/trace.jsonl
detjs --det-help                             # every option
```

Without `--det` (and without `DETJS=1`) `detjs vitest|jest` runs the project's
own CLI unchanged.

`--det-cache=DIR|URL` adds the cache with proof (skip test files whose every recorded input is unchanged, with a
receipt per reused result): [NODE-CACHE.md](NODE-CACHE.md).

## Layout

```
crates/detpy-node     napi-rs bindings: Recorder (recordPacked = batched events), Cassette,
                      verify / verifyText, deriveSeed(Words), shuffleOrder, shuffleIndices,
                      orderDigest, digest, mergeTraces, backends
crates/detpy-core     + order::shuffle_indices (one level of the hierarchical shuffle)
                      + trace::merge_traces (concatenate per-file trace parts)
node/src/native.js    loads the addon once per process (shared by every realm)
node/src/state.js     per-process state: current test, event buffer (flushed to Rust in batches)
node/src/sites.js     call sites (first frame outside Node internals and detjs), runner frames
node/src/clock.js     virtual clock, Date, performance.now, process.hrtime, virtual timers
node/src/seeds.js     Math.random, crypto.getRandomValues/randomUUID, observed OS entropy
node/src/fsorder.js   sorted readdir / readdirSync / promises.readdir / opendir
node/src/network.js   closed network, record/replay (net, tls, dns => http, https, fetch, undici)
node/src/controls.js  installation (process-wide and per realm), per-file trace parts
node/src/session.js   main process: options, DETJS_* environment, merge of parts, compare
node/src/vitest/      cli.js (Node API + sequencer), runner.mjs/shell.js (custom runner in the worker)
node/src/jest/        cli.js (in-process jest-cli), sequencer.js, runner.js (wraps jest-circus)
```

## How a `--det` run works

1. The wrapper turns its options into `DETJS_*` variables (inherited by every
   worker thread or child process) and starts the runner:
   * **Vitest** through its Node API (`parseCLI` + `startVitest`, Vitest
     1.4–5.x) with `fileParallelism: false`, `maxWorkers: 1`,
     `maxConcurrency: 1`, `sequence.shuffle/concurrent: false`, a sequencer
     that sorts files by path (or shuffles them with the seed) and the detjs
     runner. The pool (threads/forks) and its isolation are kept; only
     parallelism is removed.
   * **Jest** in the same process (`jest-cli` `run`) with `--runInBand`
     (each file in its own vm context, as usual, one at a time),
     `--maxConcurrency=1`, `--no-randomize` (Jest ≥ 29.2), the detjs sequencer
     and the detjs `testRunner`, which delegates to the project's own runner
     (jest-circus) found with `--showConfig`.
   The choice (pool, isolation, serial) is written in the trace header
   (`meta.isolation`, `meta.serial`).
2. In the worker, before the test file is imported, the controls are
   installed: process-wide ones on Node modules (`fs`, `net`, `tls`, `dns`,
   `crypto`, `timers`, `timers/promises`, `process.hrtime`; ESM named exports
   re-synced) and per-realm ones on the global object of the test realm
   (`Math.random`, `Date`, `performance`, `crypto`, timers; Jest: the vm
   context of the file).
3. Each test file writes a trace *part* (one Rust `Recorder`); tests are
   bracketed by the runner hooks (Vitest `onBeforeRunTask`/`onAfterRunTask`,
   jest-circus `test_start`/`test_done`), which reseed the generators, reset
   the wall clock and the network counters, and finish the fingerprint with
   the outcome.
4. At the end the wrapper merges the parts in execution order (Rust
   `merge_traces`) into `.detjs/trace.jsonl`.

Events follow the shared event vocabulary: `op` = unprefixed Node API name
(`Date.now`, `fs.readdir`, `crypto.randomUUID`, `net.connect`, …; timers use
`setTimeout` with value `schedule:<ns>`/`fire:<ns>`), `site` = source-mapped
original file and line relative to the repository root (the stack of the
test realm's `Error`, which Vitest and Jest source-map), header `meta` with
`runtime=node`, `runtime_version`, `runner`, `seed`, `controls`. `event.rs`
and the encoding are not modified by detjs.

Test ids: `<file relative to the root>::<describe>::…::<test name>`; a
duplicated name in a file gets ` #2`, ` #3` (in declaration order).

## Controls

| # | control | how |
|---|---|---|
| 1 | order | files sorted by path, tests in declaration order; `--det-seed=N` shuffles files → describe blocks → tests reproducibly with the Rust SplitMix64 shuffle (`shuffle_indices`, the same algorithm as the Python module → class → test shuffle). Runner shuffles (`sequence.shuffle`, `randomize`) are switched off. Executed order in the trace. |
| 2 | seeds | `Math.random` = xoshiro128** reseeded per test with `derive_seed(seed, test id)` (and per file before the first test, for module-level draws); `crypto.getRandomValues` and `crypto.randomUUID` (global Web Crypto, `node:crypto`, `webcrypto`) from a second stream of the same key. `crypto.randomBytes/randomFillSync/randomInt` are observed (`entropy` events), controlled only with `--det-urandom`. |
| 3 | virtual clock | `Date`, `Date.now`, `new Date()`, `Date()`, `performance.now`, `process.hrtime(.bigint)`: one virtual ns counter, tick per read (default 1 µs), **adaptive tick** (after 1000 consecutive reads with no other event every read doubles the tick, up to 1 s; Python doubles after 8: on Node, React's scheduler reads the clock hundreds of times per render, and after 8 reads the virtual clock ran 194 s ahead within one recharts test, breaking code that compares `performance.now()` with Vitest's fake `requestAnimationFrame` timestamps: 1113 tests broken by `--det`). The wall clock restarts at `--det-epoch` (2025-01-01Z) for every test; `performance.now()` counts from the start of each test file, as in a fresh worker (found on recharts: counted from the process start, it reached values that Vitest's fake `requestAnimationFrame` timestamps, which start at 0, could not catch up with in later files: 40 tests broken in a full run, none with the file alone). |
| 4 | virtual timers | `setTimeout`, `setInterval`, `clear*`, `timers/promises.setTimeout`: one queue ordered by (virtual due time, creation order), fired one per macrotask; the clock jumps to the due time. While no real I/O is pending (no socket, server, file request, child process, worker beyond the baseline of the file) timers fire without waiting, one at a time and only once the other pending `setImmediate` callbacks have run (React `act()` and scheduler chains; found on apollo-client by the harness: a response mocked 20 ms later arrived before `act()` had flushed the previous render; at most 1000 deferrals in a row); when I/O is pending they also wait for the real delay so that the I/O can complete first (the analogue of the Python rule "sleep for real while other threads are alive"). `--det-timer-budget` (100 000) fast firings per test bound intervals that are never cleared; `--det-timers=real` makes every timer wait. Only timers created *inside a test* are virtual; timers created outside tests (module level, `beforeAll`, teardown) are the realm's own, and when a test ends its pending virtual timers are released to the realm's own timers with the real delay that remains (found on dom-testing-library by the harness: a timer leaked by a finished `waitFor` fired at once under fast time and crashed the run, while jsdom would have cleared it at teardown). `setImmediate` keeps the native FIFO order (already deterministic) and is recorded. Timer handles support `ref/unref/hasRef/refresh/close`, numeric ids and `Symbol.toPrimitive`. Jest's modern fake timers are re-created on top of the virtual ones. |
| 5 | filesystem order | `fs.readdir`, `readdirSync`, `promises.readdir` (names, Buffers, Dirents, `recursive`), `opendir`, `opendirSync`, `promises.opendir` (read eagerly, iterated sorted). |
| 6 | closed network | `net.Socket#connect` (so `net.connect`, `http`, `https`, global `fetch`, `undici`), `tls.connect`, `dns.lookup`/`resolve*` (callback and promises) towards non-local hosts fail with `NetworkBlockedError` (`ECONNREFUSED`, `ENOTFOUND` for DNS). Loopback and Unix sockets allowed; `--det-allow-host`; local proxies from `*_PROXY` count as external. `--det-record` records per test the byte streams (plaintext above TLS, at `tls.connect`) into the cassette; later runs replay them through a Unix-socket replay server (TLS with a throwaway certificate, verification disabled for that socket only). |
| 7 | isolation | serial execution, recorded (see above). |
| 8 | fingerprint | every interaction becomes an event `(source, op, call site, value)`; the Rust core chains them with BLAKE3. Events are buffered in JS and sent to Rust in batches (`recordPacked`). |

Calls whose first frame outside Node internals and detjs belongs to the test
runner (vitest, vite, tinypool, jest-*, @jest, expect, …) use the real
functions and are not recorded: the runner's own timeouts and RPC timers keep
real time (Python: pytest plugins keep real timers).

## Known limits

Found by the shell tests (**T**), by the harness (**H**) or by design (**D**).

| # | limit | found |
|---|---|---|
| J1 | Native addons, child processes and user-created worker threads are not controlled (they get real clocks, randomness and network); child processes and workers count as pending I/O, so timers wait for real meanwhile. | D |
| J2 | Vitest `vmThreads`/`vmForks` pools and browser mode run tests in another realm than the worker global: the realm controls do not reach them. | D |
| J3 | Jest `setupFiles` run before the detjs test runner (Jest calls them first): code there sees the real globals and its events are not recorded; `setupFilesAfterEnv` is fine. Legacy fake timers (`legacyFakeTimers`) keep Jest's original real timers. Jasmine (`jest-jasmine2`) runners get the controls but no per-test brackets. | D |
| J4 | Fast virtual timers fire in (due time, creation) order; whether a timer fires before or after real I/O completes depends on real scheduling once I/O is pending (the decision uses `process.getActiveResourcesInfo()`), so tests racing timers against sockets or files can still differ (`time` divergences). | D |
| J5 | Infrastructure detection captures a structured stack (8 frames, then 30) on every patched call; the source-mapped site is computed once per distinct raw position and cached. Still the main cost of `--det` on hot clock loops (react-redux: a test rendering 100 000 components with React's scheduler reading the clock: 3 s without `--det`, 25 s with it, 71 s before the cache; MEASURED locally); `--det-sites=off` turns it off (then runner frames are not told apart). References captured before installation (runner internals, Jest `setupFiles`) keep the real objects. | D |
| J6 | `Date.now()` has millisecond resolution: with the 1 µs tick it advances by 1 ms every 1000 reads (or faster under the adaptive tick). | D |
| J7 | Network replay: a replayed socket is a Unix socket (`remoteAddress`/`remotePort` undefined); request bytes that differ from the recording are reported (`replay.mismatch`), not rejected; TLS replay does not negotiate ALPN `h2`; `new dns.Resolver()` instances are not guarded (connections are). | T,D |
| J8 | Only the order of directory enumeration is normalised; libraries that issue several asynchronous `readdir` calls in parallel (fast-glob) still merge results in completion order. | D |
| J9 | (Vitest projects get the detjs runner and ordering on every resolved project, found by the harness on date-fns: before the fix project configs ignored them.) A file run by two projects of a Vitest workspace / Jest multi-project config yields two parts with the same test ids; the verifier then keeps one. | D |
| J11 | Playwright Test is measured only (`node/src/register.js`, enabled with `NODE_OPTIONS=--require` in the worker processes): controls without per-test brackets or traces; the browser and web servers are not controlled. | D |
| J14 | Jest under `--det` runs in band with `--forceExit`: a handle left open by a suite would otherwise keep the single process alive forever (react-testing-library hangs in band without `--det` too; in worker mode Jest kills the workers). Recorded in `meta.isolation`. | H |
| J13 | Vitest (and Jest, since matrix-js-sdk: Jest compiles its `testRunner` with the project's Babel config, whose `transform-runtime` then required `@babel/runtime` from detjs's directory) load the detjs runner through a one-line shim in `<root>/node_modules/.detjs/` (removed at exit): a runner outside the project root is served by Vite and refused when the project restricts `server.fs` (found on jotai: 0 of 44 files ran). | H |
| J12 | The wrappers call the runners' Node APIs in-process, so they reproduce what the runners' own CLIs set up first: `NODE_ENV=test` (Jest's bin; Babel configs such as kcd-scripts depend on it), `TEST`/`VITEST`/`NODE_ENV` and the CLI filters at `createVitest` (Vitest's `startVitest`). Found by the harness on user-event and jotai/pinia. | H |
| J15 | CPU time is not virtual time: a loop bounded by a virtual deadline (apollo-client: `setInterval(…, 1)` calling `gc()` for 1000 virtual ms) runs every iteration that the virtual deadline allows (1000 `gc()` calls instead of ~50 in real time) and can exceed the runner's *real* test timeout. The runners' timeouts are not virtualised. | H |
| J16 | A custom Jest `runner` (jest-light-runner, used by babel and prettier) runs the tests without jest-circus's `testRunner`, out of detjs's reach: Level 0 does not apply to them (0 of ~25 000 tests traced); detjs warns and records it in `meta.isolation`. `DETJS_JEST_RUNNER=replace` uses Jest's default `jest-runner` instead, but the suites written for the custom runner (native ESM) then fail (measured: babel 238/238 suites, prettier 1429/1429, under `--det` and the serial reference alike). | H |
| J17 | Each patched call (clock, random, fs) runs a few extra JavaScript frames (the wrapper, event recording, call-site capture): code that recurses close to V8's stack limit can overflow under `--det` only (assistant-ui: a JavaScript bash emulator reported `Maximum call stack size exceeded` in 4 tests). | H |
| J10 | With Vitest `isolate: false`, several files can be collected before the first runs: the module-level seed of later files is approximate. | D |

The harness results (`harness/node/results/`) add the limits found on real
projects; see the report there.
