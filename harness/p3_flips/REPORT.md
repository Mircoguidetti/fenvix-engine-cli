# P3: outcome flips under `--det` alone, fixes and measurements (2026-11-27)

Spec: "P3, classify and remove the outcome flips under `--det` alone (codex-multi-auth, ironcurtain; agentic-qe
status)", rev 5. Branch `claude/p3-flips`. Steps A (re-measure) and B (classify, `CLASSIFY.md`, `rows.jsonl`, cae15081)
are done; this report covers step C (the ARTIFACT engine causes, fixed test-first by founder decision) and the
measurements behind each fix. Step D (re-measure the flip lists on the final engine, the 69 codex-multi-auth + 17
ironcurtain mapping, suites base vs head, BASELINE.md) is **not done yet**; see the last section.

Standing lines of the spec:
- S4: merge-gates AC2 (<= 60) is superseded by UNDECIDED = 0.
- S5: parallel proof on these repositories is out of P3.
- Pid-token change (b), 7d17d725, approved (D1 = A); its no_claim: a pid glued to text and read as a real process
  reference stays virtual, and that fails loud.

## 1. What was fixed (each test-first; founder decision in brackets)

| shape | cause | tests (red first) | fix | decision |
|---|---|---|---|---|
| `vi.waitFor` / `expect.poll` next to a long test timer | the runner's safe timers a test starts were not pending work: virtual time jumped to the long timer past the 5 s deadline | 4130fae6 (`p3-timers-safe-poll.test.js`), 7e0bd791 | e93dbc84, 27260389 | P1, A (2026-11-26) |
| a `Date.now()` poll loop for a file a detached helper writes (test (b)) | a test holds no handle to a process a child left behind: nothing pending, the loop runs out in virtual time | test (b) `host-values-timers.test.js`; 595ef344, 92d3b682 (`p3-timers-child.test.js`) | b6ec7638, 881e56b6 | P2, D1 = A (2026-11-27) |
| alakajam: node-sqlite3 queries under a 5 s suite timeout, tarn's 60 s acquire timeout pending | node-sqlite3 runs queries on the thread pool and leaves no active resource: nothing pending, virtual jump to the 60 s timer; SQLITE_BUSY follows a timed-out test whose write still holds the lock | be2c9166, 9a9a2680, 92d3b682, 59cfdd43 (`native-work.test.js`) | d9d46c42, 881e56b6, b4d87b1e | D2 = A (2026-11-27) |

Rules as built:
- P1 (`src/deadline.js` `installVitest`, `src/clock.js`): a Vitest safe `setTimeout` / `setInterval` a test starts
  that is not a runner deadline counts as pending until it runs or is cleared; dropped at test end.
- P2 (`src/clock.js` `childPaced`, `src/children.js` `noteChildStart`): after a test started a child process or a
  worker (spawn / exec / fork, their Sync forms, Worker), its timers of up to 1000 ms run at real pace;
  `DETJS_CHILD_PACE_MS` overrides the bound, `0` turns it off. Longer timers and other tests stay virtual.
- Native work (`src/sched.js` `NATIVE_WORK`): node-sqlite3's callback calls (Database close / exec / wait /
  loadExtension, Statement bind / get / run / all / each / reset / finalize, Backup step / finish) count as pending
  until their callback runs (`each`: its completion callback, an added one when it has only a row callback, or its
  row callback called with an error); a statement whose constructor or prepare callback gets an error is not counted
  from then on; a call still in flight when the test that started it ends keeps counting for up to 3 s of real time,
  then stops (a call that never calls back, started by a test, a hook or module scope, costs at most that) and the
  running test is reported as reading the real clock (not reused by the cache). A timer fired at real pace because a
  runner poll (P1) or a child-starting test (P2) keeps the driver slow is recorded as a choice real time made.

Test (b) passes from b6ec7638 on (CHANGELOG "Fixed"; harness/det_host_values/REPORT.md section 8).

## 2. Measurements

All on this machine; the six repositories with the same `measure.py` call as `harness/det_host_values/proof_run.sh`
(engine selected with `FENVIX_ENGINE`); bounds: wall par branch/trunk <= 1.10, identical drop <= 0.5% of tests.

### P1: six repositories, 3 reps, head cae15081 vs e93dbc84

| repository | identical head / P1 | allowed drop | wall P1/head | exits |
|---|---|---|---|---|
| nestjs-pino | 258 / 257 | 1.3 | 0.945 | 0 -> 0 |
| agentsys | 1542 / 1542 | 11.1 | 1.061 | 1 -> 1 |
| claudekit | 792 / 790 | 4.1 | 0.973 | 0 -> 0 |
| sqlectron | 14 / 14 | 0.1 | 0.949 | 1 -> 1 |
| ironcurtain | 0 / 0 | 35.2 | 0.988 | 1 -> 1 |
| codex-multi-auth | 0 / 0 | 43.3 | 1.019 | 1 -> 1 |

### P2 and native work: six repositories against bb41d043 (P1 + release-1 519bf1a0)

