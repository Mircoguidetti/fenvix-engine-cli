# R-010 · Review of the market test

Model: Opus 5.5 high. Attach: fenvix-engine-cli and fenvix-brain-cli. New session (founder's other account).

```
You are the reviewer for one delivery. Read fenvix-brain-cli CLAUDE.md, prompts/REVIEWER.md, prompts/COMMON.md and RULES.md and follow them. English only.
Delivery: fenvix-brain-cli sessions/2026-11-17-market-test/REPORT.md (PARTIAL). Engine: fenvix-engine-cli branch claude/market-test, commit e2107683, harness harness/market_test/ (a copy of harness/skip_study2 v3.1).
The headline decides how we describe the market: "7 of 10 large Python repositories skip a mean of at least 50% of test time with proof; 0 of 7,280 verified skips changed a pass or fail". Check above all:
1. Recompute medians, means, the 7-of-10 count and the minutes-saved-per-month estimates from the raw results. Is the "env-ok" view (files failing at the first commit left out) fair, and does the 7-of-10 still hold in the "all units" view?
2. Verification: are the 7,280 verified skips a fair sample (random per commit, fresh run at the same commit, independent of the cache)? Recompute 0 wrong for pass/fail.
3. The prefect hole (test IDs contain the commit hash read from .git, which the capture excludes, limit N9): turn it into a failing test of the proof rule on a branch review-claude/market-test, and say whether other projects can hit the same class (anything derived from .git or the version string).
4. Sampling: are sampled files and transitions picked by a rule fixed in advance, and are low results (litellm, transformers, mlflow) reported as plainly as high ones?
Every number you report carries MEASURED, ESTIMATED, DECLARED or UNKNOWN.
Deliver sessions/2026-11-18-review-market-test/REPORT.md in fenvix-brain-cli main, first line APPROVED or FIX n. In chat only: "Report ready: <path>".
```
