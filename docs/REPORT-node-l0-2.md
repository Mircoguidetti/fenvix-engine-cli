# Node L0 (detjs) — fix round after review R-005

Session node-l0, 2026-11-17/18. Branch `claude/node-l0`. Labels: MEASURED (this work), ESTIMATED, DECLARED (with
source), UNKNOWN; NOISY = shared host (GitHub-hosted runners).

The review file (fenvix-brain-cli `sessions/2026-11-17-review-node/REPORT.md`) cannot be read from this session
(attaching fenvix-brain-cli was refused twice). The four items below are taken from the coordinator's message; the
reviewer's notes on customer-facing claims were not available, so the last section lists the claims of the final
report that were checked and changed.

The updated final report is `docs/REPORT-node-l0.md` (regenerated); the result files are in
`harness/node/results/node-final/` (the six re-measured projects come from `node-fix2/`; what they replaced is kept in
`node-before-fixes-6/`).

## Summary of before / after

| item | before (REPORT-node-l0.md at dcfe8bd) | after |
|---|---|---|
| 1. main metric | 129/421 = 30.6% (ids that change between runs counted) | 239/341 = **70.1%** (MEASURED); on the same data as before, only the denominator rule changed: 129/321 = 40.2% |
| 1. working tree | not restored between runs | restored before every run (b8b3185); tanstack-table: 36 tests with run-dependent ids → 0 |
| 2. runs per project | 5 projects partial (xstate 5, excalidraw 6, growi 6, recharts 7, vercel 7 runs per mode) | all 41 projects 10 baseline + 10 `--det` (MEASURED) |
| 3. fingerprint coverage | 98.8% (79661/80649; tests without a fingerprint left out) | **96.4%** (79615/82619; 1926 tests without a fingerprint counted as not covered, 1923 of them type-check tasks) |
| 4. regression tests | 20 shell tests; 5 fix commits without a test | 27 tests; every fix has a test, each checked at the parent of its fix |
| tests broken by `--det` | 48 | 44 (MEASURED; 3 of them fail in only 1 of 10 `--det` runs, no cause attributed) |

## 1. Main metric denominator

**Rule (as Python Block 1, P-008, e01d707).** A test counted as unstable in the baseline because it is *absent* from
some baseline runs is not a flaky test: its id contains a run-dependent value (a time in the test name), or its file
appeared during the round. It is excluded from the metric (`ci.py csv_metrics`, the same definitions as
`detpy_harness.csv_metrics`). The metric is computed from the per-test CSVs of every project.

**Working tree.** The harness now records the checkout after install (and after the fallback build) and restores it
before every run: new untracked or ignored entries are removed, modified tracked files are checked out again
(`node_harness.snapshot_tree` / `clean_tree`, b8b3185; tested by hand on a checkout: new files and directories removed,
a modified README restored, `node_modules` kept). tanstack-table wrote test files under `.cache/` that later runs
collected.

| measurement | unstable in baseline | ids excluded | reproduced | % |
|---|---:|---:|---:|---:|
| published (dcfe8bd) | 421 | 0 | 129 | 30.6% |
| same data, exclusion rule | 321 | 100 (yup 40, tanstack-table 36, recharts 14, happy-dom 10) | 129 | 40.2% |
| after the re-runs (item 2) and the tree restore | 341 | 70 (yup 40, recharts 20, happy-dom 10) | 239 | **70.1%** |

tanstack-table with the tree restored (MEASURED): 1856 → 1816 tests (the 40 test files written under `.cache/` no
longer collected), 36 → 0 tests with run-dependent ids, broken by `--det` 4 → 0 (they were tests from `.cache/`), 29
entries removed in total over the round.

The remaining excluded ids are genuine: yup builds 40 test names from the date, recharts 20, happy-dom 10.

## 2. Run counts

Five projects had stopped early on the per-project time budget (5400 s, of which 60% for the baseline / `--det`
phase). They were re-run with a budget of 18000 s and a job limit of 355 minutes (the round job timeout is now
configurable), together with tanstack-table (item 1), in run
[44160127701](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44160127701).

