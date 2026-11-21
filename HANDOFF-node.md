# HANDOFF: P-041 Node (rows JS-02, JS-07, JS-09, F-06, F-02 Node)

Written 2026-11-20 by the P-041 session, stopped because the account is close to its weekly limit. Branch
`claude/node` (this commit) holds everything: no work is left only in a worktree (all six helper branches merged:
node-A time/scheduling, node-B network/randomness, node-C Vitest/Jest shells, node-D cache/verifier/process models,
node-par JS-07 parallel, node-repro F-02 Node). No PR into `claude/release-1` has been opened yet; the report
`sessions/2026-11-20-node/REPORT.md` is not written yet. Status of the rows: **PARTIAL** (open items below).

Numbers: MEASURED (local command, this container: 4 vCPU shared with up to six parallel sessions, Node 22.23.5 unless
said), DECLARED (a helper's report, not re-run by the coordinator), UNKNOWN.

## 1. Merged (green where said)

| package | what | evidence |
|---|---|---|
| coordinator (P-041 wrong results) | clock family (runner fake timers on the virtual clock G-0122/G-0142, uptime, timeOrigin, marks, AbortSignal.timeout, perf_hooks, Intl format of now; virtual day G-0120; `--det-cache-real-clock` G-0121; cache off when a control is disabled G-0123); worker threads under Level 0, child processes / workers recorded as uncontrolled, vm contexts controlled, native addons never reused (JS-09); async crypto; network (UDP closed, keep-alive per test, replay mismatch fails, credentials redacted, nock/msw interceptors); env reads recorded; TZ/locale pinned; concurrent I/O order recorded; machine facts, keygen, mkdtemp, timers/promises, Atomics.wait, DNS resolvers; `--det-cache-max-age`; `detjs verify` usage; G-0181 | `node/test/node-p041.test.js`: 49/49 (MEASURED, `cd node && node --test test/node-p041.test.js`, before the last merges) |
| node-A | G-0143 G-1410 G-0144 G-0463 G-0464 G-1478 G-1435 G-1484 G-1412 G-1411 G-1434 G-1468 G-2167 G-2168 | `node/test/time-p041.test.js` 27 pass 1 skip (DECLARED); every test failed on the old code 8e972f0 (DECLARED) |
| node-B | G-1415..G-1421 G-1426..G-1429 G-2165 | `node/test/network-p041.test.js` 21/21 on Node 22 and 24 (DECLARED) |
| node-C | G-0453 G-0402 G-1588 G-0461 (not reproducible on Vitest 3) G-1437 G-1476 G-1477 G-1475 G-1467 G-1312 G-1436 G-1466 G-1290 (serial runs) G-2180 G-2183 (refused) G-2162 G-2164 | `node/test/runners-p041.test.js` 23/23 Vitest 3/4/5 + Jest (DECLARED) |
| node-D | G-1397 G-1394 G-1399 G-1401 (Vitest; kept refusal for Jest) G-1402 G-2161 G-2225 G-1481 G-1482 G-1483 G-0145..G-0149; kept refusals proven sound: G-1582..G-1586 G-2220..G-2224 | `node/test/cache-p041.test.js` 36/36 and runner suites (DECLARED) |
| node-par | parallel lanes with a fixed plan for Vitest threads/forks and Jest workers / workerThreads, with the cache: G-1304 G-1395 G-1396 G-1448 G-1450 G-1455 G-1457 G-1458 (G-1044: its Node part; the Go part is out of scope) | `node/test/parallel-p041.test.js` 22/22 (DECLARED, before its last WIP); measurements in `harness/node_parallel/results/` |
| node-repro | `detjs` options `--det-order`, `--det-outcomes`, `--det-collect`, `--det-order-seed`; `python/detpy/fenvix_js.py` (Vitest, Jest, Playwright adapters for repro/explore/replay over `detpy.repro`); `detjs playwright` shell | `node/test/repro-p041.test.js`, `tests/test_fenvix_js.py`; measurement `harness/node_repro/results/REPORT.md` |
| Rust | `cargo test -p detpy-core`: 137/137 (MEASURED, at facf42b9) | |

## 2. Still open

| item | cause found so far | files touched | next step |
|---|---|---|---|
| JS-07 G-1449 / G-1456 (Vitest `test.concurrent` / `describe.concurrent` / `sequence.concurrent`, Jest `test.concurrent` serialised under --det) | needs a per-test Level 0 context while tests interleave. node-par built it in its last commits (a3e4e321 `src/concur.js`: test id, event buffer, clock, generators and control state carried by AsyncLocalStorage, timers fire in their test's context, concurrency in the cache key; c017a888 Jest 29 starts concurrent tests before `test_start`) and was stopped before testing it fully; last commit 2a5f411f is WIP | `node/src/concur.js`, `state.js`, `clock.js`, `seeds.js`, `jest/runner.js`, `vitest/shell.js`, `test/parallel-p041.test.js` | run `node --test --test-concurrency=1 test/parallel-p041.test.js` and the concurrent cases; check per-test fingerprints are equal serial vs concurrent and across runs; re-measure the 8-concurrent-tests file (MEASURED before: Vitest 5.1 plain 2.1 s vs --det 3.7 s; Jest 30 3.4 s vs 4.6 s) |
| dom-testing-library: 2 of 666 fingerprints differ parallel vs serial, not flagged by the run (MEASURED by node-par: 664/666, outcomes 666/666) | source-map's `Math.random` (quick-sort) is drawn lazily in a different test depending on which files ran earlier in the process | 64fb01fc: draws a library makes for the runner use their own streams (not recorded) | re-measure with `python3 harness/node_parallel/measure.py --name dom-testing-library --dir <clone at 6049cc0bc7> --runner jest`; if any difference remains, make the run report it (carried state) |
| yaml: the cache records nothing, serially too (`record input: lone leading surrogate`) | test names with lone UTF-16 surrogates go into the JSON handed to the Rust policy, which serde rejects | 64fb01fc: "ids and capture strings wired" (one encoding of ids to Rust) — not verified on yaml | rerun on yaml (pin 528ef30d6d, vitest 4.1.11): a second `--det-cache` run must reuse, and a regression test with a lone surrogate in a test name (no two ids may collapse) |
| mobx base (jest 30): nothing cached, "reads a clock Level 0 does not virtualize" | which clock: UNKNOWN (process.uptime, performance.timeOrigin and Intl format of now became virtual after be3e39d; mobx was measured before) | none yet | rerun the measurement; read `.detjs/cache-summary.json` `not_cached_detail`; virtualize the clock or show the refusal sound with a test |
| F-02 Node final report | not received (helper stopped). Measured: fenvix repro on 90 tests of the Node Block 1 flaky set (16 repositories): REPRODUCED 49/90 = 54.4 % of attempted, 49/50 = 98.0 % of those with a stable id (40 ids contain run-dependent values and cannot be collected); cause named 49/90; replay 10/10 with one fingerprint 49/90; median 149.85 s per repro (MEASURED by the helper, `harness/node_repro/results/REPORT.md`); not attempted: 411 − 90 tests | `node/src/repro.js`, `session.js`, `vitest/*`, `jest/*`, `node/src/playwright/*`, `python/detpy/fenvix_js.py`, `harness/node_repro/` | per gap (G-0420 G-0438 G-0447 G-0448 G-0449 G-1174 G-1459 G-1460 G-0406 G-0455) check its test in `repro-p041.test.js` / `tests/test_fenvix_js.py`; give P-039 (claude/verifier-cli) the hook in `fenvix.py` (`from .fenvix_js import register; register(ADAPTERS)`); attempt the rest of the set |
| full-suite failures (section 4) | `r021-fixes`: "stat() mtime read by the test: keyed by its value, a touch reruns" and "fs.promises.cp of a fixture tree, then the copy is read" fail at "run 1 must pass" / "run 2 must reuse": mtime reads are now mapped onto the virtual clock and refused by the cache (node-A G-0143), and the cp case is likely the same Stats path | `node/src/fstime.js`, `cache/capture.js`, `test/r021-fixes.test.js` | decide the contract (mapped mtime of an unchanged file keyed by value vs refused) and align the test or the code; then the full suite on the final code |
| verifier: constant `uncontrolled.*` values | on release-1's verifier a constant `uncontrolled.level0` / `.child` / `.thread` event does not make two runs differ; claude/verifier-cli's verifier treats `uncontrolled.*` as never identical | `node/src/controls.js`, `children.js`, `ioorder.js` | confirm after verifier-cli merges; do not add per-run nonces (they would break replay 10/10 with one fingerprint) |
| PR + CI + report | not started | | `git fetch origin claude/release-1 && git merge origin/claude/release-1`; open the PR `claude/node` → `claude/release-1`; CI release-1.yml (Node 22/24/26) green; write `sessions/2026-11-20-node/REPORT.md` |

Gap-by-gap status for every Node audit gap of the rows: helper reports (node-A/B/C/D) above; the classification table
draft is in section 2 of the future REPORT (not committed).

## 3. Full Node suite: commands

```bash
cd node
npm ci --no-audit --no-fund
node scripts/build.js            # REQUIRED: claude/node changes Rust (planLanes, flags); a stale addon fails policy suites
node --test --test-concurrency=1 test/*.test.js
cargo test -p detpy-core         # from the repository root
python -m pytest tests/test_fenvix_js.py   # needs the wheel: maturin develop --release
```

Optional runtimes: Bun is used when installed; Deno through `DETJS_DENO=<path to deno>`. Node 24: `/opt/node24/bin/node`
in this container. Do not edit `node/src` while a cache suite runs (the cache configuration digest includes it). Takes
about 1.5-2 h on 4 vCPU; background shells here stop after 30 min unless given a longer timeout.

## 4. Last full-suite result

No CI run exists for claude/node yet (no PR). Last local run: `cd node && node --test --test-concurrency=1
test/*.test.js` on bb786c4b (before the node-par and node-repro merges), stopped by the coordinator after 85
top-level groups to merge them: **83 ok, 2 not ok** (MEASURED):

```
not ok 83 - r021 fixes: vitest
    not ok 4 - stat() mtime read by the test: keyed by its value, a touch reruns
    not ok 7 - fs.promises.cp of a fixture tree, then the copy is read
not ok 84 - r021 fixes: jest
    (the same two subtests)
```

The files after `r021-fixes.test.js` in alphabetical order (regressions, review-*, runner-*, runners-p041,
time-p041, unchanged, verifier-inputs if merged) were not reached in that run. Earlier partial runs: all-runners-2,
cache, controls, jsdom, node-p041, policy-equivalence, projects green on earlier heads (MEASURED).
