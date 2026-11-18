PARTIAL (intermediate 2 of P-019: run 4 numbers for all 5 projects; documenso re-measurement after a fix, run 5, pending; REPORT.md follows)

# INTERMEDIATE-2 · P-019 L2 browser round 2

Session P-019. Repository fenvix-engine-cli, branch `claude/l2-browser-r2` (= origin/claude/node-l0 @ 9ffbb0a + round
1's 11 patches + round 2 commits). Measurements on GitHub-hosted runners (4 vCPU, Chromium headless, retries 0,
`--workers=1` for every `--det` run). Reference run: **run 4**
[44284824592](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44284824592) (all 5 projects), plus
**run 5** [44301381294](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44301381294) (documenso after
the fix for a defect run 4 found). Raw data: `tracks/l2-browser-r2/results/` on the branch. Table generator:
`python3 tracks/l2-browser-r2/harness/aggregate.py tracks/l2-browser-r2/results`.

## In one paragraph

The per-source controls closed what they were built for: the start state (database + files) is restored before every
replay, the server's clock and random no longer depend on its background work, web workers are seeded, server pushes
are gated, and the test code's own clock is virtual. Full suites now give one identical fingerprint for 127 of 481
tests on the four non-documenso projects (round 1: 33 of 481), and the one solid-start target replays 10/10 with one
fingerprint. But the exit number is **not reached**: 0 of 15 real flaky targets replay 10/10 with one fingerprint *and*
fail in some seed (target ≥ 60%). What still differs between two replays is no longer a missing control on one
source: it is **when** the runner acts on the page (Playwright lives in real time, page and server in virtual time),
plus clocks outside JavaScript (the database). Both need the heavier design proposed at the end (lockstep virtual
time, ESTIMATED 7-11 days; a VM only for the database-clock class).

## Exit numbers

| Exit number | Target | Result | Label |
|---|---|---|---|
| Real flaky targets that replay 10/10 with one fingerprint **and** fail in some seed | ≥ 60% | **0 of 15 (0%)** | MEASURED, run 4 |
| ... of which replay 10/10 with one fingerprint (any outcome) | - | 1 of 15 (7%): solid-start "hash-only change before hydration" (round 1: 0 of 15) | MEASURED |
| ... of which fail in at least one of seeds 1-8 | - | 3 of 15: actual "keeps the search" (seed 1), uptime-kuma "saves the data retention period" (seed 2), uptime-kuma "RSS feed escapes" (seed 1); their failing seed replayed 10 times gives 7, 9 and 11 fingerprints | MEASURED |
| Tests broken by the controls, per project | < 2% | actual 2/74 = **3%**, etherpad 21/289 = **7%**, solid-start 3/47 = **6%**, uptime-kuma 10/71 = **14%**, documenso 267/595 = 45% in run 4 → run 5 after the fix: pending | MEASURED |
| Slowdown vs the project's configured run (full suite, median wall) | < x3 | solid-start **x2.4**, uptime-kuma x3.4, actual x3.7, documenso x6.4, etherpad x11.4 | MEASURED |
| Replay command works from a clean checkout | works | printed for every failing test and run by the harness for the 3 failing seeds after deleting `.detjs` (except the state snapshot) and `test-results`: it runs, but **0 of 3** reproduce one fingerprint; 1 of 3 reproduces the failing outcome | MEASURED |
| Honest comparison with Playwright retries + trace viewer | - | see section below: today retries + trace viewer are better for these 15 targets | ESTIMATED from MEASURED rates |
| New Playwright projects | optional | none added (reason below) | - |

### Per project (run 4, MEASURED; round 1 in brackets, run 44069979210)

