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

Regression suites after the fixes (local, MEASURED): `node/test/l2r2.test.js` + `playwright.test.js` 13 of 13 pass;
`l2r3.test.js` 3 of 3 pass + 1 `todo` (a defect found this round, section 6).

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
| M1 `read ECONNRESET` on a runner API request (keep-alive socket closed by the server while the runner reuses it; ESTIMATED) | 36 | documenso | yes (27 of 36) | parallel API workers + a network layer that can make the server's close cross the runner's reuse |
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
targets each (run 44382873510; attempts 1 and 2 failed to start Postgres under libfaketime, kept as
`e5-documenso-attempt1/2.json`; the control comes from attempt 1, run 44327291710):

| Variant | Database `now()` confirmed | FIND_DOCUMENTS non-admin | DELETE_RECIPIENT missing reason | First divergence |
|---|---|---|---|---|
| control (real clocks) | real time | 5 P, **5 fp** | 5 P, **5 fp** | `GET /api/auth/session-json` body |
| start-at epoch (clock runs) | `20:02:03.27` | 10 P, **10 fp** | 10 P, **10 fp** | same |
| frozen at epoch | `20:02:00` exactly | 10 P, **10 fp** | 10 P, **10 fp** | same |
| epoch + 1 ms per clock call | `20:02:00.137` | 10 P, **10 fp** | 10 P, **10 fp** | same |

**Decision (MEASURED):** with the database clock and the app process's clock pinned, documenso still gives a new
fingerprint in every replay, and the first diverging event does not move. The database clock is not what makes
documenso diverge, or not alone; round 2's class C (and its "clock shim second" proposal) rests on run-2 texts that
showed `createdAt` differences, but those are not the first divergence under pinned clocks. What differs in
`session-json`: PENDING (job `e5diag`, run 44389754462, two replays with the bodies kept). libfaketime itself works for
Postgres (also checked locally on Postgres 16 in all three modes): a clock shim costs about an hour of setup, as the
reviewer expected, but buys nothing measurable here yet.

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

## 7. Decision

PENDING
