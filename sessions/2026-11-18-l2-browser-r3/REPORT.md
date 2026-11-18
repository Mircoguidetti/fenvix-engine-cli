PARTIAL

# REPORT · L2 browser round 3 (review R-011: FIX 6, experiments E1, E2, E5, E6, step 3, decision)

Session 2026-11-18, branch `claude/l2-browser-r3` of fenvix-engine-cli (= round 2 delivery `claude/l2-browser-r2` @
786181b + `review-input/` + the reviewer's six failing tests). Measurements on GitHub-hosted runners (4 vCPU) unless
marked "local" (this container, 4 vCPU). Raw data: `tracks/l2-browser-r3/results/`. Tables:
`python3 tracks/l2-browser-r3/harness/analyze.py`. Runs: PENDING.

## In one paragraph

PENDING

## 1. The six review tests (all fail on 786181b, MEASURED)

| Test | After this branch | What changed |
|---|---|---|
| R1 `node/test/review-r011.test.js` (elapsed-time budget hidden) | **passes** (local; Actions build job of run 44326292154: 18 of 18 fixture tests pass) | The test code's clock adds the real time waited since the test's first clock read, floored to 1 s (`DETJS_PW_WORKER_CLOCK_WAIT_MS`). The 1.5 s request now measures >= 1100 ms under `--det`: the test fails as it does plain |
| R2 same file (12.5 days of skew) | **passes** (same) | The test code's clock follows the app server's message clock (epoch + released messages x 100 ms), strictly increasing over the run (persisted across worker restarts). Skew in the fixture: under 1 ms. Round 2's per-test hash offset (up to 24.8 days) is gone |
| H1 `tracks/l2-browser-r2/review/test_review_r011.py` | **passes** | `aggregate.py`: a target is *control-induced* when it is in `broken_by_controls` or passes in every plain run while every default-seed `--det` replay fails; control-induced targets count toward none of "identical", "fail in some seed", "failing seed reproduces", "replay command reproduces", and are reported apart (`control_induced`) |
| H2 | **passes** | same rule: `fail in some seed` on the round-2 data is **0 of 15** (was 3; the 3 are control-induced) |
| H3 | **passes** | Cause found: actual runs `playwright test --browser=chromium` with a config without projects; the printed command kept `--project=chromium` and dropped `--browser=chromium`, so it matched no project and ran no test. Fix: the replay command carries `--browser`/`--timeout`/`--ignore-snapshots`; fixture test `node/test/l2r3.test.js` "H3" fails before (checked by restoring the old `reporter.js`) and passes after. Re-measured on actual (run 44327291710, MEASURED): seed 1 times out, the printed command `npx detjs playwright --det --det-seed=1 --det-epoch=... test e2e/accounts.mobile.test.ts:67 --project=chromium --browser=chromium` runs its test and times out too. Written into `tracks/l2-browser-r2/results/actual.json` by `tracks/l2-browser-r3/harness/remeasure_h3.py`, the round-2 value kept as `replay_cmd_outcome_r2: "missing"` |
| H4 | **passes** | `aggregate.py` counts and lists tests that fail in every configured run and pass in every `--det` run (`hidden_by_controls`): 1 on the round-2 data (documenso `should reject order change on a PENDING envelope`, FFF / PP) |

Regression suites after the fixes (local, MEASURED, final engine): `playwright.test.js`, `l2r2.test.js`, `l2r3.test.js`,
`review-r011.test.js`: **19 pass, 0 fail, 1 `todo`** (a defect found this round, section 6).

**Cost of the R1 fix (MEASURED, section 4 E5):** the real-wait part makes any date the test code reads more than 1 s
after its first read depend on real time. documenso's seed helpers write such a date (`emailVerified`), so its replays
cannot be identical while the part is on. It is a switch (`DETJS_PW_WORKER_CLOCK_WAIT_MS`, default 1000, 0 = off):
outcome truth (R1) and value determinism conflict for elapsed-time reads, and only a clock that also advances with the
waits on the other side (lockstep, or a VM) removes the conflict. Decision for the founder/coordinator; the default
keeps R1 (a silent pass is worse than a non-identical fingerprint).

**Defect of this round's fix, found and fixed (MEASURED):** a clock read in test code *outside any test* (module level,
worker fixtures) left the wait origin at 0, so the wait part became the whole real time since 1970: documenso's
`emailVerified` came out as `2083-10-06T20:02:32Z` under a 2026 epoch, and different in every replay. Fixed in the
worker (`firstReal` set at install, no wait part outside a test), regression test `l2r3.test.js` "a clock read outside
any test" (fails before: test-code date 2081 under a 2025 epoch; passes after). Every `--det` number of runs
44327291710 and 44326636551 (step 3, E2, H3) was measured with this defect; step 3 was re-run on the fixed engine
(section 5).

