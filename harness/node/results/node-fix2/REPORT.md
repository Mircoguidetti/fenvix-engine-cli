# detjs Level 0 (Node / TypeScript): measurement report (`node-fix2`)

Generated 2026-11-18 04:04 UTC with detjs 0.1.0 on GitHub Actions (ubuntu-latest) ([run](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44160127701)). Per repository: 10 baseline runs interleaved with 10 `--det` runs. Baseline = the realistic configuration: random order with a different seed per run where the runner supports it (Vitest `--sequence.shuffle --sequence.seed=N`; Jest `--randomize --seed=N`, Jest >= 29.2 only) and two parallel workers (`--maxWorkers=2`). `--det` = fixed order (files sorted by path, tests in declaration order), one worker, files in sequence, all Level 0 controls. Then, for every test unstable in the baseline, `--det --det-seed=1..20` with 10/10 confirmation of the seed that makes it fail. Labels: MEASURED (by this harness), DECLARED (with source), UNKNOWN; NOISY = shared host.

Verifier: Rust verifier through the Python binding (detpy 0.1.0).

## Main metric

**Baseline-unstable tests made reproducible: 110/159 = 69.2%** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| documented flaky | 3 | 10782 | 70 | 47 | 67.1% | 5 | 0 | 18 |
| popular (HEAD) | 3 | 16257 | 89 | 63 | 70.8% | 24 | 0 | 2 |
| total | 6 | 27039 | 159 | 110 | 69.2% | 29 | 0 | 20 |

**Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 0 (fixed order): 1, 1: 76, 2-5: 32, 6-10: 1; median 1.

**First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `random` 60, `time` 41, `outcome-only` 8, `fs` 1.

## Documented flaky tests (MEASURED)

Documented = tests in the files changed by the flaky-test fix of the Hashemi et al. dataset, or matching the file/test named by the GitHub issue (issue titles often name no test: then nothing matches).

| documented flaky tests found in the measured projects | flaky in our baseline | reproduced |
|---:|---:|---:|
| 1 | 0 | 0 |

## Causes of baseline-flaky tests not reproduced under `--det` (MEASURED, keyword heuristics)

Classes: `concurrency/event-order` (async ordering, timers racing real I/O, timeouts), `external` (network, processes, files, environment), `l0-gap` (a source Level 0 controls still differs, or shared state Level 0 should reset), `unknown`. Evidence per test in `<repo>.causes.json`.

| pool | concurrency/event-order | external | l0-gap | unknown |
|---|---:|---:|---:|---:|
| flaky | 2 | 0 | 20 | 1 |
| popular | 2 | 0 | 2 | 22 |
| total | 4 | 0 | 22 | 23 |

* `concurrency/event-order`: excalidraw-flaky `ory::singleplayer undo/redo::should create new history entry on scene import via drag&drop` (test source uses async , await , waitfor); excalidraw-flaky `tory::singleplayer undo/redo::should end up with no history entry after initializing scene` (test source uses async , await , waitfor); xstate `examples/effect-workflows/test/inspection.test.ts::runs offline by default` (test source uses async , await , waitfor)
* `l0-gap`: excalidraw-flaky `t.tsx::history::singleplayer undo/redo::should disable undo/redo buttons when stacks empty` (diverging event `time`: a controlled source still differs between runs); excalidraw-flaky ` are selected when user clicks on B, on pointer up only elements from B should be selected` (diverging event `time`: a controlled source still differs between runs); excalidraw-flaky `excalidraw/tests/regressionTests.test.tsx::regression tests::adjusts z order when grouping` (diverging event `time`: a controlled source still differs between runs)
* `unknown`: excalidraw-flaky `ages/excalidraw/tests/regressionTests.test.tsx::regression tests::key a selects arrow tool` (no marker in the source, exception or fingerprint (source not found)); recharts ` when the child is a function::should rerender with the final state when isActive is false` (no marker in the source, exception or fingerprint); recharts `sx::selectCartesianGraphicalItemsData::should return empty array in a chart with root data` (no marker in the source, exception or fingerprint)

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). **15 tests** (MEASURED), of which 12 fail in every `--det` run.

Cause: `fixed-order` = the test also fails under `--det` with every Level 0 control disabled (only the fixed order and serial execution remain): an order/isolation dependency hidden by the random parallel baseline, not a Level 0 control; otherwise the controls whose `--det-disable` makes it pass; `unexplained` = none does.

