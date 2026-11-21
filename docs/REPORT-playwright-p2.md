PARTIAL / PARKED — intermediate report, P-060 (Passo 2, block 3: Playwright). Work parked by the coordinator
(Passo 1 still open). Points 1-4 of P-060 are NOT done. No pull request, nothing merged into claude/release-1.

# REPORT · Playwright complete (P-060), intermediate

Branch `claude/playwright-p2` of `fenvix-engine-cli`, started from `claude/release-1`. Session 2026-11-21.
"Local" = this session's container (4 vCPU, Chromium 1243 headless shell standing in for the pinned build, which the
proxy does not let it download). Every other number comes from GitHub Actions, workflow `l2-browser-lockstep.yml`,
results in `tracks/l2-browser-lockstep/results/` (each result file names its run id).

## 1. Port of the Level 2 lockstep work onto claude/release-1

- `claude/l2-browser-lockstep-ytoqnv` and `claude/release-1` share **no git history** (`git merge-base` finds no
  common commit), so the port was **applied by hand**: the diff of the lockstep branch since its own base (9ffbb0a5)
  for `node/`, `crates/`, `chromium/`, `docs/L2-BROWSER.md`, the workflow and the harness, applied as a 3-way patch on
  the trunk. Eight files conflicted (shared core: `clock.js`, `seeds.js`, `sites.js`, `detjs.js`, the napi binding,
  `lib.rs`, `package.json`, lock file) and were resolved by hand. L2's per-message timer context was renamed `_mctx`,
  because the trunk uses `_ctx` for concurrent tests.
- **Rewritten fix**: the "test start alignment" of the previous session (its commit `a31d6ae`, branch `local-align`)
  had **never been pushed** and was lost with its container. It was rewritten here (commit 2c8d8e01): the next test
  starts at T(end of the previous test function) + 3 s of engine time, and the value is kept in the clock file so the
  worker Playwright starts after a failed test aligns the same way (MEASURED local, documenso delete-recipient seed-2
  group: second test at T=879 or 899 ms in 4 replays before; T=3819 ms in 4 of 4 after, 1 fingerprint).
- `detjs playwright --det` now runs the Level 2 shell; the trunk's Level 0 shell is kept for the repro driver's flags
  (`--det-order`, `--det-outcomes`, `--det-collect`, `--det-order-seed`) and `--det-level=0`.
- Defects of the port found and fixed on Actions or locally: trunk Level 0/1 records that vary per process or with real
  time in app servers (file ages, process facts, I/O completion order, Level 1 timer/IO choices) are kept out of the
  fingerprint in Level 2 runs (`DETJS_LEVEL2=1`, set only by `detjs playwright` / `detjs serve`); controls are no longer
  started in off-thread loader threads (`--import=tsx`); Prisma interactive transactions get a 10 min real-time limit
  under lockstep; hub workers are identified by Playwright's parallel index, not the process id.

## 2. Gate (10 lockstep runs per target, one engine), run 44921091693

| Project | Targets with 1 fingerprint in 10 runs | Label |
|---|---|---|
| sveltekit | 2 of 2 | MEASURED, run 44921091693 |
| uptime-kuma | 2 of 2 | MEASURED, run 44921091693 |
| actual | 1 of 2 ("[Tracking] applies budget template": 3 fingerprints, first divergence `page.random` 702 vs 701 draws) | MEASURED, run 44921091693 |
| documenso | 0 of 2 (all 20 runs timed out in teardown, see 3) | MEASURED, run 44921091693 |

Before the port fixes, sveltekit and uptime-kuma gave 10 fingerprints in 10 runs (MEASURED, run 44904997963).

Hunts finished in run 44921091693 before the stop: uptime-kuma 2 of 2 reproduced 10/10 with 1 fingerprint, actual 4 of
9 (MEASURED). The other hunts of that run (documenso, sveltekit, the 2-worker hunt) did not finish. **Point 1 (>= 60% of
the 55 targets) is NOT measured on the final engine.**

## 3. documenso: engine-caused failure, GitHub Actions only

- Every lockstep run of both documenso gate targets ends with `Tearing down "context" exceeded the test timeout of
  60000ms`; the plain runs pass (MEASURED, runs 44904997963, 44909741100, 44921091693). Locally the same targets pass
  with 1 fingerprint (MEASURED local). This is a failure caused by the engine.
