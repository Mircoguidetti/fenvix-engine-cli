# detjs Level 0 (Node / TypeScript): measurement report (`node-validate3`)

Generated 2026-11-16 17:18 UTC with detjs 0.1.0 on GitHub Actions (ubuntu-latest) ([run](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43915811302)). Per repository: 3 baseline runs interleaved with 3 `--det` runs. Baseline = the realistic configuration: random order with a different seed per run where the runner supports it (Vitest `--sequence.shuffle --sequence.seed=N`; Jest `--randomize --seed=N`, Jest >= 29.2 only) and two parallel workers (`--maxWorkers=2`). `--det` = fixed order (files sorted by path, tests in declaration order), one worker, files in sequence, all Level 0 controls. Then, for every test unstable in the baseline, `--det --det-seed=1..2` with 3/3 confirmation of the seed that makes it fail. Labels: MEASURED (by this harness), DECLARED (with source), UNKNOWN; NOISY = shared host.

Verifier: Rust verifier through the Python binding (detpy 0.1.0).

## Main metric

**Baseline-unstable tests made reproducible: 0/4 = 0.0%** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 3 times out of 3 AND some `--det` configuration makes it pass.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| popular (HEAD) | 4 | 6741 | 4 | 0 | 0.0% | 4 | 0 | 0 |
| total | 4 | 6741 | 4 | 0 | 0.0% | 4 | 0 | 0 |

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
| popular | 0 | 0 | 0 | 4 |
| total | 0 | 0 | 0 | 4 |

* `unknown`: mobx `e/action.js::should be possible to change observed state in an action called from computed` (no marker in the source, exception or fingerprint); mobx `sn't bork (global) state::it should not break internal consistency when exception occurred` (no marker in the source, exception or fingerprint); mobx `ling.js::peeking inside autorun doesn't bork (global) state::it should recover from errors` (no marker in the source, exception or fingerprint)

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). **97 tests** (MEASURED), of which 97 fail in every `--det` run.

Cause: `fixed-order` = the test also fails under `--det` with every Level 0 control disabled (only the fixed order and serial execution remain): an order/isolation dependency hidden by the random parallel baseline, not a Level 0 control; otherwise the controls whose `--det-disable` makes it pass; `unexplained` = none does.

| cause &#124; exception | tests | examples |
|---|---:|---|
| `unexplained &#124; unknown` | 96 | luxon: test/datetime/create.test.js::<file>: ● Test suite failed to run (first diverging source: -)<br>luxon: test/datetime/degrade.test.js::<file>: ● Test suite failed to run (first diverging source: -) |
| `fixed-order (fails without --det too) &#124; Error` | 1 | mobx: packages/mobx-react-plugin/__tests__/vite.test.ts::Vite plugin::plugins from babel overrides and env count as extra transforms: Error: expect(received).toContain(expected) // indexOf (first dive |

## Timing

Quiet timing pass: not run (UNKNOWN).

* Round timings, serial `--det` vs the random parallel baseline: median 0.1% — **NOT COMPARABLE** (different parallelism and order).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 3 runs): 0; unstable in the baseline and stable under `--det`: 4
* stable in both modes but with a different majority outcome: 2219
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 4489 (100.0%); not covered: 0

## Per repository (MEASURED)

| repo | pool | pinned at | node | runner | random baseline | tests | unstable | reproduced | seeds explored | broken by det | not covered | documented present / flaky / reproduced |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [date-fns](https://github.com/date-fns/date-fns) | popular | [a9739fb3e5](https://github.com/date-fns/date-fns/commit/a9739fb3e5384a810e90d7376446f6d84ecc5029) | node v22.23.5 | vitest 5.0.1 | yes | 222 | 0 | 0 | 0 | 0 | 0 |  |
| [luxon](https://github.com/moment/luxon) | popular | [f427515a38](https://github.com/moment/luxon/commit/f427515a38f6a671f8de663e6bcc040ed81f114e) | node v18.20.8 | jest 29.4.3 | no (Jest < 29.2) | 1262 | 0 | 0 | 0 | 58 | 0 |  |
| [mobx](https://github.com/mobxjs/mobx) | popular | [bf94b8e866](https://github.com/mobxjs/mobx/commit/bf94b8e866c58995f78189c5412cf06042012720) | node v22.23.5 | jest 30.3.0 | yes | 1065 | 4 | 0 | 2 | 39 | 0 |  |
| [immer](https://github.com/immerjs/immer) | popular | [784c86bb23](https://github.com/immerjs/immer/commit/784c86bb234e805566481c9425fcb2a3897e8bcc) | node v22.23.5 | vitest 3.2.6 | yes | 4192 | 0 | 0 | 0 | 0 | 0 |  |

## Discarded candidates

| repo | pool | reason | detail |
|---|---|---|---|
| dayjs | popular | unsupported | jest 22.4.4 (detjs needs jest-circus, the default runner since Jest 27) |
| pw-slate | playwright | no-runner | olvable: t evalTypeScript (node:internal/process/execution:291:3) at node:internal/main/eval_string:74:3 { code: 'MODULE_NOT_FOUND', requireStack: [ '/tmp/work/src/pw-slate/x.js' ] } Node.js v22.23.5  |

## Playwright end-to-end suites (measured, not built on)

1 projects at HEAD, Chromium only, `--retries=0`. Baseline: the project's own parallel workers. `--det`: `--workers=1` and the Level 0 controls inside the Playwright worker processes (seeds, clock, timers, fs order, closed network for the test process; `node/src/register.js`). The browser and the web servers are separate processes and are not controlled; Playwright has no test shuffle, so `--det-seed` only changes the seeds. No per-test fingerprints (no hook into the Playwright runner).

**Baseline-unstable browser tests: 0 of 52 (0.0%)** (MEASURED); of these, never fail under `--det`: 0, fail sometimes under `--det`: 0, always fail under `--det`: 0, reproduced 0. Tests broken by `--det`: 0.

| repo | runner | tests | unstable baseline | unstable --det | became stable | broken by --det |
|---|---|---:|---:|---:|---:|---:|
| [pw-msw](https://github.com/mswjs/msw) | playwright 1.63.0 | 52 | 0 | 0 | 0 | 0 |

Share of the baseline-unstable tests of this round that are browser tests: 0/4 = 0.0% (MEASURED, not weighted by project size).

## Notes

* Flaky pool: the dataset of Hashemi, Tahir, Rasheed, 'An Empirical Study of Flaky Tests in JavaScript' (ICSME 2022, Zenodo 10.5281/zenodo.6673741) is the public dataset of JavaScript flaky tests used first: each project is pinned at the parent of a commit that fixes a flaky test. It covers only 18 projects, most of which do not run their suites with Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites), so it cannot supply 25 projects; the pool is completed with popular projects that have GitHub issues documenting flaky Jest/Vitest tests, each pinned at the last commit before the issue was opened.
* The JS-TOD (order-dependent Jest tests) and environmental-flakiness replication packages were not fetched.
* Only GitHub-hosted runners were used; numbers labelled NOISY come from shared virtual machines.
