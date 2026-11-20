PAUSED

# REPORT · L2 browser lockstep, continuation (row JS-04: Playwright Test with Chromium)

Session 2026-11-20, branch `claude/l2-browser-lockstep-ytoqnv`. Paused at the coordinator's request (budget), mid-round.
The >= 60% exit (>= 33 of 55 identical 10/10 with the real failure, one engine version) is **not yet measured**.
"Local" = this session's container (4 vCPU; native Postgres 16 under libfaketime, inbucket binary; Chromium 1243
standing in for the pinned 1248/1255/1228, which the proxy does not let this container download). Everything else
is GitHub Actions.

## Done

### Open A: documenso reset group replays (cause found and fixed by family)

- Diagnosis (MEASURED locally, `tracks/l2-browser-lockstep/harness/gate.py` hunt with `seed_map` replay-only mode
  and response bodies kept; CI run 44761272887 confirms the split on the old engine: 16 of 18 seed-1 targets with
  2-3 fingerprints in 3 replays). The response bodies differ only in timestamps, e.g. session-json `createdAt
  …03.078Z` vs `…03.098Z`. Ids, rows and the server fingerprint are identical. So the engine clock T at the start
  of a test differed by 20 ms between replays.
- Cause 1: after a test function ends, Playwright's teardown (error-context aria snapshot, artifacts, context close)
  issues runner calls whose admission advances T in 20 ms steps. How many steps passed before the next test depended
  on real time. API-only tests (no teardown work) were the ones that already replayed identically.
- Cause 2: the test code's Prisma writes got the same millisecond, because T does not move while test code works.
  Lists ordered by `createdAt` then came back in either order.
- Cause 3: `Promise.all` seeding (documenso `seedDocuments`) wrote rows in the database's real-time order.
- Fixes (engine):
  - ef4f005: teardown hold (superseded, see below); runner Prisma writes one ms apart.
  - 48b11ca: Prisma gate (the test code's database operations as engine messages) with one worker too, on by
    default.
  - a31d6ae (local branch `local-align`, NOT pushed yet): test start alignment. The next test starts at T(end of
    the previous test function) + `DETJS_LS_TEST_GAP_MS` (default 3000). A teardown that runs past the gap is
    recorded as a stall. The hold becomes opt-in.
- Result (MEASURED locally, seed-1 group of 18 targets + 1 other test, 2 replays, same epoch):
  - old engine: 6 of 19 tests identical;
  - ef4f005 (hold, without the Prisma gate): 18 of 19;
  - with the gate (48b11ca + ca3a330): 19 of 19.
  - The Prisma gate changes the seed draws: seed 1 now gives the real failure for 6 of 18 (it was 18 of 18), so
    seeds must be searched again (run 17 does this).

### Regression caused by ef4f005, and its fix

- Gate run 44783946608 (MEASURED): actual `[Tracking] applies budget template` gave **6 fingerprints in 10 runs**
  (it was 1). The final DOM is captured at a run-dependent point of an animation (`translateY(-0.45px)
  scale(0.998)` vs `0px scale(1)`). Cause: the hold loop settled every 10 ms of real time while it waited, and
  settles pump page frames.
- a31d6ae removes the hold from the default path; teardown runs as before ef4f005, and the start alignment
  replaces it. Its verification is in progress, not finished:
  - actual's regressed target 10x locally, and the documenso seed-1 pair (the first pair attempt was invalid: a
    stale app server from an interrupted run held port 3000);
  - lockstep + the 4 node suites on a31d6ae.
- Coordinator decision: a31d6ae may be pushed once (1) the local suites are no worse than now and (2) the
  regressed target gives 1 fingerprint in 10 locally.

### Open B: documenso parallel-worker targets (2 workers)

- Run 44717542771: every huntp run hit the 45 min run timeout (MEASURED).
- Causes, all found locally:
  1. the hub answered "idle" forever while a released message waited for its latency;
  2. a fetched response waiting for its page's FETCH_MS did not count as a runner wait;
  3. `expect.poll`'s interval sleep was classified as the test watchdog, because TimeoutManager is in every
     test timer's async stack.
