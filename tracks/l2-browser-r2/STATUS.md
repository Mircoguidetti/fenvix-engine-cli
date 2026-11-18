# STATUS · l2-browser round 2 (P-019)

Branch `claude/l2-browser-r2` = origin/claude/node-l0 @ 9ffbb0a + round 1's 11 patches + round 2 commits.
Harness: `tracks/l2-browser-r2/harness/` (round 1's, plus `mode: diagnose`, state restore, failing-seed x10,
replay-command check). Workflow `.github/workflows/l2-browser-r2.yml` (push changing `tracks/l2-browser-r2/RUN`).

## Done
- Diagnosis run 1 (44275149752): INTERMEDIATE-1 in fenvix-brain-cli sessions/2026-11-18-l2-browser-r2/.
- S3 `--det-state` (files + Postgres template copies), `detjs state save|restore`.
- S1+S2 message-scoped server clock/random + request-scoped server fingerprint (DETJS_PW_SCOPE).
- S4 seeded web workers (marked worker URLs, seed script prepended).
- S5 server pushes held to chunk boundaries after a quiet barrier (DETJS_PW_GATE_PUSH).
- S6 settled final DOM (DETJS_PW_SETTLE_MS).
- Exploration: seeded latency in chunks (DETJS_PW_LATENCY).
- Replay command printed per failing test.
- Tests: node/test/l2r2.test.js (6), node/test/playwright.test.js (5) pass locally.

## Next
- Diagnosis run 2 (round 2 controls) -> remaining sources; then the full measurement (RUN mode unset).
