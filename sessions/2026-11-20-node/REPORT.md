PARTIAL

# P-041 Node: rows JS-02, JS-07, JS-09, F-06, F-02 Node

Session 2026-11-20 (continuation of the stopped P-041 session; `HANDOFF-node.md`). Branch `claude/node`, PR #8 into
`claude/release-1`. Labels: MEASURED (with the command or run id), ESTIMATED, DECLARED (with source), UNKNOWN. Local
numbers come from this container (4 vCPU, Node 22.23.5, 24.22.3, 26.13.1) unless stated otherwise.

<!--STATUS-->

## 1. Rows

### JS-07: parallel `--det` and concurrent tests (G-1449, G-1456, G-1044 Node part, G-1304, G-1395, G-1396, G-1448, G-1450, G-1455, G-1457, G-1458)

What is true:
- Concurrent tests (Vitest `test.concurrent`, `describe.concurrent`, `sequence.concurrent`; Jest `test.concurrent`) run
  interleaved under `--det`. Each test runs in its own Level 0 context (`node/src/concur.js`).
  Per-test fingerprints are equal across runs, with `--det-workers=2`, and with `--maxConcurrency=1` (the same tests
  run one at a time). Written as plain serial tests, every event except the `sched.concurrent` marker is identical.
  Test: `node/test/parallel-p041.test.js` ("tests interleave ..."), 4/4 on Vitest and Jest (MEASURED,
  `node --test --test-concurrency=1 --test-name-pattern="tests interleave" test/parallel-p041.test.js`).
- 8 concurrent tests, each doing a real 0.5 s child process plus a 0.2 s virtual timer (3 runs each; MEASURED, this
  container, `node/test/.tmp/conc8`). Serial execution would need at least 5.6 s, so the tests really interleave:

  | runner | plain | `--det` |
  |---|---|---|
  | Vitest 5.1 | 1.81–1.89 s | 1.69–1.71 s |
  | Jest 30 | 1.88–1.98 s | 2.05–2.07 s |

- Parallel lanes for Vitest and Jest (the helpers' work, re-measured below) and now for node:test.
  `detjs node-test --det-workers=N` or `--test-concurrency=N` runs one driver per lane with a fixed plan; each file
  still runs in its own process. Placement, cross-lane hazards and the cost of serial are reported.
  Tests: `node/test/customer-nodetest.test.js` (2 lanes overlap; fingerprints equal to the serial run; the plan is
  sticky) and `parallel-p041.test.js`.
- dom-testing-library, 666 tests (Jest 29): before the fix, 5/666 fingerprints differed between parallel and serial
  runs and the run did not report it (MEASURED, `harness/node_parallel/measure.py --name dom-testing-library`).
  - Cause: source-map's lazy `Math.random` (quick-sort while Jest's source-map-support hook maps a stack). Two
    defects in `sites.runnerInitiated` made those draws count as the test's:
    1. inside an `Error.prepareStackTrace` hook, V8 gives a nested capture the default text, not call sites;
    2. the recursion filled the 40 frames that were examined.
  - Also, draws made by detjs' own work (`quiet`) used the test's stream.
  - Fixed in `node/src/sites.js` and `node/src/seeds.js`. After the fix: 666/666 equal, serial vs serial and serial
    vs parallel twice (MEASURED, 4 local runs on the clone at 6049cc0bc7).
  - Regression test: `parallel-p041.test.js` "a draw inside the runner's stack-trace hook ...". It fails on the old
    code (2/2) and passes on the new.

What is not true: nothing open in this row.

### JS-02 / JS-09 / F-06 (Level 0 controls, native code / workers / children, cache with proof)

- yaml (pin 528ef30d6d, Vitest 4.1.11), the lone-surrogate bug: the second `--det-cache` run reuses 3424/3424 tests,
  and `--det-cache-verify` finds 0 mismatches over 3422 verified tests (MEASURED).
  Regression test: `parallel-p041.test.js` "test names with unpaired surrogates".
