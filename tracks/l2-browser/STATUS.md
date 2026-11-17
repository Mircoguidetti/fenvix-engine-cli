# STATUS · track l2-browser (P-014)

Updated 2026-11-17 07:55 UTC. Local branch `track-l2-browser` in a scratch worktree of
/home/user/fenvix-engine-cli; base `9ffbb0a` (origin/claude/node-l0, rebased at resume). Patches:
`patches/` (`git am` on the base; 7 commits).

## Done
- Prototype `detjs playwright --det ...` (node/src/pw/): wrapper config (workers=1, retries=0, detjs
  reporter); browser controls in the Playwright worker (CDP virtual time in gated 20 ms chunks, seeded
  Math.random/crypto in pages and test code, HTTP + WebSocket ordered through one queue with a server quiet
  barrier, long-poll passthrough); app servers get Level 0 controls + per-test brackets; one shared trace.
  `detjs serve` for servers started outside the runner.
- docs/L2-BROWSER.md (design note).
- node/test/playwright.test.js: fixture app with 3 cross-process races; 4 tests pass locally (MEASURED);
  two fail before their fix (server path containing "playwright"; first-navigation deadlock).
- Harness `harness/` + workflow `.github/workflows/l2-browser.yml` (push to `RUN`): etherpad, uptime-kuma,
  documenso, actual, rallly, solid-start. Dry run on a local toy project works.

## Next
- Read results/*.json from the first Actions batch, fix what breaks, second batch; REPORT.md.
