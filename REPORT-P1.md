NOT DONE

# P1: the engine's run-level false alarms (phase 2 report)

Branch `claude/p1-false-alarms`. Status per item (coordinator's approval of 2026-11-23, order F, A1, C, E, B, D;
merge ordered by the coordinator, not by this session):

| item | status | MEASURED gain (final round 1 vs before round 1) |
|---|---|---|
| F nested file operations | **DONE** | claudekit F 225 → 1, identical 555 → 790 with E; `--det` serial 21.7 / 21.1 s → 8.7 s, parallel 21.0 / 21.6 s → 9.1 s; sqlectron F 8 → 0 |
| A1 KEPT/proxy variables read outside tests | **DONE** | agentsys A 1,540 → 0, identical 0 → 1,542 (with D) |
| C virtual pid | **NOT DONE (reverted)** | +35 identical on nestjs-pino, but **+207 failing tests** on ironcurtain under `--det` (section C) |
| E stat/readdir order | **DONE** (with a follow-up commit) | claudekit E 22 → 0 |
| B scope of files read outside tests | **PARTLY DONE**: B1 done, B2 not implemented | ironcurtain run-level B 7,033 → 0 (B-abs 7,033 → 165 scoped); codex-multi-auth run-level B removed in one of two final rounds |
| D entropy controlled by default (option 3) | **DONE** | agentsys D 99 → 0, sqlectron D 5 → 0 |

**Tests that became identical: 778 → 2,555 (+1,777) in round 1, 2,551 in round 2** (6 repositories, S1 vs P1w4,
4 workers). First line `NOT DONE` because C is not done and B2 is not implemented; the rest is ready for the
coordinator's `/review` and merge order.

## 1. How it was measured