| cause &#124; exception | tests | examples |
|---|---:|---|
| `time &#124; Error` | 11 | excalidraw-flaky: packages/excalidraw/tests/history.test.tsx::history::multiplayer undo/redo::conflicts in bound text elements and their containers::should preserve latest remotely added binding and u<br>excalidraw-flaky: packages/excalidraw/tests/history.test.tsx::history::multiplayer undo/redo::conflicts in bound text elements and their containers::should preserve latest remotely added binding and u |
| `seeds+time+timers+fs+net &#124; AssertionError` | 3 | excalidraw-flaky: packages/excalidraw/tests/search.test.tsx::search::should match frame names: AssertionError: expected undefined to be 3 // Object.is equality (first diverging source: time)<br>excalidraw-flaky: packages/excalidraw/tests/search.test.tsx::search::should match text and cycle through matches on Enter: AssertionError: expected undefined to be 2 // Object.is equality (first diver |
| `time+timers &#124; TypeError` | 1 | vercel-flaky: packages/cli/test/unit/util/events.test.ts::printEvents()::does not signal alias assignment when the stream errors: TypeError: Invalid state: ReadableStream is locked (first diverging so |

## Timing

Quiet timing pass: not run (UNKNOWN).

* Round timings, serial `--det` vs the random parallel baseline: median 65.7% — **NOT COMPARABLE** (different parallelism and order).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 3; unstable in the baseline and stable under `--det`: 159
* stable in both modes but with a different majority outcome: 25
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 24642 (97.6%); not covered: 599 (`time` 486, `entropy` 79, `fs` 33, `beyond-trace` 1)

## Per repository (MEASURED)

| repo | pool | pinned at | node | runner | random baseline | tests | unstable | reproduced | seeds explored | broken by det | not covered | documented present / flaky / reproduced |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [excalidraw-flaky](https://github.com/excalidraw/excalidraw) | flaky | [5cf547650b](https://github.com/excalidraw/excalidraw/commit/5cf547650b700b35507e83773695098150b810d2) ([doc](https://github.com/excalidraw/excalidraw/issues/11713)) | node v18.20.8 | vitest 3.0.6 | yes | 1611 | 67 | 44 | 4 (budget) | 14 | 548 | 0 / 0 / 0 |
| [growi-flaky](https://github.com/growilabs/growi) | flaky | [3fc185a4e6](https://github.com/growilabs/growi/commit/3fc185a4e696d614d08f3e9cfd4040226f9d772f) ([doc](https://github.com/growilabs/growi/issues/12252)) | node v22.23.5 | vitest 3.2.6 | yes | 5959 | 2 | 2 | 10 | 0 | 11 | 1 / 0 / 0 |
| [vercel-flaky](https://github.com/vercel/vercel) | flaky | [17d9ebaf8e](https://github.com/vercel/vercel/commit/17d9ebaf8e9b335d550dea1a243743a74edc772e) ([doc](https://github.com/vercel/vercel/issues/17501)) | node v22.23.5 | vitest 2.0.3 | yes | 3212 | 1 | 1 | 4 | 1 | 35 | 0 / 0 / 0 |
| [xstate](https://github.com/statelyai/xstate) | popular | [8e53990c2f](https://github.com/statelyai/xstate/commit/8e53990c2f9318d2d649b8af1a3c96af970d9bf2) | node v22.23.5 | vitest 3.2.7 | yes | 5043 | 7 | 3 | 8 (budget) | 0 | 5 |  |
| [recharts](https://github.com/recharts/recharts) | popular | [548327520b](https://github.com/recharts/recharts/commit/548327520b0d643178287eaf03d40a35e0ebf37b) | node v22.23.5 | vitest 4.1.11 | yes | 9398 | 82 | 60 | 13 (budget) | 0 | 0 |  |
| [tanstack-table](https://github.com/TanStack/table) | popular | [564a459b74](https://github.com/TanStack/table/commit/564a459b74834c77631e0d6fdba7661383bbc1b4) | node v22.23.5 | vitest 5.1.0 | yes | 1816 | 0 | 0 | 0 | 0 | 0 |  |

## Playwright end-to-end suites (measured, not built on)

No Playwright project measured (UNKNOWN).

## Notes

* Flaky pool: the dataset of Hashemi, Tahir, Rasheed, 'An Empirical Study of Flaky Tests in JavaScript' (ICSME 2022, Zenodo 10.5281/zenodo.6673741) is the public dataset of JavaScript flaky tests used first: each project is pinned at the parent of a commit that fixes a flaky test. It covers only 18 projects, most of which do not run their suites with Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites), so it cannot supply 25 projects; the pool is completed with popular projects that have GitHub issues documenting flaky Jest/Vitest tests, each pinned at the last commit before the issue was opened.
* The JS-TOD (order-dependent Jest tests) and environmental-flakiness replication packages were not fetched.
* Only GitHub-hosted runners were used; numbers labelled NOISY come from shared virtual machines.
