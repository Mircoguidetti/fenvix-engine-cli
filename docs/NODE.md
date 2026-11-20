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
detjs vitest run --det --det-workers=4       # parallel lanes with a fixed plan (also: --maxWorkers=4)
detjs jest --det -w 4                        # Jest workers, one lane per worker
detjs jest --det --det-plan=.detjs/run1.jsonl  # replay the lanes of an earlier parallel run
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
     1.4–5.x) with `maxConcurrency: 1`, `sequence.shuffle/concurrent: false`,
     a sequencer that sorts files by path (or shuffles them with the seed) and
     the detjs runner. Serially (the default): `fileParallelism: false`,
     `maxWorkers: 1`; in parallel: the lanes of a fixed plan (below). The pool
     (threads/forks) and its isolation are kept.
   * **Jest** in the same process (`jest-cli` `run`) with `--maxConcurrency=1`,
     `--no-randomize` (Jest ≥ 29.2), the detjs sequencer and the detjs
     `testRunner`, which delegates to the project's own runner (jest-circus)
     found with `--showConfig`. Serially (the default): `--runInBand` (each
     file in its own vm context, one at a time, in the main process); in
     parallel: `--maxWorkers=N`, one worker process per lane (below).
   The choice (pool, isolation, serial or lanes) is written in the trace header
   (`meta.isolation`, `meta.serial`, `meta.parallel`).
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
4. At the end the wrapper merges the parts in the serial order (Rust
   `merge_traces`) into `.detjs/trace.jsonl`; a parallel run's trace has the
   same order as the serial run's, and `detjs verify` compares them test by
   test.

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
| 7a | environment | every variable a test reads is an event (`other` `env.get NAME=<digest of the value>`, `env.has`, `env.list` for enumerations), once per name and test; values never reach the trace. Jest's per-file copy of the environment included (P-041, audit G-0126). |
| 7b | time zone, locale | pinned for the runner and every process it starts when the job leaves them to the machine: `TZ` unset → `UTC`, neither `LC_ALL` nor `LANG` set → `C.UTF-8` (`LANGUAGE` removed); a value the job sets is kept; `--det-tz=ZONE\|keep`, `--det-locale=LOC\|keep` choose explicitly. detjs restarts itself with the pinned environment (ICU reads the locale at start-up). Header `meta.pinned`, `meta.tz`, `meta.locale` (G-0139, G-0140). |
| 7c | threads, processes, vm | `worker_threads` workers started by a test get the Level 0 controls (`--require src/worker-preload.js` in their `execArgv`; seeds and clock keyed by the test id and the worker's index); their messages and exit code are events (`worker.message`, `worker.exit`) and the test gets one `uncontrolled.thread` event. Child processes run as they are (determinism inside them is outside the release scope): one `uncontrolled.child` event per test, `child.result` (status and output digests) for synchronous calls, `child.exit` for asynchronous ones. `vm.createContext` / `runInNewContext` / `Script#runInNewContext` inside a test: the new context gets the realm controls (Math.random, Date, Web Crypto, the timers it has). (G-0124, G-0125, G-0134, G-0152) |
| 7d | concurrent I/O | the completion order of a test's overlapping asynchronous file operations and connections is recorded (`io.complete <kind>#<n>`, one `uncontrolled.io` event): a different order is a different fingerprint. Sequential I/O records nothing (G-0150, G-0151). |
| 7 | isolation | serial execution by default; parallel lanes with a fixed plan on request (see "Parallel"); recorded (see above). |
| 8 | fingerprint | every interaction becomes an event `(source, op, call site, value)`; the Rust core chains them with BLAKE3. Events are buffered in JS and sent to Rust in batches (`recordPacked`). |

Clock details (P-041): the runners' fake timers (`vi.useFakeTimers`, `jest.useFakeTimers` modern, Bun's) start
their fake clock at the virtual clock, not the machine's time, unless the test or the configuration gives `now`
(audit G-0122, G-0142); `getRealSystemTime()` answers the virtual clock; Jest `advanceTimers` (the fake clock follows
real time) is a real-clock read for the cache. `process.uptime()` counts from the start of the file on the virtual
clock (+1 s); `performance.timeOrigin` is the epoch; `performance.mark()` / `measure()` without explicit times use the
virtual `performance.now()`; the host's `performance` (also `require('perf_hooks').performance` under Jest) is
virtual for test code; `AbortSignal.timeout(ms)` runs on the virtual timers (G-0135..G-0138, G-0141). If a control
cannot be installed in a realm, detjs prints a warning, records `uncontrolled.level0` in every later test of the
process and the cache does not reuse them (G-0181).