## 2. Corrections to the round-2 report (the claims the reviewer marked wrong)

| Round-2 claim | Corrected |
|---|---|
| "3 of 15 fail in at least one of seeds 1-8" and "Why the exploration found no reproducible failing seed" | **0 of 15**. All 3 failures are caused by the controls (plain runs of the same filter PPP): actual "keeps the search" times out in 10 of 10 default-seed replays; uptime-kuma "saves the data retention period" and "RSS feed escapes" are in uptime-kuma's broken-by-controls list. The exploration found no failing seed at all; the paragraph described our own breakage |
| Replay command "runs" for the 3 failing seeds; "1 of 3 reproduces the failing outcome" | It ran its test in **2 of 3** (actual: no outcome, cause in section 1 H3). The one that "reproduced" (uptime-kuma, F) reproduced a failure the controls cause, not a flake |
| "127 of 481 identical fingerprints" | Arithmetic right; "identical" means equal in the **2** full-suite `--det` runs (`det: 2`), not 10 of 10 |
| "Only 2 tests flaked in the baseline (both documenso update-envelope-items)" | One is `admin-find-documents ... recipient prefix matches by recipient name` (FPP), the other `update-envelope-items ... combined title and order change` (FPF) |
| "all PPP except documenso EMAIL_TRANSPORT ... passes alone" | In run 5 EMAIL_TRANSPORT ran **PFP** plain: it failed alone 1 of 3, the only target that flaked without detjs in round 2 (10 replays + 8 seeds under `--det` all pass) |
| documenso's 8 broken = 3 goto timeouts + 1 send timeout + 3 expired | 3 + 1 + 3 = 7; the 8th is `template-field-prefill v2` (toBeVisible). The 2 ablated are `persist-embed-signature` and `expired-recipient-field-signing`, not the timeouts |
| (not in any round-2 table) | documenso `update-envelope-items ... should reject order change on a PENDING envelope` fails in 3 of 3 configured parallel runs and passes with `--workers=1` and in both `--det` runs: a parallel-worker failure `--det` hides (now counted, H4) |
| Diagnosis class A on etherpad ("14 of 15 sampled: final DOM, page draw count") | The 15 samples were the first 15 diverged tests in suite order (one file). Suite-wide reasons: **net 210**, other 25, sched 17, random 8 of 260: 81% of etherpad's divergences start at a network event, unclassified |
| Class A on actual (runner acts in real time) | Supported only as "the end-of-test observation differs": the two diverging events are taken by detjs's own real-time settle loop. Tested in E2 (section 4) |
| documenso's 3 "expired" tests: ESTIMATED cause test-vs-server clock skew | Proven by R2 (12.5 days of skew on a fixture) and fixed in the engine; not yet re-measured on documenso |
| The 4 non-documenso projects were measured on the delivered engine | Run 4 (their only measurement) predates fix 697c9729; re-run in step 3 (section 5) |

## 3. E1: the target set re-established

