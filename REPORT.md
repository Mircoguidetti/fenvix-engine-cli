DONE

# REPORT: Engine P0, no false green

- Branch: `claude/p0-no-false-green`, cut from `claude/release-1` @ bfaf70b4.
- Merged into `claude/release-1` with `git merge --no-ff`.

## Summary

- **One exit rule on every path.** B1, B2, B6: `node/src/exit-status.js`.
  - Runs: a failed or NOT PROVEN test exits 1, a detjs error exits 2.
  - `detjs verify`: its exit code equals Python `verify_exit_code` on every fixture row.
- **The hazard re-run reports NOT PROVEN** for the tests it did not account for (B3).
- **Named Vitest projects** are re-run and accounted as files (B4).
- **Never-started tests are in the trace as `skipped`** (B5): tests of a failed `beforeAll`, and of a nested
  `afterAll` failure.
- **Every run prints exactly one `detjs: status: ...` line and stamps `meta.status`** (B7).
- **Docs and TODOS updated** (B8, B9).
- **The gstack `/review` ran in five rounds.** Its findings were fixed or are listed below.
  - The founder decisions taken in it are D1 to D6.
  - D5 changes a gate: the hazard re-run never lowers the first run's exit code.
- **Merge rule, "no new red against the trunk" (coordinator rule 3):** holds. Every test that fails on this branch
  also fails on bfaf70b4. The lists and commands are under "Failing tests: branch vs trunk".
- **Exception to coordinator rule 4, granted by the founder in D6:**
  - The fixes made after the last full `/review` round were not reviewed again by a full round.
  - They were tested: unit tests, the full Node suite, and CI.
  - The residual findings are listed here and in `TODOS.md` (P1).

## Founder decisions taken during this work (2026-11-23)

- **AC5, Jest.** Criterion: "both tests are in the trace with the outcome Jest reports (`failed`)". Vitest stays
  `skipped`.
  - Jest 30 (circus) fails each test of a failing `beforeAll` itself.
  - Writing `skipped` over that failure would turn red into not-red.
- **Merge rule.** "No new red against the trunk", plus `/review`, then merge and the final REPORT.
- **`/review` D1 = A.** Fix the wrapper false green.
  - Confirmed live: a file that failed to load, next to a hazard failure the re-run cleared, exited 0.
  - The same happened on bfaf70b4 (MEASURED).
- **D2 = A.**
  - Jest `--forceExit` (and any `process.exit` path) gets the exit rule: `exit-status.record()` applies `runExit`
    to `process.exitCode` at once.
  - The mocha shell exits 1, not 2, on failures. Mocha exits with its failure count; 2 means a detjs error.
- **D3 = A.** The informational fixes were applied.
- **D4 = A.** The four CRITICAL findings were fixed and the diff re-reviewed.
- **D5 = A, "never lower the red" (gate change).**
  - `wrapperRunnerCode(status1, status2, rerunTraced)` returns pass 1's non-zero code whatever pass 2 does.
  - The re-run still decides what the merged trace says for the hazard files.
  - It prints `the one-lane re-run of the hazard files passed, but the first run's exit code N stands`.
  - Three rounds of trying to tell "a red explained by the hazard" from "any other red" each leaked a new hole, so
    the default is deny.
  - **Gate edits kept under D5:**

    | test | expectation was | is now |
    |---|---|---|
    | `node/test/parallel-p041.test.js`: P1 shared-path (vitest, jest), P1 fixed-port (vitest, jest), vitest named project | exit 0 | exit 1, plus the "exit code 1 stands" message |
    | `node/test/runner-node-test.test.js`: "P1 one-lane re-run" | exit 0 | exit 1, plus the message |

  - `docs/LIMITS.md` P1 row: "Closed for the trace, open by decision for the exit code". The cost: a run whose
    only red is a placement artifact stays red until the next plan, which puts the hazard files in one lane.
- **D6 = A, "fix the 7, then merge".**
  - The seven open items were fixed, each with a test.
  - Then the full suite and CI ran, then the merge, with the explicit exception to the `/review` rule.