Calls whose first frame outside Node internals and detjs belongs to the test
runner (vitest, vite, tinypool, jest-*, @jest, expect, …) use the real
functions and are not recorded: the runner's own timeouts and RPC timers keep
real time (Python: pytest plugins keep real timers).

## Parallel (`--det-workers`)

Default: serial, as before. A run is parallel when it is asked for: `--det-workers=N|N%|auto`, or the runner's own
worker option on the command line (Vitest `--maxWorkers=N`, `--fileParallelism`; Jest `--maxWorkers=N`, `-w N`).
`--det-workers=1`, Jest `--runInBand`/`-i` and Vitest `--no-file-parallelism` keep it serial; a `maxWorkers` in a
configuration file does not ask for parallel. `--det-plan=TRACE|JSON` replays the lanes of an earlier run (implies
their number of workers). Code: `node/src/parallel.js`.

**The plan.** After the order and the cache decision (main process, the runner's sequencer), the files that run are
placed in N lanes: `detpy_core::schedule::plan` (the planner of the Python xdist path, napi `planLanes`): atoms =
files, or groups of files joined by a together-edge learnt from an earlier run (below); cost = median of the file's
last 3 recorded durations (`.detjs/plan-state.json`; unknown = median of the known); longest-processing-time first,
ties broken by the atom key's digest; sticky (an atom keeps its previous lane while the makespan stays within 10 % +
1 s of LPT's); every lane is a subsequence of the serial order. The plan is a function of (file list in detjs' order,
seed, worker count, recorded durations, previous plan, together-edges) and of nothing measured during the run; it
is written in the trace header (`meta.parallel.plan`: lanes, digest, digest of its inputs, costs, together-edges,
dispatch order), so `--det-plan=<trace>` reruns the same placement. The files are handed to the runner by planned
start time (a lane's next file when its predecessor should end).

**The lanes.**

| runner | how the plan is held |
|---|---|
| Vitest `threads`, `forks` (isolate=true, the default), 3.x–5.x | `fileParallelism: true`, `maxWorkers: N` (also each project and pool options); every file runs in a fresh worker; before collecting, the detjs runner waits until the previous file of its lane has finished (marker files in the run directory) and sets `VITEST_POOL_ID` to the lane: one file of a lane at a time, in plan order, pool id unique among files running at once (as Vitest's own). The main process also marks a file finished when Vitest reports it final (a worker that died); a worker that waits for a file the runner has not started while every worker waits (a runner whose dispatch order differs from the plan, e.g. Vitest 3 grouping files by environment) goes on after 5 s and reports `lane order broken`. |
| Jest workers (`jest-worker`, child processes), 29.x–30.x | `--maxWorkers=N`; detjs replaces the `Worker` class jest-runner constructs by one with jest-worker's sticky `computeWorkerKey`: the task of a file goes to its lane's worker, lane k bound to worker k before the first task (`JEST_WORKER_ID` = k + 1); each worker process therefore runs exactly its lane's files, in plan order. The workers start with `src/jest/worker.js` preloaded (the cache capture and the test environment wrapping, as the main process does in band). `workerThreads: true` works the same way (the preload goes in the threads' `execArgv`), with and without the cache. |
| Vitest `isolate: false`, `vmThreads`/`vmForks`, browser mode, typecheck; Jest custom `runner`, `--detectOpenHandles`; `--det-record` | parallel refused: the run stays serial and says why (stderr, `meta.parallel.requested.refused`). A worker shared by several files would make placement decide what state a file inherits; network recording writes one cassette per process. |
| Playwright Test (`src/register.js`) | not controlled: Playwright's dispatcher assigns tests to workers at run time; every worker says so on stderr and in `$DETJS_PLAYWRIGHT_PLACEMENT` (JSON lines: pid, worker and parallel index, `placement_controlled: false`, `level0`). `--workers=1` for a fixed placement. Found here (MEASURED, Playwright 1.65.1): Playwright sets `TEST_WORKER_INDEX` only after the worker started, after the preload, so `register.js` does not install the Level 0 controls in its workers at all (`level0: false`); it now says so instead of staying silent. |

**What placement can change, and how it is caught.** Per test, Level 0 resets the clock and reseeds per test id,
so a parallel test's events differ from its serial ones only through what other files did:

* *State carried between files of one process* (Jest: a worker, or the in-band process, runs many files): before
  each file the runner compares Node's shared modules (`fs`, `path`, `http`, `child_process`, `crypto`, … every
  own property, one level into plain objects), the process's global object and its working directory with the
  state before the earlier files of that process; what an earlier file changed and left changed is reported
  (`CARRIED STATE <file>: fs.existsSync (changed by <file>)` on stderr, `meta.parallel.carried`) and the file's
  results are not cached (`carried`). Serially (in band) the same rule applies. Vitest's isolated workers start
  fresh: nothing is carried.