Each project's suite selection as its CI runs it (configured Playwright workers, retries 0), **20 runs plain and 10
runs under round 1's CPU stress** (one busy process per core), failure message kept for every failure. Run 44327291710
(5 round-1/2 projects) and 44326636551 (new project), MEASURED. Selection differences from round 2: actual runs its 3
target files (47 tests, 4 workers) instead of shard 1/3, because "keeps the search" is outside shard 1/3; documenso adds
the ui target file to its api + license selection.

| Project | Tests | Flaky without load (fail in plain runs) | Flaky only under stress | Round-1/2 targets that failed at all |
|---|---|---|---|---|
| actual (3 target files) | 47 | 3: "extends after budgeting" desktop **4/20**, "applies budget template" Tracking **8/20**, Envelope 1/20 | 6: every `accounts.mobile` test and 2 more time out under stress (beforeEach 60 s, 9-10 of 10) | **4 of 4**: 2 without load ("extends", "applies budget template"), 2 under stress only ("keeps the search", "reconciles": 0/20 plain, 10/10 stressed) |
| documenso (api + license + ui file) | 599 | **31**: 27 `read ECONNRESET` on runner API requests, 2 `update-envelope-items` (`toBeFalsy`, **15/20** and 7/20), 2 EMAIL_TRANSPORT (`Element is outside of the viewport`, 5/20 each, never both in one run) | 10: 9 ECONNRESET, 1 `template-field-prefill` toBeVisible | **2 of 5**: EMAIL_TRANSPORT (5/20 plain), DELETE_RECIPIENT "a missing reason" (4/20 plain, ECONNRESET). FIND_DOCUMENTS x2 and SEARCH: 0/30 |
| etherpad | 289 | 0 | 0 | **0 of 2** (0/30 each) |
| solid-start | 47 | 0 | 0 | **0 of 1** (0/30) |
| uptime-kuma (1 worker, as configured) | 71 | 1: "saves the data retention period" **1/20** (3/10 stressed) | 1: "RSS feed escapes" (0/20, 1/10: test timeout) | **2 of 3**; "creates a group": 0/30 |
| **sveltekit** (new, `basics` app, CI leg `pw:dev` js 1/2, 4 workers) | 254 | 0 | 3: INP "does not block next paint" (403.6 ms vs a 400 ms budget), `data-sveltekit-preload-code` (2/10), `preload-data` (1/10) | - (no prior targets) |

**What this says (MEASURED):** of round 1/2's 15 targets, **7 never failed** in 30 runs each (etherpad 2, solid-start 1,
documenso FIND_DOCUMENTS x2 and SEARCH, uptime-kuma "creates a group"): the reviewer's ceiling of 8 of 15 holds with
one change (uptime-kuma "data retention" did fail plain this time, actual "reconciles" and "keeps the search" only
under stress). Across the 6 projects there are **55 flaky tests** in 30 runs each (plain + stressed), by mechanism (from
the failure messages; mechanism ESTIMATED where marked):

