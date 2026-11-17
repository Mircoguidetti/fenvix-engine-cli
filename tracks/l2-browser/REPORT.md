PARTIAL

The measurement is complete (final run 44069979210 landed for all 5 projects), but the exit is not reached: **0 of 15
real flaky browser tests replay 10/10 with one fingerprint** (MEASURED), and the controls break tests in every project.

# REPORT · track l2-browser (P-014): Level 2 for browser end-to-end tests

Updated 2026-11-17. Engine: local branch `track-l2-browser` = `origin/claude/node-l0` @ `9ffbb0a` + the 11 patches in
`patches/` (`git am`). Measurement: `.github/workflows/l2-browser.yml` on this branch (push to `RUN`), harness
`harness/`, raw results `results/<name>.json` (+ `results/<name>/` diagnostics), tables from
`python3 harness/aggregate.py`. **Every real-project number below is from the final run 44069979210** (nonce 9; GitHub
Actions hosted runners, 4 vCPU; Chromium headless; retries 0; virtual epoch = the job's start minute), unless it says
otherwise. rallly is excluded (its baseline is broken in our setup: every test fails or times out also without detjs).

## Headline

- **Exit number: share of real flaky browser tests that replay 10/10 with one fingerprint and pass in some seed:
  0 of 15** (MEASURED; etherpad 2, documenso 5, actual 4, uptime-kuma 3, solid-start 1). All 15 were replayed 10 times
  under `--det`; every one gave 2-10 distinct fingerprints in 10 replays. Sources: 12 known flaky tests from earlier
  batches / the idle study, 3 found in this job's baseline + stressed runs.
  - The **outcome** repeated 10/10 in 9 of 15 (MEASURED). Two of those 9 (actual "keeps the search after opening a
    transaction", uptime-kuma "saves the data retention period") fail in all 10 replays and in every seed while plain
    runs of the same filter pass 3/3: they behave as broken by the controls, not as a reproduced flake.
  - uptime-kuma "RSS feed escapes malicious monitor names" flips under `--det` with the default seed (PPPFFPFPPF) while
    plain runs pass 3/3 (MEASURED): the controls do not fix its order.
  - documenso's 5 targets replay P then 9 x F with 2 fingerprints. ESTIMATED cause: seeded random makes the same test
    users/emails in every replay, the Postgres database is not reset between runs, so replays 2-10 hit
    `Unique constraint failed on the fields: (email)`. The 9 identical failing replays are this collision, not a
    reproduced flake. "Fail in some seed: 8 of 15" includes these 5.
  - **Fixture app** (3 cross-process races built for the purpose): 2 of 2 flaky tests replay with one fingerprint
    (10/10 and 3/3), pass in one seed and fail in another, and the failing seed fails again 3/3 with one fingerprint
    (MEASURED, local and on Actions). The mechanism works where the app has no uncontrolled background work.
- **Tests broken by the controls** (pass in every baseline run, fail in at least one `--det` run; MEASURED):
  - four projects (actual, etherpad, solid-start, uptime-kuma): **33 of 481 tests (28 in every `--det` run)**:
    actual 3/74, etherpad 15/289, solid-start 3/47, uptime-kuma 12/71.
  - documenso separately: **510 of 595 (269 always)**, dominated by the database collision above (ESTIMATED cause).
- **Full-suite fingerprints identical across `--det` runs** (MEASURED): four projects **33 of 481** (32 of them passing
  in every run; the two "33"s are a coincidence). documenso 303/595, but 263 of those are identical *failures*, 34
  skipped, only **6 passing**.
- **Slowdown** of `--det` (MEASURED, median wall of the full suite vs the project's configured run / vs `--workers=1`):
  solid-start x2.2 / x2.0, actual x3.3 / -, uptime-kuma x4.3 / - (already serial), etherpad x11.3 / x5.9, documenso
  x6.3 / - (but most documenso tests failed under `--det`, so its time is not a clean slowdown). "-": no serial run in
  this job.
- **Comparison with Playwright retries** (ESTIMATED from MEASURED baseline rates, n = 3-4 runs): a test with p = 0.25
  under documenso's CI retries 4 is reported in 0.1% of CI runs and hidden by a retry in 25%; with
  `retain-on-failure` its failing attempt is traced in 25% of runs. The trace is a recording to read, not a replay.
  `--det` aims at a replay command, and on the real projects it does not yet deliver one.

## Final-run tables (`python3 harness/aggregate.py`, run 44069979210)

| Project | Tests | Baseline runs (normal+stress) | Flaky in this job | Baseline wall s | Serial wall s | Det wall s | Slowdown vs configured / serial | Identical fp, full suite (passing every run) | Broken by controls |
|---|---|---|---|---|---|---|---|---|---|
| actual (shard 1/3) | 74 | 3+2 | 7 | 274 | - | 895 | x3.3 / - | 4/74 (3; 2 runs) | 3 (3 always) |
| documenso (api+license) | 595 | 4+2 | 12 | 248 | - | 1565 | x6.3 / - | 303/595 (6; 2 runs) | 510 (269 always) |
| etherpad | 289 | 4+2 | 1 | 148 | 283 | 1664 | x11.3 / x5.9 | 13/289 (13; 2 runs) | 15 (13 always) |
| solid-start | 47 | 3+1 | 1 | 44 | 48 | 96 | x2.2 / x2.0 | 12/47 (12; 3 runs) | 3 (2 always) |
| uptime-kuma | 71 | 2+2 | 0 | 276 | - | 1185 | x4.3 / - | 4/71 (4; 2 runs) | 12 (10 always) |

Flaky tests targeted (P pass, F fail; `-` not in that run). All MEASURED.

| Project | Flaky test | Source | Baseline | Stress | Plain, same filter | 10 replays `--det` | Distinct fp | Seeds 1-4 | Failing seed, 3 replays |
|---|---|---|---|---|---|---|---|---|---|
| actual | Mobile Accounts: keeps the search after opening a transaction | known | PPP | FP | PPP | FFFFFFFFFF | 10 | FFFF | seed 1: FFF (4 fp) |
| actual | Mobile Budget: applies budget template | known | PPP | FP | PPP | PPPPPPPPPP | 10 | PPPP | - |
| actual | Automatic budget range: extends after budgeting the last month | known | PPP | PP | PPP | PPPPPPPPPP | 10 | PPPP | - |
| actual | Mobile Accounts: reconciles an account | known | PPP | FP | PPP | PPPPPPPPPP | 10 | PPPP | - |
| documenso | FIND_DOCUMENTS: non-admin user is rejected with 401 | known | PPPP | PP | PPP | PFFFFFFFFF | 2 | PPPP | - |
| documenso | FIND_DOCUMENTS: recipient prefix with numeric value | known | PPPP | PP | PPP | PFFFFFFFFF | 2 | PPPP | - |
| documenso | SEARCH: non-admin authenticated user is rejected | known | PPPP | PP | PPP | PFFFFFFFFF | 2 | PPPP | - |
| documenso | EMAIL_TRANSPORT: updating a subscription claim | known | (ui project, not in suite) | | PPP | PFFFFFFFFF | 2 | PPPP | - |
| documenso | DELETE_RECIPIENT: a missing reason is rejected | this job | PFPP | PP | PPP | PFFFFFFFFF | 2 | PPPP | - |
| etherpad | embed links: the embed as iframe code (read only) | known | PPPP | PP | PPP | PPPPPPPPPP | 10 | PPPP | - |
| etherpad | embed links: share link encodes pad names | this job | PPPP | PF | PPP | PPPPPPPPPP | 10 | PPPP | - |
| solid-start | handles a hash-only change before hydration | this job | PPP | F | PPP | PPPPPPPPPP | 10 | PPPP | - |
| uptime-kuma | saves the data retention period | known | PP | PP | PPP | FFFFFFFFFF | 10 | FFFF | seed 1: FFF (4 fp) |
| uptime-kuma | creates a group from the monitor form | known | PP | PP | PPP | PPPPPPPPPP | 10 | PPPP | - |
| uptime-kuma | RSS feed escapes malicious monitor names | known | PP | PP | PPP | PPPFFPFPPF | 10 | F P P (3 seeds) | seed 1: FPF (4 fp) |

Caveat (unchanged from the interim report): most of these flakes appeared only in stressed runs (one CPU hog per core);
the `--det` replays and plain runs were unstressed, so "passes under `--det`" says little about them. Only documenso's
DELETE_RECIPIENT (baseline PFPP) is a baseline flake among the targets.

### Ablation: which control breaks which test

Scope: the first 3 always-broken tests per project (14 tests); one single-test run per cell (MEASURED, n = 1 each).
"Server off": app server without Level 0 controls; "net off": no ordered HTTP/WebSocket queue; "vtime off": no CDP
virtual time; "seeds off": no seeded Math.random/crypto in pages and test code.

| Project | Broken test | All on | Server off | Net off | Vtime off | Seeds off | Reading |
|---|---|---|---|---|---|---|---|
| etherpad | Remembers the username after a refresh | F | F | **P** | F | F | net queue |
| etherpad | pad deletion token, modal suppressed | F | F | **P** | F | **P** | net queue or seeds |
| etherpad | creator-owned pad settings act as defaults | F | F | **P** | F | **P** | net queue or seeds |
| uptime-kuma | clears the heartbeats shown in the monitor | T | F | **P** | F | F | net queue |
| uptime-kuma | past incidents section is hidden | T | **P** | T | **P** | T | server controls + virtual time together |
| uptime-kuma | moves a monitor to another group by drag | F | F | F | F | F | no single control |
| documenso | FIND_DOCUMENTS: non-admin user is rejected | F | F | F | F | **P** | seeds (fits the email collision) |
| documenso | FIND_DOCUMENTS: recipient prefix matches | F | F | F | F | F | no single control |
| documenso | sendDocument: should not block initial send | F | F | F | F | T | no single control |
| solid-start | server function ping | F | F | F | F | F | no single control (or the serial wrapper config) |
| solid-start | server function only referenced inside onClick | P | P | P | P | P | passes alone: fails only after other tests |
| actual | Mobile Budget [Envelope]: moves a category | P | P | F | P | F | passes alone: suite/order dependent |
| actual | Mobile Budget [Envelope]: applies budget template | P | P | P | P | P | passes alone: suite/order dependent |
| actual | Mobile Budget [Tracking]: moves a category | P | F | F | P | F | passes alone: suite/order dependent |

(T = timed out.) Summary of the 14 (MEASURED, single runs): **the ordered network queue alone cures 4** (all 3 etherpad,
1 uptime-kuma; two of them also cured by seeds off), **seeds alone 1** (documenso), **server or virtual time 1**
(uptime-kuma), **5 fail with every single control off**, **4 pass alone with all controls on** (they break only inside
the full `--det` suite: order or accumulated state). The other 19 broken tests of the four projects and 507 of
documenso were not ablated: which control breaks them is UNKNOWN.

### Comparison with Playwright's own retries and trace viewer

Only tests with 0 < p < 1 in this job's baseline (retries 0); ESTIMATED with independent attempts, n = 3-4 runs per p.

| Project | Flaky test | p (baseline) | CI retries r | P(failure reported) = p^(r+1) | P(hidden by retries) = p(1-p^r) | CI trace | P(failing attempt traced) |
|---|---|---|---|---|---|---|---|
| actual | Mobile Budget [Tracking]: applies budget template | 1/3 | 1 | 0.111 | 0.222 | - | - |
| documenso | 6 tests (DELETE_RECIPIENT missing reason, Inbox status pagination, soft-delete search, team template visibility, audit-log move, ...) | 1/4 each | 4 | 0.001 | 0.249 | retain-on-failure | 0.250 |

With `trace: 'on-first-retry'` (etherpad, uptime-kuma) a failing attempt is traced with probability p^2; with
`retain-on-failure` (documenso) with p. Either way the trace is a recording (DOM snapshots, network, console; DECLARED,
Playwright docs) and cannot run the failure again. `--det --det-seed=N` is meant to be that replay command: on the
fixture it is one; on the 5 real projects it is not yet (0 of 15 above).

## What was built

- `docs/L2-BROWSER.md` (one page): what is controlled, what is not (limits B1-B8), what a full VM would add.
- `detjs playwright --det [--det-seed=N] [playwright test args]` (`node/src/pw/`) and `detjs serve --det -- <cmd>` for
  servers started before the runner. Controls: CDP virtual time in 20 ms chunks (`paced`: never ahead of real time);
  seeded Math.random/crypto in every frame and in the test code; Level 0 of detjs in Node app servers (seeded generators
  and OS entropy, one virtual wall clock, virtual timers, sorted readdir) with per-test brackets (`x-detjs-test`) and a
  quiet barrier; one ordered queue for documents, fetch/XHR, the runner's `request` calls and page-to-server WebSocket
  frames (seeded with `--det-seed`), released only between virtual-time chunks; workers serialised. Per-control
  switches (`--det-server/net/vtime/browser-seeds=off`). One shared trace in the Level 0 format, compared by the Rust
  verifier.
- `node/test/playwright.test.js`: 5 tests on the fixture (pass locally and on Actions, MEASURED).
- Harness `harness/`: per project, baseline runs (own parallelism, retries 0), stressed runs, serial run, known flaky
  tests targeted (10 replays under `--det`, seeds 1-4, 3 replays of the first failing seed, 3 plain runs), full-suite
  `--det` runs, ablation of broken tests.

## Engine bugs found and fixed (each with a test that fails before the fix and passes after)

1. App server whose path contains `playwright` taken for a runner helper and left uncontrolled.
2. First `page.goto` right after a virtual time grant deadlocked (MEASURED 2 of 6 single-test runs hung before, 0 of
   10 after).
3. `page.goto` and a runner API request issued together were ordered by browser latency (2 fingerprints in 10 runs
   before, 1 after; MEASURED).
4. Without `--det`, `node_modules/.bin` was not on PATH: webServer commands (`cross-env`, `next`) failed.
5. In app servers Vite counted as test-runner infrastructure and kept the real clock (solid-start).

## Why fingerprints still diverge (from the verifier's first divergence; ESTIMATED)

- **Server background work** (etherpad, solid-start, uptime-kuma: first divergence is `server.fingerprint`, event
  counts differ by 1-8): file watchers, dev-server transforms, socket.io heartbeats and timers at real deadlines
  interleave with request handling.
- **Server-to-page WebSocket frames and response bodies** (uptime-kuma: `ws.recv` / `browser.done` bodies differ;
  etherpad 207 of 276 diverged tests by `net`): frames are relayed as they arrive, not gated to chunk boundaries.
- **Page draw order** (actual: 25 of 70 diverged tests first differ at `page.random`, with different draw counters; the other 45 at the server fingerprint): the app's logic runs
  in a web worker outside virtual time and seeds (limit B3).
- **Persistent state** (documenso): seeded identities + a database that survives between runs; also the order of
  the first event (runner API request vs page) differs between replays.

## What is still missing to reach the exit

1. **Hermetic state per replay**: database reset/snapshot between `--det` runs (documenso; Level 0's job, not done
   for browser projects). Without it, a seeded replay is a different test.
2. **Server background work under control**: either a request-scoped server fingerprint (only events caused by the
   test's requests) or virtual time for watchers/heartbeats; the main cause in 3 of 5 projects.
3. **Gating of server-to-page WebSocket frames** to virtual-time chunks (socket.io apps), and a fix for the net queue,
   which alone breaks 4 of the 14 ablated tests.
4. **Web workers** inside virtual time and seeds (actual).
5. **Stressed `--det` replays**: most targets flaked only under CPU load; the replays were unstressed.
6. Each of 1-4 needs a failing test first. With these, the 10/10 fingerprint share on real projects is UNKNOWN; a
   deterministic VM (Level 2 as designed) would cover 2-4 by construction.

## Honest assessment

Process-level Level 2 makes most browser + Node server tests repeat their **outcome**, but not their **fingerprint**
on real apps (0 of 15 flaky targets, 33 of 481 full-suite tests on four projects; MEASURED). It breaks 7% of tests on
four projects (33 of 481) and costs x2.2-x11.3 wall time (MEASURED). On a purpose-built fixture it does what Level 2
promises. The gap is uncontrolled server background work, server push, web workers and non-hermetic state.