* *Cross-worker interference*: in a parallel run every test process records the paths each file read, listed and
  wrote and the fixed ports it listened on or connected to on loopback; after the run a path one lane wrote and
  another lane read, listed or wrote, or a port two lanes used, is reported (`CROSS-WORKER read-write <path>:
  <file> (lane 1) / <file> (lane 2)`, `meta.parallel.hazards`); both files are not cached (`cross-worker`), and the
  pair becomes a together-edge: the next plan puts them in one lane, in serial order (as the serial run).
  Environment changes do not cross: Vitest threads get a copy of the environment, forks and Jest workers are
  processes, and Jest gives each test file its own copy.
* *Placement variables*: in a parallel run a test that reads its worker or pool id (`JEST_WORKER_ID`,
  `VITEST_POOL_ID`, `VITEST_WORKER_ID`) depends on its lane: its results are not cached (`placement`). Serially
  every test sees `JEST_WORKER_ID=1` (in band) and `VITEST_POOL_ID=1`: the cache keys these reads with that value;
  `VITEST_WORKER_ID` counts the files before a test's file, so a read of it is never cached, serially too. A copy of
  the whole environment (`{...process.env}`: the reads that follow an enumeration) is keyed as the whole
  environment, as before, which holds the serial values only (limit J18).
* *Deviations from the plan*: each file's marker records its process, thread, lane, pool or worker id and the files
  that ran before it in its process; the merge compares them with the plan and reports any difference
  (`PLACEMENT <file>: ...`, `meta.parallel.placement.deviations`).

Cost shown to the user: every serial run ends with `detjs: serial run: N files, X s of test-file time (MEASURED); with
--det-workers=C (this machine's CPUs) about Y s (ESTIMATED ...)`, and the serial header says how to ask for lanes;
a parallel run ends with `detjs: parallel: X s of test-file time ran in Y s across N lanes (MEASURED)`
(`meta.parallel.timing`).

The parallel trace is merged in the serial order; `detjs verify serial.jsonl parallel.jsonl` (or `--det-compare`)
compares every test's fingerprint and outcome.

## Known limits

Found by the shell tests (**T**), by the harness (**H**) or by design (**D**).

