# detjs Level 0 (Node / TypeScript): measurement report (`node-rerun2`)

Generated 2026-11-17 08:20 UTC with detjs 0.1.0 on GitHub Actions (ubuntu-latest) ([run](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44040787847)). Per repository: 10 baseline runs interleaved with 10 `--det` runs. Baseline = the realistic configuration: random order with a different seed per run where the runner supports it (Vitest `--sequence.shuffle --sequence.seed=N`; Jest `--randomize --seed=N`, Jest >= 29.2 only) and two parallel workers (`--maxWorkers=2`). `--det` = fixed order (files sorted by path, tests in declaration order), one worker, files in sequence, all Level 0 controls. Then, for every test unstable in the baseline, `--det --det-seed=1..20` with 10/10 confirmation of the seed that makes it fail. Labels: MEASURED (by this harness), DECLARED (with source), UNKNOWN; NOISY = shared host.

Verifier: Rust verifier through the Python binding (detpy 0.1.0).

## Main metric

**Baseline-unstable tests made reproducible: 0/0 = n/a** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| documented flaky | 2 | 52845 | 0 | 0 | n/a | 0 | 0 | 0 |
| popular (HEAD) | 1 | 899 | 0 | 0 | n/a | 0 | 0 | 0 |
| total | 3 | 53744 | 0 | 0 | n/a | 0 | 0 | 0 |

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
| popular | 0 | 0 | 0 | 0 |
| total | 0 | 0 | 0 | 0 |


## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). **1667 tests** (MEASURED), of which 1667 fail in every `--det` run.

Cause: `fixed-order` = the test also fails under `--det` with every Level 0 control disabled (only the fixed order and serial execution remain): an order/isolation dependency hidden by the random parallel baseline, not a Level 0 control; otherwise the controls whose `--det-disable` makes it pass; `unexplained` = none does.

| cause &#124; exception | tests | examples |
|---|---:|---|
| `fixed-order (fails without --det too) &#124; unknown` | 1667 | babel-flaky: codemods/babel-plugin-codemod-object-assign-to-object-spread/test/index.js::<file>: ● Test suite failed to run (first diverging source: -)<br>babel-flaky: codemods/babel-plugin-codemod-optional-catch-binding/test/index.js::<file>: ● Test suite failed to run (first diverging source: -) |

## Timing

Quiet timing pass: not run (UNKNOWN).

* Round timings, serial `--det` vs the random parallel baseline: median -88.7% — **NOT COMPARABLE** (different parallelism and order).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 0; unstable in the baseline and stable under `--det`: 0
* stable in both modes but with a different majority outcome: 52845
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 899 (100.0%); not covered: 0

## Per repository (MEASURED)

| repo | pool | pinned at | node | runner | random baseline | tests | unstable | reproduced | seeds explored | broken by det | not covered | documented present / flaky / reproduced |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [babel-flaky](https://github.com/babel/babel) | flaky | [ddf20013bd](https://github.com/babel/babel/commit/ddf20013bdfd960308090865777bf4cf3c8d1f8d) ([doc](https://github.com/babel/babel/issues/16083)) | node v20.20.2 | jest 29.6.2 | yes | 25792 | 0 | 0 | 0 | 238 | 0 | 0 / 0 / 0 |
| [prettier-flaky](https://github.com/prettier/prettier) | flaky | [e51ff9ad41](https://github.com/prettier/prettier/commit/e51ff9ad41b0c8e22aaad2d7d6b99710ccebfd3d) ([doc](https://github.com/prettier/prettier/issues/18150)) | node v20.20.2 | jest 30.2.0 | yes | 27053 | 0 | 0 | 0 | 1429 | 0 | 0 / 0 / 0 |
| [immutable-js](https://github.com/immutable-js/immutable-js) | popular | [abfaef3c08](https://github.com/immutable-js/immutable-js/commit/abfaef3c08905918e9fa05d0595e7e220fd36dbf) | node v22.23.5 | jest 29.7.0 | yes | 899 | 0 | 0 | 0 | 0 | 0 |  |

## Playwright end-to-end suites (measured, not built on)

No Playwright project measured (UNKNOWN).

## Notes

* Flaky pool: the dataset of Hashemi, Tahir, Rasheed, 'An Empirical Study of Flaky Tests in JavaScript' (ICSME 2022, Zenodo 10.5281/zenodo.6673741) is the public dataset of JavaScript flaky tests used first: each project is pinned at the parent of a commit that fixes a flaky test. It covers only 18 projects, most of which do not run their suites with Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites), so it cannot supply 25 projects; the pool is completed with popular projects that have GitHub issues documenting flaky Jest/Vitest tests, each pinned at the last commit before the issue was opened.
* The JS-TOD (order-dependent Jest tests) and environmental-flakiness replication packages were not fetched.
* Only GitHub-hosted runners were used; numbers labelled NOISY come from shared virtual machines.