## Failing tests: branch vs trunk (merge rule proof)

### Local runs

Container: 4 CPUs, Node v22.23.5, Python 3.13.18, Vitest 5.1.0, Jest 30.5.2. All MEASURED.

- **Rust.** `cargo test -p detpy-core -p detpy-node`.
  - Branch: 0 failed, 204 passed.
  - bfaf70b4: no Rust change in the diff; the CI build job passes on both.
- **Node.** `cd node && npm test` (`node --test --test-concurrency=1 test/*.test.js`).
  - Branch (2c67961): 975 tests, 968 pass, 3 fail, 3 cancelled, 1 skipped. Failing subtests:
    - `parallel-p041` "jest: parallel lanes": the before hook fails and its 3 tests are cancelled.
    - `repro-p041` "--det-order: exactly the listed tests…" (vitest).
    - `runner-bun` "two --det runs give identical fingerprints…".
    - `runner-node-test` "a file another test file wrote: not cacheable".
  - bfaf70b4: the same four fail, plus `parallel-p041` "jest: placement effects".
- **Python.** `python -m pytest tests/ -q -p no:cacheprovider`.
  - Branch: 16 failed, 1349 passed, 80 skipped. The 16:
    - `test_packaging::test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs`;
    - `test_py_cache`: `::test_the_virtual_clocks_own_probe_of_threads_is_not_the_tests_read`,
      `::test_g2214_a_test_that_crashes_its_worker_is_a_record_of_the_merged_trace`;
    - `test_r023c_fixes::test_e2_shutil_copy2_into_a_temporary_directory_stays_reusable`;
    - `test_review_r056_pycache`: `test_w3_file_size_read_through_posix` (4 params),
      `test_w3_file_existence_read_through_posix_access` (2), `test_w3_file_mtime_read_through_posix_stat`,
      `test_w4_pwd_read_through_posix_environ`, `test_w5_kernel_release` (2),
      `test_w8_c_seeded_random_is_controlled_or_refused`, `test_w11_object_addresses_match_uncached_det`.
  - bfaf70b4: the same 16 ids fail.
- **Python runner suite, zope.** `pytest tests/test_runners_zope.py`, in a venv with `zope.testrunner` and the
  same wheel.
  - Branch: 29 failed, 5 passed.
  - bfaf70b4: 29 failed, 5 passed; the failing ids are identical (sorted lists diffed).

Branch counts for the Rust and Python suites come from the earlier full runs. The diff since then touches only
`node/`, docs and `TODOS.md`.

### `release-1.yml` (workflow_dispatch)

Trunk run 45041985747 at bfaf70b4. Branch run 45146058099 at 2c67961.

| job | trunk | branch |
|---|---|---|
| build, smoke python, smoke node | success | success |
| attacks | failure | failure |
| python 0/4 | failure | failure |
| python 1/4 | success | success |
| python 2/4 | success | success |
| python 3/4 | failure | cancelled |
| node 0/4 | cancelled | cancelled |
| node 1/4 | failure | success |
| node 2/4 | cancelled | success |
| node 3/4 | cancelled | failure |

Fail-fast cancels the rest of a matrix, so the two runs do not cover the same tests.

- **Branch node 3/4.** One failure: `runner-node-test` "a file another test file wrote: not cacheable" (job log
  137596685684). This test fails on bfaf70b4 too (local run above); CI cancelled it there. It now fails at an
  earlier assertion:
  - On bfaf70b4, run 1 exits 0: the wrapper cleared the parallel red. The test then fails on the "written by"
    message, because the parallel default reports a cross-worker hazard instead.
  - On this branch, run 1 exits 1: pass 1's red stands, by D5.
  - I did not change this test. It was already red on the trunk for its own reason, and D5 authorized only the
    P1 expectations listed above.
