# detjs Level 0 (Node / TypeScript): measurement report (`node-validate4`)

Generated 2026-11-16 17:31 UTC with detjs 0.1.0 on GitHub Actions (ubuntu-latest) ([run](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43917700732)). Per repository: 2 baseline runs interleaved with 2 `--det` runs. Baseline = the realistic configuration: random order with a different seed per run where the runner supports it (Vitest `--sequence.shuffle --sequence.seed=N`; Jest `--randomize --seed=N`, Jest >= 29.2 only) and two parallel workers (`--maxWorkers=2`). `--det` = fixed order (files sorted by path, tests in declaration order), one worker, files in sequence, all Level 0 controls. Then, for every test unstable in the baseline, `--det --det-seed=1..1` with 2/2 confirmation of the seed that makes it fail. Labels: MEASURED (by this harness), DECLARED (with source), UNKNOWN; NOISY = shared host.

Verifier: Rust verifier through the Python binding (detpy 0.1.0).

## Main metric

**Baseline-unstable tests made reproducible: 1/2 = 50.0%** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 2 times out of 2 AND some `--det` configuration makes it pass.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| popular (HEAD) | 2 | 2231 | 2 | 1 | 50.0% | 1 | 0 | 0 |
| total | 2 | 2231 | 2 | 1 | 50.0% | 1 | 0 | 0 |

**Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 1: 1; median 1.

**First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `outcome-only` 1.

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
| popular | 0 | 0 | 0 | 1 |
| total | 0 | 0 | 0 | 1 |

* `unknown`: mobx `ling.js::peeking inside autorun doesn't bork (global) state::it should recover from errors` (no marker in the source, exception or fingerprint)

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). **1 tests** (MEASURED), of which 1 fail in every `--det` run.

Cause: `fixed-order` = the test also fails under `--det` with every Level 0 control disabled (only the fixed order and serial execution remain): an order/isolation dependency hidden by the random parallel baseline, not a Level 0 control; otherwise the controls whose `--det-disable` makes it pass; `unexplained` = none does.

| cause &#124; exception | tests | examples |
|---|---:|---|
| `fixed-order (fails without --det too) &#124; Error` | 1 | mobx: packages/mobx-react-plugin/__tests__/vite.test.ts::Vite plugin::plugins from babel overrides and env count as extra transforms: Error: expect(received).toContain(expected) // indexOf (first dive |

## Timing

Quiet timing pass: not run (UNKNOWN).

* Round timings, serial `--det` vs the random parallel baseline: median 161.1% — **NOT COMPARABLE** (different parallelism and order).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 2 runs): 0; unstable in the baseline and stable under `--det`: 2
* stable in both modes but with a different majority outcome: 12
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 2205 (100.0%); not covered: 0

## Per repository (MEASURED)

| repo | pool | pinned at | node | runner | random baseline | tests | unstable | reproduced | seeds explored | broken by det | not covered | documented present / flaky / reproduced |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [luxon](https://github.com/moment/luxon) | popular | [f427515a38](https://github.com/moment/luxon/commit/f427515a38f6a671f8de663e6bcc040ed81f114e) | node v18.20.8 | jest 29.4.3 | no (Jest < 29.2) | 1204 | 0 | 0 | 0 | 0 | 0 |  |
| [mobx](https://github.com/mobxjs/mobx) | popular | [bf94b8e866](https://github.com/mobxjs/mobx/commit/bf94b8e866c58995f78189c5412cf06042012720) | node v22.23.5 | jest 30.3.0 | yes | 1027 | 2 | 1 | 1 | 1 | 0 |  |

## Discarded candidates

| repo | pool | reason | detail |
|---|---|---|---|
| pw-slate | playwright | no-runner | olvable: t evalTypeScript (node:internal/process/execution:291:3) at node:internal/main/eval_string:74:3 { code: 'MODULE_NOT_FOUND', requireStack: [ '/tmp/work/src/pw-slate/x.js' ] } Node.js v22.23.5  |

## Playwright end-to-end suites (measured, not built on)

No Playwright project measured (UNKNOWN).

## Notes

* Flaky pool: the dataset of Hashemi, Tahir, Rasheed, 'An Empirical Study of Flaky Tests in JavaScript' (ICSME 2022, Zenodo 10.5281/zenodo.6673741) is the public dataset of JavaScript flaky tests used first: each project is pinned at the parent of a commit that fixes a flaky test. It covers only 18 projects, most of which do not run their suites with Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites), so it cannot supply 25 projects; the pool is completed with popular projects that have GitHub issues documenting flaky Jest/Vitest tests, each pinned at the last commit before the issue was opened.
* The JS-TOD (order-dependent Jest tests) and environmental-flakiness replication packages were not fetched.
* Only GitHub-hosted runners were used; numbers labelled NOISY come from shared virtual machines.