| Mechanism | Tests | Projects | Without load? | What reproduces it |
|---|---|---|---|---|
| M1 `read ECONNRESET` on a runner API request (mechanism UNKNOWN: the keep-alive close/reuse race was the first guess, a local fixture did not produce it, section 6) | 36 | documenso | yes (27 of 36) | parallel API workers + a network layer that can make the server's close cross the runner's reuse |
| M2 parallel-worker data interference (`update-envelope-items`, passes with `--workers=1` in round 2) | 2 | documenso | yes | one scheduler across N workers |
| M3 shared UI list + random names + parallel workers (EMAIL_TRANSPORT; mechanism UNKNOWN) | 2 | documenso | yes | multi-worker scheduling, maybe seeds alone (UNKNOWN) |
| M4 runner vs app ordering in one worker (uptime-kuma: the test's fill lands before the page loads the saved value: received "18030"; actual "Failed to navigate to the next month") | 2 | uptime-kuma, actual | yes | seeded latency on the right response, under a runner-gated clock (lockstep) for one fingerprint |
| M5 timeouts under CPU starvation (actual 8 incl. "applies budget template", uptime-kuma RSS, documenso 1) | 10 | actual, uptime-kuma, documenso | 2 of 10 (actual "applies budget template", slow even unstressed) | a seed space that reaches the deadlines (E6) + one fingerprint per replay |
| M6 perf budget / counters under load (sveltekit) | 3 | sveltekit | no | INP: CPU time as virtual time (VM-class); preload counters: seeded latency (ESTIMATED) |

## 4. E2, E5, E6

### E2 freeze-before-observe (actual, run 44327291710, MEASURED)

`--det-freeze=on`: at the end of the test function the pages stop receiving virtual time and the final DOM and page
random stats are taken at once (no real-time settle loop). 10 frozen replays and 5 control replays (same engine, no
freeze) of actual's 3 targets that passed in round 2:

| Target | Frozen: outcomes, fingerprints | Control: outcomes, fingerprints | First divergence (frozen) |
|---|---|---|---|
| "applies budget template" | 10 P, **6 fp** | 5 P, 3 fp | event #199 `page.random` (draw counts 699 vs 702) |
| "extends after budgeting the last month" (desktop) | 10 P, **1 fp** | 5 P, **1 fp** | - |
| "reconciles an account" | 10 P, **10 fp** | 5 P, 5 fp | event #3: `server.busy` vs `worker.seeded` (a scheduling event, at the start) |

**Decision (MEASURED):** freezing the observation does not make actual's replays identical. Where they differ, the
divergence is in the page's work before the end of the test (draw counts) or in scheduling at the start. Class A on
actual is not only our settle loop. "extends after budgeting" already gives one fingerprint on this engine with or
without freeze (round 2: 3 fp). The fixture test (`l2r3.test.js` E2) shows the same thing: a page that keeps ticking
while the runner polls in real time gives 2 fingerprints in 3 runs, frozen. The cheapest next check of lockstep's core
hypothesis is the reviewer's E3 (grants only while a runner call is in flight), not run this round.

### E5 database clock under libfaketime (documenso, MEASURED)

Postgres (container, same data volume) and the app server's Node process (Prisma's Rust engine lives in it) under
libfaketime pinned to the run's epoch, `FAKETIME_DONT_FAKE_MONOTONIC=1`. Three variants, 10 `--det` replays of 2
targets each (run 44382873510, file `e5-documenso-attempt3.json`; attempts 1 and 2 failed to start Postgres under
libfaketime, kept as `e5-documenso-attempt1/2.json`; the control comes from attempt 1, run 44327291710). These runs
carry the clock defect found below:

| Variant | Database `now()` confirmed | FIND_DOCUMENTS non-admin | DELETE_RECIPIENT missing reason | First divergence |
|---|---|---|---|---|
| control (real clocks) | real time | 5 P, **5 fp** | 5 P, **5 fp** | `GET /api/auth/session-json` body |
| start-at epoch (clock runs) | `20:02:03.27` | 10 P, **10 fp** | 10 P, **10 fp** | same |
| frozen at epoch | `20:02:00` exactly | 10 P, **10 fp** | 10 P, **10 fp** | same |
| epoch + 1 ms per clock call | `20:02:00.137` | 10 P, **10 fp** | 10 P, **10 fp** | same |

**What differs, then (job `e5diag`, run 44389754462, DB frozen, the two `session-json` bodies kept):** only
`"emailVerified":"2083-10-06T20:02:32.328Z"` vs `"...20:02:46.008Z"`. That date is made by documenso's seed helper in
**test code** (`new Date()`), and it exposed a defect of this round's test-code clock (section 1: reads outside any
test pushed the clock to epoch + real time). Fixed, then E5 again on the fixed engine (run 44407937328, 5 replays per
arm, MEASURED):

