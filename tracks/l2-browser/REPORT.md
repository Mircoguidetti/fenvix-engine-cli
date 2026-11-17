PARTIAL

# REPORT · track l2-browser (P-014): Level 2 for browser end-to-end tests

Updated 2026-11-17 11:45 UTC. Engine: local branch `track-l2-browser` = `origin/claude/node-l0` @ `9ffbb0a` + the
11 patches in `patches/` (`git am`). Measurement: `.github/workflows/l2-browser.yml` on this branch (push to `RUN`),
harness `harness/`, raw results `results/<name>.json` (+ `results/<name>/` diagnostics), tables from
`python3 harness/aggregate.py`. All real-project numbers: GitHub Actions hosted runners (4 vCPU), Chromium headless,
retries 0. Each number names its run and engine version, because they come from different batches.

**Why PARTIAL:** the final combined run **44069979210** (etherpad, documenso, actual, uptime-kuma, solid-start; 11
patches; known flaky tests targeted first; per-control ablation of broken tests) was launched at 11:00 and is still
queued behind the shared Actions queue. Its results commit themselves into `results/`; finishing the report is
`python3 harness/aggregate.py` plus rewriting the headline.

## Headline

- **Fixture app** (3 cross-process races built for the purpose: browser vs server, page timer vs fetch, runner API
  request vs page navigation; local and on Actions): **2 of 2 flaky tests replay with one fingerprint** (10/10 and
  3/3 runs), **both pass in some seed and fail in another, and the failing seed fails again 3/3 with one fingerprint**
  (MEASURED). Without `--det` server UUID, page random value and page clock differ in every run (MEASURED).
- **Real projects, flaky tests (interim):** 11 flaky tests found in 5 baseline + 3 stressed runs (actual 8, uptime-kuma
  3, etherpad 0, solid-start 0; MEASURED). 2 of them were replayed 10 times under `--det`: **the outcome repeated 10/10
  in both, but the fingerprint did not: 10 distinct fingerprints in 10 runs, for both** (MEASURED). So the share of
  real flaky browser tests that replay 10/10 with an identical fingerprint is **0 of 2** so far. One of the two (actual)
  passes under `--det`; the other (uptime-kuma, "saves the data retention period") failed in all 13 `--det` runs
  (default seed and seeds 1-3): it behaves as broken by the controls, not as a reproduced flake.
- **Tests broken by the controls** (pass in every baseline run, fail under `--det`; MEASURED): etherpad 10 always + 4
  sometimes of 288; uptime-kuma 11 always of 71; solid-start 3 always of 47; actual 0 always + 2 sometimes of 74.
- **Full-suite fingerprints identical across `--det` runs** (MEASURED): etherpad 20/289 (3 runs), uptime-kuma 3/71 (2),
  actual 3/74 (2), solid-start 16/47 (3). Same outcome in every run for almost all tests; same fingerprint for few.
- **Slowdown** of `--det` (MEASURED, median wall): etherpad x6.5 vs its configured run (185 s -> 1,200 s), x3.6 vs
  serial; uptime-kuma x4.3 (273 s -> 1,182 s; already serial); actual x3.6 (269 s -> 976 s), x2.2 vs serial;
  solid-start x2.2 (46 s -> 101 s), x2.0 vs serial.

| Project | Run, engine | Tests | Flaky (baseline+stress) | Broken by controls | Identical fp, full suite | Slowdown (configured / serial) |
|---|---|---|---|---|---|---|
| etherpad | 44043803663, 8 patches, 2025 epoch | 288 | 0 | 10 always + 4 sometimes | 20/289 (3 runs) | x6.5 / x3.6 |
| uptime-kuma | 44049271859, 10 patches, 2025 epoch | 71 | 3 (stress only) | 11 always | 3/71 (2 runs) | x4.3 / x4.3 |
| actual | 44043803663, 8 patches, 2025 epoch | 74 | 8 (2 in baseline alone) | 2 sometimes | 3/74 (2 runs) | x3.6 / x2.2 |
| solid-start | 44052628988, 11 patches, 2025 epoch | 47 | 0 | 3 always | 16/47 (3 runs) | x2.2 / x2.0 |
| documenso | 44043803663 | 595 | unusable: `maxFailures: 1` on CI stopped every run at its first failure | - | - | - |
| rallly | 44049271859 | 66 | unusable: every test fails or times out also without detjs in our setup | - | - | - |

## What was built

- `docs/L2-BROWSER.md` (one page): what is controlled, what is not (limits B1-B8), what a full VM would add.
- `detjs playwright --det [--det-seed=N] [playwright test args]` (`node/src/pw/`) and `detjs serve --det -- <cmd>` for
  servers started before the runner. Controls: CDP virtual time in 20 ms chunks (`paced`: never ahead of real time);
  seeded Math.random/crypto in every frame and in the test code; Level 0 of detjs in Node app servers (seeded generators
  and OS entropy, one virtual wall clock, virtual timers, sorted readdir) with per-test brackets (`x-detjs-test`) and a
  quiet barrier; one ordered queue for documents, fetch/XHR, the runner's `request` calls and page-to-server WebSocket
  frames (sorted choice; seeded with `--det-seed`), released only between virtual time chunks; workers serialised.
  One shared trace in the Level 0 format, compared by the Rust verifier.
