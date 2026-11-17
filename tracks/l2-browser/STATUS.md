# STATUS · track l2-browser (P-014)

Updated 2026-11-17. Local branch `track-l2-browser` in a scratch worktree of /home/user/fenvix-engine-cli; base
`9ffbb0a` (origin/claude/node-l0). Patches: `patches/` (`git am` on the base; 11 commits).

## State
- Final run 44069979210 landed for etherpad, documenso, actual, uptime-kuma, solid-start; REPORT.md rewritten from
  `python3 harness/aggregate.py` (rallly excluded in the script). First line PARTIAL: 0 of 15 real flaky tests replay
  10/10 with one fingerprint; controls break 33 of 481 tests on four projects and 510 of 595 on documenso.
- No run is queued. Do not push RUN again without the coordinator's go (shared queue).

## Next (engine work, each needing a failing test first)
- Database reset per `--det` replay (documenso), request-scoped server fingerprints, gated server-to-page WebSocket
  frames, web workers under virtual time; then stressed `--det` replays.
