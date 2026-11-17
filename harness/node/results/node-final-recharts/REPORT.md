# detjs Level 0 (Node / TypeScript): measurement report (`node-final-recharts`)

Generated 2026-11-17 16:56 UTC with detjs 0.1.0 on GitHub Actions (ubuntu-latest) ([run](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44107322834)). Per repository: 10 baseline runs interleaved with 10 `--det` runs. Baseline = the realistic configuration: random order with a different seed per run where the runner supports it (Vitest `--sequence.shuffle --sequence.seed=N`; Jest `--randomize --seed=N`, Jest >= 29.2 only) and two parallel workers (`--maxWorkers=2`). `--det` = fixed order (files sorted by path, tests in declaration order), one worker, files in sequence, all Level 0 controls. Then, for every test unstable in the baseline, `--det --det-seed=1..20` with 10/10 confirmation of the seed that makes it fail. Labels: MEASURED (by this harness), DECLARED (with source), UNKNOWN; NOISY = shared host.

Verifier: Rust verifier through the Python binding (detpy 0.1.0).

## Main metric

**Baseline-unstable tests made reproducible: 0/67 = 0.0%** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| popular (HEAD) | 1 | 9348 | 67 | 0 | 0.0% | 18 | 0 | 49 |
| total | 1 | 9348 | 67 | 0 | 0.0% | 18 | 0 | 49 |

## Documented flaky tests (MEASURED)

Documented = tests in the files changed by the flaky-test fix of the Hashemi et al. dataset, or matching the file/test named by the GitHub issue (issue titles often name no test: then nothing matches).

| documented flaky tests found in the measured projects | flaky in our baseline | reproduced |
|---:|---:|---:|
| 0 | 0 | 0 |

## Causes of baseline-flaky tests not reproduced under `--det` (MEASURED, keyword heuristics)

Classes: `concurrency/event-order` (async ordering, timers racing real I/O, timeouts), `external` (network, processes, files, environment), `l0-gap` (a source Level 0 controls still differs, or shared state Level 0 should reset), `unknown`. Evidence per test in `<repo>.causes.json`.

| pool | concurrency/event-order | external | l0-gap | unknown |
|---|---:|---:|---:|---:|
| flaky | 0 | 0 | 0 | 0 |
| popular | 1 | 1 | 9 | 56 |
| total | 1 | 1 | 9 | 56 |

* `concurrency/event-order`: recharts `r.spec.tsx::Bar background zIndex::should handle negative zIndex values in background prop` (test source uses act()
* `external`: recharts `test/component/Text.spec.tsx::scaleToFit=true::scales text to fit the width` (test source uses https://)
* `l0-gap`: recharts `pec.tsx::<YAxis /> Label::label prop::should render label if label prop is a React element` (diverging event `time`: a controlled source still differs between runs); recharts ` distributed ticks when domain={[0, 1000]} and dataKey is "noExist", and allowDataOverflow` (shared state not reset by Level 0: document.); recharts `YAxis.spec.tsx::<YAxis />::Should pass data, index, and event to the onClick event handler` (diverging event `time`: a controlled source still differs between runs)
* `unknown`: recharts ` when the child is a function::should rerender with the final state when isActive is false` (no marker in the source, exception or fingerprint); recharts `test/cartesian/YAxis/YAxis.spec.tsx::<YAxis />::Render ticks reversed` (no marker in the source, exception or fingerprint); recharts `est/cartesian/YAxis/YAxis.spec.tsx::<YAxis />::Should render 5 ticks when domain={0,10000}` (no marker in the source, exception or fingerprint (source not found))

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). **0 tests** (MEASURED), of which 0 fail in every `--det` run.

## Timing

Quiet timing pass: not run (UNKNOWN).

* Round timings, serial `--det` vs the random parallel baseline: median 60.2% — **NOT COMPARABLE** (different parallelism and order).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 0; unstable in the baseline and stable under `--det`: 67
* stable in both modes but with a different majority outcome: 4
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 9206 (100.0%); not covered: 0

## Per repository (MEASURED)

| repo | pool | pinned at | node | runner | random baseline | tests | unstable | reproduced | seeds explored | broken by det | not covered | documented present / flaky / reproduced |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [recharts](https://github.com/recharts/recharts) | popular | [f27aeba629](https://github.com/recharts/recharts/commit/f27aeba6293c66c0e8b602e4351faf6d2de42875) | node v22.23.5 | vitest 4.1.11 | yes | 9348 | 67 | 0 | 1 (budget) | 0 | 0 |  |

## Playwright end-to-end suites (measured, not built on)

No Playwright project measured (UNKNOWN).

## Notes

* Flaky pool: the dataset of Hashemi, Tahir, Rasheed, 'An Empirical Study of Flaky Tests in JavaScript' (ICSME 2022, Zenodo 10.5281/zenodo.6673741) is the public dataset of JavaScript flaky tests used first: each project is pinned at the parent of a commit that fixes a flaky test. It covers only 18 projects, most of which do not run their suites with Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites), so it cannot supply 25 projects; the pool is completed with popular projects that have GitHub issues documenting flaky Jest/Vitest tests, each pinned at the last commit before the issue was opened.
* The JS-TOD (order-dependent Jest tests) and environmental-flakiness replication packages were not fetched.
* Only GitHub-hosted runners were used; numbers labelled NOISY come from shared virtual machines.
