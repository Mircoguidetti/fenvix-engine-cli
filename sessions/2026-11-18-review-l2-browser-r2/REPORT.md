FIX 6

# Review R-011 · P-019 L2 browser, round 2

Reviewer session, 2026-11-18. Delivery: fenvix-engine-cli `claude/l2-browser-r2` @ 786181b (this branch,
`claude/review-r011`, is that commit + `review-input/`). Contract: P-019 "Done means". Report reviewed: REPORT.md
(PARTIAL) + INTERMEDIATE-1/2. Runs 44284824592 (run 4) and 44301381294 (run 5): both exist, `push` on
`claude/l2-browser-r2`, conclusion success (checked through the API). Run 5's head (4dabab63) has the same `node/`
code as the delivered commit; run 4's head (ac22f224) does **not** contain fix 697c9729.

Six failing tests, committed on this branch:

- `node/test/review-r011.test.js` (R1, R2: engine, real Chromium fixtures): `node --test test/review-r011.test.js`
- `tracks/l2-browser-r2/review/test_review_r011.py` (H1-H4: measurement):
  `python3 -m unittest tracks/l2-browser-r2/review/test_review_r011.py -v`

All six FAIL on the delivered commit (MEASURED, this container). The PARTIAL verdict of the delivery stands; the
six are about what the numbers and the controls claim, and about the base the next design would be measured on.

## What I re-ran

| What | Result | Label |
|---|---|---|
| `node --test test/l2r2.test.js test/playwright.test.js` (after `npm ci` + `npm run build` of the native core) | **13 of 13 pass**, 2 min 17 s | MEASURED |
| `python3 tracks/l2-browser-r2/harness/aggregate.py tracks/l2-browser-r2/results` | same tables as the report | MEASURED |
| Independent recomputation from `results/*.json` (own script: outcomes per run, medians, broken = PPP baseline and ≥1 F in `--det`) | matches, see Q1 | MEASURED |
| Round 1 raw data (`claude/loving-maxwell-58mv2w:tracks/l2-browser/results/`) joined with round 2 per target | see Q2 | MEASURED |
| Diagnosis texts in history (run 2 diag files, commit 178fe48; deleted from the tree by the run-4 commits) | see Q1 | MEASURED |
| GitHub Actions | none started (kept light: every number was recomputable from the committed raw data) | - |

## Q1. Are the numbers right?

