# STATUS · track l2-browser (P-014)

Updated 2026-11-17 09:30 UTC. Local branch `track-l2-browser` in a scratch worktree of
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
- Runs: batch 3 (44043803663: etherpad, actual still running; documenso broke: maxFailures=1 on CI and a 2025
  epoch against real-time Postgres/test worker -> harness now passes --max-failures=0 and a job-start epoch);
  batch 6 (44049271859: uptime-kuma, rallly running); batch 7 (44052628988: solid-start, 11 patches);
  batch 8 (documenso, new harness). Then REPORT.md (harness/aggregate.py prints the tables).
