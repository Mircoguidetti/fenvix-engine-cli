# detjs Level 0 (Node / TypeScript): measurement report (`node-rerun`)

Generated 2026-11-17 09:13 UTC with detjs 0.1.0 on GitHub Actions (ubuntu-latest) ([run](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44032723166)). Per repository: 10 baseline runs interleaved with 10 `--det` runs. Baseline = the realistic configuration: random order with a different seed per run where the runner supports it (Vitest `--sequence.shuffle --sequence.seed=N`; Jest `--randomize --seed=N`, Jest >= 29.2 only) and two parallel workers (`--maxWorkers=2`). `--det` = fixed order (files sorted by path, tests in declaration order), one worker, files in sequence, all Level 0 controls. Then, for every test unstable in the baseline, `--det --det-seed=1..20` with 10/10 confirmation of the seed that makes it fail. Labels: MEASURED (by this harness), DECLARED (with source), UNKNOWN; NOISY = shared host.

Verifier: Rust verifier through the Python binding (detpy 0.1.0).

## Main metric

**Baseline-unstable tests made reproducible: 2/140 = 1.4%** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| documented flaky | 4 | 31723 | 140 | 2 | 1.4% | 137 | 0 | 1 |
| total | 4 | 31723 | 140 | 2 | 1.4% | 137 | 0 | 1 |

**Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 1: 1, 6-10: 1; median 4.

**First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `random` 2.

## Documented flaky tests (MEASURED)

Documented = tests in the files changed by the flaky-test fix of the Hashemi et al. dataset, or matching the file/test named by the GitHub issue (issue titles often name no test: then nothing matches).

| documented flaky tests found in the measured projects | flaky in our baseline | reproduced |
|---:|---:|---:|
| 0 | 0 | 0 |

## Causes of baseline-flaky tests not reproduced under `--det` (MEASURED, keyword heuristics)

Classes: `concurrency/event-order` (async ordering, timers racing real I/O, timeouts), `external` (network, processes, files, environment), `l0-gap` (a source Level 0 controls still differs, or shared state Level 0 should reset), `unknown`. Evidence per test in `<repo>.causes.json`.

| pool | concurrency/event-order | external | l0-gap | unknown |
|---|---:|---:|---:|---:|
| flaky | 117 | 0 | 2 | 19 |
| popular | 0 | 0 | 0 | 0 |
| total | 117 | 0 | 2 | 19 |

* `concurrency/event-order`: matrix-js-sdk-flaky `de in toDevice messages to an unverified device when globalBlacklistUnverifiedDevices=true` (test source uses async , await , promise.all); matrix-js-sdk-flaky `x-client-methods.spec.ts::MatrixClient::addThreePidOnly::should make expected POST request` (test source uses async , await , promise.all; also http://); matrix-js-sdk-flaky `s.spec.ts::MatrixClient::agreeToTerms::should send `user_accepts` via body of POST request` (test source uses async , await ; also http., https://)
* `l0-gap`: matrix-js-sdk-flaky `ReadUpTo()::invalid receipts::accepts unthreaded receipts pointing at an event in a thread` (shared state not reset by Level 0: mockreturnvalue); matrix-js-sdk-flaky `s::Room::getEventReadUpTo()::invalid receipts::ignores receipts pointing at missing events` (shared state not reset by Level 0: mockreturnvalue)
* `unknown`: matrix-js-sdk-flaky `spec/integ/matrix-client-methods.spec.ts::<file>` (no marker in the source, exception or fingerprint (source not found)); matrix-js-sdk-flaky `atrix-client-methods.spec.ts::MatrixClient::deleteDevice::should pass through an auth dict` (no marker in the source, exception or fingerprint); matrix-js-sdk-flaky `ds.spec.ts::MatrixClient::getRoomSummary::should allow fallback to the deprecated endpoint` (no marker in the source, exception or fingerprint)

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). **4 tests** (MEASURED), of which 3 fail in every `--det` run.

Cause: `fixed-order` = the test also fails under `--det` with every Level 0 control disabled (only the fixed order and serial execution remain): an order/isolation dependency hidden by the random parallel baseline, not a Level 0 control; otherwise the controls whose `--det-disable` makes it pass; `unexplained` = none does.