| Report claim | Recomputed | Verdict |
|---|---|---|
| 0 of 15 targets meet the exit number | 0 of 15 | correct |
| 1 of 15 replays 10/10 with one fingerprint (solid-start) | 1 (solid-start, 1 fp in 10) | correct |
| 127 of 481 identical fingerprints (4 projects), round 1: 33 | 49+29+43+6 = 127; round 1 4+13+12+4 = 33 | arithmetic correct; **"identical" means equal in 2 full-suite `--det` runs**, not 10/10 (`det: 2` in params) |
| Broken by controls: actual 2/74, etherpad 21/289, solid-start 3/47, uptime-kuma 10/71, documenso 267 (run 4) → 8/595 (run 5) | identical, both with aggregate.py and independently | correct as counted; but (a) actual's target "keeps the search" times out in 10/10 `--det` replays with plain PPP and is outside shard 1/3, so it is in no broken count; (b) only pass→fail is counted (H4) |
| documenso run 4: 382 identical (68 passing), x6.4, 206 net | 382, 68, x6.37, net 206 (file at 8d74be1) | correct |
| Slowdown: solid-start x2.4, uptime-kuma x3.4, actual x3.7, documenso x4.6 (run 5), etherpad x11.4 | 2.35, 3.44, 3.68, 4.60, 11.37 (median of 2 det runs / median of 3 baselines) | correct |
| Failing seed replayed: 7, 9, 11 fingerprints | 7, 9, 11 (11 = 10 replays + the seed's first run) | correct |
| 3 of 15 "fail in some seed" | 3 by aggregate.py, **but all 3 are failures the controls cause** (plain PPP; two are in uptime-kuma's broken list; actual's times out 10/10 with the default seed). Round 1 said so explicitly; round 2 presents them as exploration results | **wrong reading** (H2) |
| Replay command "runs" for the 3 failing seeds, 1 of 3 reproduces the failing outcome | actual: outcome `missing` (the printed command did not produce a result for its test); uptime-kuma: F (a failure we cause); RSS: P | **wrong** (H3); the "1 of 3" is a reproduction of a control-induced failure, not of a flake |
| "Only 2 tests flaked in the baseline (both documenso update-envelope-items)" | one is `admin-find-documents … recipient prefix matches by recipient name` (FPP), the other `update-envelope-items … combined title and order change` (FPF) | wrong wording (NOTE) |
| "all PPP except documenso EMAIL_TRANSPORT … passes alone" | run 5 (the documenso reference run): EMAIL_TRANSPORT plain runs **PFP**: it failed alone 1 of 3, the only target that flaked without detjs this round; 10 replays + 8 seeds under `--det` all pass | wrong for run 5 (NOTE; it matters for Q2) |
| documenso's 8 broken = 3 goto timeouts + 1 send timeout + 3 expired | 3 + 1 + 3 = 7; the 8th is `template-field-prefill v2` (toBeVisible); the 2 ablated are `persist-embed-signature` and `expired-recipient-field-signing`, not the timeouts | wrong breakdown (NOTE) |

Not in any table: documenso `update-envelope-items … should reject order change on a PENDING envelope` fails in
**3 of 3** configured (parallel) runs and **passes** in the `--workers=1` run and in both `--det` runs (H4). The
three failures this job's baseline found are all parallel-worker failures, and all three pass under `--det`.

### Is the diagnosis supported by the traces?

| Class | Evidence in the delivered data | Verdict |
|---|---|---|
| C. Clocks outside JavaScript (documenso) | Run-2 diag texts (history, 178fe48): bodies differ only in `createdAt`/`updatedAt`/`id`, with **real** wall times 12 s apart (`10:01:26.204Z` vs `10:01:38.746Z`) while the run's virtual epoch is the job's start minute. Run 4/5: all 15 sampled first divergences are `browser.done` bodies; 348 of 364 diverged tests have a `net` first divergence | **supported** (Prisma engine vs Postgres `now()` not separated; the run-4/5 texts were not kept) |
| A. When the runner acts — actual | 14 of 15 sampled first divergences are the last 3-4 events of the test (`page.random` stats, `dom.digest`): every request, response and choice before them is identical. Suite-wide reasons: other 17, random 8 of 25 | **supported as "only the end-of-test observation differs"**. Those two events are taken by detjs's own `settle()` loop (`worker.js:604-621`), which sleeps real 100 ms steps while page virtual time keeps being granted. So the evidence shows the *observation instant* is real-time dependent; it does not show that runner actions change what the app does |
| A. — etherpad | Report: "14 of 15 sampled: final DOM, page draw count". The 15 samples are the first 15 diverged tests in suite order, all from one file (`a11y_dialogs.spec.ts`). Suite-wide (`det_verify.reasons`, same JSON): **net 210**, other 25, sched 17, random 8 of 260 | **not supported**: 81% of etherpad's divergences start at a network event (bodies or WebSocket frames), which no table explains |
| A. — uptime-kuma | sched 44, net 14, other 4, random 3 of 65: mostly the queue's choice order (`sched.io`, `server.busy`) | consistent with real-time arrival at the queue; not shown to be the runner |
| B. Server work inside a message (etherpad targets) | `server.fingerprint` 90 vs 87 events; diag texts lost (the report says so) | asserted, ESTIMATED as labelled |

## Proven errors (6 failing tests)

| # | Test | Fails because | Why it matters |
|---|---|---|---|
| R1 | `review-r011.test.js` R1 | The test code's clock advances 1 ms per read (`installWorkerSeeds`), not with time waited. A test asserting a request answers within 1 s (server takes 1.5 s real) **fails plain and passes under `--det`** (elapsed under `--det`: 1 ms) | The controls silently turn a real failure into a pass: any elapsed-time budget in test code (perf budgets, "within N ms" checks, deadline loops) stops testing anything. No counter sees it |
| R2 | `review-r011.test.js` R2 | The test code's clock starts at epoch + (hash of test id mod 2^31) ms (fix 697c9729); server and page start at the epoch. Fixture: test vs server "now" differ by **1 079 841 630 ms = 12.5 days** under `--det`; the test passes plain | Proves the ESTIMATED cause of documenso's 3 broken "expired" tests. It is a defect of the round-2 fix, cheap to fix (one wall clock shared by test code and server, uniqueness from the per-test read counter or a sub-second per-test offset), not something that needs lockstep. It applies to every project, but the 4 non-documenso projects were measured (run 4) **without** this fix |
| H1 | `test_review_r011.py` H1 | A synthetic target the controls break deterministically (plain PPP, every `--det` run fails with one fingerprint) is counted by aggregate.py as identical 10/10 **and** reproduced by its failing seed **and** reproduced by the replay command | The exit metric counts tests we break as successes. Any next design that makes control-induced failures deterministic would inflate the headline number |
| H2 | H2 | aggregate.py `fail_seed` = 3; all 3 are control-induced (see Q1) | The report's "3 of 15 fail in some seed" and its paragraph "why the exploration found no reproducible failing seed" read our own breakage as exploration |
| H3 | H3 | actual's printed replay command produced no outcome for its test (`missing`) | The report says the command "runs" for 3 of 3; it ran its test in 2 of 3 |
| H4 | H4 | aggregate.py has no count of tests that fail in the configured run and pass under `--det` (documenso: 1, FFF → PP) | `--det` forces `--workers=1` (`cli.js:138`): failures that need parallel workers disappear and the reported numbers cannot show it |

Fix expectations: R1/R2 in the engine (each with the test passing); H1/H2/H4 in aggregate.py (control-induced
failures excluded from the exit metric and reported apart; fail→pass counted); H3: find why the command produced no
outcome and either fix it with one light Actions run of that one target or correct the report. Also correct the
report texts listed in Q1.

## Q2. Is lockstep virtual time (7-11 days) the right next design, and would it reach the exit number?

**It would not reach ≥ 60% on these 15 targets, whatever its quality.** The limit is not determinism but the target
set and the failure conditions (MEASURED, rounds 1 + 2 raw data joined per target):

1. **8 of 15 targets never failed in any non-`--det` run of either round** (baseline, stress, serial, plain): actual
   "extends after budgeting", documenso FIND_DOCUMENTS ×2 and SEARCH, etherpad "embed as iframe", uptime-kuma ×3. A
   perfect replay engine can at most give them "one fingerprint, passes". Ceiling on this set: **7 of 15 = 47%**.
2. Of the 7 that did fail, **5 failed only under CPU stress** (actual ×3, etherpad share link, solid-start), 1 only
   in a parallel baseline (documenso DELETE_RECIPIENT, round 1), 1 alone in plain runs (documenso EMAIL_TRANSPORT,
   run 5, 1 of 3). Lockstep makes a run insensitive to load by construction; it reproduces a load-induced failure
   only if the seed space stretches latencies past the test's timeouts. Today's seeded latency is at most 25 chunks
   = 500 ms virtual (`DETJS_PW_LATENCY` default `0,0,0,1,5,25`), against expect timeouts of 5-20 s. The design's
   point 4 (virtual deadlines) makes this explicit: without a seed space that reaches the deadlines, no seed fails.
3. **Parallel workers are outside the design.** `--det` forces `--workers=1`; the 3 failures this job's baseline
   found all pass with one worker (H4). The idle study's flaky e2e tests were cross-process (two workers on one
   filesystem, runner vs server under load). Lockstep as proposed is one scheduler per worker process; N workers
   sharing a server and a database need one scheduler across processes. Not in the design, not in the 7-11 days.
