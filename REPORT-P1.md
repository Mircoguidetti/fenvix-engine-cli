DONE

# P1: the engine's run-level false alarms (phase 2 report)

Branch `claude/p1-false-alarms`. Status per item (coordinator's approval of 2026-11-23, order F, A1, C, E, B, D;
merge ordered by the coordinator, not by this session):

| item | status | MEASURED gain (final round 1 vs before round 1) |
|---|---|---|
| F nested file operations | **DONE** | claudekit F 225 → 1, identical 555 → 790 with E; `--det` serial 21.7 / 21.1 s → 8.7 s, parallel 21.0 / 21.6 s → 9.1 s; sqlectron F 8 → 0 |
| A1 KEPT/proxy variables read outside tests | **DONE** | agentsys A 1,540 → 0, identical 0 → 1,542 (with D) |
| C virtual pid | **DONE** (second attempt, mapped at every OS boundary, 1541685) | nestjs-pino C 35 → 0, identical 223 → 257 (258); C 550 / 548 → 3 / 40 on codex-multi-auth / ironcurtain; gate: ironcurtain 226 / 407 failed as before, codex-multi-auth's gate-run excess did not reproduce in 3 + 3 repeat runs (section C) |
| E stat/readdir order | **DONE** (with a follow-up commit) | claudekit E 22 → 0 |
| B scope of files read outside tests | **DONE**: B1, and B2 narrowed by rule 3 (944e86a) | ironcurtain run-level B 7,033 → 0 (B-abs 7,033 → 165 scoped); codex-multi-auth: B2 removes its `.codex` `stat:missing` entries in every run; one run-level entry of another kind (`<tmp>/api-routes.json`, `stat:file`, read after its file closed) is left in one of the two rounds (section B) |
| D entropy controlled by default (option 3) | **DONE** | agentsys D 99 → 0, sqlectron D 5 → 0 |

**Tests that became identical: 778 → 2,555 (+1,777) in round 1, 2,550 in round 2 on the final engine 0903cf2**
(6 repositories, S1 vs P1w4, 4 workers; 2,555 / 2,551 on d9c5854, before the D follow-up). With C (1541685): **2,589 in round 1, 2,603 in round 2** (section C); final engine 944e86a (C + B2): **2,593 / 2,587** (section B). First line `DONE`: every item is implemented. Two things the coordinator should see first:
B2 is narrower than the design (rule 3, section B), and one codex-multi-auth run-level entry of another kind is left
open (a proposal in section B). Ready for the coordinator's `/review`; merge only on the founder's authorization.

**Fail-safes before the merge (founder decision D1 = C of 2026-11-24, section 3.1).** The identical counts above
were measured BEFORE the three fail-safes, on S1 vs P1w4 pairs (one worker against four). The A1 fail-safe
discharges an `env:` entry only when every compared run used one worker, and Jest is now compared run-wide
(`files_outside_scope: "run"`), so the A1 gain on agentsys (Jest; A 1,540 → 0, identical 0 → 1,542) is expected
not to hold on S1 vs P1w4 pairs. **Not re-measured**: no figure after the fail-safes is given here.

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
* Re-measurement on the final engine **0903cf2** (the D follow-up: entropy drawn before seeding, Bun password/CSRF;
  section 3 D), same loop and build steps from a worktree at 0903cf2 (`/tmp/pm-p1/wt-final4`, the addon copied:
  no Rust change since d9c5854), `--out $PM_WORK/p1-after4`, 2026-11-24. `engine_commit` in every row:
  `0903cf229418300297669137d264c1a5abe69ca1+modified`. Data: `harness/p1/after-final.json`,
  `after-final-round2.json`, `after-final-serial-pair.json`, `harness/p1/data/after-final/`. Section 2.1.

## 2. Before / after per repository

Engine d9c5854 (the final engine 0903cf2 is in section 2.1). Round 1 (round 2 in brackets), counts by `tally.py`
category:

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

### 2.1 Re-measurement on 0903cf2 (final engine)