| Arm | FIND_DOCUMENTS non-admin | DELETE_RECIPIENT missing reason | First divergence |
|---|---|---|---|
| real clocks, wait part on (default) | 5 P, 5 fp | 5 P, 5 fp | event #29 `folder.getFolders` body / event #24 scheduling choice |
| real clocks, wait part off (`DETJS_PW_WORKER_CLOCK_WAIT_MS=0`) | 5 P, 5 fp | 5 P, 5 fp | event #24 scheduling choice / #29 body |
| DB + app process frozen by libfaketime, wait part off | 5 P, 5 fp | 5 P, 5 fp | **event #24: the queue chose the page's `GET folder.getFolders` in one replay and the test's `admin.recipient.delete` (or `admin.document.find`) API request in the other** |

**Decision (MEASURED):** documenso's first divergence is not a clock below JavaScript. With the session-json date
fixed, every arm (frozen database included) first differs at the network queue: whether the page's background fetch
or the runner's next API request is pending first depends on when the runner acts in real time. That is class A, the
same as actual and uptime-kuma. Round 2's class C ("clocks outside JavaScript", proposal "clock shim second")
does not hold as the blocker on these targets. libfaketime works for Postgres (also checked locally on Postgres 16 in
all three modes, about an hour of setup as the reviewer expected), but buys nothing measurable until class A is gone.

### E6 a seed space that reaches the deadlines

Fixture (local, MEASURED, `l2r3.test.js` E6): a page loads data with three chained fetches and the test expects it
within 2 s. Round 2's latency list (`0,0,0,1,5,25` chunks = max 500 ms): seeds 1-8 **all pass**. With a choice `D` that
holds a message for 1.5 x the deadline (`--det-latency=0,0,1,5,25,D`): seed 6 fails, and its 3 replays fail with **one
fingerprint**. So exploration can reach load-induced timeouts once the seed space reaches the deadlines.

Real targets (run 44383743101, MEASURED): the two real flakes that fail without load and run in one worker:

| Target (real failure) | Round-2 list, seeds 1-8 | Deadline list, seeds 1-8 | Failing seed replayed 5x | Same failure as the real one? |
|---|---|---|---|---|
| actual "extends after budgeting" ("Failed to navigate to the next month", 4/20 plain) | 8 P | 8 F (7 "selected-budget-month not found", 1 timeout) | 5 F, 3 fp | **no**: the hold breaks the page before the step that flakes |
| uptime-kuma "data retention" (received "18030", 1/20 plain) | 1 P, 6 F (received "180" or ""), 1 skipped | 8 F (field not found / "180") | 5 F, 5 fp (round-2 list), 5 F, 3 fp (deadline) | **no** |

**Decision (MEASURED):** a seed space that reaches the deadlines reproduces a timeout on a fixture, but on the two real
targets it produces failures of our own (earlier steps, other values) and never the real one. Holding any message
blindly breaks the test at its first wait. Reproducing a real flake needs a seed space aimed at the step that flakes
(hold only messages released after the page the failing step uses has settled, ranked by distance to the failing
assertion), and a way to say "same failure": the failure message and location must match the plain failure.
aggregate.py should count a seed as reproducing only then (today: any failure counts).

## 5. Step 3: the 4 non-documenso suites on this engine

Two full `--det` runs per suite on this branch's engine (697c9729 + the R1/R2 clock), compared with the plain runs of
the same job (20 for etherpad, solid-start and uptime-kuma; 2 runs of shard 1/3 for actual) and with round 2 run 4
(engine without 697c9729). Run 44327291710, MEASURED. The new project is in the last row.

