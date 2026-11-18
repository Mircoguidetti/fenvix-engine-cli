# P-025 · Self-check in production: audit reruns of skipped tests

Written 2026-11-18 by the coordinator (founder's acceptance rule, P-024 item 5). Start when the shared cache (claude/shared-cache) closes its R-008d round. Model: Opus 5.5 high. Repositories: fenvix-engine-cli (work), fenvix-app (work, claude/github-app), fenvix-brain-cli (read).

```
You are a work session for fenvix. All output in English. Today a test skipped with proof is never rerun in a customer's run; the only checks are our studies. Build the self-check:
1. Engine (detpy and detjs, `--det-cache-audit=<share>`, default 5%): in every run, a seeded random share of the tests that would be reused with proof is run fresh instead, in addition to the reuse decision being recorded; the fresh outcome is compared with the cached one (outcome, and the set of test ids). The seed and the chosen tests are in the receipts, so an audit is reproducible.
2. A mismatch is a wrong skip: the run reports it in summary.json (`audit: {checked, matched, wrong, flaky_evidence}`), the key is marked untrusted in the shared cache (no reuse until a new fresh run records it again), and the GitHub App raises an alert (a log line at ERROR plus a row the dashboard shows; paging is configured later). A mismatch that a second fresh run does not reproduce is flaky with evidence, not wrong.
3. The dashboard and the billing ignore audited tests as "skipped" (they ran).
4. Report per project and over all projects: checked, wrong, and the 95% upper bound on the wrong-skip rate (rule of three when wrong = 0).
Tests for every rule (a planted wrong reuse must be caught by the audit at 100% share; the untrusted key must stop reuse). Branch claude/audit-reruns from claude/shared-cache in the engine; in fenvix-app on claude/github-app. Report: sessions/2026-11-18-audit-reruns/REPORT.md on the engine branch (first line DONE or PARTIAL). In chat only: "Report ready: <path>".
```
