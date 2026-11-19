### Idea 3. Dependency-update verdict

**What the customer gets.** On a Dependabot or Renovate pull request: "this bump changes code executed by 312 of 9,400 tests; those 312 ran and passed; the other 9,088 provably never load the package and are reused". Plus what the new version does differently in those tests: new env vars read, new hosts contacted, new files opened.

**Why only a deterministic engine with proof.** It needs the per-test list of installed distributions actually loaded (we record runtime identity by content and the files each test reads) and a trustworthy "unchanged" for the rest. Everyone else gives up here by their own words:
* Blacksmith Vitest: "a lockfile change runs everything" [6]. Datadog TIA: lists "library dependencies" among what it cannot see [16]. Harness TI: changes to build files "can cause TI to select all tests" [21]. Turborepo: the lockfile is part of the global hash [41].
* GitHub's Dependabot compatibility score is "the percentage of CI runs that passed" in **other** public repositories [42] (opened 2026-11-18): a statistic about strangers' suites, not a fact about this one.

**Who pays and why.** Teams with many dependency PRs (bots open them daily). It also attacks one of our own weak cases. In the engine the runtime identity enters as one digest per run (`runtime_digest` passed to `store.begin`, read in `python/detpy/proofcache.py` on origin/claude/rust-hotpaths); how many results a single bump invalidates in practice is UNKNOWN (the market-test report shows one case: prefect, an installed package's `entry_points.txt` after a bump, 118 reruns, MEASURED). It is not the main cause of the 16% of commits that rerun everything: that report's cause table names core modules, shared test utilities, root `conftest.py`, `pyproject.toml` and package metadata that embeds the commit hash.

**Evidence of demand.** The vendors' own caveats above are the evidence that the case is common enough to document. Share of commits that are dependency-only in large Python repositories: UNKNOWN (measured in the plan).

**Build size.** 6 to 12 session-days: split runtime identity from one whole-environment digest into per-distribution identity per test; record which entry-point groups and metadata a test queries; the PR comment.

**Risks.** Plugin discovery reads the metadata of every installed package, which makes the whole environment an input unless we record the query precisely. Native libraries loaded by other native libraries must be followed (we follow children with strace on Linux only).

### Idea 4. Calendar and environment exploration
### Validation plan, idea 3 (dependency-update verdict)

1. **Find the commits.** In the 10 market-test repositories, list the last 30 commits each that change only dependency files (lockfile, requirements, `pyproject` pins). Number: their share of all commits.
2. **Today's engine.** Skip share on those commits: UNKNOWN, to be measured on this set (one runtime digest per run suggests low; the prefect case shows partial reuse).
3. **Per-distribution identity.** Prototype: per test, the set of installed distributions whose files it read or imported, plus the metadata queries it made. Re-walk the same commits. Verify every reuse with a fresh run, as in the market test.
4. **Known breakages.** From the same histories, the dependency bumps followed by a red CI or a revert. Check that every test that broke is inside the "affected" set.
5. **Behaviour difference.** For affected tests, diff the footprint before and after the bump (new env vars, hosts, files). Count bumps with at least one new external effect: this sizes the security-signal reading.
**The number that says yes:** mean share of test time reused with proof on dependency-only commits of at least 50%, with 0 wrong over at least 5,000 verified reuses (95% upper bound 0.06% by the rule of three) and 100% of historically broken tests inside the affected set. No: under 25% (plugin discovery makes everything an input), which would send the work to recording metadata queries more finely before anything is promised.

### Validation plan, idea 4 (short)