4. **Class C** (database clock) blocks the only target that flaked without detjs this round (EMAIL_TRANSPORT,
   documenso) and is the first divergence of 348 of 595 documenso tests. The proposal puts it second.
5. **The class A evidence does not yet justify lockstep**: on actual everything up to the end-of-test snapshot is
   identical (the snapshot instant is real-time dependent because of detjs's own settle loop); on etherpad 81% of
   divergences are network events nobody has classified.

What lockstep would still miss: load-induced and parallel-worker flakes (the documented majority), clocks below JS,
real I/O latency, rendering work not governed by virtual time (compositor-driven animations, frame production:
UNKNOWN whether CDP virtual time controls them in headless Chromium for these apps), and its own risk on
Playwright internals (the traces say Playwright 1.61.1).

### Cheapest experiments that decide before 7-11 days are spent (all $0, Actions kept to one job each)

| # | Experiment | Cost (ESTIMATED) | Decides |
|---|---|---|---|
| E1 | **Re-establish the target set**: each of the 15 targets 20× plain with the configured workers, 10× under the round-1 CPU stress; record the failure message. Keep targets with ≥ 1 failure and a known condition; add 1-2 projects with unstressed baseline flakes (P-019 allows it) | 0.5 day + 1 job | whether ≥ 60% is reachable at all, and which conditions (load, workers, alone) the seed space must cover |
| E2 | **Freeze-before-observe**: stop granting page virtual time when the test body ends and take `dom.digest`/`page.random` frozen (no real-time settle loop); 10 replays of actual's 3 passing targets | 2-4 hours + 1 job | whether actual's class A is our observation artifact (then 1 fp without lockstep) |
| E3 | **Runner-gated grants spike**: grant chunks only while a Playwright protocol call is in flight (count pending calls in the worker's client connection), page time frozen otherwise; 10 replays of actual ×3, etherpad ×2, uptime-kuma "creates a group" | 1-2 days + 1 job | the core hypothesis of lockstep. Go if ≥ 4 of 6 reach one fingerprint; otherwise class A is something else (frames, WebSocket timing) and lockstep would not fix it |
| E4 | **Classify etherpad's 210 net divergences**: rerun 2 full `--det` suites with `DETJS_PW_DIAG_DIR`, keep the texts, diff the first diverging body/frame | 1 job, 2 hours of reading | whether etherpad is class A, B, C or a new source |
| E5 | **Database clock shim**: start Postgres (and the Node process holding Prisma's engine, with `FAKETIME_DONT_FAKE_MONOTONIC=1`) under libfaketime pinned to the run's epoch with per-call increments; 10 replays of 2 documenso targets | 2-4 hours + 1 job | whether class C needs a VM or an hour of setup |
| E6 | **Seed space reaches the deadlines**: fixture whose response takes > the expect timeout only on some seed; check that some seed of 1-8 fails and replays with one fingerprint | 2 hours, local | whether exploration can ever reproduce load-induced failures (today: no, max 500 ms) |

Proposal: run E1, E2 and E6 first (one day together). If E1 shows the reachable share is low, the next round is a
target-set and exploration round, not lockstep. If E2/E3 pass, lockstep is justified, but its estimate must add
multi-worker scheduling and a seed space for latency up to the timeouts (UNKNOWN cost; ESTIMATED several days more).

## Per-source controls: tests they break silently

Checked in the code and the data:

- **Silent** (outcome changes with no counter): elapsed-time assertions in test code (R1); parallel-worker failures
  hidden by `--workers=1` (H4, documenso 1 test, MEASURED).
- **Visible but misattributed**: test-code vs server clock skew of 0-24.8 days (R2) breaks anything that compares a
  test-made time with the server's clock (documenso's 3 "expired" tests).
- **Risk (not turned into a test)**: the test-code clock goes backwards between tests of one worker (each test
  starts at its own hash offset), so a worker-scoped fixture caching a token with an expiry can see it expired or
  valid for days. Cheapest test: a worker fixture storing `Date.now() + 3600e3`, two tests checking it; expected
  under `--det`: same validity as plain.
- **Risk**: the run-4 numbers of actual, etherpad, solid-start and uptime-kuma were measured on code without
  697c9729 (worker clock spread, reseed on every draw). The delivered engine was measured on documenso only. Cheapest
  test: one Actions job with 2 full `--det` runs of the 4 suites, compare the broken lists.
- **Risk**: socket.io kept on long-polling under the queue (uptime-kuma "connects over websocket"): any app that
  behaves differently on polling is tested on a path production does not use. Cheapest test: count tests whose
  socket.io transport differs plain vs `--det` (log the transport from the page in a fixture).

## Notes (do not block)

- The "clean checkout" exit item is not measured: the check deletes `.detjs` (except the snapshot) and
  `test-results` in the same workspace; the report says so. The snapshot kept by the check is itself state a clean
  checkout would not have.
- The retries comparison uses p from n = 3 runs and the two parallel-worker flakes; `--det` cannot replay either of
  them (they pass with one worker). The comparison should say that in one line.
- INTERMEDIATE-1 names `results/<project>/diag/dN/` as raw data; the run-4 commits deleted those folders and did not
  add run-4 texts. The class A/B/C table of the final report therefore rests on run-2 texts plus run-4 event types.
- The 15-sample `det_diverged_examples` (`study.py:551`, first 15 in suite order) is not a sample; use the suite-wide
  `reasons` or a seeded random sample.