- mobx (Jest 30, `packages/mobx/__tests__/base`), the clock refusal.
  - The clock was `performance.timeOrigin`, read by jsdom when Jest's jsdom environment builds its window. Found by
    instrumenting the engine at be3e39d^, the code that refused it; stack:
    `jsdom/lib/jsdom/browser/Window.js:384 installOwnProperties`.
  - Since be3e39d that clock is virtual. Now 811 tests are recorded; 5 are not cached because their outcome failed
    (3 tests fail without detjs too, with the same names) (MEASURED; serial and `--det-workers=4`).
  - Test: `parallel-p041.test.js` "jsdom environment": the window's `timeOrigin` equals the virtual one and is the same
    in every run; results are recorded and reused, serially and in lanes.
- r021 mtime/cp contract. Chosen contract: a file time the test did not set is read on the virtual clock as its age at
  the test start. That value depends on when the run happens, so the test is never reused, and a touch changes the
  fresh result (refuse rather than key: the age cannot be attributed to a file input). The cp case was the same
  Stats path and was fixed in 1afde1f.
  - Aligned tests: `r021-fixes.test.js`, `runner-node-test.test.js`, `r021b-fixes.test.js` G1 (Stats printing).
  - Found while aligning: on Jest, the runner's console read the Stats fields first, which hid the test's own read
    from the cache, so such a test was reused (a wrong-reuse hazard). Fixed in `fstime.js` and `cache/capture.js`; the
    test now refuses on both runners.
- Verifier and constant `uncontrolled.*` values. claude/verifier-cli's verifier never calls a test with an
  `uncontrolled.*` event identical. The per-run nonce in `uncontrolled.level0` is removed, so such tests keep one
  fingerprint across replays. Test: `verifier-inputs.test.js` "a constant uncontrolled source".
- Review P1 on the trunk (`node/test/review-p1-verifier.test.js`, the reviewer's file, unchanged): 4/4 green.
  - `/dev/urandom` read as a file is now observed like the other OS entropy, or controlled with `--det-urandom`.
  - TZ/locale (coordinator decision, option A): always pinned to UTC / C.UTF-8 under `--det`. A job keeps its own value
    only with `--det-tz` / `--det-locale` (a zone or locale, or `keep`). That is the same contract as Python and is in
    the docs. The keep-path cases were rewritten and pinned-default cases added.
  - `fenvix repro --runner node-test` works.
- After the verifier-cli merge:
  - the Rust cassette redaction kept only `*`, while detjs records a digest tag, so every Node replay mismatched. The
    redaction now keeps a detjs tag (Rust test `redact_keeps_a_detjs_tag_and_masks_everything_else`);
  - G-1483 wording and the timers-vs-I/O verify expectation follow the new verifier (uncontrolled io is never
    identical);
  - tap's whole-environment enumeration is refused: tap's per-process variables are not in the session's keyed
    environment.
- Node 26: a mapped Stats object inspected differently from a plain copy (own `Symbol(partial*Ns)` fields). Fixed in
  `fstime.js`, which was the only failure of PR #8's first CI round on Node 26 (run 44799891005).

### F-02 Node (flaky test → reproducible defect)

- `fenvix repro | explore | replay` for Vitest, Jest, Playwright and now node:test. node:test gained `--det-order`,
  `--det-collect` and `--det-outcomes`, and the listed order wins over the shuffle.
- `fenvix.py` registers the adapters: `from .fenvix_js import register; register(ADAPTERS)`.
- With an installed wheel, detjs is found from the working directory (the project's `node_modules/.bin/detjs`, or an
  engine checkout).
- Ids with run-dependent values (a date or a random number in the name) are reproduced through their stable id
  under `--det` (`fenvix_js.stable_id`); ambiguous matches are refused.
  - Tests: `tests/test_fenvix_js.py` (21 tests), `test_fenvix_cli.py`, `customer-nodetest.test.js` (the order-dependent
    test is reproduced and its setter named).
- Measurement on the whole Node Block 1 flaky set: see section 3.

## 2. Coordinator items of this session

- Reviewer file `review-p1-verifier.test.js`: 4/4 (above).
- Customer-shaped node:test project (`node/test/customer-nodetest.test.js`): 36 TypeScript files run with
  `--experimental-strip-types` (no build), PGlite 0.3.15 in every database test, `fetch` fakes, a shared module.
  Proved:
  - the same per-test fingerprints in two runs, and the four `--test-shard=k/4` runs together give exactly the
    whole run;
  - `--test-concurrency=2` gives 2 overlapping lanes with a fixed plan and the same fingerprints as the serial run;
  - `--det-cache` reuses every file; a change to the shared module reruns exactly its 9 dependents, serially and in
    lanes;
  - each file starts from an empty database (PGlite state does not leak between files);
  - an order-dependent test becomes a defect (REPRODUCED 10/10 with one fingerprint, setter named, replay command).

  4/4 on Node 22, 24 and 26 (MEASURED, local). Not covered: the few tests that use a real Postgres service (no
  database server in the test job), and the customer's own 837-file suite and its 2-vCPU timing (UNKNOWN: not
  available here).

