# STATUS · track l2-browser (P-014)

Updated 2026-11-17 07:15 UTC. Local branch `track-l2-browser` in a scratch worktree of
/home/user/fenvix-engine-cli; base `040e827` (origin/claude/node-l0 at start). Patches:
`patches/` (`git am` on the base).

## Done
- Prototype `detjs playwright --det ...` (node/src/pw/): wrapper config (workers=1, retries=0,
  detjs reporter), NODE_OPTIONS preload: Playwright workers get the browser controls (CDP virtual
  time in gated chunks, seeded Math.random/crypto in pages, HTTP + WebSocket ordered through one
  queue, long-poll passthrough), app servers get Level 0 controls + per-test brackets + quiet
  barrier; reporter writes one shared trace (.detjs/trace.jsonl). `detjs serve` for servers
  started outside the runner.

## Next
- docs/L2-BROWSER.md (design note), tests (fail without / pass with), 2-3 real Playwright projects
  with known flaky tests on Actions (10x replay, fingerprints, broken-by-controls, slowdown),
  comparison with Playwright retries/trace viewer, REPORT.md.