Round 1 (round 2 in brackets), same columns; the before column is unchanged:

| repository | identical after | A | B-tmp | B-abs | C | D | E | F | noise | other |
|---|---|---|---|---|---|---|---|---|---|---|
| agentsys | **1,542** (1,538) | 0 (0) | 0 | 0 | 1 (1) | 0 (0) | 0 | 1 (1) | 327 (327) | 353 (357) |
| codex-multi-auth | 0 (0) | 4,552 (0) | 36 (8,661) | 0 | 550 (0) | 0 | 0 | 4 (0) | 3,520 (1) | 1 (1) |
| ironcurtain | 0 (0) | 5,163 (5,170) | 266 (266) | 165 (165) | 548 (548) | 4 (4) | 0 | 135 (121) | 752 (759) | 0 |
| nestjs-pino | 223 (223) | 0 | 0 | 0 | 35 (35) | 0 | 0 | 9 (9) | 2 (2) | 0 |
| claudekit | **790** (789) | 0 | 0 | 0 | 2 (2) | 0 | 0 | 1 (0) | 20 (22) | 1 (1) |
| sqlectron (sqlite3 rebuilt) | 0 (0) | 43 (43) | 0 | 0 | 0 | 0 (0) | 0 | 0 | 0 | 0 |
| **total** | **2,555** (2,550) | | | | | | | | | |

* Same as d9c5854 within one test per repository and round; the D follow-up changed no count.
* codex-multi-auth: run-level B (8,661 tests) is gone in round 1 and present in round 2 here, the opposite of
  d9c5854; the same timing-dependent `stat` (section 2, B).
* Outcomes (`outcome_counts`): identical to d9c5854 for agentsys, nestjs-pino, claudekit, sqlectron; ironcurtain
  `--det` parallel 408 / 407 failed (407 / 406 on d9c5854; serial 226 in both); codex-multi-auth `--det` serial
  411 / 429 failed, parallel 389 / 330 (400 / 438 and 428 / 368 on d9c5854; plain 6 / 6).
* Run time: round 1 ran on a loaded machine (plain, which the engine does not touch, was slower too: sqlectron plain
  5.54 → 23.76 s, claudekit 7.65 → 11.82 s); round 2 matches d9c5854: claudekit `--det` serial 9.07 s, parallel
  9.16 s; sqlectron serial 7.80 s, parallel 4.67 s. No run time is claimed from round 1.

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

### C: virtual pid, mapped at every OS boundary — DONE (second attempt, the founder's D1 = A of 2026-11-24)
* First attempt (4167c87, 4939fc1, 3ddaa2d): test code read `4194305 + digest(seed, file)`; only `process.kill` was mapped.
  MEASURED: nestjs-pino 223 → 258 identical, but ironcurtain `--det` serial 226 → 433 failed: its docker suites pass
  `process.pid` to `ps -o lstart= -p <pid>` (src/docker/docker-resource-lifecycle.ts:76) and the virtual pid did not
  exist for `ps`. Reverted (8f125d7, 94850de, d9c5854).
* Second attempt, ordered by the coordinator (founder decision D1 = A, /plan-eng-review record 477ae28 on new-brain):
  * Commits:
    * 125e757, 615088e, a8222fc: the first attempt re-applied.
    * 7cfadf6: the boundary tests. Red on ea110c8 (26 of 26).
    * 844ea5c: the mapping.
    * 1541685: the order fix (below), plus one more test case.
  * One function maps a virtual pid back to the real one: `toRealPid`, `node/src/facts.js`. Every boundary uses it:
    * `process.kill`.
    * child_process argument lists, command strings and the child's environment (spawn, exec, execFile, fork and the
      sync forms; `node/src/children.js`).
    * `/proc/<pid>` paths: fs read, stat, access, readdir, readlink, open, realpath and createReadStream, in their
      sync, callback and promise forms.
    * `os.getPriority` and `os.setPriority`.
    * The run's `<run dir>/vpid/` table, for other processes of the run (workers running detjs).
    `process.ppid` stays real. docs/NODE.md row 7f.
  * Not mapped (no_claim of the test):
    * native code given the pid;
    * the number sent over a socket, or written to a file that a process not running detjs reads (a child the test
      started: `src/runners/preload.js` leaves those alone).