## 3. F-02 Node measurement: every test of the Node Block 1 flaky set

<!--F02-->

## 4. Suites

Local, on the merged tree (`claude/node` 0db339a2 = release-1 f84dde74 + this branch), MEASURED,
`cd node && node --test --test-concurrency=1 test/*.test.js`:

| Node | tests | pass | fail | skipped |
|---|---:|---:|---:|---:|
| 22.23.5 | 857 | 856 | 0 | 1 |
| 24.22.3 | 857 | 856 | 0 | 1 |
| 26.13.1 | 857 | 856 | 0 | 1 |

- The skipped test is the reviewer file R-021's own F3b case on Jest ("process.env in a test file is a copy"), which
  was already skipped before this session.
- Deno suites are skipped as whole files when Deno is not installed (it is outside the Node 22/24/26 scope).
- `cargo test -p detpy-core`: 152/152 (MEASURED).
- `python -m pytest tests/test_fenvix_js.py tests/test_fenvix_cli.py tests/test_packaging.py`: 64 passed, 2 skipped,
  after the packaging fix, 0 failed (MEASURED). The skips are verifier-cli's and packaging's own cases.
- CI of PR #8: <!--CI-->


## 5. Every Node audit gap of these rows

The 138 audit gaps (`claude/gap-audit:sessions/2026-11-20-gap-audit/gaps.jsonl`) named by the helpers' packages, the
handoff and the P-041 tests. "Test" lists the test files that carry the gap id (node/test unless a Python file).