- **Branch python 0/4.** Main step: 2 failed, both from the list of 16 above (`test_py_cache` ×2). Runner-suites
  step: 58 failed, 89 passed.
  - On the trunk that step was cancelled, so CI shows no comparison.
  - Zope: identical on both trees (above, MEASURED).
  - Django, nose2 and ward: ESTIMATED identical, not run. The branch changes no Python or Rust source; the only
    Python file it adds is `tests/test_exit_status_contract.py`.
- **Branch node 1/4 passed** where the trunk's failed (`repro-p041` "--det-order"). That test still fails locally
  on both trees. UNKNOWN why CI passed it here; I do not count it as fixed.
- **attacks.** Fails on both runs. Not compared line by line: ESTIMATED same cause, since the attack suites run
  the same Python and Node failures listed above.

No test was skipped, deselected or quarantined. The only expectation changes are the D5 gate edits listed above.

## Acceptance criteria

All results MEASURED in this container, unless marked otherwise.

### AC1: `node/test/exit-regression.test.js`

Command: `node --test test/exit-regression.test.js`.

- On bfaf70b4, with only the new test file present: (a), (b) and (c) pass; (d) fails (help said
  `default: serial`), as the spec requires.
- On the branch: 4/4 pass.
- Deviation in (c), documented in the test:
  - Vitest 5 traps SIGTERM in its main process, and the detjs child ends with status 143 and signal null, also on
    bfaf70b4.
  - The fixture adds a `globalSetup` that removes those listeners, so the signal really kills the child.
- Re-exec marker: a pid/ppid check, with the threads pool and `DETJS_PINNED`, `TZ`, `LC_*`, `LANG` cleared.

### AC2: shared fixture `node/test/fixtures/exit-cases.json`

- Rows:
  - `runExit`: the 7 spec rows, plus "a runner code that is not a number" (exit 1).
  - `verifyExit`: 7 rows, plus 2 precedence rows, plus `inputs_recorded: null` (exit 1, `not_proven`).
- `node --test test/exit-status.test.js`: all pass. The file also covers `countStatus` and `record()` setting
  `process.exitCode`.
- `python -m pytest tests/test_exit_status_contract.py`: passes. Every `verifyExit` row equals
  `verify_exit_code`.

### AC3: `node/test/verify-exit.test.js`

- Fixtures are derived at test time from a real `detjs node-test --det` trace:
  - a NOT PROVEN pair, with `not_proven_outside_tests`;
  - an inputs-not-recorded pair, with `meta.inputs` removed;
  - a control pair, the trace unchanged: `identical`, exit 0.
- bfaf70b4: both pairs exit 0 (3/3 fail).
- Branch: both pairs exit 1 with `--json` status `not_proven` (3/3 pass).

### AC4: hazard re-run accounting

- **(a) Pure functions.** `node/test/parallel-rerun-account.test.js` covers `accountRerun`, `fileOf`, `labelFile`,
  `hazardFiles`, `wrapperRunnerCode`, `rerunArgs`, the never-started mark and `namePattern`.
  - Branch: 9/9 pass.
  - bfaf70b4: the original 6 fail (functions absent).
- **(b) Vitest named project.** `parallel-p041.test.js`, test "vitest named project".
  - Branch: the hazard files' tests are reported, "0 failed of 2", and the exit is 1 (D5).
  - bfaf70b4: fails with "0 failed of 0 test(s)".
  - Second half of this defect: the re-run was handed `project|file` labels as paths. These are now normalised to
    the file.

### AC5: `node/test/trace-skipped.test.js`

- Vitest:
  - bfaf70b4: the trace has 0 tests.
  - Branch: both tests are recorded `skipped`.
