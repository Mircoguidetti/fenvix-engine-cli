# P-028: Validate idea 3, dependency-update verdict (measurement only)

You are a work session for fenvix (deterministic CI engine: Rust core in crates/, Python shell python/detpy). All output in English. Read CLAUDE.md and NOW.md of the brain repository (fenvix-brain-cli), then sessions/2026-11-18-fable-new-value/REPORT.md sections "Idea 3. Dependency-update verdict" and "Validation plan, idea 3". This task is that validation plan, nothing more: measure, do not build the product.

Engine repository: fenvix-engine-cli. Start from branch claude/cache-proof-step1 (cache with proof, review R-009 fixes). Work on a new branch claude/dep-verdict. Market-test data and harness: branch claude/market-test (10 large Python repositories, results and walk harness).

Steps (from the validation plan):
1. In the 10 market-test repositories, list the last 30 commits each that change only dependency files (lockfile, requirements, pyproject pins). Report their share of all commits.
2. Measure today's engine on those commits: share of test time reused with proof (one runtime digest per run today).
3. Prototype per-distribution identity: per test, the set of installed distributions whose files it read or imported, plus the metadata/entry-point queries it made. Re-walk the same commits. Verify every reuse with a fresh run, as the market test did.
4. Known breakages: from the same histories, dependency bumps followed by a red CI or a revert. Check that every test that broke is inside the "affected" set.
5. For affected tests, diff the footprint before and after the bump (new env vars, hosts, files). Count bumps with at least one new external effect.

The number that says yes: mean share of test time reused with proof on dependency-only commits >= 50%, with 0 wrong over >= 5,000 verified reuses (rule-of-three bound), and 100% of historically broken tests inside the affected set. No: under 25%.

Every number labelled MEASURED / ESTIMATED / DECLARED / UNKNOWN. Do not change the engine's default behaviour; the prototype stays behind a flag. Write the report in the brain repository at sessions/2026-11-18-dep-verdict/REPORT.md (first line YES, NO or PARTIAL with the number) and push it to main of fenvix-brain-cli as sessions/README.md explains. In chat write only: "Report ready: sessions/2026-11-18-dep-verdict/REPORT.md".