| project | runs (baseline + `--det`) | tests | reproduced / unstable (ids excluded) | ids excluded | broken by `--det` |
|---|---|---|---|---|---|
| xstate | 5+5 → 10+10 | 5043 → 5043 | 0/6 → 3/7 | 0 → 0 | 0 → 0 |
| excalidraw-flaky | 6+6 → 10+10 | 1611 → 1611 | 0/57 → 44/67 | 0 → 0 | 14 → 14 |
| growi-flaky | 6+6 → 10+10 | 5959 → 5959 | 0/2 → 2/2 | 0 → 0 | 0 → 0 |
| recharts | 7+7 → 10+10 | 9348 → 9398 | 0/53 → 60/62 | 14 → 20 | 0 → 0 |
| vercel-flaky | 7+7 → 10+10 | 3212 → 3212 | 0/1 → 1/1 | 0 → 0 | 1 → 1 |
| tanstack-table | 10+10 → 10+10 | 1856 → 1816 | 0/0 → 0/0 | 36 → 0 | 4 → 0 (2 of the 4 had run-dependent ids) |

All 41 projects in the numbers now have 10 baseline and 10 `--det` runs (MEASURED; per project in
`node-final/summary.json`, `per_repo_strict`). The excalidraw job is marked failed in Actions after its measurement
step: its results (10+10 runs, seed exploration) were committed; the failure came later in the job.

**What the jump from 40.2% to 70.1% means.** The five partial projects had reproduced nothing because the time budget
ran out *before* the seed exploration, which is what reproduces a baseline-flaky test; the earlier figure counted their
unstable tests in the denominator with no chance to be reproduced. Completing them added 110 reproduced tests. The
result is concentrated: recharts (60/62) and excalidraw (44/67) give 104 of the 239; without these two projects the
figure is 135/212 = 63.7%. Over the 27 projects with at least one baseline-unstable test, the median per-project
share is 100% (MEASURED, small counts per project; valibot 51/51, quasar 15/17, react-admin 11/27, apollo-client 3/24).

Versions: 35 projects were measured with detjs at a6d2fbd, the six re-run projects at b8b3185, whose detjs code is that
of e747edd (a6d2fbd plus `performance.now()` counted per test file, which only changes what `performance.now()`
returns in later files).

## 3. Fingerprint coverage

**Rule.** A test that ran under `--det` but has no fingerprint at all is now counted as not covered (`nofp_ran`).
Before: 79661/80649 = 98.8%. Same data with the rule: 79661/82575 = 96.5%. After the re-runs: **79615/82619 = 96.4%**
(MEASURED).

**Why there is no fingerprint (zod: 1847).** 1923 of the 1926 are Vitest *type-check* tasks: `*.test-d.ts` files,
and zod runs every test file a second time in type-check mode (`typecheck.enabled`; ids
`file::file::…`). Type-check tasks are checked by `tsc` and no test code is executed, so the runner hooks that bracket
a test never run and there is nothing to fingerprint. The runtime copy of each zod test is covered. This cannot be
fixed in Level 0 (nothing runs to be controlled); the tasks stay counted as not covered, labelled as type-check
(`nofp_typecheck` in `summary.json`). The other 3 are nuxt `treeshake-client.test.ts` tests (`it.each` in a describe
that mocks `process.cwd()`); a fixture reproducing that pattern is traced normally, so the cause is UNKNOWN.

## 4. Regression tests

`node/test/regressions.test.js` adds one test per defect fixed without a test. Each test was run against a worktree at
the parent of its fix commit (with the test file of the fix commit for the older ones) and at HEAD (MEASURED):