- `node/test/playwright.test.js`: 5 tests on the fixture (pass locally and on Actions, MEASURED).
- Harness: per project, baseline runs (project's own parallelism, retries 0), known flaky tests targeted first (10
  replays under `--det`, seeds until both outcomes, 3 replays of the first failing seed, plain runs with the same
  filter), stressed runs (one CPU hog per core), a serial run, full-suite `--det` runs, ablation of each test broken
  by the controls (server / net / vtime / page seeds off, one at a time).

## Engine bugs found and fixed (each with a test that fails before the fix and passes after)

1. App server whose path contains `playwright` taken for a runner helper and left uncontrolled (fixture).
2. First `page.goto` right after a virtual time grant deadlocked: Chrome suspends the page's DevTools session while its
   navigation is pending, so the chunk could not end (MEASURED 2 of 6 single-test runs hung before, 0 of 10 after).
3. `page.goto` and a runner API request issued together were ordered by browser latency (2 fingerprints in 10 runs
   before, 1 after; MEASURED).
4. Without `--det`, `node_modules/.bin` was not on PATH: webServer commands (`cross-env`, `next`) failed (uptime-kuma, rallly).
5. In app servers Vite counted as test-runner infrastructure (because of Vitest) and kept the real clock: real
   timestamps in temp file names and `?t=` URLs (solid-start).

## Findings: why fingerprints still diverge

- **Server background work** (solid-start, etherpad, uptime-kuma): per-test server event counts differ by 1-8 events
  between runs (solid-start 691 vs 692, 512 vs 520; etherpad 107 vs 109). File watchers, dev-server transforms, socket.io
  heartbeats and other timers run at real deadlines and interleave with request handling. A shell per process cannot
  order them; a deterministic VM can, or a request-scoped server fingerprint would hide them (ESTIMATED, from the
  verifier output).
- **Page draws in a different order** (actual): same number of Math.random/crypto draws, different digest, so the order
  of draws differs; the app's logic runs in a web worker that is outside virtual time and seeds (limit B3; ESTIMATED).
- **Server-to-page WebSocket frames** are relayed as they arrive, not gated to chunk boundaries (etherpad, uptime-kuma
  are socket.io apps; the broken tests there are mostly multi-user and live-update tests). A gated relay was tried on a
  fixture and could not be shown to change anything there, so it was not committed (no failing test).
- **Clock mix** (documenso): the default 2025 virtual epoch was compared against Postgres and the Playwright worker on
  real 2026 time. The final run uses the job's start minute as epoch for every `--det` run and for `detjs serve` (a
  harness choice, not a measured cure).

## Comparison with Playwright's own retries and trace viewer

From MEASURED baseline failure rates p (retries 0) and the projects' CI settings, ESTIMATED with independent attempts:
actual's two baseline-flaky tests (p = 0.2, CI retries 1) are hidden by the retry in 16% of CI runs and reported in 4%.
Under load (stressed runs) the same suite failed 4-6 tests per run. With `trace: 'on-first-retry'` (etherpad,
uptime-kuma) the recorded trace is of the retry, which usually passes: a failing attempt is traced with probability
p^2. With `retain-on-failure` (documenso) the failing attempt is traced with probability p. In both cases the trace is a
recording to read (DOM snapshots, network, console; DECLARED, Playwright docs): it cannot run the failure again.
`--det --det-seed=N` aims at a replay command; on the fixture it is one (same seed: same order, values, outcome,
fingerprint). On the real projects measured so far the outcome repeats, but the fingerprint does not.

## Honest assessment so far

Process-level Level 2 makes browser + Node server runs repeat their **outcome** (most tests, every run), but not their
**fingerprint** on real apps: dev servers, socket.io pushes and web workers keep real-time behaviour that the shells do
not order. It breaks 4-15% of tests in socket-heavy apps (etherpad 14/288, uptime-kuma 11/71) and costs x2-x6.5 wall
time. On a purpose-built fixture it does what Level 2 promises. The gap is what a deterministic VM would close.

## Next

1. Read run 44069979210 (`python3 harness/aggregate.py`): known flaky tests of documenso (4, idle study) and etherpad
   (1), actual (4) and uptime-kuma (3) targeted first; per-control ablation of the broken tests; documenso with
   `--max-failures=0` and a real-time epoch. Rewrite the headline, first line DONE.
2. Engine candidates, each needing a failing test first: server-to-page frame gating, request-scoped server
   fingerprints, virtual time for web workers.