| cause &#124; exception | tests | examples |
|---|---:|---|
| `fixed-order (fails without --det too) &#124; unknown` | 2 | babel-flaky: packages/babel-core/test/errors-stacks.js::@babel/core errors::error inside config file: @babel/core errors > error inside config file (first diverging source: -)<br>babel-flaky: packages/babel-core/test/errors-stacks.js::@babel/core errors::error inside config file with more frames: @babel/core errors > error inside config file with more frames (first diverging s |
| `seeds+time+timers+net &#124; AssertionError` | 1 | vercel-flaky: packages/cli-exec/tests/index.test.ts::passes timeout through to execa: AssertionError: expected VercelCliError: Vercel CLI command "/tmp/… { …(5) } to deeply equal ObjectContaining{…} ( |
| `time+timers &#124; TypeError` | 1 | vercel-flaky: packages/cli/test/unit/util/events.test.ts::printEvents()::does not signal alias assignment when the stream errors: TypeError: Invalid state: ReadableStream is locked (first diverging so |

## Timing

Quiet timing pass: not run (UNKNOWN).

* Round timings, serial `--det` vs the random parallel baseline: median 62.9% — **NOT COMPARABLE** (different parallelism and order).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 1; unstable in the baseline and stable under `--det`: 140
* stable in both modes but with a different majority outcome: 2573
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 2625 (98.5%); not covered: 41 (`fs` 32, `entropy` 8, `time` 1)

## Per repository (MEASURED)

| repo | pool | pinned at | node | runner | random baseline | tests | unstable | reproduced | seeds explored | broken by det | not covered | documented present / flaky / reproduced |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [matrix-js-sdk-flaky](https://github.com/matrix-org/matrix-js-sdk) | flaky | [dc1cccfecc](https://github.com/matrix-org/matrix-js-sdk/commit/dc1cccfeccb0a34dce3f2d7249aef44dbbb92cbe) ([doc](https://github.com/matrix-org/matrix-js-sdk/issues/4331)) | node v20.20.2 | jest 29.7.0 | yes | 2707 | 137 | 0 | 20 | 0 | 0 | 0 / 0 / 0 |
| [babel-flaky](https://github.com/babel/babel) | flaky | [ddf20013bd](https://github.com/babel/babel/commit/ddf20013bdfd960308090865777bf4cf3c8d1f8d) ([doc](https://github.com/babel/babel/issues/16083)) | node v20.20.2 | jest 29.6.2 | yes | 25554 | 0 | 0 | 0 | 2 | 0 | 0 / 0 / 0 |
| [react-testing-library-flaky](https://github.com/testing-library/react-testing-library) | flaky | [1c931a6c03](https://github.com/testing-library/react-testing-library/commit/1c931a6c03091d725eccee7767d9ec696d5d33c6) ([doc](https://github.com/testing-library/react-testing-library/issues/1419)) | node v18.20.8 | jest 29.7.0 | yes | 250 | 2 | 2 | 7 | 0 | 0 | 0 / 0 / 0 |
| [vercel-flaky](https://github.com/vercel/vercel) | flaky | [17d9ebaf8e](https://github.com/vercel/vercel/commit/17d9ebaf8e9b335d550dea1a243743a74edc772e) ([doc](https://github.com/vercel/vercel/issues/17501)) | node v22.23.5 | vitest 2.0.3 | yes | 3212 | 1 | 0 | 4 (budget) | 2 | 41 | 0 / 0 / 0 |

## Playwright end-to-end suites (measured, not built on)

No Playwright project measured (UNKNOWN).

## Notes

* Flaky pool: the dataset of Hashemi, Tahir, Rasheed, 'An Empirical Study of Flaky Tests in JavaScript' (ICSME 2022, Zenodo 10.5281/zenodo.6673741) is the public dataset of JavaScript flaky tests used first: each project is pinned at the parent of a commit that fixes a flaky test. It covers only 18 projects, most of which do not run their suites with Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites), so it cannot supply 25 projects; the pool is completed with popular projects that have GitHub issues documenting flaky Jest/Vitest tests, each pinned at the last commit before the issue was opened.
* The JS-TOD (order-dependent Jest tests) and environmental-flakiness replication packages were not fetched.
* Only GitHub-hosted runners were used; numbers labelled NOISY come from shared virtual machines.
