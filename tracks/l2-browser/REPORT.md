PARTIAL

# REPORT · track l2-browser (P-014): Level 2 for browser end-to-end tests

Updated 2026-11-17 10:00 UTC. Engine: local branch `track-l2-browser` = `origin/claude/node-l0` @ `9ffbb0a` + the
11 patches in `patches/` (`git am`). Measurement: `.github/workflows/l2-browser.yml` on this branch (push to `RUN`),
harness `harness/`, raw results `results/<name>.json` (+ `results/<name>/` diagnostics), tables from
`harness/aggregate.py`. Every row below names its run, patch count and harness.

## Headline (so far)

- **Fixture app** (3 cross-process races: browser vs server, page timer vs fetch, runner API request vs page
  navigation; local, Chromium, Playwright 1.65.1): **2 of 2 flaky tests replay with one fingerprint** (10/10 and 3/3
  runs), **both pass in some seed and fail in another, and the failing seed fails again 3/3 with one fingerprint**
  (MEASURED). Without `--det` the same runs give a different server UUID, page random value and page clock every run
  (MEASURED). This is a fixture built for the purpose, not a real project.
- **solid-start** (real project, 47 Playwright tests, no flaky test in 5 baseline + 3 stressed runs; run 44052628988,
  11 patches): **3 of 47 tests broken by the controls (always)**, **16 of 47 tests with identical fingerprints over 3
  `--det` runs**, slowdown **x2.2** against the configured run and **x2.0** against a serial run (46 s -> 101 s)
  (all MEASURED, GitHub Actions 4 vCPU). The diverging fingerprints are the app server's own events (Vite dev server):
  see Findings.
- **etherpad** (288 Playwright tests, server started outside the runner under `detjs serve`; run 44043803663, 8 patches,
  first harness, 2025 epoch): **no flaky test in 5 baseline + 3 stressed runs** (MEASURED; the idle study saw 1 in 6
  runs); under `--det` **10 tests always broken + 4 sometimes**, **20 of 289 tests with identical fingerprints over 3
  runs**, slowdown **x6.5** against the configured run (185 s -> 1,200 s) and **x3.6** against a serial run (329 s)
  (MEASURED). Most broken tests have two users or two devices in one test (collaboration through socket.io).
- **actual** (74 Playwright tests, shard 1/3, 4 workers, app logic in the browser and a web worker; run 44043803663,
  8 patches, first harness): **8 flaky tests** in 5 baseline + 3 stressed runs (2 in baseline alone; MEASURED). Under
  `--det` all 8 passed in both full-suite runs; 2 other tests fail sometimes under `--det` (not always). One flaky test
  was replayed 10 times: **10/10 passed but with 10 different fingerprints** (same draw counts, different page random
  digest: the order of draws differs between runs, ESTIMATED cause the web worker, limit B3). **3 of 74 tests with
  identical fingerprints over 2 runs.** Slowdown **x3.6** against the configured run (268 s -> 976 s) and **x2.2**
  against a serial run (436 s) (MEASURED).
- **rallly**: baseline broken in our setup (every test fails or times out also without detjs): no numbers.
- **Share of real flaky browser tests that replay 10/10 with one fingerprint and pass in some seed**: UNKNOWN yet. The
  final batch (etherpad, documenso; known flaky tests from the idle study targeted first) is waiting for the shared
  Actions queue.

## What was built

- `docs/L2-BROWSER.md`: what is controlled, what is not (limits B1-B8), what a full VM would add.
- `detjs playwright --det [--det-seed=N] [playwright test args]` (`node/src/pw/`) and `detjs serve --det -- <cmd>`
  for servers started before the runner. Controls: CDP virtual time in 20 ms chunks (`paced`: never ahead of real
  time); seeded Math.random/crypto in every frame and in test code; Level 0 of detjs in Node app servers (seeded
  generators and OS entropy, one virtual wall clock, virtual timers, sorted readdir) with per-test brackets
  (`x-detjs-test`) and a quiet barrier; one ordered queue for documents, fetch/XHR, the runner's `request` calls and
  page-to-server WebSocket frames (sorted choice, seeded with `--det-seed`), released only between virtual time
  chunks; workers serialised. One shared trace in the Level 0 format, compared by the Rust verifier.
- `node/test/playwright.test.js`: 5 tests on the fixture (pass locally and on Actions, MEASURED).
- Harness: per project, baseline runs (project's own parallelism, retries 0), known flaky tests targeted first
  (10 replays under `--det`, seeds until both outcomes, 3 replays of the first failing seed, plain runs with the same
  filter), stressed runs (one CPU hog per core), a serial run, full-suite `--det` runs, ablation of each test broken
  by the controls (server / net / vtime / seeds switched off one at a time).

## Engine bugs found on real projects and fixed (each with a test that fails before the fix)

1. App server whose path contains `playwright` taken for a runner helper, left uncontrolled (fixture).
2. First `page.goto` right after a virtual time grant deadlocked about 1 run in 3: Chrome suspends the page's
   DevTools session while its navigation is pending, so the chunk could not end (fixture, MEASURED 2/6 before, 0/10 after).
3. `page.goto` and a runner API request issued together were ordered by browser latency: 2 fingerprints in 10 runs
   (fixture, MEASURED before; 1 fingerprint in 10 after).
4. Without `--det`, `node_modules/.bin` was not on PATH: webServer commands (`cross-env`, `next`) failed (uptime-kuma, rallly).
5. In app servers Vite was treated as test-runner infrastructure (because of Vitest) and kept the real clock: real
   timestamps in temp file names and `?t=` URLs (solid-start). Fixing it made Vite deterministic in its timestamps, but
   the server fingerprints still diverge (below).

## Findings so far

- solid-start, server fingerprints: before fix 5 the divergence was the real timestamp in Vite's temp config file name;
  after it, per-test server event counts differ by a few events between runs (691 vs 692, 512 vs 520): background work
  of the dev server (file watching, module transforms, timers at real deadlines) interleaves with request handling.
  A process-level shell cannot order that; this is what a deterministic VM (or a request-scoped server fingerprint)
  would add. ESTIMATED cause, from the verifier output.
- solid-start, 3 broken tests: server functions (`POST /_server`) answer 500 or never answer under the controls,
  and a cookie set by a server-function redirect is lost. Cause UNKNOWN; the final batch runs the per-control ablation.
- documenso, first batch: unusable (config `maxFailures: 1` on CI stopped every run at its first failure, and a
  2025 virtual epoch was compared against Postgres and the Playwright worker on real 2026 time). Harness now passes
  `--max-failures=0` and uses the job's start minute as epoch (a harness choice, not a measured cure).

## Comparison with Playwright's own retries and trace viewer

Method (numbers pending): per flaky test, the measured failure rate p (retries 0) gives the chance that the
project's CI retries hide it, p(1-p^r), and the chance it is reported, p^(r+1) (ESTIMATED from MEASURED p, independent
attempts). With `trace: 'on-first-retry'` (etherpad, uptime-kuma) the trace is of the retry, which usually passes: a
failing attempt is traced with probability p^2. With `retain-on-failure` (documenso) the failing attempt is traced with
probability p, but a trace is a recording: it cannot re-execute the failure. `--det --det-seed=N` is a replay command:
the same seed gives the same order, values and outcome.

## Next

Final batch (one run): etherpad, documenso and the healthiest third project, same 11 patches and harness.
