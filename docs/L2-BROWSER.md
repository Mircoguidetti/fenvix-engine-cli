# Level 2 for browser tests (prototype)

Goal: a Playwright test that touches a browser and an app server gives the same result and the same
fingerprint in every run with the same seed, and a seeded change of the free choices (which message arrives
first) explores the orders a real run can take. This is Level 2 of `docs/ARCHITECTURE.md` reached from the
outside: instead of one deterministic VM around every process, each process of the run is controlled by its
own shell and the messages between them go through one ordered queue. Command: `detjs playwright --det
[--det-seed=N] [playwright test args]` (`node/src/pw/`); servers started outside the runner: `detjs serve
--det -- <command>`.

## Why

Every flaky e2e test found by the idle study (6 of 6, `harness/idle_study/REPORT.md` on
`claude/loving-maxwell-58mv2w`, MEASURED) is cross-process: browser vs server, runner vs app server under load,
two workers on one filesystem. Level 0/1 control one process; these need the browser, the server and the
messages between them under one schedule.

## What is controlled

| Source of difference | Control | Where |
|---|---|---|
| Browser time (Date, performance.now, setTimeout, requestAnimationFrame, CSS animations) | CDP `Emulation.setVirtualTimePolicy`, policy `advance` with a budget: virtual time is granted in chunks of 20 ms, starting at the run's epoch; `paced` (default) never lets it run ahead of real time, `fast` skips idle time | `worker.js` `setupPage` |
| Randomness in pages (Math.random, crypto.getRandomValues, crypto.randomUUID) | init script in every frame: xoshiro128** seeded from (seed, test id, document URL); draw counters and a digest go into the fingerprint | `page-init.js` |
| Randomness in test code (random names, e-mails) | the Level 0 generators of detjs in the Playwright worker, reseeded per test | `worker.js` `installWorkerSeeds` |
| App server (Node) | Level 0 of detjs in the server process: seeded Math.random, crypto and OS entropy, one virtual wall clock for the run, virtual timers, sorted readdir; network left open (databases). Per-test bracket: the first request carrying `x-detjs-test` switches the server's fingerprint and generators to that test | `server.js` |
| Order of HTTP messages (documents, fetch, XHR from pages; `request` fixture calls from the runner) | one queue per worker: a request waits for a 15 ms quiet window, then one pending request is chosen (sorted by method, URL and body digest; with `--det-seed`, a seeded choice) and runs to completion before the next one. Before each release the worker waits for the app server to be quiet (`/__detjs/quiet`: no request in flight, event loop idle 20 ms) | `worker.js` `pump`, `barrier` |
| WebSocket frames | `routeWebSocket` relay: page-to-server frames go through the same queue; server-to-page frames are recorded (heartbeats excluded) | `worker.js` `setupWebSockets` |
| Responses vs page timers | the queue releases only between two virtual time chunks: a response always lands at a chunk boundary, never in the middle of a timer burst | `whenPaused`, `whenQueueIdle` |
| Workers | `workers=1`, `fullyParallel=false`, `retries=0` forced through a wrapper config | `wrap.cjs` |

Fingerprint (one shared trace, `.detjs/trace.jsonl`, same format and Rust verifier as Level 0): per test, the
queue choices, request and response digests, WebSocket frame digests, page random stats, a digest of the final
DOM of every page, the server's per-test fingerprint and the outcome. `detjs verify A B ...` compares runs.

## What is not controlled (prototype limits)

- B1 Server written in another language: only `detpy` (Python) has the same controls; the bracket header and
  the quiet barrier are not implemented there yet (the order of requests still is).
- B2 Databases, caches, mail catchers and other services: real time and their own scheduling. The quiet
  barrier waits for the app server, not for them.
- B3 Web workers, service workers, iframes of other origins: not seeded; their timers follow the page's
  virtual time only where Chrome applies it.
- B4 Firefox and WebKit: no CDP virtual time; only Chromium is controlled.
- B5 Pages opened by the app (popups) get virtual time when Playwright reports them, a few milliseconds late.
- B6 Rendering and layout (fonts, GPU, viewport races such as "element is outside of the viewport"): the
  same inputs at the same virtual instants, but the compositor still runs in real time.
- B7 Long-lived requests (long polling, event streams, dev-server pings) pass outside the queue
  (`DETJS_PW_PASSTHROUGH`).
- B8 Parallel workers: serialised (`--workers=1`), which also removes load-induced failures instead of replaying them.

## What a full VM would add later

A deterministic VM (one core, recorded inputs: Antithesis-style, or rr/Hermit for Linux processes) would cover
B1, B2, B3 and B6 at once: databases and non-Node servers, the compositor, thread scheduling inside Chrome, and
exact replay of load-induced failures (the scheduler can slow one process on purpose). Costs: a whole-run
slowdown on CPU-bound suites (the idle study measured 1.04 to 3.9 busy cores per suite, MEASURED, all of which
a one-core VM serialises), a custom hypervisor or kernel, and container images instead of the customer's
runner. The prototype keeps the customer's runner and measures how far process-level control gets.

