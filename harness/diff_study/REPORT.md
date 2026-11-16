# Execution diff study: base vs head of merged PRs under `--det`

Status: DRAFT (interim, 42 PRs). Numbers are refreshed when run 4 lands.

Question: if we run the base and the head of real merged pull requests under
`--det` (same seed, same order) and compare per-test traces, is the result
clean enough to be the center of a product ("execution diff", Move 1 of
`sessions/2026-11-16-fable-olix-moves/REPORT.md` in the brain repository)?

Interim verdict: NO-GO as product center on today's trace. The diff is clean
(99.4% identical, MEASURED) because only 2.5% of tests carry any event beyond
outcome and end-of-test random state (MEASURED): 30,461 tests ran PR-changed
code and, with a stable site identity, 0 show a stable divergence in a changed
file (MEASURED). Of 192 surviving mutants the trace diff flags 2 (1.0%), both
thread-interleaving noise; a prototype return-value event flags 31 (16.1%)
(MEASURED).