- Jest (founder's criterion): both tests are recorded `failed`. True on bfaf70b4 too.

### AC6: `node/test/exit-paths-p0.test.js`, 12/12 pass

The spec's four paths, each with one failing test. Each gives exit 1, exactly one status line, and
`meta.status.failed === 1`:

- normal;
- re-exec;
- wrapper with a hazard;
- wrapper without a hazard.

On bfaf70b4 these four fail on the status assertions.

Added from `/review`:

- a file that fails to load;
- a `beforeAll` failure, and a nested `afterAll` failure;
- `--det-isolate`;
- mocha with 2 failures (exit 1, not 2);
- Jest `--forceExit`;
- Jest `--det-isolate` with a load failure;
- a Jest `--det-isolate` test named "… #42", previously filtered out and green;
- a node:test `todo`.

### AC7: docs and TODOS

- `--det-workers` default is the machine's CPUs: `session.js` HELP and `docs/NODE.md`.
- Exit-code tables for runs and verify: `docs/CLI.md` and `docs/VERIFY-CONTRACT.md` §6.
- The parallel paragraph and the P1 row in `docs/LIMITS.md`.
- `TODOS.md`: the P2 item, plus the P1 review residuals.

### AC8

See "Failing tests: branch vs trunk". No test fails on the branch that passes on bfaf70b4.

## Where each change is hooked, and why

### B6: `node/src/exit-status.js`, the one owner of the exit rule

Exports: `runExit`, `verifyExit`, `verifyStatus`, `countStatus`, `statusLine`, `record`, `recordedStatus`. The input
shapes are in its header comment.

- **`bin/detjs.js`, normal path.** `process.exitCode = runExit({...recordedStatus(), runnerCode: code})` for a
  `--det` runner run, or for any process that wrote a trace.
  - Error handlers call `runExit({internalError: true})`, which gives 2.
- **`record()`** also applies `runExit` to `process.exitCode` at the moment the trace is written. Jest
  `--forceExit` and other `process.exit` paths never return to `bin/detjs.js`.
- **`src/parallel-rerun.js`.** `runExit({...counts, runnerCode: wrapperRunnerCode(status1, status2, rerunTraced)})`.
  - `wrapperRunnerCode`: 2 if either pass returned 2; otherwise pass 1's code if non-zero (D5); otherwise pass 2's
    code if non-zero; 1 if the re-run left no trace; else 0.
  - On a child's signal: exit code 1, then the signal is re-raised.
- **`detjs verify`.** `verifyExit(summary)`; `--json` adds `status: verifyStatus(summary)`. Precedence: diverged,
  then not_proven, then input_differs, then identical.
- **Forwarding only:** the TZ re-exec forwards `r.status ?? 1` and re-raises signals.

### B3 and B4: `src/parallel-rerun.js`

- `accountRerun` returns `want`, `unaccounted`, `complete`, `notProven` and `notProvenFiles`.
- For each file it prints one line: `detjs: parallel: NOT PROVEN <file>: ...` with the cause, either "its trace
  is missing" or "it ran K of its N test(s)".
- Re-run records carrying the `sched.never_started` event do not count as a re-run of the test.
- `fileOf` drops `@@project`; `labelFile` drops `project|`.
- Pass 2 drops file-selection flags (`--shard`, `--changed`, `--related`, `--onlyFailures`, `--watch`, …) and
  their values. Only hazard files are spliced into the merged trace.
- The trace of pass 1 is read only if pass 1 wrote it: an inode, size and mtime stamp is taken before and after.

### B5: never-started tests

- `state.js` tracks the `begun` ids. `controls.recordNeverStarted(ids)` writes a `skipped` record with the event
  `sched.never_started`, at site `<detjs>`.
- **Vitest** (`vitest/shell.js` `__neverStarted`) is called in `onAfterRunFiles`, before `closeFile`, and in
  `__open` before switching file. There the part is still open and the file's task tree is complete.
- **Jest** (`jest/runner.js`) is called in the runner's `finally`, after `endPending()` and before `closeFile`.
- Both only fill tests still in the run (the `--det-order` filter), and do nothing under `--det-collect`.

### B7: status line and `meta.status`

- **`session.finish`.** After `mergeTraces`, `stampStatus`:
  - counts the merged trace;
  - inserts `"status":{...}` as the first key of the header's `meta`, by a text edit of the header line;
  - writes a temp file beside the real path, opened with `wx` and the original mode, then renames it;
  - makes no Rust change.

  Then `record()`, then one synchronous stderr line, whose write is guarded.
- **`printsStatus`** is false in three cases, so each run prints exactly one line:
  - wrapper pass 2;
  - wrapper pass 1 when its own run found a hazard (the wrapper prints for the merged trace);
  - `--det-isolate` children.
- **`isolate.js`** counts its merged records, stamps `meta.status`, prints one line and calls `record()`.
- **Counting rule.**
  - passed → `passed`; skipped and todo → `skipped`.
  - Every other outcome (failed, error, interrupted, unknown) → `failed`.
  - NOT PROVEN tests are counted only in `not_proven`.
  - `meta.status` counts records. The exit code is the verdict (documented).

**B7 runner coverage** (MEASURED, one line plus `meta.status` plus exit 1 for one failed and one passed test):

- vitest, jest, node-test, mocha, bun-test, playwright (no browser), and `--det-isolate` for vitest and jest.
- deno-test, ava, tap, jasmine and uvu are not installed here, so NOT MEASURED. They finish through the same
  `runners/common.js` → `session.finish` path.

## Decisions on the appendix points

1. **Wrapper with no hazard.** The pass-1 child writes the final trace and prints the line. The wrapper forwards
   its code.
2. **Exactly one line.** Enforced through `DETJS_HAZARD_PASS`, as above.
3. **`header.meta.status`** is set without a Rust change.
4. **Partly accounted re-run.** Every unaccounted test is NOT PROVEN and the exit is 1.
5. **`--json` precedence.** diverged > not_proven > input_differs > identical.
6. **AC3 fixtures.** As described under AC3.
7. **AC1(c).** As described under AC1, including the deviation.
8. **`runnerCode` and `internalError` are separate inputs.** The wrapper mapping is described under B6. It
   changed under D5.
9. **The standalone Vitest-only test** is placed after the parameterised blocks.
10. **Jest hook.** The runner's `finally`.

## `/review` history

- gstack was installed after the founder's confirmation.
- Five rounds ran: Review Army specialists, red team, Claude adversarial pass. Codex is not installed.
- Rounds 1–4 led to D1–D5, with fixes in 72435ac, 3e1f12b, daeac96, 4a74046 and 4c55b99.
- Round 5 left seven open items. Fixed under D6 in 2c67961, with a test each:
  - the Jest `--det-isolate` name filter (`namePattern`);
  - the never-started mark ignored by `accountRerun`;
  - node:test `todo`;
  - guarded stderr writes in `finish`;
  - an exclusive temp file and mode via the file descriptor in `stampStatus`;
  - the signal fallback exit code;
  - `--watch` dropped from pass 2, and the LIMITS paragraph.
- No new full round after 2c67961, by founder exception (D6).

## Residual findings (not fixed; also in `TODOS.md` as P1)

None of these lets a red run exit 0: the exit code never goes below pass 1's.

- `meta.status` can read `failed=0` on a red run, because it counts records only (B7). Documented.
- B5 synthetic records go through per-test hooks.
- A runner's own exit code 2 maps to detjs exit 2; codes 3 and above collapse to 1.
- Paths that contain `|` or `@@` are parsed ambiguously.
- When the wrapper cannot read pass 1's trace, no status line is printed (a message says so).
- A nested detjs inherits `DETJS_HAZARD_*`.
- `stampStatus` reads the whole trace into memory.
- Vitest positional filters may make pass 2 run extra files. Their records are no longer spliced in.
- `footer.missing` is not counted.
- B5 is a no-op under jest-jasmine2.
- A `--det-isolate` collection failure is now red, a new false-red channel.
- There are no tests for the B5 collect and order guards, nor for the splice filter.
- A test skipped in pass 2 counts as cleared in the trace; the exit code is unaffected.

## Open (pre-existing, not in scope)

- The trunk is red in CI and locally. See the lists above.
- The hazard re-run drops `--det-order` (`repro-p041`).
- The 168-failed-tests exit 0 seen on agentic-qe is DECLARED; its path is UNKNOWN. Any path that reaches `runExit`
  with failed > 0 now exits 1.