| Project | Tests | Identical fp, full suite (passing every run) | Broken by controls | Slowdown vs configured / vs serial | Targets: one fp 10/10 | Targets failing in some seed |
|---|---|---|---|---|---|---|
| actual (shard 1/3) | 74 | 49 (48) [4] | 2 = 3% [3] | x3.7 / x2.3 [x3.3] | 0 of 4 (2, 6, 3, 5 fp) | 1 of 4 |
| documenso (api + license) | 595 | 382 (68) [303 (6)] | 267 = 45% [510] | x6.4 / x2.6 [x6.3] | 0 of 5 (10 fp each) | 0 of 5 |
| documenso, run 5 (after the fix) | 595 | pending | pending | pending | pending | pending |
| etherpad | 289 | 29 (29) [13] | 21 = 7% [15] | x11.4 / x6.4 [x11.3] | 0 of 2 (3, 2 fp) | 0 of 2 |
| solid-start | 47 | 43 (41) [12] | 3 = 6% [3] | x2.4 / x2.1 [x2.2] | **1 of 1** | 0 of 1 |
| uptime-kuma | 71 | 6 (6) [4] | 10 = 14% [12] | x3.4 / x3.4 [x4.3] | 0 of 3 (7, 9, 10 fp) | 2 of 3 |

Only 2 tests flaked in the 3 baseline runs of this job (both documenso `update-envelope-items`); the 15 fixed targets
are round 1's flaky set, re-checked in plain mode (3 plain runs each: all PPP except documenso EMAIL_TRANSPORT, which
does not run in the suite filter but passes alone). No CPU stress runs this round (budget went to replays).

## Diagnosis (INTERMEDIATE-1) and what each fix did

INTERMEDIATE-1 (`sessions/2026-11-18-l2-browser-r2/INTERMEDIATE-1.md`) listed 7 sources by targets blocked. Every fix
below starts with a fixture test in `node/test/l2r2.test.js` that fails with the round-1 behaviour (shown by a switch,
or by running the old code) and passes after. 8 of 8 l2r2 tests and 5 of 5 round-1 Playwright tests pass locally
(MEASURED).