* Correction (2026-11-24): commit 7cfadf6 says "red on ea110c8: 26 of 26". That check ran in a worktree without
  `node_modules`, so the fixture runs failed before any assertion. Redone with `node_modules`: all 28 cases fail on
  0903cf2 (the same node/src as ea110c8), each at `expect(process.pid > 4194304)`, because the test sees the real pid.
  All 28 pass on 1541685 and on 944e86a.
* Regression tests:
  * `node/test/p1-c-pid-boundaries.test.js`, 28/28 on 1541685, in vitest and jest. One case per boundary, among them
    the ironcurtain `ps -o lstart= -p <pid>` call.
  * Another worker of the run reaches the pid through the table.
  * Acceptance 2: a test that fails when the pid is odd, run under two seeds that give pids of different parity, is
    reported diverged or NOT PROVEN (it passed).
  * Stat identity: fstatSync, lstatSync and statSync through named bindings agree. This case was added after the
    first gate run (see below).
  * `node/test/p1-c-virtual-pid.test.js` 6/6.
  * P0 exit tests unmodified, with the above: 69/69.
* First gate run, 844ea5c (`harness/p1/data/c-gate-844ea5c/`): **failed**.
  * ironcurtain `--det` serial went from 226 / 226 to 411 / 410 failed.
  * Cause: the `/proc` fs wrappers were installed over src/fstime.js. That control keeps its Stats mapping as the
    outermost wrapper and re-wraps at each test start. A named ESM import of `lstatSync` (as in ironcurtain's
    src/docker/ca.ts) kept the retired mapping while `fstatSync` was mapped, so a directory's virtual inode differed
    between the two and the code threw "parent directory changed while it was being inspected".
  * MEASURED: test/ca.test.ts had 32 failed (2 on 0903cf2); 2 failed with the wrappers off.
  * Fixed in 1541685: the wrappers are installed below the fs controls.
* Gate run, 1541685: same loop and judge as 0903cf2, 2026-11-24 (`harness/p1/data/c-gate-1541685/`,
  `harness/p1/c-gate-1541685*.json`).
  * Failed tests, plain / `--det` serial / `--det` parallel, round 1 and round 2:
    * ironcurtain: 20 / **226** / **407**, and 20 / **226** / **407**. 0903cf2 had 20 / 226 / 408 and 20 / 226 / 407.
    * agentsys, nestjs-pino, claudekit and sqlectron: unchanged in every run.
    * codex-multi-auth: plain 6 / 6. `--det` serial 460 / 437 (0903cf2: 411 / 429). `--det` parallel 439 / 349
      (0903cf2: 389 / 330).
  * Codex-multi-auth's excess comes from 24 tests: each failed in one of the four C runs and in none of the eight
    runs without C (d9c5854, 0903cf2). 22 of them are in test/runtime-rotation-proxy.test.ts. The project does use the
    pid (`lib/rotation.ts:624`, `process.pid % 100` sets the credential offset), but a virtual pid is the same in
    every run, so a pid-caused failure would repeat.
  * Checked: 3 more full `--det` serial runs per engine, alternating, on the same machine
    (`harness/p1/data/c-codex-repeats/`).
    * Failed: 0903cf2 439 / 434 / 439; 1541685 429 / 431 / 435.
    * None of the 24 failed in any of the six runs.
    * No test failed only with C; 5 failed only without it.
  * Read as: codex-multi-auth's `--det` failure count varies by run (400-438 on the same engine before C), and the gate
    run's excess did not reproduce. MEASURED, not proven: a pid-dependent failure that occurs once in more than seven
    runs cannot be excluded.
  * P0 exit tests unmodified (no diff against e7338950), and passing.