| Project | Broken by the controls (round 2 run 4) | Same tests? | Hidden by the controls | Identical fingerprints in 2 runs (round 2) | First-divergence reasons | Slowdown vs plain |
|---|---|---|---|---|---|---|
| actual (shard 1/3, 74) | **2 = 2.7%** (2) | same 2 (`moves a category`, Envelope + Tracking) | 1 ("applies budget template" Envelope: failed both plain shard runs, passed both `--det`) | **26** (49) | random 42, other 6 (round 2: other 17, random 8) | x3.0 (vs 2 plain runs of 433-448 s that had 60 s timeouts; NOISY) |
| etherpad (289) | **20 = 6.9%** (21) | 20 in both; `timeslider follow` no longer broken | 0 | 31 (29) | net 194, sched 31, other 24, random 9 | x12.8 |
| solid-start (47) | **3 = 6.4%** (3) | same 3 | 0 | 42 (43) | sched 4, other 1 | x2.4 |
| uptime-kuma (71) | **10 = 14.1%** (10) | 9 in both; "filters monitors by tag" new; "data retention" no longer counted (it failed once plain this time) | 0 | 9 (6) | sched 49, net 11 | x3.8 |
| sveltekit (254, new) | **43 = 16.9%** | - | 0 | 144 | other 60, sched 33, net 15 | **x13.5** |

So fix 697c9729 and the R1/R2 clock did not change the broken lists of the 4 projects (MEASURED: 34 of the 36 round-2
broken tests are broken again; etherpad `timeslider follow` passes now; uptime-kuma "data retention" failed once plain so
it no longer counts as ours; 1 new). Identical fingerprints moved within 3 on etherpad, solid-start and uptime-kuma, but
**fell on actual from 49 to 26** with first divergences now at `random` events (page draw counts). Cause: PENDING (A/B
job below).

## 6. Found this round

- **Unread fetch body holds the network queue** (MEASURED, local fixture): a page `fetch` whose body is never read
  gets no `requestfinished`, so the queue releases nothing else until the 5 s completion timeout. Fixture: passes
  plain in 210 ms, fails under `--det` on its 2 s deadline. Test: `l2r3.test.js` "unread fetch body" (`todo`).
  Cheapest fix (ESTIMATED 2-4 hours): complete fetch/XHR items on response headers and record the body digest at a
  fixed slot of the test's event list when it arrives. Likely contributor to the remaining goto/send timeouts among
  the broken-by-controls (UNKNOWN until re-measured).

- **M1 is not the simple keep-alive race** (MEASURED, local, `tracks/l2-browser-r3/fixtures/keepalive-*.js`): a
  Node server with `keepAliveTimeout` 50 ms and 20 ms, a Playwright API request context reusing the socket with idle
  gaps around the timeout, server in the same and in a separate process, runner idle or busy-waiting when the close
  arrives: **0 errors in 2 200 requests** (800 + 800 in-process, 600 with a separate server process). documenso's 36 ECONNRESET tests (section 3) have another cause or a narrower
  window; UNKNOWN.

## 7. Decision

### The fair target set and the reachable share

The fair set is the **55 tests that both passed and failed in E1** (6 projects, 30 runs each, configured workers,
plain + stressed), each with its failure message (section 3). A test counts as reachable by a design when that design
gives 10/10 replays with one fingerprint **and** a seed whose failure is the real one (same message and step).
Today (MEASURED): **0 of 55**. No seed reproduced a real failure (E6: 0 of 2 tried). Replays are not identical on the
three projects that flake without load: documenso (E5, every clock arm), actual (E2, frozen or not), uptime-kuma
(E6 replays: 3-5 fp). After this round's fixes, **the first divergence on all three is the same kind: when the runner
acts in real time** (documenso: which of the runner's request and the page's fetch reaches the queue first; actual:
page draw counts and early scheduling events; uptime-kuma: queue order, `sched` 49 of 62 diverged tests). The
database clock is not the first blocker on documenso (E5).