| # | Source (targets blocked) | Control built | Test | Effect measured on the targets |
|---|---|---|---|---|
| S3 | Start state not restored (documenso 5) | `detjs playwright --det-state=FILE` and `detjs state save\|restore\|status`: files and Postgres databases (template-database copy) restored to one snapshot before every run | file-state test (fails before: replay 2 hits replay 1's user), Postgres restore test (real temp cluster) | documenso targets: P/F in round 1 → **10 of 10 pass** in every replay and seed |
| S1 | Server clock and random shared with background work (6) | clock and seeded random scoped to the message being handled (AsyncLocalStorage): values depend on the message's position and the reads inside it, not on background reads | "server scope" test (DETJS_PW_SCOPE=0 diverges) | solid-start target: 1 fingerprint 10/10; etherpad: every body and frame identical, server fingerprint still differs (see below) |
| S2 | Background jobs in the server fingerprint (6) | request-scoped server fingerprint (sorted events per message; background events counted apart, not fingerprinted) | same test | as S1 |
| S4 | Web worker not seeded (actual 4) | Worker/SharedWorker URLs marked by the page init script; the seed script is prepended to the worker script | "web workers" test (DETJS_PW_WORKER_SEEDS=0 diverges) | actual: worker UUIDs identical in every replay (were the first divergence of all 4 targets) |
| S5 | Server push order (uptime-kuma 3) | WebSocket frames announced to the server; server pushes held to a chunk boundary after a quiet barrier; one-shot timers of a message keep the server busy | "server pushes" test (real entropy race; DETJS_PW_GATE_PUSH=0 shows 2+ orders) | push-vs-response order no longer the first divergence on uptime-kuma |
| S6 | Virtual instant of observation (3) | final DOM taken after the page settles (no running animations) | covered by the suites | partial: the root cause is structural (below) |
| - | Test code's own clock (documenso `new Date()` in seed helpers; found in diagnosis run 2) | the Playwright worker's Date/performance.now are virtual for test code (driver keeps the real clock) | "worker clock" test (DETJS_PW_WORKER_CLOCK=0: 3 fingerprints) + regression test for the stall below | - |
| - | API-only tests not fingerprinted (round-1 gap: `request.newContext` contexts were never patched) | patched | covered by the worker clock test | - |

### Defects of our own found by the measurements (and fixed, each with a regression test)

1. **The worker's virtual clock reached the driver's own pacing** (run 3, cancelled): the test code's `Date.now()` was
   read by the paced grant loop under the test's async stack, page time stalled, uptime-kuma's first `page.goto` never
   reached "load". Fix: the driver captures the real clock at load. Test: "paced virtual time" (fails before).
2. **Test data repeated across tests** (run 4, documenso 266 of 595 tests failing on `Unique constraint failed on
   (email)`): only `Math.random` switched the worker to the test's seeded stream. After a failing test Playwright
   starts a new worker, which began from the same initial stream, so the next test drew the previous worker's crypto
   bytes (documenso's `nanoid()` e-mails), failed, and the cascade repeated. Also every test's virtual clock started at
   the epoch, so `Date.now()`-built names repeated across tests. Fix: every seeded draw switches to the current test's
   stream; each test's clock starts at epoch + (hash of the test id mod 2^31) ms. The same test gets the same values in
   a full run and alone. Test: "unique test data" (fails on the old code and with DETJS_PW_RESEED_ANY=0 /
   DETJS_PW_WORKER_CLOCK_SPREAD=0). Re-measured in run 5: pending.

## What still differs between two replays (run 4, MEASURED first divergences; cause ESTIMATED)

| Class | Where | First diverging event | Cause |
|---|---|---|---|
| A. Instant at which the runner acts | actual (all 4 targets; 10 of 15 sampled suite divergences are the final DOM, 4 the page draw count), etherpad (14 of 15 sampled: final DOM, page draw count 22 vs 21), uptime-kuma (server-busy barrier that times out in one replay and not the other, page draws, DOM) | `page.random` 587 vs 589 draws, `dom.digest`, `server.busy` vs `sched.io` | page virtual time is granted in 20 ms chunks paced by the real clock; Playwright actions, retries and `expect` polling are real-time, so each runner action reaches the page after a real-time-dependent number of chunks. Per-source controls cannot remove this |
| B. Server work still inside a message | etherpad targets (server fingerprint 90 vs 87 events, every body and frame identical) | `server.fingerprint` | ESTIMATED: timers created while handling a message (inherit its async context) fire in real time and land in the message before or after the test ends; same root as A. The diagnosis texts for this run were lost to a harness bug (fixed in 714d5083) |
| C. Clocks outside JavaScript | documenso (all 5 targets: 10 fingerprints in 10 replays; first divergence a response body, e.g. `GET /api/trpc/folder.getFolders` with identical request) | `browser.done` body digest | Prisma's Rust query engine and Postgres `now()` / `@default(now())` write real timestamps into rows the API returns (diagnosis run 2). No per-process JS control reaches them |

Broken by the controls (remaining, by ablation of the 2 sampled per project): mostly the network queue (documenso 2 of
2, etherpad 2 of 2, solid-start 1 of 2, uptime-kuma 1 of 2 pass with `net` off), one with all controls (solid-start
"server function ping": fails with every control off too, so the `detjs` wrapper itself), uptime-kuma
"connects over websocket" (socket.io stays on long-polling under the queue; cause ESTIMATED), uptime-kuma drag-and-drop (fails with every
single control off: combination). Reducing them below 2% means mostly making the queue transparent for long-lived
connections; with lockstep time (below) the queue no longer needs to hold requests in real time.

### Why the exploration found no reproducible failing seed

Seeds reorder queued messages and add seeded latency in virtual time. 3 targets fail in some seed, but replaying that
seed gives 7-11 fingerprints: the failure is real-time-dependent (class A), not seed-determined. On the fixture app
with three cross-process races (round 1 and still in the test suite) a seed does reproduce the failure 3/3 with one
fingerprint: the mechanism works where class A and C are absent.

## Honest comparison with Playwright retries and the trace viewer

- **Retries** (documenso CI config: retries 4, `trace: retain-on-failure`), ESTIMATED from MEASURED baseline rates
  (n = 3 runs): the two tests that flaked in this job's baseline have p = 1/3 and 2/3. With retries 4 the failure is
  reported in 0.4% and 13% of CI runs and **hidden by a retry in 33% and 54%** of runs. A failing attempt is traced in
  33% / 67% of runs.
- **Trace viewer**: gives a recording (DOM snapshots, network, console) of the one failing attempt; it does not replay
  it. For our 15 targets it is today strictly more useful than `detjs`: a `detjs` replay of the failing seed does not
  fail again with one fingerprint (0 of 3), so the replay command is not yet a reproduction.
- **Where `detjs` already adds something** (MEASURED): one command that restores the start state (documenso: the 5
  targets went from P/F in two replays to 10/10 passing), per-test fingerprints that say *which* event first differs
  (the diagnosis table of this round was built with them in hours), and on apps without class A/C behaviour (fixture
  app, most of solid-start: 43 of 47 tests identical) a seed that reproduces a cross-process race.
- Not measured: the time a developer needs to find a flake's cause with each tool (UNKNOWN).

## The heavier design: lockstep virtual time (proposal, with cost)

Evidence that per-source controls stop short: after S1-S5 the remaining first divergences on actual, uptime-kuma and
etherpad are of one kind (class A): the page did a different amount of work before the runner's next action (page
draw counts 22 vs 21, a toast mid-animation, the page's socket.io messages in another order, a server barrier that
times out in one replay only). The runner (test code, Playwright's own retry waits, `expect` polling) lives in real
time; the page and the server live in virtual time. No per-source control removes that gap.

Design (one clock for runner, browser and server, inside the customer's runner, no VM):
1. In the Playwright worker, the Playwright server's waits (retry intervals, `waitForTimeout`, actionability and
   `expect` polling intervals) and the test code's timers become virtual timers of one scheduler.
2. Page virtual time advances only inside the scheduler, never paced by the real clock. While a CDP command to a page
   is pending (the runner waits on the page), the scheduler grants chunks; while the runner computes between two
   commands, page time is frozen. The CDP pipe is ordered, so a command's answer always precedes the end-of-chunk
   event: the number of chunks per wait is a function of the page's state, not of real time.
3. When nothing is runnable (no pending command, no queued message, servers quiet), the scheduler jumps virtual time
   to the earliest due timer among the worker, the pages and the app servers (`/__detjs/advance`) and fires it. Server
   background timers then fire at deterministic points of the run (today they fire in real time: class B).
4. Deadlines (test timeout, `expect` timeout) become virtual: a test fails on its virtual budget, the same in every
   replay; a wall-clock guard stays as a safety net.

What it covers: classes A and B, seeded exploration of timing (a seed can stretch any wait, not only hold a response),
and most of the slowdown (idle time is skipped instead of waited: etherpad spends ESTIMATED one third of its extra time
in up-to-1 s server-busy waits, 597 of them in one run, MEASURED count). What it does not cover: class C (clocks
outside JavaScript: Prisma's query engine, Postgres `now()`) and real I/O latency. Those need clock virtualisation
below JavaScript (an LD_PRELOAD clock shim for the engine library, a database with a controlled clock) or the
deterministic VM of ARCHITECTURE.md L2.

Cost (ESTIMATED, one engineer-session stream): scheduler and virtual waits for Playwright 1.5x-1.6x internals 4-6
days; server `/__detjs/advance` with gated background timers 2-3 days; re-measure on the 5 projects 1-2 days: **7-11
days**. Risk: Playwright internal APIs change between versions (mitigation: patch at module level per minor version, a
compatibility test per Playwright release). Expected slowdown: lower than today's paced mode, UNKNOWN until measured.

The VM route (ARCHITECTURE.md L2) remains the complete answer for class C and load-induced failures; ESTIMATED
months, not days, and it moves the customer off their own runner. **Proposal: lockstep first** (it keeps the product
inside `runs-on`), clock shim for the database engine second, VM later only if the count of tests in class C stays
high: that count is the go/no-go number (today documenso: all 5 targets, and 206 of 595 suite tests whose first divergence is
a network event, MEASURED in run 4, an upper bound for class C).

## Decisions taken in this session

- The server fingerprint is **request-scoped**: only events in the async context of a message the queue released are
  fingerprinted; background work is counted, not fingerprinted. Reason: background work (stats, log rotation, dev
  server scanners) is not part of what a test observes; fingerprinting it made identical tests look different.
- The test code's clock is virtual (per test, its own instant). Reason: seed helpers write `new Date()` into rows the
  app returns.
- Start state is a **spec file** (`{"files": [...], "postgres": [urls], "commands": {...}}`) saved by the first run
  and restored before every replay, not an automatic database discovery. Reason: explicit, works with any Postgres the
  test uses; other databases through `commands`.
- No new Playwright project was added: all 5 round-1 projects run in baseline this round (rallly, broken in round 1,
  was not among the 5), and the budget went to replays of the 15 targets.
- No draft PR opened: the session's system rules forbid opening a PR unless the founder asks; the branch is pushed.

## What blocks / what is missing

- The exit number needs lockstep virtual time (class A/B) and a database clock (class C). Not started: it is a design
  change for the founder to approve (above).
- Broken-by-controls stays above 2% on every project; the remaining ones are mostly the network queue holding
  long-lived connections and real-time waits.
- The "clean checkout" check runs the printed command in the same job after deleting `.detjs` (except the state
  snapshot) and `test-results`; a fresh `git clone` + install was not done (cost of a second install per project).
- CPU-stress baselines were not run this round, so the 15 targets' flake rates are round 1's.

## Links

- Branch: https://github.com/Mircoguidetti/fenvix-engine-cli/tree/claude/l2-browser-r2
- Main commits: efa7555d (`--det-state`), 5bb972c7 (S1/S2/S4/S5/S6 controls, exploration), 1de5878d (worker seeds,
  fixture tests), cd86d2e7 (replay command, harness), 0af1fa94 (worker clock, API contexts, HMR passthrough), 0b4357d6
  (driver real clock fix), 697c9729 (unique test data fix), 714d5083 (harness keeps diagnosis evidence)
- Code: `node/src/pw/{worker,server,snapshot,cli,reporter,page-init}.js`, `node/src/{clock,seeds}.js`,
  `node/test/l2r2.test.js`, `docs/L2-BROWSER.md` (round 2 section), harness `tracks/l2-browser-r2/harness/`
  (`study.py`, `diagdiff.py`, `aggregate.py`), workflow `.github/workflows/l2-browser-r2.yml`
- Runs: diagnosis [44275149752](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44275149752) and
  [44279789112](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44279789112); run 3
  [44283131715](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44283131715) (cancelled, carried
  defect 1); run 4 [44284824592](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44284824592); run 5
  [44301381294](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44301381294)
- Status file: `tracks/l2-browser-r2/STATUS.md`

## Errors or gaps found in this brain

- `sessions/README.md` says the first line is DONE, NOT DONE or BLOCKED; P-019 asks for DONE or PARTIAL. This report
  follows the prompt.
- P-019 says the branch is "based on origin/claude/node-l0 @ 9ffbb0a plus round 1's patches"; round 1's harness lives
  only on `claude/loving-maxwell-58mv2w` (`tracks/l2-browser/`), so it was copied to `tracks/l2-browser-r2/` here.
- COMMON.md asks for a draft PR at the end; the session's system rules forbid opening a PR unless the founder asks
  explicitly. The coordinator should say which rule wins.
- INTERMEDIATE-1's first line was "PARTIAL (intermediate 1 ...)" because no other word fits an intermediate delivery.