| fix commit | defect (project) | test | fails at the parent | passes at HEAD |
|---|---|---|---|---|
| a6d36ff | Vite refused the runner outside the root (jotai) | jsdom project, `server.fs` restricted to the root: 0 of 2 files ran | yes | yes |
| 7c91f0e | in band, an open handle kept Jest alive (react-testing-library) | suite leaves a server listening | yes (killed at 120 s) | yes |
| 8b67806 | the project transform compiled the detjs runner (matrix-js-sdk, immutable-js) | transform that throws on files outside the project | yes | yes |
| 8b67806 | extra `at async main` frame in async stacks (babel) | custom runner that awaits its tests and inspects its stack | yes | yes |
| 83516ab / a6d2fbd | custom Jest runner bypassed detjs silently (babel, prettier) | warning in stderr and `meta.isolation` | yes | yes |
| 50036b6 | runner timers must stay real | 10 s virtual sleep in a test with a 3 s timeout | no: the defect was introduced and fixed inside the same change, the parent never had it; the test guards the behaviour | yes |
| bedbfd5, 1746af8, e9a41c7, d3075a1, a6d2fbd | (tests added with the fix) | `projects.test.js`, `jsdom.test.js`, `unchanged.test.js` | yes | yes |
| e747edd | `performance.now()` per test file (recharts) | two-file fixture | Jest yes; Vitest no (each Vitest file already gets a fresh worker under the default isolation; recharts hit it through its own configuration) | yes |

Shell tests: 27/27 pass locally (MEASURED); `cargo test -p detpy-core` 44/44. The CI tests job of run 44160127701 ran
at b8b3185, before the regression tests were added (20/20).

## Customer-facing claims checked

The reviewer's notes were not readable; these are the claims of `docs/REPORT-node-l0.md` that were checked and
changed:

* The main metric is now stated as what it is: tests that were flaky **in our own baseline runs** (random order, two
  workers), reproduced = fail 10/10 under a seed or the fixed order **and** pass under some `--det` configuration. It
  is not a rate on known flaky tests: none of the flaky tests named by the projects' issues was flaky in our baseline,
  so Level 0 has reproduced **no documented flaky test** in this round (MEASURED: 31 found in the suites, 0 flaky in
  our baseline).
* The figure is concentrated in two projects (104 of 239 from recharts and excalidraw) and per-project counts are
  small; the per-project breakdown is given instead of only the aggregate.
* Coverage is reported with tests that ran without a fingerprint counted as not covered (96.4%).
* Shortfalls stay explicit: 16 of 25 documented-flaky projects, 3 of 5 Playwright projects; babel and prettier
  (Level 0 not applied, J16) and matrix-js-sdk (`--det` runs crash, UNKNOWN cause) are outside the numbers; the
  Hashemi et al. dataset supplied no measurable project.
* Playwright: only the test process (Node side) is under Level 0; no claim on browser flakiness.
* Slowdown: median 3.1% over 9 projects, NOISY (shared runners), not a general performance claim; call-site capture
  costs much more on clock-heavy code (J5: 3 s → 25 s on one react-redux test, MEASURED locally).

## Re-check R-005b: wording fixes

Applied to `docs/REPORT-node-l0.md` (generated by `harness/node/final_report.py`):

1. **Concentration and seed exploration.** The summary now states that recharts and excalidraw give 104 of the 239
   reproduced tests (without them 135/212 = 63.7%). The main-results heading says "seeds 1..20 at most": seed
   exploration stopped on the per-project time budget in 9 of the 41 projects (MEASURED: apollo-client 3 seeds,
   excalidraw 4, happy-dom 2, mermaid 2, quasar 3, react-admin 2, recharts 13, svelte 15, xstate 8); their remaining
   baseline-unstable tests may be reproducible with more seeds.
2. **Labels without a cause.** The causes of tests broken by `--det` are now taken from the per-test CSVs, and a test
   that fails in at most one `--det` run is listed as "no cause" instead of with the controls the ablation happened to
   name: the 3 excalidraw `search.test.tsx` tests labelled `seeds+time+timers+fs+net` fail in 1 of 10 `--det` runs.
   The Playwright table no longer has a "became stable" column: pw-msw's 1 test that was unstable in the baseline and
   stable under `--det` is not credited to Level 0, because the `--det` runs also use one worker and no one-worker run
   without `--det` was made to separate the two.
