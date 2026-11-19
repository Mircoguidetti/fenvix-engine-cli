### Idea 2. Exact culprit (commit or input)

**What the customer gets.** For every test that turns red: "caused by commit abc123, function `parse_header`" or "caused by `urllib3` 2.3.0 to 2.4.0" or "caused by env var `TZ` now set in the workflow" or "caused by the runner image update", with a replay command for before and after. It also answers the daily question "it failed and nobody changed the code".

**Why only a deterministic engine with proof.** A bisect step needs one execution only when a run is deterministic; with a flaky test each step needs many reruns and still may lie. The footprint prunes the search: only commits that changed something the test actually read are candidates, and results for the others are already in the cache. And the suspect set is not only commits: the proof key lists every input (code units, files, env vars, runtime identity), so the difference between the last green key and the red key is a short list that can be tested one by one.
* Trunk: bisects **batches of PRs** in the merge queue, by rerunning CI [20]. Develocity: its agent labels a failure "flaky, pre-existing, or caused by your change" and estimates the reruns needed [17]. Datadog: an AI assigns one of 14 cause categories [16]. Blacksmith: log search and SSH [4]. None can name a changed input, because none records inputs per test.
* Antithesis: mentions "difficult bisections" as a solved internal problem [15], but for systems packaged for its hypervisor.

**Who pays and why.** The same platform lead, for hours of debugging removed; and coding agents, which need "was it my change?" before spending tokens.

**Evidence of demand.** 28% of flaky Python tests come from test infrastructure, not from code (DECLARED [37]). Blacksmith's root filesystem is a clone of GitHub's images "which we routinely update" and runners may be silently upgraded to a bigger size [40][5] (notes 2026-11-17, [5] opened 2026-11-18): environment changes under the customer are normal. Our own head-to-head: of 16 realistic CI environment changes, 14 broke at least one test (MEASURED, NUMBERS.md).

**Build size.** 6 to 10 session-days: key diff between two runs, candidate pruning, a driver that rebuilds an input set (checkout, pinned package, env) and replays one test.

**Risks.** Rebuilding an old environment exactly (old wheels, old images) is the hard part; we have runtime identity by content, so we know when we failed to rebuild it. A culprit that is "two inputs together" needs a slightly larger search.

### Idea 3. Dependency-update verdict
### Validation plan, idea 2 (exact culprit)

1. **Cases with known answers, three kinds.**
   a. *Planted code regressions:* 200 mutants over 10 repositories, each committed k commits back in a replayed history (k from 5 to 200), each killing at least one test.
   b. *Real history:* every pass-to-fail transition already in the market-test and cache-proof walks (10 repositories, 50 commits each), with the true culprit taken from the commit that the project itself reverted or fixed, where identifiable.
   c. *No-code reds:* the 16 realistic CI changes of the head-to-head (14 of which break tests): package bump, env var, locale, time zone, file permissions, runner image. Applied one at a time and also two at a time (to test the search with a decoy).
2. **Run the finder.** Input: the red test and the last green key. Output: one commit or one input. Record the number of test executions, wall time and whether the environment could be rebuilt exactly (runtime identity equal).
3. **Baseline.** `git bisect run` with the same test under plain pytest: executions and wall time; for the flaky cases, how often it names the wrong commit in 10 attempts.
4. **Flaky defects.** 50 reproduced order-dependent defects from the mixed round: find the commit that introduced the polluter. Ground truth where the project's history shows the fix.
**The number that says yes:** at least 95% correct culprits over at least 300 cases, with a median of 3 test executions or fewer per case, and 14 of 14 no-code reds attributed to the right input. No: under 85%, or the old environment cannot be rebuilt in more than 20% of cases (that would make it a different, harder product).

### Validation plan, idea 3 (dependency-update verdict)
