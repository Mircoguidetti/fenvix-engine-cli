# STATUS · track l2-browser (P-014)

Updated 2026-11-17 11:50 UTC. Local branch `track-l2-browser` in a scratch worktree of
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
- REPORT.md is PARTIAL (interim real-project numbers from batches 3, 6, 7; fixture numbers).
- Final run 44069979210 (nonce 9; etherpad, documenso, actual, uptime-kuma, solid-start; 11 patches; harness with
  known flaky targets first + ablation; 200-min budget) queued since 11:00 behind the shared queue. When it lands:
  `git pull`, `python3 tracks/l2-browser/harness/aggregate.py`, rewrite REPORT.md headline, first line DONE.
- When aggregating: exclude rallly (baseline broken) and any documenso result not from 44069979210; stress-only
  flaky tests are not comparable with unstressed --det runs (see REPORT caveat).
- Do not push RUN again without the coordinator's go (shared queue).