| gap | severity | area | status | test |
|---|---|---|---|---|
| G-0120 | WRONG-RESULT | Node / cache | fixed + test | node-p041 |
| G-0121 | WRONG-RESULT | Node / cache | fixed + test | node-p041 |
| G-0122 | WRONG-RESULT | Node / cache | fixed + test | node-p041 |
| G-0123 | WRONG-RESULT | Node / cache | fixed + test | node-p041 |
| G-0124 | WRONG-RESULT | Node / child_process | fixed + test | node-p041 |
| G-0125 | WRONG-RESULT | Node / child_process | fixed + test | node-p041 |
| G-0126 | WRONG-RESULT | Node / det env | fixed + test | node-p041 |
| G-0127 | WRONG-RESULT | Node / det network | fixed + test | node-p041 |
| G-0128 | WRONG-RESULT | Node / det network | fixed + test | node-p041 |
| G-0129 | WRONG-RESULT | Node / det network | fixed + test | node-p041 |
| G-0130 | WRONG-RESULT | Node / det network | fixed + test | node-p041 |
| G-0131 | WRONG-RESULT | Node / det network | fixed + test | node-p041 |
| G-0132 | WRONG-RESULT | Node / det random | fixed + test | node-p041 |
| G-0133 | WRONG-RESULT | Node / det random | fixed + test | node-p041 |
| G-0134 | WRONG-RESULT | Node / det random | fixed + test | node-p041 |
| G-0135 | WRONG-RESULT | Node / det time | fixed + test | node-p041, runner-mocha, runner-node-test |
| G-0136 | WRONG-RESULT | Node / det time | fixed + test | node-p041, runner-mocha, runner-node-test |
| G-0137 | WRONG-RESULT | Node / det time | fixed + test | node-p041 |
| G-0138 | WRONG-RESULT | Node / det time | fixed + test | node-p041 |
| G-0139 | WRONG-RESULT | Node / det time | fixed + test | node-p041 |
| G-0140 | WRONG-RESULT | Node / det time | fixed + test | node-p041 |
| G-0141 | WRONG-RESULT | Node / det time | fixed + test | node-p041 |
| G-0142 | WRONG-RESULT | Node / det time | fixed + test | node-p041 |
| G-0143 | WRONG-RESULT | Node / det time | fixed + test | r021-fixes, r021b-fixes, time-p041 |
| G-0144 | WRONG-RESULT | Node / det time | fixed + test | controls, regressions, time-p041 |
| G-0145 | WRONG-RESULT | Node / runner Bun | fixed + test | cache-p041, runner-bun |
| G-0146 | WRONG-RESULT | Node / runner Deno | fixed + test | cache-p041, runner-deno |
| G-0147 | WRONG-RESULT | Node / runner Jasmine | fixed + test | cache-p041, runner-b-cases, runner-b-specific |
| G-0148 | WRONG-RESULT | Node / runner Mocha | fixed + test | cache-p041, policy-equivalence, runner-mocha |
| G-0149 | WRONG-RESULT | Node / runner uvu | fixed + test | cache-p041, runner-b-cases, runner-b-specific |
| G-0150 | WRONG-RESULT | Node / scheduling | fixed + test | node-p041 |
| G-0151 | WRONG-RESULT | Node / scheduling | fixed + test | node-p041 |
| G-0152 | WRONG-RESULT | Node / workers | fixed + test | node-p041 |
| G-0181 | WRONG-RESULT | Refusal / Node: realm installation failed | fixed + test | legacy-proof-policy, node-p041 |
| G-0402 | BLOCKS-USE | Limits / NODE-CACHE.md custom Jest runner | fixed + test | runners-p041 |
| G-0406 | BLOCKS-USE | Limits / NODE.md J11 (Playwright Test) | fixed + test (detjs playwright shell, `fenvix repro --runner playwright`); the browser and web servers are separate processes, not controlled (L2 browser lockstep is not in this release: reported as uncontrolled) | playwright-p041, test_fenvix_js.py |
| G-0420 | BLOCKS-USE | Limits / RELEASE-1.md repro/explore Node | fixed + test | test_fenvix_js.py |
| G-0438 | BLOCKS-USE | Node / explore | fixed + test | tests/test_fenvix_js.py (test_standalone_command_line: explore) |
| G-0447 | BLOCKS-USE | Node / replay | fixed + test | repro-p041 |
| G-0448 | BLOCKS-USE | Node / repro | fixed + test | test_fenvix_js.py |
| G-0449 | BLOCKS-USE | Node / repro | fixed + test | test_fenvix_js.py |
| G-0453 | BLOCKS-USE | Node / runner Jest | fixed + test | runners-p041 |
| G-0455 | BLOCKS-USE | Node / runner Playwright Test | fixed + test (same as G-0406) | playwright-p041, test_fenvix_js.py |
| G-0461 | BLOCKS-USE | Node / runner Vitest | fixed + test | runners-p041 |
| G-0463 | BLOCKS-USE | Node / scheduling | fixed + test | time-p041 |
| G-0464 | BLOCKS-USE | Node / scheduling | fixed + test | time-p041 |
| G-1044 | DEGRADES | Go / parallel under --det | Node part fixed + test (parallel lanes, Vitest/Jest/node:test); Go part out of scope (go-live languages: Python and Node only) | parallel-p041 |
| G-1174 | DEGRADES | Limits / detjs no --det-order | fixed + test | repro-p041 (--det-order) |
| G-1290 | DEGRADES | Limits / NODE-CACHE.md Jest globalSetup | fixed + test | runners-p041 |
| G-1304 | DEGRADES | Limits / NODE.md control 7 (Jest in band) | fixed + test | parallel-p041 (jest lanes) |
| G-1312 | DEGRADES | Limits / NODE.md J3 (Jest setupFiles) | fixed + test | runners-p041 |
| G-1394 | DEGRADES | Node / cache | fixed + test | cache-p041 |
| G-1395 | DEGRADES | Node / cache | fixed + test | parallel-p041 (vitest lanes) |
| G-1396 | DEGRADES | Node / cache | fixed + test | parallel-p041 (jest lanes) |
| G-1397 | DEGRADES | Node / cache | fixed + test | cache-p041 |
| G-1398 | DEGRADES | Node / cache | fixed + test | node-p041 |
| G-1399 | DEGRADES | Node / cache | fixed + test | cache-p041 |
| G-1401 | DEGRADES | Node / cache | fixed + test for Vitest (decided after globalSetup); Jest: refusal kept, proven sound + test (Jest decides before globalSetup) | cache-p041 |
| G-1402 | DEGRADES | Node / cache | fixed + test | cache-p041 |
| G-1406 | DEGRADES | Node / det env | fixed + test | node-p041 |
| G-1407 | DEGRADES | Node / det env | fixed + test | node-p041 |
| G-1408 | DEGRADES | Node / det env | fixed + test | node-p041 |
| G-1409 | DEGRADES | Node / det fs | fixed + test | node-p041 |
| G-1410 | DEGRADES | Node / det fs | fixed + test | time-p041 |
| G-1411 | DEGRADES | Node / det fs | fixed + test | time-p041 |
| G-1412 | DEGRADES | Node / det fs | fixed + test | time-p041 |
| G-1413 | DEGRADES | Node / det network | fixed + test | node-p041 |
| G-1414 | DEGRADES | Node / det network | fixed + test | node-p041 |
| G-1415 | DEGRADES | Node / det network | fixed + test | network-p041 |
| G-1416 | DEGRADES | Node / det network | fixed + test | network-p041 |
| G-1417 | DEGRADES | Node / det network | fixed + test | network-p041 |
| G-1418 | DEGRADES | Node / det network | fixed + test | network-p041 |
| G-1419 | DEGRADES | Node / det network | fixed + test | network-p041 |
| G-1420 | DEGRADES | Node / det network | fixed + test | network-p041 |
| G-1421 | DEGRADES | Node / det network | fixed + test | network-p041 |
| G-1422 | DEGRADES | Node / det random | fixed + test | node-p041 |
| G-1423 | DEGRADES | Node / det random | fixed + test | node-p041 |
| G-1424 | DEGRADES | Node / det random | fixed + test | node-p041 |
| G-1425 | DEGRADES | Node / det random | fixed + test | node-p041 |
| G-1426 | DEGRADES | Node / det random | fixed + test | network-p041 |
| G-1427 | DEGRADES | Node / det random | fixed + test | network-p041 |
| G-1428 | DEGRADES | Node / det random | fixed + test | network-p041 |
| G-1429 | DEGRADES | Node / det random | fixed + test | network-p041 |
| G-1430 | DEGRADES | Node / det time | fixed + test | node-p041 |
| G-1431 | DEGRADES | Node / det time | fixed + test | node-p041 |
| G-1432 | DEGRADES | Node / det time | fixed + test | node-p041 |
| G-1433 | DEGRADES | Node / det time | fixed + test | node-p041 |
| G-1434 | DEGRADES | Node / det time | fixed + test | time-p041 |
| G-1435 | DEGRADES | Node / det time | fixed + test | time-p041 |
| G-1436 | DEGRADES | Node / det time | fixed + test | runners-p041 |
| G-1437 | DEGRADES | Node / det time | fixed + test | runners-p041 |
| G-1448 | DEGRADES | Node / parallel Jest | fixed + test | parallel-p041 (jest lanes, workerThreads) |
| G-1449 | DEGRADES | Node / parallel Jest | fixed + test | parallel-p041 |
| G-1450 | DEGRADES | Node / parallel Jest | fixed + test | parallel-p041 (cache in lanes) |
| G-1455 | DEGRADES | Node / parallel Vitest | fixed + test | parallel-p041 (vitest lanes) |
| G-1456 | DEGRADES | Node / parallel Vitest | fixed + test | parallel-p041 |
| G-1457 | DEGRADES | Node / parallel Vitest | fixed + test | parallel-p041 (cache in lanes) |
| G-1458 | DEGRADES | Node / parallel Vitest | fixed + test | parallel-p041 (the cost of serial is shown) |
| G-1459 | DEGRADES | Node / replay | fixed + test | playwright-p041, repro-p041 |
| G-1460 | DEGRADES | Node / runner all | fixed + test | repro-p041 |
| G-1466 | DEGRADES | Node / runner Jest | fixed + test | runners-p041 |
| G-1467 | DEGRADES | Node / runner Jest | fixed + test | runners-p041 |
| G-1468 | DEGRADES | Node / runner Jest | fixed + test | time-p041 |
| G-1475 | DEGRADES | Node / runner Vitest | fixed + test | runners-p041 |
| G-1476 | DEGRADES | Node / runner Vitest | fixed + test | runners-p041 |
| G-1477 | DEGRADES | Node / runner Vitest | fixed + test | runners-p041 |
| G-1478 | DEGRADES | Node / scheduling | fixed + test | time-p041 |
| G-1481 | DEGRADES | Node / verifier | fixed + test | cache-p041 |
| G-1482 | DEGRADES | Node / verifier | fixed + test | cache-p041 |
| G-1483 | DEGRADES | Node / verifier | fixed + test | cache-p041 |
| G-1484 | DEGRADES | Node / workers | fixed + test | time-p041 |
| G-1582 | DEGRADES | Refusal / Node cache: clock-real | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-1583 | DEGRADES | Refusal / Node cache: dynamic import | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-1584 | DEGRADES | Refusal / Node cache: keygen | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-1585 | DEGRADES | Refusal / Node cache: loader | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-1586 | DEGRADES | Refusal / Node cache: preload | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-1588 | DEGRADES | Refusal / Node: custom Jest runner warning | fixed + test | runners-p041 |
| G-2161 | MINOR | Node / cache | fixed + test | cache-p041 |
| G-2162 | MINOR | Node / det env | fixed + test | runners-p041 |
| G-2163 | MINOR | Node / det env | fixed + test | node-p041 |
| G-2164 | MINOR | Node / det env | fixed + test | runners-p041 |
| G-2165 | MINOR | Node / det network | fixed + test | network-p041 |
| G-2166 | MINOR | Node / det random | fixed + test | node-p041 |
| G-2167 | MINOR | Node / det random | fixed + test | time-p041 |
| G-2168 | MINOR | Node / det random | fixed + test | time-p041 |
| G-2169 | MINOR | Node / det time | fixed + test | node-p041 |
| G-2180 | MINOR | Node / runner Jest | fixed + test | runners-p041 |
| G-2183 | MINOR | Node / runner Vitest | fixed + test (watch mode refused under --det with a message) | runners-p041 |
| G-2184 | MINOR | Node / scheduling | fixed + test | node-p041 |
| G-2185 | MINOR | Node / verifier | fixed + test | node-p041 |
| G-2186 | MINOR | Node / verifier | fixed + test | node-p041 |
| G-2187 | MINOR | Node / verifier | fixed + test | node-p041 |
| G-2220 | MINOR | Refusal / Node cache: /proc | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-2221 | MINOR | Refusal / Node cache: env-unobserved | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-2222 | MINOR | Refusal / Node cache: recording | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-2223 | MINOR | Refusal / Node cache: UDP | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-2224 | MINOR | Refusal / Node cache: unobserved | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |
| G-2225 | MINOR | Refusal / Node: capture not written | refusal kept, proven sound + test (it never gives a wrong result) | cache-p041 |

