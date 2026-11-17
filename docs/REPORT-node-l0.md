# Node L0 (detjs) — final report

Session node-l0, 2026-11-16/17. Repository fenvix-engine-cli, branch `claude/node-l0`. Labels: MEASURED (this work), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host (GitHub-hosted runners).

## Summary

* **Main metric (MEASURED):** baseline-unstable tests made reproducible by `--det` / `--det-seed`: **129/421 = 30.6%** over 41 projects (16 with documented flaky tests, 25 popular at HEAD; jest 8, vitest 33). Documented-flaky pool: 51/192 = 26.6%; popular pool: 78/229 = 34.1%.
* **Fingerprint coverage (MEASURED):** 79661 tests had an identical fingerprint in every fixed-order `--det` run, 988 did not (98.8% covered): `time` 807, `fs` 91, `entropy` 87, `random` 2, `beyond-trace` 1.
* **Tests broken by `--det` (MEASURED):** 48 after the L0 fixes of this session, 41 of them failing in every `--det` run.
* **Slowdown of `--det` (MEASURED, NOISY):** median 3.1% over 9 projects (serial runner without `--det` vs `--det`, quiet timing pass).
* **Playwright (MEASURED, measured only):** 3 projects; see the Playwright section.
* **Shortfalls (MEASURED):** documented-flaky pool 16/25 projects, Playwright 3/5 (see Projects and Playwright). Not in the numbers: babel and prettier (custom Jest runner, Level 0 not applied, J16) and matrix-js-sdk (`--det` runs crash in band, UNKNOWN cause).
* Shell tests: per-control tests for Vitest and Jest, 20/20 pass locally and on CI (MEASURED).

## What was built (steps 1–3)

Details in `docs/NODE.md` and `docs/REPORT-node-l0-INTERMEDIATE-1.md`.