| repository | b6ec7638, 1 rep: identical / wall | 881e56b6: identical / wall (reps) |
|---|---|---|
| nestjs-pino | 258 / 258, 1.018 | 258 / 258, 1.010 (1) |
| agentsys | 1552 / 1552, 1.023 | 1552 / 1552, 0.946 (1) |
| claudekit | 793 / 792, 0.977 (3 reps: 793 / 793, 1.038) | 791 / 790, 0.992 (1) |
| sqlectron | 14 / 14, 0.995 | 14 / 14, 0.968 (1) |
| ironcurtain | 0 / 0, 0.966 | 0 / 0, 0.957 (1) |
| codex-multi-auth | 0 / 0, 1.107 (missed at 1 rep) | 0 / 0, 1.038 (3) |

All bounds met on 881e56b6; exits unchanged everywhere. b4d87b1e changes only the native-work release timing, which
runs only where node-sqlite3 is loaded; none of the six has it installed (NATIVE.md), so it was not re-measured there.
The 1-rep codex-multi-auth reading on b6ec7638 (1.107) was replaced by the 3-rep reading on 881e56b6 (1.038). The
P2 prototype (same rule, not yet per-test) read 0.951 / 1.005 / 1.101 (3 reps: 1.064) / 0.981 / 0.608 / 1.009.

### Cases cleared at L1 (timers real) by each fix, 2 `--det` runs each

Sets of step B's L1 rows (`rows.jsonl`) and P3b's alakajam / drydock rows (claude/p3b-engine-only @ 7f94795, read
only), each set's plain `--det` command. A case clears when both runs give its plain outcome.

| repository | L1 cases | cleared on cae15081 | cleared by P1 (e93dbc84) | of P1's rest, cleared by the P2 prototype |
|---|---|---|---|---|
| ironcurtain | 13 | 0 | 9 | 2 / 4 |
| codex-multi-auth | 37 | 1 | 23 | 12 / 14 |
| agentic-qe | 41 | 1 | 18 | 7 / 23 |
| drydock (P3b) | 75 | 0 | 47 | 0 / 28 |
| alakajam (P3b) | 114 | 0 | 1 | not run (see below) |

No case P1 cleared was lost by the P2 prototype. The L1 sets were not re-run on the final engine.

The 6 cases whose outcome changed under P1, plus one codex case that went p/p -> f/f between prototype and commit,
3 runs each on head and P1: all unstable or failing on both engines, none passing steadily on head and failing
steadily on P1. agentic-qe "should pass null feedback" fails with "Hook timed out in 15000ms" (the time cause L4).

### alakajam, whole suite (221 tests), plain once and `--det` twice per engine

| engine | result | "timed out" failures | SQLITE_BUSY failures | wall |
|---|---|---|---|---|
| plain | 217 passed, 4 skipped | 0 | 0 | 32.7 s |
| b6ec7638 (before) | 114 / 113 failed | 105 / 109 | 9 / 4 | 79.1 / 66.1 s |
| b4d87b1e (after) | 217 passed, 4 skipped (both runs) | 0 / 0 | 0 / 0 | 69.8 / 67.0 s |

881e56b6 left one alakajam test failing in both runs (tournament.service "should return nothing for events that are
not tournaments", timed out): it released a test's calls at its own end while the next test waited for the pool's
connection the previous query still held. b4d87b1e (red test 59cfdd43) fixes it.

## 3. Reviews

- /review of P1 (cae15081..e93dbc84): 0 critical, 8 informational; items 3-7 fixed in 7e0bd791 / 27260389; open as
  known slowdowns (no outcome change): runner safe timers never cleared (waitUntil's failure path, settle grace) keep
  a test at real pace until they fire; one global safe-timer set slows concurrent siblings.
- /review of P2 and native work (bb41d043..ecc7864e): two pending-work leaks (each() with only a row callback and no
  rows; a statement failing in its constructor on a closed database) and an over-broad 'error'-event release, fixed
  test-first in 92d3b682 / 881e56b6 with per-test child pacing and `DETJS_CHILD_PACE_MS=0`. Open: synchronous spawns
  also start pacing (by design: test (b) launches its helper with spawnSync); the Database open is not counted; an
  addon loaded before the engine's hooks is only partly tracked; two advisory extractions (trackOwned / trackWork, the
  two `Module._load` hooks).

## 4. Known defects and not done

- Other thread-pool addons: hnswlib-node and sharp have the same blind spot, not counted (NATIVE.md).
- Timer-caused flips where no fixed shape applies: drydock's 28 L1 cases left by P1 (15 hook 10 s, 10 test 5 s
  timeouts, 3 assertions) are not cleared by P2; agentic-qe's hook timeouts (15 s) follow the time cause (L4).
- Step C's time cause (L4) with the five P3b checks, and step D (re-measure the flip lists on the final engine, the
  69 + 17 mapping, suites base vs head, BASELINE.md, gstack /review of the whole branch) are not done.