| # | limit | found |
|---|---|---|
| J1 | Native addons and child processes are not controlled (they get real clocks, randomness and network); they are recorded (`uncontrolled.child`, `child.result`) and the cache never reuses a test that uses one. Worker threads get the controls but their interleaving with the test is not ordered (`uncontrolled.thread`). Child processes and workers count as pending I/O, so timers wait for real meanwhile. | D |
| J2 | Vitest `vmThreads`/`vmForks` pools and browser mode run tests in another realm than the worker global: the realm controls do not reach them. | D |
| J3 | Jest `setupFiles` run before the detjs test runner (Jest calls them first): code there sees the real globals and its events are not recorded; `setupFilesAfterEnv` is fine. Legacy fake timers (`legacyFakeTimers`) keep Jest's original real timers. Jasmine (`jest-jasmine2`) runners get the controls but no per-test brackets. | D |
| J4 | Fast virtual timers fire in (due time, creation) order; whether a timer fires before or after real I/O completes depends on real scheduling once I/O is pending (the decision uses `process.getActiveResourcesInfo()`), so tests racing timers against sockets or files can still differ (`time` divergences). | D |
| J5 | Infrastructure detection captures a structured stack (8 frames, then 30) on every patched call; the source-mapped site is computed once per distinct raw position and cached. Still the main cost of `--det` on hot clock loops (react-redux: a test rendering 100 000 components with React's scheduler reading the clock: 3 s without `--det`, 25 s with it, 71 s before the cache; MEASURED locally); `--det-sites=off` turns it off (then runner frames are not told apart). References captured before installation (runner internals, Jest `setupFiles`) keep the real objects. | D |
| J6 | `Date.now()` has millisecond resolution: with the 1 µs tick it advances by 1 ms every 1000 reads (or faster under the adaptive tick). | D |
| J7 | Network replay: a replayed socket is a Unix socket (`remoteAddress`/`remotePort` undefined); request bytes that differ from the recording reset the connection (the test sees the error, the trace has `replay-mismatch`, detjs prints the request; G-0130); recorded and replayed connections are closed when their test ends, so keep-alive agents reconnect per test (G-0129); credential request headers (`Authorization`, `Cookie`, `*-token`, `*-key`, ...) are stored as a digest padded to the same length (G-0131); UDP to non-local addresses is refused like a connection (G-0128); sockets intercepted by a mocking library (nock >= 14 / @mswjs/interceptors: an own `connect` on the socket and on its handle) are answered by the mock, the network stays closed for everything else (G-0127). TLS replay does not negotiate ALPN `h2`; `new dns.Resolver()` instances are not guarded (connections are). | T,D |
| J8 | Only the order of directory enumeration is normalised; libraries that issue several asynchronous `readdir` calls in parallel (fast-glob) still merge results in completion order. | D |
| J9 | (Vitest projects get the detjs runner and ordering on every resolved project, found by the harness on date-fns: before the fix project configs ignored them.) A file run by two projects of a Vitest workspace / Jest multi-project config yields two parts with the same test ids; the verifier then keeps one. | D |
| J11 | Playwright Test is measured only (`node/src/register.js`, enabled with `NODE_OPTIONS=--require` in the worker processes): controls without per-test brackets or traces; the browser and web servers are not controlled. Playwright versions that set `TEST_WORKER_INDEX` after the worker starts (1.65.1, MEASURED) get no controls at all; placement across workers is never controlled (see "Parallel"). | D,T |
| J19 | `test.concurrent`, `describe.concurrent` and `sequence.concurrent` still run one test at a time under `--det` (`maxConcurrency: 1`): their waits on virtual timers cost nothing, but waits on real I/O add up (MEASURED here, one file of 8 concurrent tests, 4 waiting 0.5 s on virtual timers and 4 on a child process: Vitest 5.1 plain 2.1 s vs `--det` 3.7 s, Jest 30 plain 3.4 s vs 4.6 s, on a shared 4 vCPU machine). A deterministic interleaving needs per-test clocks, generators and event buffers carried by async context (AsyncLocalStorage) instead of the process-wide test bracket: not built (audit G-1449, G-1456). | D,T |
| J18 | Parallel lanes (`--det-workers`): what a test changes in process state that the carried-state check does not compare (a library's module-level cache outside the vm context, native state) and interference through channels the footprint does not see (native code, child processes, sockets other than fixed loopback ports, a database server) are not detected; a parallel fingerprint that differs from the serial one still shows in `detjs verify`. A test that copies the whole environment and then depends on the worker id inside the copy is keyed with the serial value (the copy is keyed as a whole). A Vitest 3 project whose files use several environments can see `lane order broken` (Vitest 3 dispatches by environment group). A worker that waits for its lane predecessor blocks its thread (`Atomics.wait`). | D |
| J14 | Jest under `--det` runs in band with `--forceExit` by default: a handle left open by a suite would otherwise keep the single process alive forever (react-testing-library hangs in band without `--det` too; in worker mode Jest kills the workers). Recorded in `meta.isolation`. | H |
| J13 | Vitest (and Jest, since matrix-js-sdk: Jest compiles its `testRunner` with the project's Babel config, whose `transform-runtime` then required `@babel/runtime` from detjs's directory) load the detjs runner through a one-line shim in `<root>/node_modules/.detjs/` (removed at exit): a runner outside the project root is served by Vite and refused when the project restricts `server.fs` (found on jotai: 0 of 44 files ran). | H |
| J12 | The wrappers call the runners' Node APIs in-process, so they reproduce what the runners' own CLIs set up first: `NODE_ENV=test` (Jest's bin; Babel configs such as kcd-scripts depend on it), `TEST`/`VITEST`/`NODE_ENV` and the CLI filters at `createVitest` (Vitest's `startVitest`). Found by the harness on user-event and jotai/pinia. | H |
| J15 | CPU time is not virtual time: a loop bounded by a virtual deadline (apollo-client: `setInterval(…, 1)` calling `gc()` for 1000 virtual ms) runs every iteration that the virtual deadline allows (1000 `gc()` calls instead of ~50 in real time) and can exceed the runner's *real* test timeout. The runners' timeouts are not virtualised. | H |
| J16 | A custom Jest `runner` (jest-light-runner, used by babel and prettier) runs the tests without jest-circus's `testRunner`, out of detjs's reach: Level 0 does not apply to them (0 of ~25 000 tests traced); detjs warns and records it in `meta.isolation`. `DETJS_JEST_RUNNER=replace` uses Jest's default `jest-runner` instead, but the suites written for the custom runner (native ESM) then fail (measured: babel 238/238 suites, prettier 1429/1429, under `--det` and the serial reference alike). | H |
| J17 | Each patched call (clock, random, fs) runs a few extra JavaScript frames (the wrapper, event recording, call-site capture): code that recurses close to V8's stack limit can overflow under `--det` only (assistant-ui: a JavaScript bash emulator reported `Maximum call stack size exceeded` in 4 tests). | H |
| J10 | With Vitest `isolate: false`, several files can be collected before the first runs: the module-level seed of later files is approximate. | D |

The harness results (`harness/node/results/`) add the limits found on real
projects; see the report there.