- Cause, found in diagnostic run 44931073657 (run 23, gate A/B with the lockstep trace kept): a page request
  (`organisation.getQuotaFlags`) **started by the page never reaches the engine** (`probe-timeout routed=8 started=9`).
  While the runner waits on `BrowserContext.close`, every settle waits 3 s for that request, the teardown hold gives up
  after 5 s without activity, and engine time then crawls in 20 ms steps to the 60 s test deadline. The same failure
  with the teardown hold off (gate2) and with test start alignment off (gate3): neither is the cause (MEASURED, run
  44931073657).
- **Two attempted fixes** (do not wait for closing pages; never give up the hold while a close is in flight; then the
  same with a 300 ms limit for several workers) **made the 2-worker case worse** (fixture: more runs with another
  fingerprint) **and were reverted**. Open.

## 4. Two workers (point 2)

- With 2 workers on the lockstep fixture, **about 2 runs in 6 give a different fingerprint** (MEASURED local).
- Cause found: the hub's decisions are **identical** between runs (180 of 180 actions, MEASURED local), but **each
  worker records them in a different order**: an action the hub pushes for a worker that was not asking waits in a
  queue and can be recorded after a later direct answer.
- A fix (actions numbered on arrival, earlier pushes applied before an answer) is in the last commit of the branch,
  marked **UNVERIFIED, WORK IN PROGRESS**: not tested, not measured.
- Speed: **2 workers were slower than 1 locally** (MEASURED local, documenso: 1 worker 27 tests in 556 s; 2 workers
  19 tests in 11.8 min; both on a loaded machine, so the absolute values are NOISY, the direction is not in doubt for
  this engine: the hub takes one decision at a time for all workers).
- The parallel proof (same outcome and one fingerprint per test as 1 worker, 2 real projects, 10 runs) is NOT measured:
  the `par` job exists in the harness but its runs were cancelled or did not finish.

## 5. Playwright cache with proof (point 3)

- Before this session (MEASURED local): `--det-cache` was accepted and silently ignored for Playwright, in both
  shells; nothing stored, 0 tests reused.
- Built: `--det-cache=DIR` for Level 2 (`node/src/pw/cache.js`, `inputs.js`). Unit of reuse: the whole selection
  (end-to-end tests share the app's server and database, a test file is never reused alone). Every Node process of the
  run records its inputs (files read, modules loaded, listings, the content before the run's own writes); the run is
  recorded only when it is provably complete. On the fixture (`node/test/pw-cache.test.js`, 2 of 2 pass, MEASURED
  local): an unchanged rerun is reused with proof, an edit of the app server reruns and gives the real new outcome, a
  server outside the run is refused.
- On the real projects the cache **refuses to record** (MEASURED local):
  - **uptime-kuma**: the app calls an **external service** (api.pwnedpasswords.com, here through the container's
    proxy); native libraries that **read files themselves** (better-sqlite3, the database file).
  - **documenso**: native libraries that **read files themselves** (skia canvas and others), the esbuild binary started
    outside tsx's transform service, and **Prisma's query engine, which opens its database connections itself, outside
    Node** (not seen; the database must be declared as start state).
- **Refusing is the correct behaviour** under the founder's rule "never a green on a doubt": a reuse needs every input
  seen; these runs have inputs the engine cannot see. It is not a defect. Making these projects cacheable needs: the
  network cassette for external calls in app servers, a declared start state covering files native libraries read,
  and the database in the start state for Prisma.

## 6. Local Node suites (all node/ tests, this branch)

| Node | Pass | Fail | Label |
|---|---|---|---|
| 24.22.3 | 875 | 10 | MEASURED local |
| 26.13.1 | 873 | 12 | MEASURED local |
| 22.23.5 | 866 | 17 | MEASURED local, NOISY (run beside documenso runs; re-run alone, the non-L2 failures passed) |

Failures that **pre-date this session**: the old-round Level 2 suites (l2r2, l2r3, playwright.test.js,
review-r011: R1 elapsed-time budget, E6 seed space, `--det-state` replay, worker clock dates, unique test data,
three-runs-identical, navigation deadlock, API request vs page.goto, `--det-seed` explores both outcomes), listed as
failing in the previous session's report (`sessions/2026-11-20-l2-continue/REPORT.md`, 10 failing there); and
"a flaky (order-dependent) test becomes a defect" (needs Python's `detpy` module, not installed in the container).
Not yet compared with the trunk: on Node 26, "tap: wrong reuse (runner specific)", "t.mockRequire", "playwright
without --det: server and page randomness differ", and the multi-worker fixture test (see 4).

## 7. State of the branch

- Last pushed commit: see the commit that adds this file. The hub-ordering fix just before it is UNVERIFIED.
- Not done: point 1 on the final engine, point 2 proof, point 3 on real projects, the documenso teardown fix, actual's
  second gate target, the PR.