* Before: `harness/p1/data/before/`, engine trunk e7338950 (DESIGN-P1.md section 1).
* After: branch **d9c5854** (F, A1, E + follow-up, B1, D; C reverted), built as spec step 6: `(cd node && npm run build)`
  (addon), `maturin build --release` of the checkout and `pip install --force-reinstall` into
  `$PM_WORK/venv/engine` (the judge `verify` runs with, B1 + A1). Measured from a worktree at that commit
  (`/tmp/pm-p1/wt-final3`), so edits in the checkout could not change the engine mid-run; `engine_commit` in every
  row: `d9c5854d75f8331b7f80ea5098051bf46bb0795f+modified` (measure.py's marker for a branch engine).
* Loop (spec step 1, `--out $PM_WORK/p1-after`), one repository at a time, nothing else running:
  `python3 measure.py --spec specs.json --name $r --reps 2 --workers 4 --skip plain_par --timeout 7200 --out
  $PM_WORK/p1-after` for agentsys, codex-multi-auth, ironcurtain, nestjs-pino, claudekit, sqlectron (2026-11-23
  20:35-21:23 UTC). Every count comes from `fenvix verify S1 P1w4 --json` (the `cmd` of each `verify` row in
  `harness/p1/data/after/<repo>/results.jsonl`), classified by `harness/p1/tally.py` (unchanged rules).
* sqlectron: measured with `sqlite3` rebuilt (43 tests) before and after, as in the design (the spec install line
  leaves it unbuilt).
* Per-item rounds (one round each, cumulative, from a worktree at the item's commit, judge built from that commit):
  `harness/p1/data/items/{F,A1,C,E,B}/`. The C, E and B rounds include C (it was reverted after them).
* Data: `harness/p1/after.json`, `after-round2.json`, `after-serial-pair.json`, `items-*.json`,
  `harness/p1/data/after/` (rows, every verify JSON, trace header lines, E events; files over 1 MB gzipped).

## 2. Before / after per repository

Round 1 (round 2 in brackets), counts by `tally.py` category:

| repository | tests | identical before | identical after | A | B-tmp | B-abs | C | D | E | F | noise | other |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentsys | 2,224 | 0 | **1,542** (1,538) | 1,540 → 0 (0) | 0 → 0 | 0 → 0 | 1 → 1 (1) | 99 → 0 (0) | 0 → 0 | 1 → 1 (1) | 583 → 327 (327) | 0 → 353 (357) |
| codex-multi-auth | 8,663 | 0 | 0 (0) | 0 → 0 (4,365) | 8,661 → 8,661 (229) | 0 → 0 | 0 → 0 (546) | 0 → 0 (0) | 0 → 0 | 0 → 0 (8) | 1 → 1 (3,514) | 1 → 1 (1) |
| ironcurtain | 7,033 | 0 | 0 (0) | 0 → 5,162 (5,157) | 0 → 266 (266) | 7,033 → 165 (165) | 0 → 548 (548) | 0 → 4 (4) | 0 → 0 | 0 → 134 (129) | 0 → 754 (764) | 0 → 0 |
| nestjs-pino | 269 | 223 | 223 (223) | 0 → 0 | 0 → 0 | 0 → 0 | 35 → 35 (35) | 0 → 0 | 0 → 0 | 8 → 10 (10) | 3 → 1 (1) | 0 → 0 |
| claudekit | 814 | 555 | **790** (790) | 0 → 0 | 1 → 0 (0) | 0 → 0 | 2 → 2 (2) | 0 → 0 | 22 → 0 (0) | 225 → 1 (1) | 9 → 20 (19) | 0 → 1 (2) |
| sqlectron (sqlite3 rebuilt) | 43 | 0 | 0 (0) | 30 → 43 (43) | 0 → 0 | 0 → 0 | 0 → 0 | 5 → 0 (0) | 0 → 0 | 8 → 0 (0) | 0 → 0 | 0 → 0 |
| **total** | | **778** | **2,555** (2,551) | | | | | | | | | |

Reading it:
* A run-level difference hides every other cause. Where B1 removed it (ironcurtain, codex-multi-auth round 2), the
  causes behind it appear as counts that were 0 before: they are not new divergences. ironcurtain A 5,162 is its
  `not_proven_outside_tests` (env entries whose digests differ between the runs, and other kinds); C 548 is
  `process.pid` (C not done).
* codex-multi-auth round 1: one run-level entry is left, `file:<tmp>/.codex/accounts.json` = `stat:missing`. In the
  parallel run it carries `file: test/accounts.test.ts`; in the serial run it was read while **no test file was
  open** (between files, after accounts.test.ts closed: a step that outlived its file), so it has no scope and stays
  run-wide. Round 2 did not hit it (B-tmp 229, scoped). Not fixed: see B.
* sqlectron A 30 → 43: its A is the native `sqlite3` addon loaded outside any test (not an environment read, design
  A.4); with F and D gone it is the only cause left, so it covers all 43 tests.
* nestjs-pino: C (35) is its remaining false alarm; C is not done.
* noise/other: tests not identical for causes outside A-F (child processes, in-test KEPT variables, order, ...).

Run time (`wall_s` of the rows, round 1 / round 2): claudekit `--det` serial 21.69 / 21.05 s before, 8.70 / 8.90 s
after; parallel 20.95 / 21.61 s → 9.11 / 9.34 s; plain serial 7.00 / 6.53 s → 7.65 / 6.85 s. sqlectron serial 19.95 /
19.39 → 7.32 / 7.53 s, parallel 15.96 / 16.04 → 4.38 / 4.32 s.

Outcomes (each run's `outcome_counts`, round 1): identical before and after for every run of agentsys, nestjs-pino,
claudekit, sqlectron and ironcurtain (serial 226 failed, parallel 407 failed in both). codex-multi-auth: plain 6 → 7
failed, `--det` serial 438 → 400 failed, parallel 429 → 428 failed (its `--det` runs fail ~400 tests on the trunk
too; not investigated here).

## 3. Per item (one round each, cumulative; identical tests and the item's count)

| repository | before | +F | +A1 | +C | +E | +B | final (C reverted) |
|---|---|---|---|---|---|---|---|
| agentsys | 0 (A1,540 D99) | 0 | **1,540** (A0) | 1,540 (C0) | 1,540 | 1,540 | 1,542 (D0) |
| codex-multi-auth | 0 (B8,661) | 0 (B38) | 0 (B36) | 0 (B8,662) | 0 (B49) | 0 (B48) | 0 (B8,661) |
| ironcurtain | 0 (B7,033) | 0 | 0 | 0 | 0 | 0 (**B417, run-level 0**) | 0 (B431) |
| nestjs-pino | 223 (C35 F8) | 223 (F6) | 223 | **258** (C0) | 258 | 258 | 223 (C35) |
| claudekit | 555 (E22 F225) | **777** (F0) | 775 | 777 | 773 (E19) | 779 (E13) | **790** (E0) |
| sqlectron | 0 (A30 D5 F8) | 0 (F0) | 0 | 0 | 0 | 0 | 0 (D0) |

codex-multi-auth's run-level B comes and goes between rounds (8,661 / 38 / 36 / 8,662 / 49 / 48 / 8,661 / 229): it
depends on whether that `stat` happens while a test file is open (timing), not on the item.

### F: one awaited file call is one operation — DONE
* Commits: fe8f883 (test, red on e7338950: 5 of 6 cases), 2d73a96 (fix: `node/src/ioorder.js`, an `AsyncLocalStorage`
  holds the running tracked operation; an operation begun in its call or its continuation is not tracked; the
  test's callbacks and promise settlements are delivered outside it; `node:fs` frames are Node internals).
* Regression test `node/test/p1-f-nested-io.test.js` (6/6): engine mkdtemp → mkdir, callback writeFile → open/write/
  close, appendFile, graceful-fs writeFile (its global `fs.close`), sequential promise calls; real-difference case:
  two reads in flight still `uncontrolled.io` and NOT PROVEN.
* Found on the trunk while writing the test: after an awaited `fs.promises.mkdtemp`, two concurrent reads leave a
  completion held for good and node:test cancels the test ("Promise resolution is still pending but the event loop
  has already resolved") — F changed an outcome on the trunk, not only a verdict.
* MEASURED: claudekit F 225 → 0 (+F round), 225 → 1 (final); sqlectron F 8 → 0; nestjs-pino F 8 → 10: its F is a
  connection (`superagent`) overlapping another operation, not this mechanism (design F.2, UNKNOWN cause).
* P2 side effect (spec: measure it, no P2 work): claudekit `--det` serial 21.0 s → 13.1 s with F alone (+F round),
  8.7 s final (with E's rm follow-up and D).

### A1: a KEPT/proxy variable read outside any test is compared by value — DONE
* Commits: a1c4045 (test, red: every test not-proven), a004572 (fix: `node/src/controls.js` writes
  `env:<NAME>=<digest>`, the enumeration `env:*` without the engine's/runner's per-process variables;
  `crates/detpy-core/src/verify.rs` `undischarged_outside` discharges an env entry when every run has the same digests;
  docs/VERIFY-CONTRACT.md sections 3-4). The cache is unchanged.
* Tests: `node/test/p1-a-env-outside.test.js` 4/4 (vitest, jest; real difference: TMPDIR differs → never stable);
  Rust `p1_a1_env_read_outside_tests_compared_by_value` (different digests, read in one run only, digest-less entries,
  `api:` entries, three runs).
* MEASURED: agentsys 0 → 1,540 identical (+A1 round), as the counterfactual predicted.
* Not discharged, correctly: codex-multi-auth's `env:*` digests differ per process because
  `test/helpers/global-sandbox.ts` sets `HOME` to a fresh `mkdtempSync` directory outside any test (real random names
  outside tests), so the enumerated environment really differs; and its `api:process.reallyExit` (A3, not approved).

### C: virtual pid — NOT DONE (reverted in 8f125d7, 94850de, d9c5854)
* Implemented as designed (4167c87 test, 4939fc1 fix, 3ddaa2d test fix): test code read
  `4194305 + digest(seed, file)`; `process.kill` mapped back; `process.ppid` kept real
  (test/exit-regression.test.js AC1(c) reads the process tree from inside a test: a virtual ppid failed it).
* MEASURED gain: nestjs-pino C 35 → 0, identical 223 → 258 (+C round).
* MEASURED damage: ironcurtain `--det` serial **226 → 433 failed tests**, parallel 407 → 423 (+C round; the plain
  run unchanged at 20). The 207 new failures are in its docker suites: `src/docker/docker-resource-lifecycle.ts:76`
  passes `process.pid` to `ps -o lstart= -p <pid>`; the virtual pid does not exist for `ps`, the identity is
  undefined and the code throws. The pid also goes into lock files, a watchdog supervisor's metadata and child
  processes (`src/docker/provision-lock.ts:113`, `src/docker-workload/resource-watchdog-supervisor.ts:156`): a
  virtual pid escapes to the operating system wherever a program hands it to another process. An engine control that
  makes passing tests fail is worse than the false alarm, so C is reverted; after the revert ironcurtain is back to
  226 / 407 failed (final rounds).
* Options for the coordinator / founder:
  1. **Record the real pid symbolically** (the counterfactual: the test sees the real pid, the event records a
     constant). Removes the 35 (MEASURED in phase 1) and breaks nothing, but a pid that differs between the runs and
     that a test used without another visible effect would be called identical: a relaxation of rule 3, so a product
     decision.
  2. **Map the virtual pid at every boundary** (child_process arguments and command strings, `/proc/<pid>` paths,
     `os.getPriority`, the run's `vpid` table for other processes, children running detjs). ESTIMATED 1-2 days, and a
     program that sends the pid over a socket or to native code still sees a pid no process has.
  3. Leave C as it is (nestjs-pino stays at 223/269).

### E: stat/readdir events in start order — DONE
* Commits: 875e82d (test, red), ec81d74 (fix: `controls.js` installs `fsorder` and `outside` after `ioorder`;
  `fsorder.js` wraps at install time), af0397a (follow-up, after the +E round left claudekit E at 19: the concurrent
  `lstat`/`readdir` steps of Node's own recursive `fs.rm` (node:internal/fs/rimraf) were recorded in completion order;
  they are steps of the rm call, not the test's observations, and are no longer recorded — `outside.js` `rmStep`;
  only rimraf: `fs.glob`'s internal listings are what the test gets back and stay recorded).
* Test `node/test/p1-e-fs-order.test.js` 3/3: 12 batches of 128 concurrent stat/lstat and 8 of 32 readdir in start
  order (trunk: 2-6 of 12 batches out of order in 5 of 5 probe runs); a size difference between runs still diverges
  (passes on the trunk); recursive rm leaves no event inside the tree (red without af0397a).
* MEASURED: claudekit E 22 → 13 (+B round, before the follow-up) → 0 (final).

### B: files read outside any test — B1 DONE, B2 NOT IMPLEMENTED
* Commits: d989cde (test), f7ad850 (B1: `outside.js` records the open test file with each entry; the header says
  `files_outside_scope: "file"` for Jest without a custom runner and for Vitest when every file runs in a fresh
  worker; `verify.rs` `scoped_inputs` / `scoped_divergence` compare a scoped entry for that file's tests only;
  docs/VERIFY-CONTRACT.md).
* B2 (drop a read of the process's own write) is **not implemented**: the bytes a hook writes can come from a source
  nothing records outside a test (`/proc`, a real temp name), and dropping the read back would call identical two runs
  that saw different bytes (rule 3). The narrower "stat only" variant has the same hole (a directory created or not
  depending on such a value). The B2 case of the regression test asserted that behaviour; it became a B1 case.
* Tests: `node/test/p1-b-outside-scope.test.js` 4/4 (vitest, jest): a hook reads a file whose bytes differ between the
  runs (written from /proc by the hook itself, or outside the project): that file's tests diverge, the other file's
  stay stable (trunk: 0/4); Rust `p1_b1_file_read_outside_tests_scoped_to_its_test_file` (red on the trunk judge).
* MEASURED: ironcurtain run-level B 7,033 → 0 in the +B round and both final rounds (165 B-abs + 266 B-tmp scoped).
  Identical stays 0: what B hid is now counted (A 5,162, C 548, F 134, noise 754).
* Left (proposal, not done): an entry read while **no** test file is open in a worker (a step that outlived its file:
  codex-multi-auth's `accounts.json` stat, final round 1) stays run-wide. Attributing it to the last file the process
  closed and to every later file of that process would scope it (ESTIMATED 0.5 day).

### D: entropy controlled by default — DONE (founder decision option 3)
* Commits: a90cdff (test, red), 7984fe7 (fix: `session.js` `urandom` on by default, `--det-urandom=off` observes;
  HELP, banner, end-of-run note; `seeds.js` protocol nonces take their own seeded stream whatever the option;
  docs/NODE.md, docs/CLI.md).
* **Correction to the decision text**: it says protocol nonces "stay real". On the trunk they are not real bytes: a
  seeded stream of their own (`seeds.js` `nonce`, docs/NODE.md G-1421 "controlled whatever the option"); with
  `--det-urandom` on, the trunk sent them to the entropy stream instead. The branch keeps the trunk default (their own
  seeded stream) under every option. Native key generation stays real and observed.
* Tests: `node/test/p1-d-entropy-default.test.js` 6/6 (serial = parallel by default; real difference with
  `--det-urandom=off` and with another `--det-seed`: never stable).
* Follow-up found by the full Node suite (two latent `--det-urandom` defects that D made the default; both fail on the
  trunk with `--det-urandom` too):
  1. `seeds.js`: the streams start in an all-zero xoshiro state until the first test or file seeds them; a
     `randomBytes` / `randomFillSync` / `randomInt` drawn before that (a runner's or a library's start-up) returned
     zero bytes every time. Playwright builds its dispatcher GUIDs from them: two equal GUIDs, the worker exited, and
     all 4 `playwright-p041` tests failed. Such draws now stay real and observed (as with `--det-urandom=off`); once
     seeded, the stream is controlled as before. Test: `p1-d-entropy-default.test.js` 7th case (red before the fix:
     `000...0` twice).
  2. `runners/bun-runtime.js`: `Bun.password.hash/hashSync` and `Bun.CSRF.generate` (native randomness the stream
     does not reach) were flagged `entropy`, which the cache policy drops when the stream is on, so a bcrypt hash with
     a real random salt was reused (`review-r032b` B4, red). They are now flagged `keygen` ("OS randomness drawn in
     native crypto"), which no option drops, like Node's own key generation. No policy change.
* MEASURED: agentsys D 99 → 0, sqlectron D 5 → 0 (final). The crypto risk is as in DESIGN-P1.md D.2 (an IV or key a
  test draws is the same in every run of that test under `--det`), stated in HELP and docs/NODE.md.

## 4. Test changes (each on its own line, with its reason)

- `node/test/p1-f-nested-io.test.js`: the concurrency guard uses `mkdtempSync` instead of `fs.promises.mkdtemp`, so it holds on the trunk too (there an awaited `fs.promises.mkdtemp` before the reads made node:test cancel the test).
- `node/test/p1-c-virtual-pid.test.js`: corrected twice (kill check in its own case; trace copied before the parallel run, fixture variables volatile, a2 no longer reads ppid), then removed with the revert of C.
- `node/test/p1-b-outside-scope.test.js`: the B2 case (expecting a read of the process's own write to be no input) became a B1 case, because B2 would hide a real difference; the trace of each run is copied right after that run (the first version compared the parallel trace with itself).
- `node/test/p1-d-entropy-default.test.js`: the drawn values go to an output file instead of `golden()` (the engine's parallel re-run failed `golden` on the trunk before verify could show the divergence).
- `node/test/p1-e-fs-order.test.js`: third case added with the rm follow-up (af0397a).
- `node/test/network-p041.test.js` G-1426: asserted the former entropy default (observed); now asserts the decided default (controlled) and the same off / on / bare flag / invalid value cases; G-1421 kept (it caught a banner wording that contained "real OS entropy" in a controlled run, fixed in the banner, not in the test).
- `node/test/cache.test.js` "never cached: child process (git included), worker thread, loopback connection, OS entropy" (vitest, jest): both runs now pass `--det-urandom=off`. Reason: the case is about real OS entropy, which since D exists only with that option (by default the draw comes from the seeded stream and the file is reusable, as it was on the trunk with `--det-urandom`, where the cache key includes the option). Every expectation is unchanged (the entropy file still runs, `os entropy` is still the reason).
- `node/test/review-r032.test.js` N8 x 3 draws x 2 runners (node-test, mocha): both runs pass `--det-urandom=off`, for the same reason; the assertion (the file is not reused) is unchanged.
- `node/test/policy-equivalence.test.js` "real node-test / mocha sessions": the first (recording) session passes `--det-urandom=off`. Reason: the second session, `--det-urandom`, is meant to be "another configuration"; since D it was the same configuration as the first, every file was reused and the dump had too few captures. The two configurations compared are again "entropy observed" and "entropy allowed"; the assertions are unchanged.
- `tests/test_runner_node.py::test_entropy_is_named_by_verify` (shared Python test, from the trunk merge f67be4a; 4 runners): the recorded run passes `-- --det-urandom=off`. Reason: its fixture "reads real OS entropy", which since D needs that option (by default the draw is seeded and both runs are identical); the assertions (verify exits 1 and names the test NOT PROVEN or DIVERGED `entropy`) are unchanged.
- `node/test/p1-d-entropy-default.test.js`: seventh case added (a draw made before any seeding is not a constant), with the follow-up fix below.
- No test was skipped, weakened or quarantined; no CI step, timeout or threshold changed.

## 5. Test suites (branch vs trunk)

PENDING: the branch and trunk suite runs (Node full suite, cargo detpy-core + detpy-node, the 52 shared Python files) are running; this section is filled when they end.

## 6. P0 exit rule

`node/test/exit-status.test.js`, `exit-regression.test.js`, `exit-paths-p0.test.js` are unmodified on the branch
(`git diff e7338950 HEAD -- node/test/exit-*.test.js` empty) and pass (section 5).

## 7. For the coordinator

* Merge: not done by this session (coordinator's instruction). The branch contains the trunk up to f67be4a (merge
  commit e40aaf6, no conflict; f67be4a changes no engine file).
* Open decisions: C (options in section 3), B2 (not implementable without hiding a real difference), the B1
  extension for reads with no file open, A3 (`api:process.reallyExit` outside tests, codex-multi-auth), sqlectron's
  native addon outside tests (design A.4).
* The other branch (claude/det-host-values) changes the same layer (sched.js, epoch, TZ): whichever merges second
  must re-run the other's regression tests (`node/test/p1-*.test.js` here) and re-measure.