* `crates/detpy-node`: napi-rs bindings of `detpy-core` (Recorder with batched events, Cassette, verifier, seeds, hierarchical shuffle, trace merge). Same trace and cassette format as Python; the harness verifies Node traces with the Python binding of the same Rust verifier, and CI checks `python -m detpy verify` on a Node trace.
* Core: shared event vocabulary cherry-picked from the L1 study branch (2ec240f, encoding 2, with its prerequisite `Source::Sched`); additive `order::shuffle_indices` and `trace::merge_traces`.
* `node/` (`detjs vitest|jest --det`): order (files sorted / seeded shuffle files → describe → tests), seeds (`Math.random`, `crypto.getRandomValues`, `crypto.randomUUID`), virtual clock (`Date`, `performance.now`, `process.hrtime`) with the adaptive tick, virtual timers (inside tests only; released to the realm's own timers when a test ends), sorted `readdir`/`opendir`, closed network with record/replay (net, tls, dns → http, https, fetch), serial execution with the isolation recorded. Ops, sites (source-mapped original `.ts` lines) and header meta follow the shared vocabulary.
* Tests: one fixture per control and runner that fails in a realistic run without `--det` and passes with it; a deterministic suite whose outcomes `--det` does not change; regression tests for each defect found by the harness (Vitest projects, jsdom accessors, leaked timers, runner environment variables, `setImmediate` chains before fast timers, clock reads that must not inflate time, per-file `performance.now()` origin), each failing before its fix and passing after.

## Projects (step 4)

**Flaky pool.** The public dataset of JavaScript flaky tests of Hashemi, Tahir, Rasheed (ICSME 2022, Zenodo 10.5281/zenodo.6673741; fetched by an Actions job into `harness/node/dataset/raw/`) was used first, each project pinned at the parent of a commit that fixes a flaky test. It has 18 projects and almost none runs on Jest ≥ 27 or Vitest at those commits (Node core, Atom, Electron, Meteor, QUnit, Karma, Jest 22–25), so it supplies 0 measurable project(s). The pool was completed with projects whose GitHub issues document a flaky Jest/Vitest test (curated list of popular repositories, then a GitHub-wide issue search restricted to JS/TS repositories with ≥ 1000 stars), each pinned at the last commit before the issue was opened.
**Selection (MEASURED).** 44 projects passed the filters and were measured (clone, install, runner found — also in a workspace package —, ≥ 50 test outcomes, < 50% failing, first run < 180 s): 16 documented-flaky, 25 popular, 3 Playwright. Discarded: no-runner 27, baseline-broken 27, too-slow 19, install-failed 15, unsupported 14, too-few-tests 5, duplicate 2, browser-install-failed 2, det-no-trace 1. Every discarded candidate is listed with its reason in `harness/node/results/node-final/REPORT.md`. Candidates discarded at first and re-checked in the final round after harness fixes were not held to the 180 s limit (excalidraw-flaky, first run 210 s).

**Shortfall:** the documented-flaky pool has 16 measurable projects, not 25 (MEASURED). The other candidates (all listed) need a build, a browser, services or an old toolchain (Jest < 27 without jest-circus, Vitest < 1.4), or their suites fail on a clean runner.

## Main results (MEASURED, 10 baseline + 10 `--det` runs per project, seeds 1..20, 10/10 confirmation)

| pool | projects | tests | unstable in baseline | reproduced | % | never fail under --det | fail sometimes | always fail |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| documented flaky | 16 | 43250 | 192 | 51 | 26.6% | 99 | 41 | 1 |
| popular | 25 | 41986 | 229 | 78 | 34.1% | 63 | 52 | 36 |
| total | 41 | 85236 | 421 | 129 | 30.6% | 162 | 93 | 37 |

Seeds explored before the reproducing seed (MEASURED): 1: 70, 11-20: 11, 2-5: 21, 6-10: 27; median 1.

First diverging event between a passing and a failing `--det` run (MEASURED): `outcome-only` 98, `time` 13, `random` 12, `fs` 5.

Documented flaky tests found in the measured suites: 31; flaky in our baseline: 0; reproduced: 0 (MEASURED; issue titles often name no test).

## Tests broken by `--det` and the L0 fixes (MEASURED)

Rounds stopped early on earlier versions of the shell are kept in `harness/node/results/node-before-fixes*`. Defects of Level 0 / the shell found by the harness and fixed in this session (each with a regression test):

| defect (project where found) | effect before the fix |
|---|---|
| Vitest projects/workspaces ignored the CLI runner (date-fns) | the `--det` controls did not apply in project configs |
| Node 18: read-only `Performance.prototype` methods (luxon) | every Jest suite failed to start (58 suites) |
| jsdom: `crypto` is an accessor (mobx) | 69 Jest suites failed to start |
| leaked virtual timer fired at once (dom-testing-library) | crash of the Jest process |
| in-process runners lacked `NODE_ENV=test` / `VITEST` (user-event, jotai) | every user-event suite failed (Babel config) |
| runner outside the project root refused by Vite `server.fs` (jotai) | 0 of 44 files ran under `--det` |
| in-band Jest never exits on suites with open handles (react-testing-library) | `--det` run timed out |
| fast virtual timers fired while React `act()` / scheduler `setImmediate` chains were pending (apollo-client) | 34 tests broken by `--det` in a local run (MEASURED locally), 3 after the fix (limit J15) |
| Jest compiled the detjs `testRunner` with the project's transform (matrix-js-sdk, immutable-js) | every suite failed under `--det` (`@babel/runtime` not found; buble syntax error) |
| awaited in-process `jest-cli` run added an `at async main` frame to async stacks (babel) | stack-trace inline snapshots failed under `--det` |
| adaptive tick doubled after 8 clock reads; React's scheduler reads the clock hundreds of times per render (recharts) | virtual `performance.now()` ran 194 s ahead within a test; code comparing it with Vitest's fake `requestAnimationFrame` timestamps looped: 1113 tests broken by `--det` |
| `performance.now()` counted from the process start (recharts) | values grew over a full run: 40 tests broken in a full run, none with the file alone; now counted from the start of each test file. recharts is the only project re-measured with this fix (commit e747edd); the others were measured on a6d2fbd |
| custom Jest `runner` (jest-light-runner) bypasses detjs (babel, prettier) | Level 0 not applied: 0 of ~25 000 tests traced; now reported (J16), not fixed |

Harness defects fixed on the way (they affected the measurement, not detjs): the project's test-script flags (`--config`, Node flags, variables) were ignored (apollo-client: every suite failed), leftover web servers survived a run (process groups now killed), runs that hang after writing their report were discarded (react-testing-library), the test-script flags were applied even when a plain run was better (vercel: 3212 → 30 tests).

Per project, the latest measurement before the last fixes (round on d3075a1 and its re-runs, or the earlier stopped rounds) against the final round:

| project | broken by --det before | after |
|---|---:|---:|
| apollo-client-flaky | 6 | 6 |
| assistant-ui-flaky | 8 | 8 |
| cheerio | 0 | 0 |
| date-fns | 0 | 0 |
| dom-testing-library | 0 | 0 |
| excalidraw-flaky | 52 | 14 |
| growi-flaky | 0 | 0 |
| h3 | 0 | 0 |
| happy-dom-flaky | 2 | 2 |
| immer | 0 | 0 |
| immutable-js | 0 | 0 |
| jotai | 0 | 0 |
| luxon | 0 | 0 |
| mermaid-flaky | 0 | 0 |
| mobx | 0 | 0 |
| msw-flaky | 0 | 0 |
| nuxt-flaky | 0 | 0 |
| pinia | 0 | 0 |
| preact-signals | 0 | 0 |
| quasar-flaky | 0 | 0 |
| query-flaky | 0 | 0 |
| react-admin-flaky | 24 | 5 |
| react-redux | 1 | 1 |
| react-testing-library-flaky | 0 | 0 |
| recharts | 40 | 0 |
| redux | 0 | 0 |
| svelte-flaky | 0 | 0 |
| tanstack-form | 0 | 0 |
| tanstack-table | 4 | 4 |
| tiptap-flaky | 0 | 0 |
| ufo | 0 | 0 |
| unstorage | 5 | 5 |
| user-event | 2 | 2 |
| valibot | 0 | 0 |
| vercel-flaky | 2 | 1 |
| vue-core | 0 | 0 |
| vueuse | 0 | 0 |
| xstate | 0 | 0 |
| yaml | 0 | 0 |
| yup | 0 | 0 |
| zod-flaky | 0 | 0 |

Remaining causes (`fixed-order` = also fails under `--det` with every Level 0 control off, i.e. an order or isolation dependency hidden by the random parallel baseline; otherwise the controls whose `--det-disable` makes the test pass):

| cause &#124; exception | tests |
|---|---:|
| `time &#124; Error` | 15 |
| `time &#124; AssertionError` | 6 |
| `time+timers &#124; Error` | 5 |
| `net &#124; Error` | 5 |
| `time+timers &#124; AssertionError` | 4 |
| `fixed-order (fails without --det too) &#124; unknown` | 4 |
| `seeds+time+timers+fs+net &#124; AssertionError` | 3 |
| `unexplained &#124; Error` | 2 |
| `time+timers &#124; TypeError` | 2 |
| `time &#124; ApolloError` | 1 |
| `unexplained &#124; AssertionError` | 1 |

**Level 0 not applied (J16).** babel-flaky (25554 tests, 0 traced), prettier-flaky (25624 tests, 0 traced) run their tests with the custom Jest runner `jest-light-runner`, which bypasses jest-circus's `testRunner` hook: detjs cannot install its controls there, so these projects are excluded from the numbers above (MEASURED on the round before the last fixes; replacing the runner by `jest-runner` made every suite fail, under `--det` and the serial reference alike).

## Causes of baseline-flaky tests not reproduced (MEASURED, keyword heuristics)

| concurrency / event order | external | L0 gap | unknown |
|---:|---:|---:|---:|
| 30 | 38 | 52 | 172 |

Evidence per test in `harness/node/results/node-final/<repo>.causes.json`.

## Timing

Quiet timing pass (MEASURED, NOISY): 9 projects, 3 serial runs without `--det` vs 3 `--det` runs, interleaved on one GitHub-hosted runner each; median slowdown 3.1% (min -13.8%, max 76.1%). Per project in the harness report. The main cost is the call-site resolution on clock-heavy code (J5 in `docs/NODE.md`).

## Playwright end-to-end suites (measured, not built on)

3 projects (MEASURED), Chromium, `--retries=0`; baseline = the project's own parallelism; `--det` = one worker plus the Level 0 controls inside the Playwright worker processes (no per-test brackets, no traces; browser and web servers not controlled).

| project | tests | unstable in baseline | unstable under --det | became stable | broken by --det |
|---|---:|---:|---:|---:|---:|
| pw-msw | 52 | 1 | 0 | 1 | 0 |
| pw-solid-start | 47 | 0 | 0 | 0 | 0 |
| pw-starlight | 26 | 0 | 0 | 0 | 0 |

Browser tests unstable in the baseline: 1 of 125; of all baseline-unstable tests of the round, 0.2% are browser tests (MEASURED, small sample, not weighted). Under `--det`: never fail 1, fail sometimes 0, always fail 0. What Level 0 covers today in browser tests is only the test process (Node side): the browser's clock, randomness, network and scheduling, where most end-to-end flakiness lives, are outside it.

**Shortfall:** 3 Playwright projects measured, not 5: the other candidates need builds or services that fail on a clean runner, a web-server port already in use before the first run (pw-zag, pw-tldraw; UNKNOWN which process holds it), or Playwright versions that cannot install Chromium on the runner's Ubuntu 26.04 (listed in the harness report).

## Limits found

The full list with the project where each was found is in `docs/NODE.md` (J1–J17). The ones that matter most for the numbers: J4 (fast virtual timers versus real I/O once I/O is pending), J5 (cost of call sites), J15 (CPU time is not virtual time: loops bounded by a virtual deadline can exceed the runner's real timeout), J16 (custom Jest runners bypass detjs), J17 (extra stack frames of patched calls: deep recursion can overflow under `--det` only), J2 (vm pools / browser mode not covered), J3 (Jest `setupFiles` run before the controls), J11 (Playwright measured only).

Not fixed: on matrix-js-sdk every `--det` run of the full suite dies in band (an error thrown by fetch-mock, `route already exists`, in a `beforeEach` of `crypto.spec.ts`; in Jest's worker mode such a crash costs one worker, in band the whole run), so the project has no `--det` trace and is out of the numbers (UNKNOWN root cause). In a subset run of the same project, tests that switch to Jest's modern fake timers inside a test hang under `--det` with the virtual clock on (they pass with `--det-disable=time`; UNKNOWN cause).

## Cockpit readiness

What the Node outputs already give per test, as the Python ones: the outcome per run, the fingerprint (trace `test` line), the first diverging event with its reason (Rust verifier, same JSON report for both runtimes), and the replay command (`detjs vitest|jest --det [--det-seed=N]` plus the cassette). What would make a stable machine-readable verdict harder:

* **Test identity.** Node test ids are `file::describe::…::name`; names are not unique in JS (duplicates get ` #2`), names can be built at run time (`test.each`, template strings) and contain any character, and a Vitest file run by two projects yields two identical ids (J9). A cockpit needs a stable id that includes the project and survives renames; Python node ids are much more stable.
* **Verdict sources are split.** Outcomes come from the runners' JSON reporters, fingerprints from the trace; they are joined by id (the harness does it). A single per-test record emitted by the shell (outcome + fingerprint + replay command) would remove that join; the Python plugin has `--det-outcomes` for this, the Node shell does not yet.
* **Replay command.** For a Jest/Vitest test it must name the runner, the project config, the seed and the test filter (`-t` / `--testNamePattern` with escaping of the name); the cassette path; and, for a pinned flaky project, the commit and the Node version. Today these are spread over the trace header and the harness CSV.
* **Coverage caveats per test.** A verdict must carry why a pass is not trustworthy: worker threads / child processes (J1), vm pools (J2), timers released to real time after the test (J4), Playwright (no fingerprint). The trace header has the run-level notes (`meta.notes`); per-test flags are not emitted yet.
* **Encoding.** Traces carry the event encoding (now 2); the verifier refuses mixed encodings, so cockpit history must be keyed by encoding version.

## Delivery notes

* fenvix-brain-cli could not be attached (refused twice by the session's permission system); reports are in `docs/` of this branch per the coordinator's fallback.
* A second Actions job to fetch the JS-TOD and environmental-flakiness replication packages from Zenodo was refused by the session's permission system and not retried.
* Harness report with every number per project and every discarded candidate: `harness/node/results/node-final/REPORT.md` (run https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44050766953).
