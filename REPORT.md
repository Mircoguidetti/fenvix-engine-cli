BLOCKED

# REPORT — Engine P0: no false green (branch `claude/p0-no-false-green`, from `claude/release-1` @ bfaf70b4)

## Why BLOCKED (three independent reasons)

1. **Merge step BLOCKED: the gstack `/review` skill is not installed.** `ls ~/.claude/skills/gstack/review/SKILL.md`
   -> `No such file or directory` (MEASURED). As the coordinator instructed, nothing was merged into
   `claude/release-1`; the branch is pushed.
2. **AC5 (Jest half) BLOCKED: the contract conflicts with Jest 30.** AC5 asks that a Jest file with a failing
   `beforeAll` and two tests leaves both in the trace as `skipped`. Jest 30 (circus) does not keep those tests
   from the per-test hook: it dispatches `test_start`/`test_done` for each and fails it with the hook's error.
   MEASURED on bfaf70b4 (`detjs jest --det` on the AC5 fixture): the trace already has both tests, outcome
   `failed`; on this branch the same. B5 covers only tests that *never reached* the per-test hook, and rewriting a
   failure Jest reported as `skipped` would turn a red test into a non-failure — against the product promise. Not
   reinterpreted: `node/test/trace-skipped.test.js` checks for Jest what B5 guarantees (both tests in the trace,
   the runner's own outcome), with the conflict written in the test. The founder decides whether AC5's Jest
   expectation should read "in the trace" or something else. (I also searched for a Jest case that DOES leave tests
   out of the trace — filtered `test.concurrent`, `-t`: none, on bfaf70b4 or here, MEASURED.)
3. **AC8 is not met and cannot be met by this branch alone: the trunk itself is red.** `release-1.yml` on
   `claude/release-1` @ bfaf70b4 (run 45041985747, push): jobs `attacks`, `python (3.13, shard 0/4)`,
   `python (3.13, shard 3/4)`, `node (24, shard 1/4)` failed (DECLARED by the GitHub Actions API,
   `list_workflow_jobs`). Locally, the 4 Node test files that fail on this branch fail identically on bfaf70b4
   (below). CI on this branch: see AC8.

## Acceptance criteria

All local numbers: MEASURED on this container (4 CPUs, Node v22.23.5, Python 3.13.18, Vitest 5.1.0, Jest 30.5.2,
addon from `cargo build -p detpy-node --release`, wheel from `maturin build --release`).

**AC1 — `node/test/exit-regression.test.js`.** `node --test test/exit-regression.test.js`
- On bfaf70b4 (only the new test file present): (a) pass, (b) pass, (c) pass, (d) FAIL (help said
  `default: serial`) — as the spec requires.
- On this branch: 4/4 pass.
- Deviation in (c), documented in the test: Vitest 5's logger traps SIGTERM in its main process
  (`Logger.addCleanupListeners`: `process.once('SIGTERM')` then `process.exit()` → 143). With the fixture exactly
  as the spec words it, the detjs child ends with **status 143, signal null**, on bfaf70b4 (MEASURED), so the
  parent cannot see a signal. The fixture adds a `globalSetup` (runs in that main process after the logger) that
  removes the SIGTERM listeners, so the signal really kills the child; then the parent ends with SIGTERM
  (bfaf70b4 and here). Re-exec marker (appendix 7): the test writes `process.pid`/`process.ppid`; the test's
  process is a child of the spawned detjs (`ppid === r.pid`, `pid !== r.pid`). `DETJS_PINNED`, `TZ`, `LC_*`,
  `LANG` are cleared; `--det-workers=1` keeps the wrapper out; `--pool=threads`.

**AC2 — shared fixture.** `node/test/fixtures/exit-cases.json` (7 runExit rows as listed in the spec, 7 verifyExit
rows plus 2 precedence rows). `node --test test/exit-status.test.js` → 18/18 pass (plus a countStatus test);
`python -m pytest tests/test_exit_status_contract.py` → 1 passed (every verifyExit row equals
`verify_exit_code`). Input fields `runnerCode` and `internalError` separate (appendix 8).

**AC3 — `node/test/verify-exit.test.js`.** Fixtures are derived at test time from one real
`detjs node-test --det` trace of a one-test suite (so their sensor declaration is always the current one; a
control pair checks the unchanged trace is `identical`, exit 0):
- NOT PROVEN pair: both headers get `not_proven_outside_tests: ["env:HTTPS_PROXY"]` (verify.rs
  `outside_not_proven`: every test NOT PROVEN).
- inputs-not-recorded pair: `meta.inputs` deleted from both headers (verify.rs: `inputs_recorded` = every run has
  `meta.inputs`).
- bfaf70b4: both pairs exit 0 (MEASURED; 3/3 fail). Branch: both exit 1 and `--json` `status: "not_proven"`;
  3/3 pass.

**AC4.** (a) `node/test/parallel-rerun-account.test.js` on `accountRerun(firstTests, rerunTests, files)` (pure,
extracted from `parallel-rerun.js main()`), `fileOf`, `labelFile`, `hazardFiles`, `wrapperRunnerCode`: 6/6 pass;
on bfaf70b4 6/6 fail (functions absent / old `fileOf`). (b) `parallel-p041.test.js`, new standalone Vitest test
"vitest named project: the one-lane re-run reports the hazard files' tests, not 0 of 0" (fixture
`test.projects: [{ test: { name: 'main', include: [...] } }]`, lanes forced with `--det-plan`): branch → pass,
"0 failed of 2 test(s)"; bfaf70b4 (src/bin stashed) → FAIL with
`the one-lane re-run is what is reported for main|tests/x.test.mjs, main|tests/y.test.mjs: 0 failed of 0 test(s)`.
Finding: the defect had a second half the spec did not list — the hazard sides are lane LABELS (`main|<file>`),
so the re-run was also handed nonexistent paths (`<root>/main|tests/x.test.mjs`). Both are normalised to the file.

**AC5 — `node/test/trace-skipped.test.js`.** Vitest: bfaf70b4 → trace has 0 tests (MEASURED); branch → both
`skipped`, pass. Jest: BLOCKED, see above (test checks both tests present, outcome `failed`).

**AC6 — `node/test/exit-paths-p0.test.js`.** One failing test through: normal path (`--det-workers=1`, TZ/locale
pre-pinned), re-exec path (env cleared; marker: the test sees `TZ=UTC`), wrapper with a hazard (two files write one
path, lanes forced by `--det-plan`; the wrapper merges), wrapper with no hazard (pass-1 child's trace is final).
Each: exit 1, exactly one `detjs: status:` line (on stderr), `meta.status.failed === 1`. Branch 4/4 pass;
bfaf70b4 4/4 fail, every one with status=1 (exit codes held; only the status assertions fail).

**AC7.** `--det-workers` default: `node/src/session.js` HELP and `docs/NODE.md` ("Parallel") now say the machine's
CPUs. Exit-code tables for runs (B1) and verify (B2, with the `--json` status words) in `docs/CLI.md` and
`docs/VERIFY-CONTRACT.md` (section 6). `TODOS.md` at the root with the one P2 item.

**AC8.**
- `cargo test -p detpy-core -p detpy-node`: 204 passed, 0 failed (MEASURED).
- `cd node && npm test` (`node --test --test-concurrency=1 test/*.test.js`, 3400 s): 958 tests, 946 pass, 8 fail,
  3 cancelled, 1 skipped (MEASURED, first full run). Breakdown:
  - `node-p041` JS-09 (2): environment — the test copies `node/detjs.linux-x64.node`, which CI puts there and I had
    not. After copying the addon there: 49/49 pass.
  - `repro-p041` "--det-order: exactly the listed tests" (vitest, jest): caused by my first B5 version (it added
    `skipped` records for tests `--det-order` removes from the run). Fixed in 508dda9 (only tests still in the run;
    nothing in `--det-collect`). After the fix the vitest case still fails, **identically on bfaf70b4** (MEASURED,
    bfaf70b4 worktree): under parallel-by-default the hazard re-run drops `--det-order` and re-runs every test.
    Pre-existing.
  - `runner-bun` "two --det runs give identical fingerprints" (seeded random differs): fails on bfaf70b4 too.
  - `runner-node-test` "a file another test file wrote: not cacheable": fails on bfaf70b4 too (parallel by default
    on 4 CPUs makes it a cross-worker hazard message instead of "written by").
  - `parallel-p041` "jest: parallel lanes" (before hook: Jest 30 refuses lanes, "parallel by default" assertion; 3
    cancelled): fails on bfaf70b4 too (there also "jest: placement effects").
  - Re-run of those five files on this branch: node-p041 49/0, repro-p041 20/1, runner-bun 40/1,
    runner-node-test 51/1, parallel-p041 35 pass/0 fail/3 cancelled; on bfaf70b4: repro-p041 20/1, runner-bun 40/1,
    runner-node-test 51/1, parallel-p041 33/1/3 cancelled. No test fails here that passes on bfaf70b4.
  - All 37 tests of the new files pass after the fix (MEASURED).
- `python -m pytest tests/` (serial, as CI): 16 failed, 1349 passed, 80 skipped (MEASURED, 1:52 h). The same 16
  fail on bfaf70b4 (MEASURED: bfaf70b4 worktree, same 16 ids, `16 failed`): `test_packaging` (the workflow gate
  test), `test_py_cache` (2), `test_r023c_fixes` (1), `test_review_r056_pycache` (12). No Python or Rust code
  changed in this branch; the only Python change is the new `tests/test_exit_status_contract.py` (passes).
- `release-1.yml` on this branch, workflow_dispatch depth light, run 45083642120 on 508dda9: **failure**
  (DECLARED by the GitHub Actions API). build, smoke (python), smoke (node), python (3.13, shard 2/4): success;
  attacks, python (3.13, shard 3/4), node (24, shard 1/4): failure; the rest cancelled by fail-fast. The same three
  jobs failed on the trunk at bfaf70b4 (run 45041985747; there also python shard 0/4). The node shard 1/4 failure
  is the same assertion with the same values on both runs (`repro-p041.test.js` "--det-order: exactly the listed
  tests", job logs 137397969624 vs 137269021593). attacks and python 3/4 logs not compared line by line: their
  equality to the trunk's is ESTIMATED from the local Python comparison above.
  (The run was started by me with workflow_dispatch: pushes to session branches run nothing and no PR was opened.)

## Where each change is hooked, and why

**B6 — `node/src/exit-status.js`**: `runExit`, `verifyExit`, `verifyStatus`, `countStatus`, `statusLine`, and
`record`/`recordedStatus` (the counts of the trace this process wrote). Input shapes in its header comment. Callers:
- `node/bin/detjs.js` normal path: `runExit({...recordedStatus(), runnerCode: code})` for a `--det` run of a
  runner (or any process that wrote a trace); other commands (`verify` 0/1/3, repro, help) keep their code. The
  error handler is `runExit({internalError: true})` (2). Same for the wrapper's error handler.
- `node/src/parallel-rerun.js`: the wrapper's final decision (replacing the old `:228-235`) is
  `runExit({...counts, runnerCode: wrapperRunnerCode(status1, status2, firstFailed, rerunTraced)})`.
- `detjs verify`: `verifyExit(rep.summary)`; `--json` adds `status: verifyStatus(...)`.
- Forwarding only, unchanged: re-exec `r.status ?? 1` (signal re-raised), wrapper `r.status` with signal
  re-raised, and the wrapper with no hazard returning pass 1's already-decided code.

**B3/B4 — `parallel-rerun.js`**: `accountRerun` decides `want`/`unaccounted`/`complete`/`notProven`/
`notProvenFiles`; one `detjs: parallel: NOT PROVEN <file>: the one-lane re-run did not account for its tests
(<cause>)` line per file (causes: `its trace is missing`, `it ran K of its N test(s)`). `fileOf` drops `@@project`;
`hazardFiles` reduces `project|file` labels to the file (`labelFile`). `meta.hazard_rerun.not_proven` lists them.

**B5 — `node/src/state.js`** tracks `begun` ids per file; **`node/src/controls.js` `recordNeverStarted(ids)`** writes
a `skipped` record (beginTest/endTest, the same way a `test_skip` is recorded) for each test of the open file with
no record. Called, independent of the cache:
- Vitest (`node/src/vitest/shell.js` `__neverStarted`): before the part closes — in `onAfterRunFiles` before
  `controls.closeFile()`, and in `__open` before switching to the next file (a worker that runs several files).
  Why there: the part is still open and the file's task tree (`det.ids`/`det.fileOf`) is complete; `writeCapture`
  only runs with `CAP` set.
- Jest (`node/src/jest/runner.js`, the runner's `finally`): after `endPending()`, before `controls.closeFile()` —
  the one point where every test event of the file is in and the part is open (appendix 10). A no-op on Jest 30 in
  every case I could build (see AC5).
- Both restricted to tests still in the run (`--det-order` filter: Vitest `det.collected`, Jest `collected`), and
  off in `--det-collect`.

**B7 — status line and `meta.status`**:
- `node/src/session.js finish` (vitest, jest, node-test, mocha, playwright, and `runners/common.js`: bun, deno,
  tap, ava, jasmine, uvu): after `native.mergeTraces`, `stampStatus` counts the merged trace and writes
  `"status":{...}` as the first key of the header's `meta` by text edit of the header line (no other byte of the
  trace changes; no Rust change — appendix 3). One stderr line, written synchronously (the runner may be exiting).
- `printsStatus`: not printed by pass 2 of the wrapper (`DETJS_HAZARD_PASS=2`), nor by pass 1 when its own run
  found a hazard (the wrapper's merged trace replaces it), nor by `--det-isolate` children (appendix 1, 2). The
  wrapper sets `DETJS_HAZARD_PASS` explicitly, so a user's own `DETJS_HAZARD_RERUN=1` (which disables the wrapper)
  still prints.
- `parallel-rerun.js`: when it merges, `meta.status` is set before `mergeTraces`, the line printed by the wrapper.
- `node/src/isolate.js` (`--det-isolate`): counts its merged records, `meta.status`, one line, `record()` for the
  exit decision.

**B7 runner coverage** (one line on stderr, `meta.status` in the header, exit 1 for 1 failed + 1 passed; MEASURED
with a manual fixture unless said): vitest yes (AC6), jest yes, node-test yes, mocha yes, bun-test yes, playwright
yes (`playwright test --det`, no browser), `--det-isolate` (vitest) yes. deno-test, ava, tap, jasmine, uvu: not
installed in this container, so NOT MEASURED; they finish through `runners/common.js` → `session.finish`, the same
code path, so they print by construction (UNKNOWN by measurement).

## Decisions on the appendix points

1. Wrapper with no hazard: the pass-1 child writes the final trace and prints (it knows it had no hazard from its
   own `meta.parallel.hazards`, the data the wrapper reads); the wrapper forwards its code. If pass 1 leaves no
   readable trace, no line is printed (no final trace), and its code is forwarded.
2. Exactly one line: as above (`DETJS_HAZARD_PASS`); the merged trace's header carries the final counts.
3. `header.meta.status`, no Rust change.
4. Partly accounted re-run: every unaccounted test is NOT PROVEN; the first run's records stand (as before) and
   the exit is 1.
5. `--json` status precedence: diverged > not_proven > input_differs > identical (fixture rows test it).
6. AC3 fixtures: `not_proven_outside_tests` and missing `inputs`, as above.
7. AC1(c): threads pool, `DETJS_PINNED` cleared, pid/ppid marker; plus the SIGTERM-untrap `globalSetup` (deviation
   above).
8. `runnerCode`/`internalError` separate; wrapper mapping: 2 if either pass returned 2; pass 1's code if it had no
   failed test; pass 2's code if non-zero; 1 if the re-run left no trace; else 0.
9. Standalone Vitest-only test after the parameterised blocks of `parallel-p041.test.js`.
10. Jest: the runner's `finally` (above).

Other decision: **outcomes other than passed/skipped/todo count as `failed`** (e.g. `interrupted`, a test whose file
ended while it ran). The spec names failed and error; leaving the rest out of every count would let the wrapper
end green where bfaf70b4 gave 1 (its `badFinal` was every outcome not passed/skipped/todo). Documented in
`exit-status.js`, the docs table, and tested.

Counting NOT PROVEN: a NOT PROVEN test is counted only in `not_proven`, not under its recorded outcome, so the four
counts partition the records.

## Open

- AC5 Jest expectation (founder decision, above).
- AC8: trunk red before this work; the pre-existing local failures above.
- The merge (gstack `/review` missing).
- `vitest`'s fallback `process.on('exit', finalize)` (runner exits without returning): the trace and the line are
  written, but the exit code is whatever the runner set, because `main()` never returns to `runExit`. Not changed.
- The hazard re-run drops `--det-order` (pre-existing, `repro-p041`), so a `--det-order` run with a hazard re-runs
  every test of the hazard files.
- The 168-failed-tests exit 0 on agentic-qe (DECLARED, path UNKNOWN): any path that reaches `runExit` with
  failed > 0 now exits 1 regardless of the runner code; whether that was the path there is UNKNOWN without its rows.