* Identical tests on 1541685 against 0903cf2, round 1 (round 2):
  * nestjs-pino: 223 → **257** (258); C 35 → 0.
  * claudekit: 790 → 790 (789 → 792); C 2 → 0.
  * agentsys: 1,542 → 1,542 (1,538 → 1,553); C 1 → 0.
  * codex-multi-auth: 0 (0); C 550 → 3 (0 → 0); run-level B in round 2 this time.
  * ironcurtain: 0 (0); C 548 → 40 (59).
  * sqlectron: 0 (0).
  * **Total: 2,555 → 2,589 (2,550 → 2,603).**
  * ironcurtain's remaining C divergences are event-order differences (a `process.pid` read at
    src/docker-workload/process-lock.ts:110 on one side, an `fs.stat` on the other), not differing pid values.
* Wall time, round 2 (round 1 ran while the machine was loaded):
  * claudekit `--det` serial 9.07 → 8.48 s, parallel 9.16 → 9.43 s.
  * nestjs-pino serial 20.79 → 18.05 s, parallel 8.54 → 7.66 s.
  * ironcurtain serial 227.77 → 204.94 s, parallel 81.66 → 66.79 s.
  * codex-multi-auth serial 438.34 → 421.47 s, parallel 142.41 → 144.29 s.
  * Plain runs, which the engine does not touch, moved by similar amounts. No speed-up is claimed.
