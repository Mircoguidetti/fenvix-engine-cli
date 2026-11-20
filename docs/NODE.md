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
node/src/sched.js     Level 1: what counts as pending I/O, sched.timer / sched.io decisions
node/src/ioorder.js   completion order of concurrent I/O: recorded; file operations delivered in start order
node/src/deadline.js  the runners' test and hook timeouts on the virtual timers (+ deadline-preload.js, Vitest workers)
node/src/fstime.js    file times on the virtual clock, utimes inverse, virtual ino/dev, fs.watch events
node/src/realmx.js    Temporal.Now, ShadowRealm, zero-filled Buffer.allocUnsafe, Jest legacy fake timers
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
| 4 | virtual timers | `setTimeout`, `setInterval`, `clear*`, `timers/promises.setTimeout`: one queue ordered by (virtual due time, creation order), fired one per macrotask; the clock jumps to the due time. While no real I/O is pending (see 4b: no socket, file request, child process or busy worker beyond the baseline of the file) timers fire without waiting, one at a time and only once the other pending `setImmediate` callbacks have run (React `act()` and scheduler chains; found on apollo-client by the harness: a response mocked 20 ms later arrived before `act()` had flushed the previous render; at most 1000 deferrals in a row); when I/O is pending they also wait for the real delay so that the I/O can complete first (the analogue of the Python rule "sleep for real while other threads are alive"), and go back to fast time as soon as it has (4b). `--det-timer-budget` (100 000) fast firings per test bound intervals that are never cleared; `--det-timers=real` makes every timer wait. Only timers created *inside a test* are virtual; timers created outside tests (module level, `beforeAll`, teardown) are the realm's own, and when a test ends its pending virtual timers are released to the realm's own timers with the real delay that remains (found on dom-testing-library by the harness: a timer leaked by a finished `waitFor` fired at once under fast time and crashed the run, while jsdom would have cleared it at teardown). `setImmediate` keeps the native FIFO order (already deterministic) and is recorded. Timer handles support `ref/unref/hasRef/refresh/close`, numeric ids and `Symbol.toPrimitive`. Jest's modern fake timers are re-created on top of the virtual ones. |
| 5 | filesystem order | `fs.readdir`, `readdirSync`, `promises.readdir` (names, Buffers, Dirents, `recursive`), `opendir`, `opendirSync`, `promises.opendir` (read eagerly, iterated sorted). |
| 6 | closed network | `net.Socket#connect` (so `net.connect`, `http`, `https`, global `fetch`, `undici`), `tls.connect`, `dns.lookup`/`resolve*` (callback and promises) towards non-local hosts fail with `NetworkBlockedError` (`ECONNREFUSED`, `ENOTFOUND` for DNS). Loopback and Unix sockets allowed; `--det-allow-host`; local proxies from `*_PROXY` count as external. `--det-record` records per test the byte streams (plaintext above TLS, at `tls.connect`) into the cassette; later runs replay them through a Unix-socket replay server (TLS with a throwaway certificate, verification disabled for that socket only). |
| 7 | isolation | serial execution, recorded (see above). |
| 7a | environment | every variable a test reads is an event (`other` `env.get NAME=<digest of the value>`, `env.has`, `env.list` for enumerations), once per name and test; values never reach the trace. Jest's per-file copy of the environment included (P-041, audit G-0126). |
| 7b | time zone, locale | pinned for the runner and every process it starts when the job leaves them to the machine: `TZ` unset → `UTC`, neither `LC_ALL` nor `LANG` set → `C.UTF-8` (`LANGUAGE` removed); a value the job sets is kept; `--det-tz=ZONE\|keep`, `--det-locale=LOC\|keep` choose explicitly. detjs restarts itself with the pinned environment (ICU reads the locale at start-up). Header `meta.pinned`, `meta.tz`, `meta.locale` (G-0139, G-0140). |
| 7c | threads, processes, vm | `worker_threads` workers started by a test get the Level 0 controls (`--require src/worker-preload.js` in their `execArgv`; seeds and clock keyed by the test id and the worker's index); their messages and exit code are events (`worker.message`, `worker.exit`) and the test gets one `uncontrolled.thread` event. Child processes run as they are (determinism inside them is outside the release scope): one `uncontrolled.child` event per test, `child.result` (status and output digests) for synchronous calls, `child.exit` for asynchronous ones. `vm.createContext` / `runInNewContext` / `Script#runInNewContext` inside a test: the new context gets the realm controls (Math.random, Date, Web Crypto, the timers it has). (G-0124, G-0125, G-0134, G-0152) |
| 4a | runner timeouts | the runners' own test and hook timeouts (Vitest 1-5 `withTimeout` / `TaskDeadline`, jest-circus `callAsyncCircusFn`) run on the virtual timers inside a test: a test whose virtual time stays within its timeout passes however long it takes in real time (CPU time is not virtual time, J15), one whose virtual time passes it fails with the runner's own timeout error at that virtual instant (a 60 s sleep against a 1 s timeout fails at once). The deadline never makes virtual time jump by itself: a test that truly hangs (no timer left, or waiting for I/O that never comes) is caught by a real watchdog, the runner's timeout in real time with no virtual timer fired meanwhile. Which one decided is recorded (`time runner.timeout virtual:<ms>` / `real:<ms>`). Deadlines are charged the virtual time without the adaptive tick's surplus. Vitest captures `Date.now` / `performance.now` before the controls: `src/deadline-preload.js` is loaded first in its workers (`execArgv`) and answers the runner's deadline checks with the deadline clock (G-0144). `beforeAll`/`afterAll` keep real timeouts (their timers are real too). |
| 4b | Level 1: timers against I/O | pending I/O = requests (file operations, DNS, writes) and handles that can complete an operation of the test: sockets, child processes, UDP, `fs.watchFile` pollers, and worker threads only while busy (from their start until first heard from, from a message posted to them until their next message). Not counted: the standard streams (G-1435), listening servers, `fs.watch` watchers, message ports, idle workers (G-1484), handles present when the file started. Rule "local I/O first, then timers": when an operation of the test completes and nothing else is pending the timers go back to fast time at once; a timer whose real delay has passed while an operation that just started (file operation, connection waiting for its first data) is pending waits a grace of its own delay (20-50 ms). Decisions are events of source `sched` (shared vocabulary, `<chosen>/<set size>:<site>#<n>`): `sched.timer` when a timer fires while I/O of the test is still pending, `sched.io` when an operation completes while timers of the test wait; a run where real latency decided otherwise diverges there and `detjs verify` names the "first diverging scheduling choice" (G-0463, G-0464, G-1478). |
| 5a | file times | (G-0143, G-1410) time fields of Stats objects the test obtains (`stat`/`lstat`/`fstat`, sync, callback, promise, FileHandle, `watchFile` listeners; `*Ms`, `*Ns`, the `atime`/`mtime`/`ctime`/`birthtime` dates) are read on the virtual clock: a time before the test start keeps its age relative to the virtual test start, a time during the test is the virtual time of the last virtual clock event at or before it (never later than virtual now), a later time keeps its distance to virtual now. `utimes`/`futimes`/`lutimes` (and promise/FileHandle forms) take virtual times: the file gets the mapped real time, and reading it back gives the virtual time that was set. `ino` and `dev` are virtual (numbered by first sight per test file). The first read of each field is an event (`fs fs.stat.<field>`); a time read whose value depends on when the run happens is a real-clock read for the cache (never reused; before, it was keyed by the exact real value while the test compared it with the virtual clock). |
| 5b | file watching | `fs.watch`, `fs.promises.watch`, `fs.watchFile` (and chokidar on top of them): every change event delivered to the test is an event (`fs.watch <path>\|<type>\|<file>`, `fs.watchFile <path>\|changed`); the kernel decides order and coalescing, the trace records it; a test that receives them is not reused by the cache (G-1411). |
| 7d | concurrent I/O | the completion order of a test's overlapping asynchronous file operations and connections is recorded (`io.complete <kind>#<n>`, one `uncontrolled.io` event): a different order is a different fingerprint. Sequential I/O records nothing (G-0150, G-0151). Level 1: the completions of concurrent file operations (callbacks and promises) are delivered in the order the operations started, so parallel directory walks (fast-glob, globby, readdirp) merge in the same order in every run (G-1412); a completion held more than 200 ms by an earlier operation that does not complete (FIFO, device) is released and recorded (`io.release`). |
| 8 | fingerprint | every interaction becomes an event `(source, op, call site, value)`; the Rust core chains them with BLAKE3. Events are buffered in JS and sent to Rust in batches (`recordPacked`). |

Clock details (P-041): the runners' fake timers (`vi.useFakeTimers`, `jest.useFakeTimers` modern, Bun's) start
their fake clock at the virtual clock, not the machine's time, unless the test or the configuration gives `now`
(audit G-0122, G-0142); `getRealSystemTime()` answers the virtual clock; Jest `advanceTimers` (the fake clock follows
real time) is a real-clock read for the cache. `process.uptime()` counts from the start of the file on the virtual
clock (+1 s); `performance.timeOrigin` is the epoch; `performance.mark()` / `measure()` without explicit times use the
virtual `performance.now()`; the host's `performance` (also `require('perf_hooks').performance` under Jest) is
virtual for test code; `AbortSignal.timeout(ms)` runs on the virtual timers (G-0135..G-0138, G-0141). `Temporal.Now` (Node 24
`--harmony-temporal` and later) is the virtual clock: `instant()` is a recorded clock read, the ISO and calendar
forms derive from it in the pinned time zone (G-1434). `Buffer.allocUnsafe` / `allocUnsafeSlow` / `SlowBuffer` are
zero-filled (G-2167). A `ShadowRealm` (`--experimental-shadow-realm`) gets the seeded `Math.random` and the virtual
`Date` of the realm that creates it (G-2168). Jest's legacy fake timers restore the virtual timers on
`useRealTimers()` (G-1468). If a control
cannot be installed in a realm, detjs prints a warning, records `uncontrolled.level0` in every later test of the
process and the cache does not reuse them (G-0181).