| Design item | Needed for | Tests of 55 it unlocks (with the items above it) | Cost (ESTIMATED, engineer-days) | UNKNOWN that could stop it |
|---|---|---|---|---|
| **1. Lockstep** (runner-gated virtual time: page time advances only while a runner call is in flight; virtual deadlines) | identical replays on actual, uptime-kuma **and documenso** (class A, now measured on all three) | 0 alone (it gives determinism, not a failing seed) | **1-2 for the E3 spike**, then 7-11 (round-2 estimate) | E3: does gating the grants on runner calls make actual's / documenso's replays identical? E2 ruled out the observation-only explanation |
| **2. Seed space aimed at the flaking step** (holds only after the page that the failing step uses has settled; deadline-reaching; a seed counts only if its failure matches the real message) | M4 runner-vs-app order (2), M5 timeouts (10), M6 preload counters (2) | 14 (25%) | 2-3 | whether one aimed hold gives uptime-kuma's "18030" and actual's "Failed to navigate" (E6: a blind hold does not) |
| **3. Multi-worker scheduling** (one scheduler across N Playwright workers; `--det` stops forcing `--workers=1`, which today hides documenso's parallel failure) | M2 (2), M3 (2) and the concurrency of M1 | 18 (33%) | 5-8 | ordering N worker processes' messages without serialising them |
| **4. Network layer for socket faults** (a seeded proxy between runner/page and server that can reset or delay a connection at a chosen point) | M1 `read ECONNRESET` (36 tests, documenso) | **54 (98%)** | 3-5 once M1's mechanism is known | M1's mechanism: the keep-alive guess gave 0 errors in 2 200 requests on a fixture; capture the server side of one failing request first (1 Actions job) |
| Database clock shim (libfaketime on Postgres + the app process) | nothing measured (E5) | 0 | 0.5-1 to productise | - |
| CPU time as virtual time | M6 INP budget (1, sveltekit) | 55 (100%) | VM-class | - |
| **VM** (ARCHITECTURE.md L2) | all 6 mechanisms | 55 | months (UNKNOWN in days) | leaves the customer's runner |

What reaches **>= 60%** (ESTIMATED, every row's count is MEASURED, its reachability is not):

- **By test count** (33 of 55): items 1 + 2 + 3 + 4 (54 of 55 if every UNKNOWN resolves): **18-29 engineer-days**
  (spike 1-2, lockstep 7-11, aimed seeds 2-3, multi-worker 5-8, network layer 3-5). Lockstep + aimed seeds alone
  reach at most 14 of 55 (25%); without item 4 the ceiling is 18 of 55 (33%). Caveat: 41 of the 55 are documenso, 36
  of them one message (ECONNRESET), so this share is mostly one project and one mechanism.
- **By mechanism** (4 of 6) **or by flaking project** (3 of 4: actual, documenso, uptime-kuma, sveltekit): items
  1 + 2 + 3 (M2, M3, M4, M5; actual, uptime-kuma, documenso): **15-24 engineer-days**.
- A VM covers all 6 mechanisms including the INP budget, at a cost of months.

Lockstep is necessary (it is the determinism half for every project that flakes without load) but not sufficient:
on its own it adds 0 reproduced flakes, and its first deliverable must be the E3 spike, not the 7-11 day block.

### Proposal

1. **E3 spike first** (1-2 days + 1 Actions job): grant page time only while a runner call is in flight, on actual
   ("applies budget template", "reconciles"), uptime-kuma ("data retention") and documenso (FIND_DOCUMENTS,
   DELETE_RECIPIENT). Go if >= 4 of 5 reach one fingerprint in 10 replays.
2. In parallel, two cheap deciders ($0): the server side of one documenso `ECONNRESET` (1 job; M1's mechanism decides
   item 4), and one aimed hold on uptime-kuma's settings response (2 hours + 1 job; decides item 2).
3. **Change the exit metric** (founder/coordinator decision): count a target only when the seed's failure matches the
   real failure (message + step), on the E1 set, reported per test **and** per mechanism, with control-induced and
   hidden tests apart (`aggregate.py` now reports both).
4. If E3 passes: next round = lockstep + aimed seeds + multi-worker (15-24 days, ESTIMATED), target >= 60% by
   mechanism; the network layer after it for the test-count share. If E3 fails: the per-process design has reached
   its limit on these apps and the VM route needs its own estimate (UNKNOWN today).