* **Decision (coordinator, 2026-11-24, after /plan-eng-review with the founder, D1 = A; record
  gstack/projects/Mircoguidetti-new-brain/main-eng-review-merge-gates-20261124-154500.md in new-brain): C passes its
  gate** (no test fails only with C in the 3 + 3 repeat runs; codex-multi-auth's gate-run excess did not reproduce).
  C stays on this branch.
* Rule 3 unchanged: the test sees the virtual pid and the event records it. A pid that differs between runs and
  changes the outcome is reported diverged or NOT PROVEN (acceptance 2, tested).

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

### B: files read outside any test — B1 DONE, B2 DONE (narrowed by rule 3)
* Commits: d989cde (test), f7ad850 (B1: `outside.js` records the open test file with each entry; the header says
  `files_outside_scope: "file"` for Jest without a custom runner and for Vitest when every file runs in a fresh
  worker; `verify.rs` `scoped_inputs` / `scoped_divergence` compare a scoped entry for that file's tests only;
  docs/VERIFY-CONTRACT.md).
* B2, first pass (phase 2): not implemented. A hook can write bytes from a source that nothing records outside a
  test (`/proc`, a real temp name). Dropping the read-back would then call two runs identical when they saw different
  bytes (rule 3). The B2 case of the regression test asserted that behaviour; it became a B1 case.
* **B2, second pass (coordinator 2026-11-24: "B2 as the P1 design review defined it"):** implemented in 944e86a (test
  1ecaa94, red on 1541685: 2 of 8).
  * The rule: a `stat` / `exists` / `access` answer of **`missing`**, outside any test, for a path inside a directory
    the same process created with **`mkdtemp`**, is no input. This holds only while that process has started no
    child process or worker thread since the directory was created (`src/children.js` counts them).
  * Why this keeps rule 3: the directory's name is random and nothing else can have written into it, so the answer is
    the process's own work. A path that exists in one run and is missing in the other is still an entry in one run
    only, so the entry sets differ and that file's tests diverge (acceptance 2, tested).
  * Narrower than the design, on purpose (rule 3):
    * A read-back of bytes the process wrote is not discharged: the bytes can come from a source nothing records
      outside a test (the first pass's reason).
    * A `present` / `file` answer stays an entry: the size can depend on such a source too.
    * A directory made with `mkdir` (a fixed name another process or an earlier run can know) stays an entry.
    * So does a directory a child or a worker could have written into.
  * Test: `node/test/p1-b2-own-dir.test.js`, 8/8 on 944e86a, in vitest and jest. The gain case (a run that stats such
    a path and one that does not are stable) is red on 1541685. Acceptance 2, the child-process guard and the `mkdir`
    guard pass on both.
  * B1 test 4/4, `verify-inputs-attacks` 34/34, P0 exit tests unmodified, passing.
  * docs/VERIFY-CONTRACT.md, `files_read_outside_tests`.
* Measured on 944e86a (all six repositories, 2 rounds, 2026-11-24; `harness/p1/data/b2-944e86a/`,
  `harness/p1/b2-944e86a*.json`):
  * codex-multi-auth: every `<tmp>/.codex/...` `stat:missing` entry is gone from all four traces, unscoped and scoped.
    Before, these were the run-level entries.
  * codex-multi-auth round 1 still diverged run-wide (8,662), because of one entry of another kind:
    `<tmp>/api-routes.json` = `stat:file size=274`. It is recorded in the parallel run only, while no test file was
    open: a step that outlived its file. It is not B2's case (the file exists), and the size can depend on what was
    written. Round 2: no run-level entry. Identical stays 0 in both rounds; what B hid is now counted (A 6,818,
    codex-multi-auth's `env:*` digests, A1 section).
  * **Decision (coordinator, 2026-11-24, /plan-eng-review with the founder, new-brain
    gstack/projects/Mircoguidetti-new-brain/main-eng-review-p1-phase2-20261124-164500.md): D1 = A, B2 as narrowed
    here (rule 3) is accepted; D2 = A, the B1 scope proposal below is not in this merge: a separate small branch after
    the merge queue.**
  * Still open (proposal, ESTIMATED 0.5 day, not done; it changes B1's scope rule, so it is the coordinator's call):
    scope an entry read while no file is open in a worker to the last file that process closed and every later file
    of that process.
  * Other repositories: B unchanged (ironcurtain run-level 0, B-abs 151 / B-tmp 268 scoped).
  * Identical, round 1 (round 2), 944e86a against 1541685: agentsys 1,542 (1,538 against 1,553); claudekit 793 (792);
    nestjs-pino 258 (257); 0 elsewhere. **Total 2,593 (2,587)**, against 2,589 (2,603) on 1541685. Within each repo's
    round-to-round spread; B2 changes no count measured here.
  * Failed tests:
    * ironcurtain: 226 / 407 and 226 / 408 (0903cf2: 226 / 408, 226 / 407).
    * agentsys, nestjs-pino, claudekit, sqlectron: unchanged.
    * codex-multi-auth `--det`: serial 439 / 489, parallel 464 / 372. Every failing test in these four runs failed
      in at least one of the 22 earlier runs of this project (with and without C). No new failure, but the count
      spread is wide (serial 400-489).
  * Wall time, round 2: no change beyond the spread of the plain runs.
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

### 3.1 Fail-safes for the three remaining rule-3 risks (founder decision D1 = C, 2026-11-24)

Ordered by the coordinator after the founder's `/plan-eng-review` of the P1 merge
(new-brain `gstack/projects/Mircoguidetti-new-brain/main-eng-review-p1-merge-20261124-215500.md`): make each risk
fail safe now; the exact fixes go to a follow-up branch after the merge queue. Each has a test that fails on 0358ea4
and passes after (red logs `/tmp/pm-p1/failsafe/a1-red.log`, `b1-red.log`, `f-red.log`).

| risk | fail-safe | test (red on 0358ea4) |
|---|---|---|
| A1: a run's `env:<NAME>=<digest>` entries are one set; with several workers they do not say which worker saw which value | **replaced 2026-11-25 by the exact fix (section 3.2)**; the one-worker fail-safe (ce9e51c) is gone | see section 3.2 |
| B1 on Jest: its worker process keeps state across files that is not tracked per file | `src/jest/cli.js`: `files_outside_scope: "run"` always | `node/test/p1-b-outside-scope.test.js`, jest: header `"run"`, the other file's tests not stable |
| F: the test's own code run inside a file operation (`fs.cp` filter, the iterable `fs.promises.writeFile` / `appendFile` draws from) was a step of that operation, its I/O hidden | `src/ioorder.js`: that code runs in a user scope; a file operation it starts marks the test `uncontrolled.io` (NOT PROVEN) | `node/test/p1-f-nested-io.test.js`, 4 "fail-safe" cases (promise and callback `cp` filter, `writeFile` and `appendFile` from an async iterable); 2 no-false-alarm cases (a filter / iterable without I/O) |

Green on ce9e51c (`/tmp/pm-p1/failsafe/`): cargo `-p detpy-core -p detpy-node` 0 failed (core 202 passed); every
`node/test/p1-*.test.js` plus the three P0 exit tests (unmodified vs 9ac63d6) **120 tests, 120 pass**; shared Python
tests 3 failed, 1,019 passed, 39 skipped: the same 3 as trunk 9ac63d6 (section 5.1). The Vitest header test below
passes on 0358ea4 by design; a mutation (`isolatedFiles` always true) makes its `isolate: false` and `singleFork`
cases fail (`/tmp/pm-p1/mut/mut.log`).

Shell-level test added (it was missing): `node/test/p1-b-outside-scope.test.js`, Vitest default writes
`files_outside_scope: "file"`, `isolate: false` and `poolOptions.forks.singleFork` write `"run"`.
Not covered by the F fail-safe: a Readable stream passed as the data (Node's stream code reads it), `fs.cpSync`.

### 3.2 A1 exact fix: values compared per file (founder decision D2 = A, 2026-11-25)

Replaces the A1 fail-safe of section 3.1 (the B1 Jest and F fail-safes are unchanged). The Node shell writes an
outside-test env read made while a test file's code ran (module scope, hooks) as `env:<NAME>=<digest>@<file>`
(`src/controls.js` `noteOutside`, the file label with its project); a read while no file is open keeps
`env:<NAME>=<digest>`. `verify.rs` `undischarged_outside` compares, per variable, the map file → set of digests: the
entry is discharged only when the maps are equal in every run (at least two runs, every entry with a digest), whatever
the worker counts; the no-file key is discharged only with one value in every run.

| test | what | red on |
|---|---|---|
| `verify.rs` `p1_a1_env_outside_compared_per_file` | swapped per-file values not discharged; equal per-file values discharged one worker vs four; a file in one run only, per-file vs no-file, several no-file values, a different value, a credential entry: kept | 1ae9265 (the serial-vs-parallel case) |
| `node/test/p1-a-env-outside.test.js` "values swap between the runs" (vitest, jest) | each file sets TMPDIR from its lane and reads it at module scope; two two-worker runs replay plans with the lanes swapped (`--det-plan`): the run-wide sets are equal, every test must be `not-proven` naming `env:TMPDIR` | **0358ea4** (both tests called `stable`, `/tmp/pm-p1/failsafe/a1-swap-red-0358.log`); on 1ae9265 the one-worker fail-safe already kept these two-worker runs |
| `node/test/p1-a-env-outside.test.js` first case (vitest, jest) | equal values per file, one-worker vs two-worker: all stable, the entry carries `@<file>` | 1ae9265 (`/tmp/pm-p1/failsafe/a1x-red.log`) |

Not covered: which test inside one file saw which value (a file's tests are one unit); a pseudo-file label that
depends on the lane (`<worker>…` of a worker thread, Playwright's `playwright-worker-N`) makes per-file keys differ
between serial and parallel runs, so such entries stay NOT PROVEN (fail-safe direction).

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
- Six P1 test files (`p1-a-env-outside`, `p1-b-outside-scope`, `p1-b2-own-dir`, `p1-c-pid-boundaries`, `p1-c-virtual-pid`, `p1-d-entropy-default`): their two-run cases add `--det-epoch=fixed` when a `--det` run names no epoch. Reason: the merge of release-1 9ac63d6 (det-host-values) gives each run the host epoch, so two separate runs differ on the clock input; `--det-epoch=fixed` is the documented opt-out the trunk's own two-run tests use. The assertions are unchanged.
- `node/test/p1-a-env-outside.test.js` first case: changed twice. The fail-safe (ce9e51c) made it expect one-worker vs two-worker `not-proven`; the exact fix (section 3.2) restores the original expectation (one-worker vs two-worker, all stable) and adds that the entry carries its file (`@tests/a...`). Net against 0358ea4: the same expectation plus one assertion.
- `verify.rs` `p1_a1_env_read_outside_tests_compared_by_value`, "several values in one run": the equal-set case now uses entries with a file (`@a.js`). Reason: several values read while no file was open are now kept (section 3.2: they cannot be tied to the tests that saw them); the same case inside one file is still discharged. The one-worker header the fail-safe added to this test is removed.
- `verify.rs` `p1_a1_discharged_only_when_every_run_used_one_worker` (the fail-safe's test) is replaced by `p1_a1_env_outside_compared_per_file`.
- `node/test/p1-b-outside-scope.test.js` both B1 cases: on Jest the other file's tests were expected stable; they are now expected not stable, and the header `"run"`. Reason: the B1 Jest fail-safe (section 3.1); Vitest expectations unchanged.
- No test was skipped, weakened or quarantined; no CI step, timeout or threshold changed.

## 5. Test suites (branch vs trunk)

Same machine, one suite at a time. Trunk = e7338950 for Node (`/tmp/pm-p1/trunk-npm-test.log`), f67be4a for cargo
and Python (worktree `/tmp/pm-p1/trunk2`, trunk wheel); branch = this branch (logs `/tmp/pm-p1/branch-*.log`).

**cargo test -p detpy-core -p detpy-node**: trunk 194 + 10 passed, 0 failed; branch 196 + 10 passed, 0 failed (the
two new verify.rs tests of A1 and B1).

**Node full suite (`cd node && npm test`)**: trunk 975 tests, 967 pass, 4 fail, 3 cancelled, 1 skipped. The first
branch run (commit e40aaf6 + the uncommitted report) had 998 tests, 976 pass, **18 fail**, 3 cancelled, 1 skipped.
Every failure, and what it was:

| failing on the branch | also on the trunk? | cause / action |
|---|---|---|
| jest: parallel lanes (3 cancelled subtests) | yes | pre-existing |
| repro options (vitest) `--det-order` across describe blocks | yes | pre-existing |
| bun: Level 0 controls, "two --det runs give identical fingerprints" | yes (same subtest) | pre-existing |
| node-test: adversarial, "a file another test file wrote: not cacheable" | yes (same subtest) | pre-existing |
| detjs playwright (4 subtests) | no | **D**: zero bytes before seeding (section 3 D, follow-up 1); fixed in 0903cf2 |
| bun: R-032b specific, B4 `Bun.password.hashSync` reused | no | **D**: native randomness flagged `entropy` (follow-up 2); fixed in 0903cf2 |
| cache with proof (vitest, jest): "never cached ... OS entropy" | no | **D** default: the test's real-entropy case now asks for `--det-urandom=off` (section 4) |
| node-test / mocha: environment read in C, entropy (N8 x 3 each) | no | same (section 4) |
| real node-test / mocha sessions: the Rust policy equals the JavaScript one | no | same (section 4) |

After 0903cf2, the 19 test files concerned (every P1 test, the three P0 exit tests, playwright, review-r032/r032b,
policy-equivalence, cache, network, unchanged, verifier attacks, and every file that draws entropy) were re-run:
**290 tests, 290 pass** (`/tmp/pm-p1/targeted.log`). The full Node suite was not re-run after 0903cf2 (about an hour);
the coordinator's `/review` CI run covers it.

**Python shared tests (53 files, `release/shard.py ... --only shared`)**: trunk 3 failed, 950 passed, 39 skipped:
`test_packaging::test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs`,
`test_py_cache::test_the_virtual_clocks_own_probe_of_threads_is_not_the_tests_read`,
`test_py_cache::test_g2214_a_test_that_crashes_its_worker_is_a_record_of_the_merged_trace`. Branch (run started
before 0903cf2) 11 failed, 942 passed, 39 skipped: the same 3, plus 4 Playwright cases of `test_fenvix_js.py` (the
zero-bytes defect, fixed in 0903cf2: re-run **5 passed**, `/tmp/pm-p1/py-pw.log`) and
`test_runner_node.py::test_entropy_is_named_by_verify` x 4 runners (D default; the test now asks for real entropy,
section 4; re-run **4 passed**).

**CI (LIGHT)**: run 45227028354 on 7984fe7 failed attacks, python shard 0, node shard 0, the same jobs as the trunk
base e7338950 (run 45165824244); trunk f67be4a (run 45186293624) failed attacks, python 3, node 0. Not re-run on the
final commit by this session.

### 5.1 After the merge of release-1 9ac63d6: final head 0358ea4 vs trunk 9ac63d6

Same machine, one after the other (2026-11-24, 18:25 to 21:44 UTC), with the same script for both heads (`/tmp/pm-p1/suites.sh`: cargo, `cd node && npm test`, the shared Python tests, `tests/attacks.py`; logs `/tmp/pm-p1/suite-final/` and `/tmp/pm-p1/suite-trunk9/`). The Python run deselects `tests/test_review_r017.py::test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does` on both heads, as the repository's CI does (`.github/workflows/release-1.yml:147`).

| suite | final 0358ea4 | trunk 9ac63d6 | failing only on final |
|---|---|---|---|
| cargo (detpy-core, detpy-node) | 0 failed (core 201 passed) | 0 failed (core 199 passed) | none |
| Node `npm test` | 1,095 tests, 1,086 pass, 5 fail, 3 cancelled, 1 skipped | 1,021 tests, 1,012 pass, 5 fail, 3 cancelled, 1 skipped | none (identical failing names) |
| Python shared | 3 failed, 1,019 passed, 39 skipped | 3 failed, 1,019 passed, 39 skipped | none (identical) |
| attacks: node | 60 / 60 pass | 60 / 60 pass | none |
| attacks: python | 12 failed, 157 passed, 2 skipped | 12 failed, 157 passed, 2 skipped | none (identical: 12 `test_review_r056_pycache` cases) |

Node failures on both heads: (b) timers; jest parallel lanes (3 cancelled); repro `--det-order`; bun "two --det runs"; node-test adversarial #7; `customer-nodetest` "a flaky (order-dependent) test becomes a defect", which in this script fails on both heads with `No module named 'detpy'` because `npm test` runs before the venv is on PATH (a script artifact, not an engine result). Python shared failures on both heads: `test_packaging` gate, `test_py_cache` virtual-clock thread probe and g2214.

## 6. P0 exit rule

`node/test/exit-status.test.js`, `exit-regression.test.js`, `exit-paths-p0.test.js` are unmodified on the branch
(`git diff e7338950 HEAD -- node/test/exit-*.test.js` empty) and pass (section 5).

## 7. For the coordinator

* Fail-safes of 2026-11-24 (section 3.1) are in; the exact fixes (per-worker A1 comparison, per-file Jest state,
  tracking the I/O of the test's own callbacks inside an operation) are for a follow-up branch after the merge queue.
  The 5 gate-edit hunks stay under decision D option 3.
* Merge: not done by this session (coordinator's instruction). The branch contains the trunk up to f67be4a (merge
  commit e40aaf6, no conflict; f67be4a changes no engine file).
* Open decisions: C (options in section 3), B2 (not implementable without hiding a real difference), the B1
  extension for reads with no file open, A3 (`api:process.reallyExit` outside tests, codex-multi-auth), sqlectron's
  native addon outside tests (design A.4).
* The other branch (claude/det-host-values) changes the same layer (sched.js, epoch, TZ): whichever merges second
  must re-run the other's regression tests (`node/test/p1-*.test.js` here) and re-measure.
