# P-024 · Fable audit of the whole system (after P-023 passes)

Written 2026-11-18 by the coordinator, asked by the founder. Starts after the end-to-end suite (P-023) passes on the deployed system. Model: Fable. Repositories: fenvix-app, fenvix-engine-cli, fenvix-brain-cli (read; report in the brain or on a branch).

## Acceptance rule (founder, 2026-11-18): when is it "done"

Reviews never prove that nothing is wrong; they stop when the evidence says the risk is low enough. The system is accepted when ALL hold:
1. Severity bar: the last review round found no High and no Medium finding in scope (Low findings are logged, not blocking).
2. Diminishing returns: two independent reviewers in a row (fresh sessions, not anchored on each other) find no new High or Medium.
3. Every finding ever made is a regression test that runs on every change (engine suite, app tests, infra tests, e2e).
4. Measured ground truth, not opinions: the end-to-end suite (P-023) passes; skip with proof is checked by fresh reruns, and the wrong-skip rate is bounded: 0 wrong in N checked skips means the true rate is below about 3/N with 95% confidence (rule of three); report N and the bound.
5. In production the product keeps checking itself: a random share of skipped tests (audit reruns, e.g. 5%) is rerun on every run, and any wrong skip pages us and disables reuse for that key.
State for each item whether it holds, with evidence.

```
You audit the whole fenvix system as an outsider would before trusting it with customer code. All output in English.
1. Read: fenvix-brain-cli (CLAUDE.md, PRODUCT.md, ARCHITECTURE.md, DECISIONS.md, NUMBERS.md, every review report under sessions/), fenvix-app (github-app/, infra/, docs/), fenvix-engine-cli (crates/, python/detpy, node/, runner/).
2. Run the end-to-end suite (fenvix-app scripts/e2e.sh) yourself and read its output.
3. Attack it as a hostile customer and as an outsider: secrets reachable from a job; one customer's data, cache entries or results reachable from another's job; forged webhooks and summaries; cost blow-ups (runaway machines, unbounded queues); a skip with proof that is wrong (try the hole classes the reviewers found: env, files, network, child processes, git, TZ, start-up processes, runtime identity across machines).
4. Check that what runs matches what the documents claim: architecture, permissions, prices and monthly costs, the numbers in NUMBERS.md, the dashboard's figures.
5. Deliver a report: first line SAFE TO DEMO / SAFE FOR FIRST CUSTOMER / NOT SAFE, then every finding with severity, evidence and the cheapest fix; and a one-page summary in Italian for the founder.
In chat only: "Report ready: <path>".
```