## Round 2 (P-019): controls added after the diagnosis

The round 2 diagnosis (two `--det` replays of each of 15 real flaky targets, first diverging event below the
digests) found six sources; each control below has a fixture test in `node/test/l2r2.test.js` that fails with the
round 1 behaviour and passes with the control.

| Source | Control | Switch |
|---|---|---|
| S3 start state (a replay finds the rows of the previous one) | `--det-state=FILE`: files and Postgres databases restored to one snapshot before every run (first run saves it; Postgres via `CREATE DATABASE ... TEMPLATE`); `detjs state save|restore` for servers started before the runner | `--det-state` |
| S1 server clock and random shared with background work | every message the queue releases is handled in its own async context on the server; clock values = the message's logical instant (epoch + n x 100 ms, n = messages the server received) + reads at the same call site x tick; random from a stream per (test, message, call site) | `DETJS_PW_SCOPE=0` restores round 1 |
| S2 background jobs in the server fingerprint | the test's server fingerprint is the list of its messages, each digested as the sorted events of its own context; events outside every message context (heartbeats, pool reapers, watchers) are counted, not fingerprinted. WebSocket frames are announced (`/__detjs/frame`) so their handling gets a context too | same |
| S5 server push vs response order | server-to-page frames are held and delivered at the next virtual-time chunk boundary, after the server is quiet | `DETJS_PW_GATE_PUSH=0` |
| S4 web workers | `Worker`/`SharedWorker` URLs created by a page are marked; the worker script is served with the seed script prepended | `DETJS_PW_WORKER_SEEDS=0` |
| S6 final DOM mid-animation | the DOM digest is taken once two snapshots 100 ms apart are equal (at most 10 tries) | `DETJS_PW_SETTLE_MS=0` |

Exploration: with `--det-seed=N` a released message may first wait a seeded number of virtual-time chunks (0, 0, 0,
1, 5 or 25; `DETJS_PW_LATENCY`), so slow-server schedules are explored and the failing one replays. Every failing
test prints its replay command (`detjs: replay <test>:` + `npx detjs playwright --det --det-seed=N
--det-epoch=... [--det-state=...] test <file>:<line> --project=<p>`), also written to `.detjs/replay.txt`.

What the fingerprint now means: the same messages crossed the process boundaries in the same order with the same
contents (requests, responses, frames), the pages drew the same random values and ended in the same DOM, and the
server handled every message of the test with the same events and values. The order of events between concurrent
chains inside one message is not fingerprinted (values no longer depend on it: they are keyed by call site);
background work is visible only through its effects on later messages.

Known limit (round 2): Playwright actions reach the page after a number of virtual-time chunks that depends on real
time (the runner is not on the virtual clock). Lockstep time (page time advances only while the runner waits on the
page, and the runner's own waits are virtual) would close it; see the round 2 report.

## Round 3 (review R-011): fixes and experiment switches

- **Test-code clock** (`worker.js` `installWorkerSeeds`): one clock for test code and app server. Value =
  max(previous value + 1 ms, epoch + released messages x `DETJS_PW_SERVER_STEP_MS` + real time since the test's first
  clock read floored to `DETJS_PW_WORKER_CLOCK_WAIT_MS` (default 1000)). The server's clock is epoch + messages
  received x STEP, so test code and server agree on "now" to within the time one test waited (round 2: up to 24.8 days
  apart); an elapsed-time budget missed by a real wait of >= 1 s still fails (round 2: 1 ms per read, waits invisible);
  values are strictly increasing over the run, also across worker restarts (`<DETJS_DIR>/worker-clock.json`).
  Residual (DECLARED): a budget missed by less than 1 s can pass under `--det`; values read more than 1 s after the
  test's first read depend on real time (not deterministic); the server's clock still does not advance with waits.
- **Replay command** (`cli.js`, `reporter.js`): carries `--browser`, `--timeout`, `--ignore-snapshots` (a config
  without projects run with `--browser=chromium` has a project only through that flag).
- **`--det-freeze=on`** (experiment E2): at the end of the test function (Playwright's didFinishTestFunction
  callbacks) every page of the test stops receiving virtual time and the final DOM and page-random stats are taken at
  once, without the real-time settle loop.
- **`--det-latency=LIST`** (experiment E6): seeded latency choices in 20 ms chunks; `D[factor]` holds a message for
  factor (default 1.5) x the test's deadline (`DETJS_PW_DEADLINE_MS`, else the project's expect timeout, else 5000 ms).
  The default list `0,0,0,1,5,25` (max 500 ms) never reaches a deadline.
- Found on a fixture while building E6 (MEASURED, not fixed): a page `fetch` whose body the page never reads does not
  complete (`requestfinished` never fires), so the network queue holds every later message until the 5 s completion
  timeout (`DETJS_PW_COMPLETE_TIMEOUT`): a test with a 2 s deadline failed under `--det` in every seed and passes plain.
