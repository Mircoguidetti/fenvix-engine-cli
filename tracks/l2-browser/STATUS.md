# STATUS · track l2-browser (P-014)

Updated 2026-11-17 10:00 UTC. Local branch `track-l2-browser` in a scratch worktree of
/home/user/fenvix-engine-cli; base `9ffbb0a` (origin/claude/node-l0, rebased at resume). Patches:
`patches/` (`git am` on the base; 11 commits).

## Done
- Prototype `detjs playwright --det ...` (node/src/pw/): wrapper config (workers=1, retries=0, detjs
  reporter); browser controls in the Playwright worker (CDP virtual time in gated 20 ms chunks, seeded
  Math.random/crypto in pages and test code, HTTP + WebSocket ordered through one queue with a server quiet
  barrier, long-poll passthrough); app servers get Level 0 controls + per-test brackets; one shared trace.
  `detjs serve` for servers started outside the runner.
- docs/L2-BROWSER.md (design note).
- node/test/playwright.test.js: fixture app with 3 cross-process races; 5 tests pass locally and on Actions (MEASURED);
  five fail before their fix (server path containing "playwright"; first-navigation deadlock; goto vs runner API order; PATH without node_modules/.bin; Vite clock as infrastructure).
- Harness `harness/` + workflow `.github/workflows/l2-browser.yml` (push to `RUN`): etherpad, uptime-kuma,
  documenso, actual, rallly, solid-start. Dry run on a local toy project works.

## Next
- PARTIAL REPORT.md pushed (fixture + solid-start numbers, 5 engine bugs fixed).
- Final run (nonce 9) launched 11:00 after node-harness and cache-proof r5 started: etherpad, documenso, actual, uptime-kuma, solid-start; 11 patches; harness with known-flaky targets first + ablation; 200-min budget.
  have started; then ONE final run: etherpad, documenso, solid-start (+ the healthiest of uptime-kuma/actual/rallly
  from batches 3/6), 11 patches, harness 3c6c260 or later (known flaky targeted first, ablation), budget ~150 min.
- Batch 8 cancelled. Batches 3 (etherpad, actual) and 6 (uptime-kuma, rallly) still running at 09:55.
