# P-029: Validate idea 2, exact culprit (measurement only)

You are a work session for fenvix (deterministic CI engine: Rust core in crates/, Python shell python/detpy). All output in English. Read CLAUDE.md and NOW.md of the brain repository (fenvix-brain-cli), then sessions/2026-11-18-fable-new-value/REPORT.md sections "Idea 2. Exact culprit" and "Validation plan, idea 2". This task is that validation plan, nothing more: measure, do not build the product.

Engine repository: fenvix-engine-cli. Start from branch claude/cache-proof-step1 (cache with proof, review R-009 fixes). Work on a new branch claude/exact-culprit. Market-test data and walks: branch claude/market-test; the 16 realistic CI environment changes of the head-to-head are in NUMBERS.md of the brain.

Steps (from the validation plan):
1. Cases with known answers:
   a. planted code regressions: 200 mutants over 10 repositories, each committed k commits back in a replayed history (k from 5 to 200), each killing at least one test;
   b. real history: every pass-to-fail transition in the market-test and cache-proof walks, with the true culprit from the commit the project reverted or fixed, where identifiable;
   c. no-code reds: the 16 realistic CI changes (package bump, env var, locale, time zone, file permissions, runner image), one at a time and two at a time (decoy).
2. A prototype finder (behind a flag): input the red test and the last green key; it diffs the proof keys, prunes candidates with the test's footprint, and replays the test deterministically once per step. Output one commit or one input. Record test executions, wall time, and whether the environment was rebuilt exactly (runtime identity equal).
3. Baseline: git bisect run with the same test under plain pytest: executions, wall time, and for flaky cases how often it names the wrong commit in 10 attempts.
4. Flaky defects: 50 reproduced order-dependent defects; find the commit that introduced the polluter.

The number that says yes: >= 95% correct culprits over >= 300 cases, median <= 3 test executions per case, and 14 of 14 no-code reds attributed to the right input. No: under 85%, or the old environment cannot be rebuilt in more than 20% of cases.

Every number labelled MEASURED / ESTIMATED / DECLARED / UNKNOWN. Do not change the engine's default behaviour. Write the report in the brain repository at sessions/2026-11-18-exact-culprit/REPORT.md (first line YES, NO or PARTIAL with the number) and push it to main of fenvix-brain-cli as sessions/README.md explains. In chat write only: "Report ready: sessions/2026-11-18-exact-culprit/REPORT.md".