- Fixed in ca3a330. The spec file that hung runs in 103 s (MEASURED locally).
- Real failures with 2 workers, seeds 0-6, local: **0 of 5 targets** (MEASURED). Outcomes are passes,
  `locator.click` 15 s timeouts and PrismaClientKnownRequestError, but never the round-3 messages.
- template-field-prefill is reproduced by the single-worker hunt anyway (seed 1, run 44704690282).
- The update-envelope-items targets most likely depend on documenso's local job runner (distribution triggers an
  internal `/api/jobs` fetch). Lockstep always lets that fetch finish before the next message, so no seed can
  reorder it. This is a hypothesis from the code, UNKNOWN until measured.

### Node suites (coordinator request): playwright, l2r2, l2r3, review-r011

- CI with the pinned Chromium 1255, run 44794750078 (MEASURED, `tracks/l2-browser-lockstep/results/suites-44794750078.txt`):
  9 pass, 10 fail, 1 todo. The same 10 fail locally on the current engine.
- On the engine before this session (e67bd9f), locally, the same 10 fail plus one more ("playwright without
  --det", which passes now). So this session added no red; the 10 are pre-existing.
- The workflow now has an optional `suites` job (RUN `"suites": true`).
- lockstep.test.js: 4/4 on CI (build job of run 44783946608) and locally.
- Preliminary sorting (not final; evidence still to be completed per test):

| Test | First evidence | Case (preliminary) |
|---|---|---|
| R1 elapsed-time budget hidden | `--det changed the outcome from failed to passed (ELAPSED_MS=1)` | (b) candidate: under lockstep a real 1.5 s wait is 1 ms of engine time by design (1422a96, round-4 lockstep decision). The intent must be re-expressed as a seed-space test. Needs the coordinator's decision |
| E6 seed space reaches the deadline | `no seed of 1-8 reaches the deadline` | (b) candidate: written for the round-3 seed space; lockstep uses aimed latencies (`DETJS_LS_LATENCIES`, timeout mechanisms). To verify |
| playwright --det: three runs identical | assertion after 181 s | (a) candidate; under investigation |
| first action is a navigation never deadlocks | `localhost:4597 is already used` | cascade of the previous test's leftover web server (harness isolation), to confirm |
| API request and page.goto ordered the same | same port error | same cascade, to confirm |
| playwright --det-seed explores both outcomes | fails in 0.5 s | probably the same cascade, to confirm |
| --det-state replays from saved files | divergence at event 2 (outcome vs api.done) | (a) candidate |
| server pushes S5 one order | push/response orders differ across 6 runs | (a) candidate |
| worker clock dates same in every run | divergence at event 0 (sched.io) | (a) candidate |
| unique test data no repeats | expect toBe failures | (a) candidate |

## Run 17 (44783946608): the one-engine round on ca3a330, in progress at pause

- gate: sveltekit 2/2 one fingerprint, uptime-kuma 2/2, actual 1/2 (the regression above); documenso pending.
  MEASURED.
- hunt: uptime-kuma 1 of 2 reproduced (MEASURED); actual, sveltekit, documenso (2 jobs) and huntp pending.
- Because of the actual gate regression, this round is not the final one: the round has to be repeated on the
  engine with a31d6ae.

## Next (in order)

1. Finish verifying a31d6ae locally (actual target 10x, documenso pair, the 5 suites); push it if the coordinator's
   two conditions hold.
2. Finish sorting the 10 suite failures with evidence; fix the (a) cases at their cause; update the (b) tests with
   the commit and decision cited.
3. Merge PR #4 (claude/release-1, 71f8081) at the next engine push, as the coordinator asked.
4. Re-run the round on one engine (gate on 4 projects, hunts on all 55, huntp) and fill in the 55-target table
   (`harness/report55.py`).
5. Open B: if the job-runner hypothesis holds, model the server's internal job requests as seedable messages.
