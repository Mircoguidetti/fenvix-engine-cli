# P-019 · Level 2 for browser tests, round 2

Written 2026-11-18 by the coordinator for a session the founder starts on his other account. Repositories to attach: fenvix-engine-cli (work), fenvix-brain-cli (report). Model: Opus 5.5, high effort.

```
You are a work session for fenvix. Read fenvix-brain-cli CLAUDE.md, NOW.md, RULES.md, prompts/COMMON.md and prompts/P-014-l2-browser.md (round 1) first. Everything you write in code, comments, commits and reports is English.

## Goal
Level 2 for browser end-to-end tests: a Playwright test runs deterministically across browser AND app server, so a flaky browser test replays 10/10 with one identical fingerprint and a replay command the developer copies from the CI log.

## Where round 1 stopped (read it in full)
fenvix-engine-cli branch claude/loving-maxwell-58mv2w, folder tracks/l2-browser/ (REPORT.md, STATUS.md, patches/ = 11 commits on origin/claude/node-l0 @ 9ffbb0a, harness/, results/; final run 44069979210). Result PARTIAL:
- 0 of 15 real flaky browser tests replay 10/10 with one fingerprint: every one gave 2-10 distinct fingerprints in 10 replays.
- Controls break 33 of 481 tests on actual, etherpad, solid-start, uptime-kuma; 510 of 595 on documenso (estimated cause: seeded random makes the same users/emails in every replay and the Postgres database is not reset, so replays 2-10 hit a unique-constraint error).
- Slowdown x2.2 to x11.3.
- On a fixture app with no uncontrolled background work the mechanism works (2 of 2 replay with one fingerprint).
Round 1's own next steps: database reset per replay, request-scoped server fingerprints, gated server-to-page WebSocket frames, web workers under virtual time.

## How to work this round
1. Diagnose before building. For each of the 5 projects, take two `--det` replays of the same test and find the FIRST diverging event between their traces (browser and server). Classify every source of divergence (timers, network/WebSocket ordering, server background jobs, database state, web workers, fonts/layout, animation frames, crypto/random, Date in the server, other). Table: source, projects hit, how many of the 15 targets it blocks.
2. Close the sources in order of how many targets each blocks. Every fix starts with a test that fails before and passes after. Required among them: the state the app starts from must be identical in every replay (database and files restored to one snapshot before each replay), and the server side must be under the engine's controls (detjs/detpy virtual time and seeded random, request handling order recorded and replayed).
3. A test the controls break is a defect of ours, not of the project: count them, and reduce them.
4. If the diagnosis shows that per-source controls cannot reach one fingerprint on real apps, say so with the evidence and propose the heavier design (one deterministic sandbox for browser + server + database, as in ARCHITECTURE.md L2) with what it would cost to build. Do not stop at "it does not work".

## Exit numbers (same projects as round 1, plus 1-2 new Playwright projects with known flaky tests if a round-1 project stays broken in baseline)
- Share of real flaky browser tests that replay 10/10 with one identical fingerprint and fail in some seed: target at least 60%.
- Tests broken by the controls: target under 2% per project.
- Slowdown vs the project's configured run: report it; target under x3.
- The replay command, printed for each reproduced test, works from a clean checkout.
- Honest comparison with Playwright retries and the trace viewer: what we add, with numbers.

## Rules
- Branch: fenvix-engine-cli `claude/l2-browser-r2`, based on origin/claude/node-l0 @ 9ffbb0a plus round 1's patches (`git am` from tracks/l2-browser/patches/). Push only to your branch.
- Heavy runs on GitHub Actions of the public repository with a push-triggered workflow on your branch; the queue is shared with other sessions, so batch runs. Never run on pull_request.
- Commit and push after every meaningful step (containers restart). Every number labelled MEASURED, ESTIMATED, DECLARED or UNKNOWN.
- No secrets in the repository.

## Delivery
INTERMEDIATE-1.md after the diagnosis table, then REPORT.md (first line DONE or PARTIAL), in fenvix-brain-cli sessions/2026-11-18-l2-browser-r2/, pushed to main as sessions/README.md explains. In chat only: "Report ready: <path>".
```