Calls whose first frame outside Node internals and detjs belongs to the test
runner (vitest, vite, tinypool, jest-*, @jest, expect, …) use the real
functions and are not recorded: the runner's RPC timers keep real time (Python: pytest plugins keep real timers);
the runner's test and hook timeouts are runner deadlines on the virtual timers (4a).

## Known limits

Found by the shell tests (**T**), by the harness (**H**) or by design (**D**).

| # | limit | found |
|---|---|---|
| J1 | Native addons and child processes are not controlled (they get real clocks, randomness and network); they are recorded (`uncontrolled.child`, `child.result`) and the cache never reuses a test that uses one. Worker threads get the controls but their interleaving with the test is not ordered (`uncontrolled.thread`). Child processes count as pending I/O, so timers wait for real meanwhile; workers only while busy (4b). | D |
| J2 | Vitest `vmThreads`/`vmForks` pools and browser mode run tests in another realm than the worker global: the realm controls do not reach them. | D |
| J3 | Jest `setupFiles` run before the detjs test runner (Jest calls them first): code there sees the real globals and its events are not recorded; `setupFilesAfterEnv` is fine. Jasmine (`jest-jasmine2`) runners get the controls but no per-test brackets. | D |
| J4 | Level 1 (4b) orders a timer after local I/O that completes within the timer's delay plus the grace; I/O slower than that (a slow child process, a remote-like local server) still races the timer in real time. Such a decision is recorded (`sched.timer` with the pending set), so two runs that differ are never called identical, but it is not controlled. Thread-pool work that is not a libuv request (zlib, crypto jobs, native addons' async work) does not count as pending I/O. | D |
| J5 | Infrastructure detection captures a structured stack (8 frames, then 30) on every patched call; the source-mapped site is computed once per distinct raw position and cached. Still the main cost of `--det` on hot clock loops (react-redux: a test rendering 100 000 components with React's scheduler reading the clock: 3 s without `--det`, 25 s with it, 71 s before the cache; MEASURED locally); `--det-sites=off` turns it off (then runner frames are not told apart). References captured before installation (runner internals, Jest `setupFiles`) keep the real objects. | D |
| J6 | `Date.now()` has millisecond resolution: with the 1 µs tick it advances by 1 ms every 1000 reads (or faster under the adaptive tick). | D |
| J7 | Network replay: a replayed socket is a Unix socket (`remoteAddress`/`remotePort` undefined); request bytes that differ from the recording reset the connection (the test sees the error, the trace has `replay-mismatch`, detjs prints the request; G-0130); recorded and replayed connections are closed when their test ends, so keep-alive agents reconnect per test (G-0129); credential request headers (`Authorization`, `Cookie`, `*-token`, `*-key`, ...) are stored as a digest padded to the same length (G-0131); UDP to non-local addresses is refused like a connection (G-0128); sockets intercepted by a mocking library (nock >= 14 / @mswjs/interceptors: an own `connect` on the socket and on its handle) are answered by the mock, the network stays closed for everything else (G-0127). TLS replay does not negotiate ALPN `h2`; `new dns.Resolver()` instances are not guarded (connections are). | T,D |
| J8 | (Fixed by 7d: concurrent file operations are delivered in start order.) Operations on FileHandle objects and streams opened by Node internals outside a test are not ordered. | D |
| J9 | (Vitest projects get the detjs runner and ordering on every resolved project, found by the harness on date-fns: before the fix project configs ignored them.) A file run by two projects of a Vitest workspace / Jest multi-project config yields two parts with the same test ids; the verifier then keeps one. | D |
| J11 | Playwright Test is measured only (`node/src/register.js`, enabled with `NODE_OPTIONS=--require` in the worker processes): controls without per-test brackets or traces; the browser and web servers are not controlled. | D |
| J14 | Jest under `--det` runs in band with `--forceExit`: a handle left open by a suite would otherwise keep the single process alive forever (react-testing-library hangs in band without `--det` too; in worker mode Jest kills the workers). Recorded in `meta.isolation`. | H |
| J13 | Vitest (and Jest, since matrix-js-sdk: Jest compiles its `testRunner` with the project's Babel config, whose `transform-runtime` then required `@babel/runtime` from detjs's directory) load the detjs runner through a one-line shim in `<root>/node_modules/.detjs/` (removed at exit): a runner outside the project root is served by Vite and refused when the project restricts `server.fs` (found on jotai: 0 of 44 files ran). | H |
| J12 | The wrappers call the runners' Node APIs in-process, so they reproduce what the runners' own CLIs set up first: `NODE_ENV=test` (Jest's bin; Babel configs such as kcd-scripts depend on it), `TEST`/`VITEST`/`NODE_ENV` and the CLI filters at `createVitest` (Vitest's `startVitest`). Found by the harness on user-event and jotai/pinia. | H |
| J15 | CPU time is not virtual time: a loop bounded by a virtual deadline (apollo-client: `setInterval(…, 1)` calling `gc()` for 1000 virtual ms) runs every iteration that the virtual deadline allows (1000 `gc()` calls instead of ~50 in real time) and could exceed the runner's *real* test timeout. Fixed by 4a: the runners' test and hook timeouts are virtual inside a test; a purely synchronous test that is slow in real time now passes under `--det` where it times out without it (its outcome no longer depends on the machine's speed). `beforeAll`/`afterAll` timeouts stay real. | H |
| J16 | A custom Jest `runner` (jest-light-runner, used by babel and prettier) runs the tests without jest-circus's `testRunner`, out of detjs's reach: Level 0 does not apply to them (0 of ~25 000 tests traced); detjs warns and records it in `meta.isolation`. `DETJS_JEST_RUNNER=replace` uses Jest's default `jest-runner` instead, but the suites written for the custom runner (native ESM) then fail (measured: babel 238/238 suites, prettier 1429/1429, under `--det` and the serial reference alike). | H |
| J17 | Each patched call (clock, random, fs) runs a few extra JavaScript frames (the wrapper, event recording, call-site capture): code that recurses close to V8's stack limit can overflow under `--det` only (assistant-ui: a JavaScript bash emulator reported `Maximum call stack size exceeded` in 4 tests). | H |
| J18 | File times (5a): files the test did not write keep their real age, which depends on when the run happens: a test that reads such a time is recorded with that value (two runs minutes apart are not identical) and never reused by the cache. Several files written between two virtual clock events get the same virtual time. Stats objects created by Node internals outside the wrapped functions (`fs.realpath`'s own `lstat`, `Dirent`) keep real values. | D |
| J19 | ShadowRealm: only `Math.random` and `Date` are controlled inside it (it has no timers, crypto or I/O). Temporal: only `Temporal.Now` is virtual (the rest of Temporal is pure computation). | D |
| J10 | With Vitest `isolate: false`, several files can be collected before the first runs: the module-level seed of later files is approximate. | D |

The harness results (`harness/node/results/`) add the limits found on real
projects; see the report there.
