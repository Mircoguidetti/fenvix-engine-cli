NOT DONE

# Engine: `--det` uses the machine's values by default (det-host-values)

Branch `claude/det-host-values` from `origin/claude/release-1` @ f67be4a3, `origin/claude/det-pins` merged first
(harness only). Not merged into the trunk (rule 5). Measured 2026-11-23 in this session's container (`nproc` 4);
`$PM_WORK=/tmp/pm-hv`, repositories at their `specs.json` commits (setup: `harness/p1/setup.sh` of
`origin/claude/p1-false-alarms`, plus `npm rebuild sqlite3` for sqlectron). Trunk engine: a separate checkout of
f67be4a3 at `/tmp/fenvix-trunk`, built there (`npm ci && npm run build`), with this branch's `harness/parallel_measure`
checked out over it (RERUN.md section 1, "+modified").

## Verdict per acceptance criterion

| AC | verdict | in one line |
|---|---|---|
| 1 | **partly**: (a) (c) (d) (e) and the deadline test met; (b) NOT DONE | (a)(c)(d)(e) fail on the trunk engine and pass on the branch; `deadline-initializer.test.js` fails on b0a4025 and passes with the approved fix; (b) fails on both (its shapes are out of `sched.js`'s reach, section 2) |
| 2 | **NOT DONE** | ironcurtain 206 -> 17 (<= 20, met); codex-multi-auth 362 -> 422 before the `deadline.js` fix, **69** after it (<= 60, missed by 9) |
| 3 | **NOT DONE (one bound)** | identical counts within 0.5% on all six; exits unchanged; wall time <= 1.10x on five, agentsys 1.110 (23.54 s vs 21.20 s) |
| 4 | **met, with the listed opt-outs** | `npm test`: the branch fails the trunk's failing groups plus (b); shared Python tests: the same 12 failures as the trunk; LIGHT CI: see section 5 |
| 5 | **met** | `node/src node/bin crates`: only allowed files; outside them `python/detpy/fenvix_js.py` (reason below) |

Timers: by the spec's stop rule the diagnosis stopped the `sched.js` work (0 of 48 sampled flips cleared without it;
the causes are outside `sched.js`'s view). The decisive cause was in `node/src/deadline.js`, which spec line 71
forbade; **the coordinator approved the one-line `INITIALIZER` fix on 2026-11-23 (D1 = A)**, now committed with its
regression test (a8e3f85): **38 of 48** sampled flips clear (bound 35: met) and the whole codex-multi-auth list drops
from 422 to **69** flips (bound 60: missed by 9). Timers stay virtual; `sched.js`, `clock.js`, `deadline-preload.js`
unchanged.

## 1. Regression tests (commit fa8e845, before any fix)

`node/test/host-values.test.js` ((a), (c), (d), (e)) and `node/test/host-values-timers.test.js` + fixture
`node/test/fixtures/timers-waiting/` ((b)). Self-contained (fixtures under `node/test/.tmp`, local servers, no
internet), so P1 can re-run them after a rebase.

| test | protects | fails_when | trunk engine (f67be4a3) | branch |
|---|---|---|---|---|
| (a) clock + certificate | host clock by default; a certificate made in a test validates | default epoch 2025-01-01 | FAILED: `Date.now() 2025-01-01T00:00:00.000Z vs real 2026-11-23T15:00:38Z`; with only the new `selfcert` validity argument applied to the trunk: `certificate has expired` | passed |
| (b) timers waiting on real work | a test waiting on something real is not timed out by virtual time | the driver fast-forwards to the runner deadline | FAILED (`Test timed out in 5000ms`; `ENOENT ... marker.txt`) | **FAILED** (NOT DONE) |
| (c) network policy | open by default (`<host>:<port> allowed`), `--det-net=closed` refuses | an external host is refused by default | FAILED (`network access to api.external.example:39243 blocked`; `--det-net` unknown) | passed |
| (d) cache with an open network | a test that used an external host is never reused; `*_PROXY` are run inputs | a live-network test is reused | FAILED (connection refused; proxy variables not inputs) | passed |
| (e) one epoch per run | parallel lanes, the re-run's passes 1 and 2, `--det-isolate` sessions, `--det-compare/--det-plan=T` share one start time; `meta.epoch` (ISO) | two sessions of one run see different start times | FAILED (`meta.epoch` absent) | passed |

no_claim: (c) and (d) use a local server standing in for an external host (a `lookup` hook resolves
`api.external.example` to 127.0.0.1). (b)'s fixture does not reproduce the Vitest 5.0.5 cascade (the engine's own
Vitest is 5.1.0, where the frame name differs); that cause is checked on the real file (section 2).

Commands and results:
- `cd node && node --test --test-concurrency=1 test/host-values.test.js` on the unmodified engine: `# pass 0 # fail 8`,
  exit 1 (`logs/tests-a-c-d-e.trunk.log`); on the branch: all 8 pass (`logs/npmtest.branch.log`, ok 69-72).
- `node --test test/host-values-timers.test.js`, unmodified engine: `# fail 1` (`logs/test-b.trunk.log`); branch:
  fails the same way (`logs/npmtest.branch.log`, not ok 68).
- Trunk + only the branch's `selfcert.js` (temporary, reverted):
  `node --test --test-name-pattern="certificate valid" test/host-values.test.js` -> `error: 'certificate has expired'`,
  `# fail 1` (`logs/test-a.trunk-plus-selfcert-only.log`).
- Test (d) deviation from the spec wording: the receipts are written by the Rust core (`native.receiptLines`, crates
  untouched) and carry only the reuse decision; the test checks that the second run's receipt says re-run and that
  the reason (`api.external.example:<port> (external host, open network)`) is in the run's `cache-summary.json`
  `not_cached_detail` (commit 209aa1a).

## 2. Timer diagnosis (codex-multi-auth b9886168)

Three sampled flips, traced with the trunk engine (`--det-trace`, events of the failing test) and instrumented
library code (`process.stderr` probes, reverted with `git checkout -- .`):

1. **`test/api-model-runtime.test.ts:320` "does not hold native model discovery open..."** (first failure of the file;
   the sampled 401/403 flip runs later in the same file). Events: `setTimeout schedule:15000000000` (the code under
   test's `AbortSignal.timeout(15000)` on a mocked fetch), then `runner.timeout virtual:5000`. The probes show the
   library returns; the test then waits in `vi.waitFor(...)`, whose polling runs on Vitest's own real timers (safe
   timers, not virtual, not I/O). Nothing is pending for `sched.js`, so the driver fires the next virtual event; the
   5000 ms deadline is due before the 15 s timer and fires at once (16 ms real).
2. **The cascade (most of the file's and the repository's flips)**: every later test of the file fails "Test timed
   out in 5000ms" within 1-9 ms and with no `runner.timeout` event. Reproduced in three lines inside the repository
   (Vitest 5.0.5): a test that waits 6 s of virtual time with a 20 s timeout, then a trivial test -> the trivial test
   fails "timed out in 5000ms" after 3 ms. Not reproduced with the engine's Vitest 5.1.0. Cause, from the deadline
   hook's own frames (temporary probe in `deadline.js`, reverted): Vitest 5.0.5's `TaskDeadline` reads its start time
   from a frame named `TaskDeadline.<instance_members_initializer>`; `deadline.js`'s `INITIALIZER` regex
   (`/^\s*at <instance_members_initializer>/`) does not match it, so the start time comes from the real clock while
   `exceeded()` reads the deadline clock (all virtual time charged in the file). Once a file has charged more than
   5 s of virtual time, every later test "exceeds" its deadline immediately. `app-bind.test.ts` shows the same shape
   (tests 39-76 fail after tests 37-38 charged 2.7 s and 9.0 s).
3. **`test/codex-bin-wrapper.test.ts:1744` "forwards an explicit loopback upstream..."**: `spawnSync` starts the
   wrapper, which leaves a detached helper; the test polls a marker file with `setTimeout(20)` (`waitForFileText`).
   Events: 250 x `setTimeout schedule:20000000 / fire`, then `runner.timeout virtual:5000`. The test process holds no
   handle to the helper (a grandchild), so nothing is pending.

None of these is the "handles opened at module level / beforeAll" shape: `sched.js` cannot observe a runner's real
polling timers, a detached grandchild or a frame-name mismatch in `deadline.js`. By the spec's stop rule the timer
part stops here; `sched.js` and `clock.js` are unchanged.

Count (spec procedure): `cp harness/det_pins/data/codex-multi-auth/flips.json /tmp/pm-hv/timers/codex-multi-auth/`,
`PM_WORK=/tmp/pm-hv python3 harness/det_pins/pins.py variants --repo codex-multi-auth --variants V0 --out
/tmp/pm-hv/timers` (exit 0, `logs/timers-variants.log`; the same 50-test sample as the trunk's),
`python3 harness/det_host_values/timers.py /tmp/pm-hv/timers` -> **0 of 48 cleared** (39 still `Test timed out in
5000ms`; `timers.out.md`, raw outcomes `data/timers/`).

First, as an experiment in a separate worktree (`data/timers-deadline-experiment/deadline-initializer.patch`):
`INITIALIZER` widened to `/^\s*at (?:[\w$.]+\.)?<instance_members_initializer>/` gave 38 of 48 at V0 and 68 flips on
the whole list (`data/timers-deadline-experiment/`, `data/find-deadline-experiment/`).

**Approved fix (coordinator decision 2026-11-23, D1 = A; a deviation from spec line 71, which forbade `deadline.js`):**
only that `INITIALIZER` line, nothing else in `deadline.js` or `deadline-preload.js`.
- Regression test first (3b777ef): `node/test/deadline-initializer.test.js` feeds the hook stack strings through
  `Error.prepareStackTrace` in a child process with the preload's box, the virtual clock and a running test:
  `at <instance_members_initializer>` + a Vitest runner frame -> a number; `at TaskDeadline.<instance_members_initializer>`
  + a Vitest runner frame -> a number; no Vitest frame -> `undefined`. On b0a4025: `# pass 1 # fail 1` (the qualified
  case returned undefined; `logs/test-deadline-initializer.before-fix.log`); with the fix (a8e3f85): `# pass 2 # fail
  0` (`logs/test-deadline-initializer.after-fix.log`). The runner-deadline tests (G-0144 / J15) still pass with it:
  `node --test --test-concurrency=1 test/time-p041.test.js test/regressions.test.js test/controls.test.js
  test/deadline-initializer.test.js` -> `# tests 52 # pass 52 # fail 0`, exit 0 (`logs/deadline-suite.after-fix.log`).
- The three-line Vitest 5.0.5 cascade as a fixture: **not added**. Vitest 5.0.5 installs from the package registry
  (`npm install --legacy-peer-deps`; a plain install fails in npm's peer-set resolution, `Cannot read properties of
  null (reading 'edgesOut')`), but in a fresh project the same `vitest/dist/chunks/run.BPv-BBRv.js` gives the plain
  frame name and the cascade does not reproduce (`Tests 2 passed` before the fix); the same file inside
  codex-multi-auth's tree fails (`1 failed`). What gives V8 the qualified name there was not identified; the real
  file stays the check (below).
- Re-run, same procedure as above, engine a8e3f853 (`PM_WORK=/tmp/pm-hv python3 harness/det_pins/pins.py variants
  --repo codex-multi-auth --variants V0 --out /tmp/pm-hv/timers2`, exit 0; `python3 harness/det_host_values/timers.py
  /tmp/pm-hv/timers2`): **38 of 48 cleared, bound 35: met** (`data/timers-after-deadline-fix/out.md`).
- Whole list (`PM_WORK=/tmp/pm-hv python3 harness/det_pins/pins.py find --repo codex-multi-auth --out
  /tmp/pm-hv/find2`, exit 0; `flips.py`): **69 flips, bound 60: missed** (trunk 362; branch before the fix 422;
  `flips.after-deadline-fix.out.md`, `data/find-after-deadline-fix/`). By first failure line: 30 `Test timed out in
  5000ms`, 9 ledger-snapshot `toMatchObject`, 6 `Storage is busy with another live ...`, 3 property-test pre-condition
  failures, 21 single assertions (helper metadata, account order, API capability resets ...); by file:
  codex-bin-wrapper 19, runtime-rotation-proxy 18, crash-mid-write 6, persisted-api-capabilities 4,
  runtime-policy-cache 4, others <= 3. Failed in one `--det` run only: 7.
- The 10 sampled flips still out of reach (`data/timers-after-deadline-fix/out.md`): `api-model-runtime` "does not hold
  native model discovery open" (`vi.waitFor` polls on Vitest's real timers while an unrelated 15 s virtual timer is
  pending); `automatic-api-checks` "stops daily discovery and drains owner cleanup with EBUSY" (timeout); two
  `codex-bin-wrapper` detached-helper tests (the test process holds no handle to the helper); `crash-mid-write` and
  `json-store-lock` (cross-process locks, also failing at V6 in Lane C); two `property/rotation.property` tests
  (pre-condition failures, cleared only with the time control off in Lane C); two `runtime-rotation-proxy` assertions
  (ledger snapshot; `503` vs `200`, both cleared only at V6 in Lane C). None is a timer that `sched.js` could hold
  back without seeing what the test waits on.

## 3. The new defaults (Node only; commit 441ce38, docs and CHANGELOG in the same commit)

- **Clock**: `session.resolveEpoch` (first match): `--det-epoch` (`fixed` = 2025-01-01); the run's `DETJS_EPOCH`,
  honoured only with the run's mark (`DETJS_EPOCH_RUN=1`, set by the outermost `bin/detjs.js`, or the existing
  `DETJS_HAZARD_RERUN=1` / `DETJS_ISOLATE_CHILD=1`); with `--det-cache` the virtual day (unchanged); the
  `meta.epoch_ns` of a `--det-compare` / `--det-plan` trace (a JSON plan has none); the host time, rounded down to the
  second. `bin/detjs.js` picks it once before its own restart, the hazard wrapper and `--det-isolate`, and also for
  `detjs repro|explore|replay`. `prepare()` removes the mark from the tests' environment. `meta.epoch` (ISO) in the
  trace header. `config.fromEnv` without `DETJS_EPOCH` under `DETJS=1` prints once `detjs: no DETJS_EPOCH, using
  2025-01-01`. Tick unchanged.
- **Time zone, locale**: `--det-tz` / `--det-locale` default `keep` (recorded as before); a pin restarts detjs as
  before.
- **Network**: `--det-net=open|closed`, default `open`: `Policy.external()` is false for every host, DNS and reverse
  DNS are not refused, the connection is a `net.connect`/`tls.connect` event `<host>:<port> allowed` with its bytes
  digested; `cache/capture.js` flags it (`<host>:<port> (external host, open network)`), so the test is never reused;
  `session.js` keeps the `*_PROXY` variables in the run inputs when the network is open. `closed` = the old `block`;
  `--det-record` and an existing cassette keep recording / replaying. Status line `network=open`.
- **selfcert**: `generate(commonName, { notBefore, notAfter })`.
- `isolate.js`: `--det-net` forwarded with its value. `parallel-rerun.js` unchanged (its passes inherit the epoch
  through the environment).
- **Timers**: unchanged (section 2).
- **Outside the listed files** (AC5): `python/detpy/fenvix_js.py` (commit 3db3da8): the repro driver started each
  detjs run on its own, so under the host-time default every run had its own epoch and a test named from
  `new Date()` changed id between the driver's collect and repro runs (`tests/test_fenvix_js.py`, branch-only
  failure). A `DetjsRunner` now passes one `--det-epoch` to every detjs it starts (the inherited run epoch of a
  `detjs repro`, else the host time). Python's own defaults are unchanged.

`git diff --stat origin/claude/release-1...HEAD -- node/src node/bin crates`: `node/bin/detjs.js`,
`node/src/cache/capture.js`, `node/src/config.js`, `node/src/isolate.js`, `node/src/network.js`,
`node/src/selfcert.js`, `node/src/session.js` (7 files, +158 -31), plus `node/src/deadline.js` (one line, approved by
the coordinator, a8e3f85). No change in `crates/`, `deadline-preload.js`, `sched.js`, `clock.js`.

### Changed tests, CI steps (opt-out flags only; one line each)

The complete list with the reason per line is `optouts.txt`. Every edit adds the old default's flag to a `--det`
invocation of a test that checks that default (`--det-epoch=fixed`, `--det-tz=UTC --det-locale=C.UTF-8`,
`--det-net=closed`), or that verifies two separate runs against each other (each run otherwise has its own epoch).
Test files: `cache.test.js`, `controls.test.js` (`goldenCheck`, closed-network run), `exit-paths-p0.test.js`,
`exit-regression.test.js`, `network-p041.test.js`, `node-p041.test.js`, `parallel-p041.test.js`, `projects.test.js`,
`review-p1-verifier.test.js`, `review-r032b.test.js` (C-intl, C-timeorigin), `runner-b-cases.js`,
`runner-bun.test.js`, `runner-deno.test.js`, `runner-mocha.test.js`, `runner-node-test.test.js`,
`runners-p041.test.js`, `time-p041.test.js`, `verifier-inputs.test.js`, `verify-inputs-attacks.test.js`,
`tests/test_fenvix_js.py` (the environment form `DETJS_EPOCH`+`DETJS_EPOCH_RUN`, since the driver starts the runs).
CI steps: `release/smoke.py` node (job "smoke (node)") and `release/install_test.py` vitest check (FULL only):
`--det-epoch=fixed` on the two runs they verify against each other. No test skipped, removed or loosened; no timeout
or threshold changed.

Two notes on these edits:
- `review-r032b` C-intl/C-timeorigin reported `WRONG REUSE` without the flag. It is not a soundness hole: the cached
  runs use the cache's virtual day and the fresh run (no cache) the host time, so the fresh run stopped being the
  attack's oracle; with one epoch for both the result is `held`, as on the trunk.
- `verifier-inputs` "CI-volatile variables are never inputs" asserts `HTTPS_PROXY` is not an input; with the open
  network it is, by this spec, so that test opts into `--det-net=closed`.

## 4. Measurements

### Flips, whole lists, plain detjs (AC2)

`PM_WORK=/tmp/pm-hv python3 harness/det_pins/pins.py find --repo ironcurtain --out /tmp/pm-hv/find` and the same for
codex-multi-auth, branch engine ddb73366 (exit 0 both; `logs/find-*.log`, raw `data/find/`); table printed by
`python3 harness/det_host_values/flips.py /tmp/pm-hv/find` (`flips.out.md` holds every remaining flip with its first
failure line):

| repository | flips trunk | flips branch | of which ENV | AC2 count (branch - ENV) | bound |
|---|---|---|---|---|---|
| ironcurtain | 206 | 17 | 0 | 17 | <= 20: met |
| codex-multi-auth | 362 | 422 | 0 | 422 | <= 60: MISSED |

codex-multi-auth: 360 of the 422 were trunk flips too; of the 62 new ones, 43 failed in one of the trunk's two
`--det` runs (the trunk had 45 tests failing in one run only, the branch 6) and 61 of 62 fail `Test timed out in
5000ms`: the deadline cascade of section 2, which now crosses its threshold in both runs instead of one. ironcurtain:
--det passed in both 6872 (trunk 6684); the 17 left are 10 timeouts in MITM / proxy / outbound-transport tests (30-60 s),
two SIGKILL process tests (watchdog, qualification evidence), one Docker admission test, one CA-concurrency
certificate comparison and three LLM-metrics assertions (`flips.out.md`).

### Flips, customer path (no bound)

`python3 harness/det_host_values/customer_run.py --out /tmp/pm-hv/customer --engine trunk=/tmp/fenvix-trunk --engine
branch=$PWD` (`runner/fenvix-run node --project <repo> --runner vitest --cache <fresh> --out <dir> --detjs "node
<engine>/node/bin/detjs.js"`, one cold run each; all four exit 1, `logs/customer_run.log`); table by
`PM_WORK=/tmp/pm-hv python3 harness/det_host_values/customer.py /tmp/pm-hv/find /tmp/pm-hv/customer`
(`customer.out.md`):

| repository | engine | exit | tests | failed in the suite (of plain-passed) | of which flaky (passed alone) | still failed | wall s |
|---|---|---|---|---|---|---|---|
| ironcurtain | trunk (f67be4a3) | 1 | 7033 | 72 | 0 | 72 | 214.56 |
| ironcurtain | branch (e09b1d34) | 1 | 7033 | 49 | 0 | 49 | 201.42 |
| codex-multi-auth | trunk (f67be4a3) | 1 | 8662 | 368 | 18 | 350 | 370.93 |
| codex-multi-auth | branch (e09b1d34) | 1 | 8662 | 365 | 18 | 347 | 368.79 |

The customer path keeps the cache's virtual day (today 00:00 UTC) as its epoch, so ironcurtain gains less there
(72 -> 49) than with plain detjs (206 -> 17): the next decision the spec names. (fenvix-run re-runs at most 20
failures alone, so "flaky" is a lower bound.)

### Proof on six repositories (AC3)

Per repository, trunk then branch, back to back: `PM_WORK=/tmp/pm-hv bash harness/det_host_values/proof_run.sh
<repo> /tmp/pm-hv/proof/<repo>` = `python3 harness/parallel_measure/measure.py --spec
harness/parallel_measure/specs.json --name <repo> --reps 1 --workers 4 --skip bare,plain_par --out <dir>/<engine>`
from each engine's checkout (every measure.py run exit 0, `logs/proof-*.log`). measure.py change (commit 873c2fa, a
harness change): P_i and S_2.. get `--det-epoch` from S_i's / S_1's `meta.epoch_ns`. Table printed by
`python3 harness/det_host_values/proof.py harness/det_host_values/data/proof` from the committed rows
(`proof.out.md`, identical to the run directory's):

| repository | engine | tests run | proven identical | NOT PROVEN | not identical | failed (par) | exit (par) | wall s (par) |
|---|---|---|---|---|---|---|---|---|
| nestjs-pino | trunk | 269 | 223 | 8 | 38 | 0 | 0 | 8.51 |
| nestjs-pino | branch | 269 | 222 | 7 | 40 | 0 | 0 | 8.57 |
| agentsys | trunk | 2224 | 0 | 1740 | 484 | 1 | 1 | 21.2 |
| agentsys | branch | 2224 | 0 | 1740 | 484 | 1 | 1 | 23.54 |
| claudekit | trunk | 814 | 555 | 230 | 29 | 0 | 0 | 20.89 |
| claudekit | branch | 814 | 555 | 230 | 29 | 0 | 0 | 21.38 |
| sqlectron | trunk | 43 | 0 | 38 | 5 | 0 | 0 | 15.73 |
| sqlectron | branch | 43 | 0 | 38 | 5 | 0 | 0 | 15.57 |
| ironcurtain | trunk | 7033 | 0 | 0 | 7033 | 408 | 1 | 175.38 |
| ironcurtain | branch | 7033 | 0 | 0 | 7033 | 385 | 1 | 110.59 |
| codex-multi-auth | trunk | 8662 | 0 | 0 | 8661 | 390 | 1 | 284.82 |
| codex-multi-auth | branch | 8662 | 0 | 4752 | 3909 | 425 | 1 | 309.79 |

| repository | identical trunk / branch | allowed drop | identical | exit trunk -> branch | wall par branch / trunk (<= 1.10) |
|---|---|---|---|---|---|
| nestjs-pino | 223 / 222 | 1.3 | met | 0 -> 0 | 1.007 met |
| agentsys | 0 / 0 | 11.1 | met | 1 -> 1 | 1.110 **MISSED** |
| claudekit | 555 / 555 | 4.1 | met | 0 -> 0 | 1.023 met |
| sqlectron | 0 / 0 | 0.2 | met | 0 -> 0 | 0.990 met |
| ironcurtain | 0 / 0 | 35.2 | met | 1 -> 1 | 0.631 met |
| codex-multi-auth | 0 / 0 | 43.3 | met | 1 -> 1 | 1.088 met |

Per-test causes (every test identical on the trunk and not on the branch; `proof.out.md`):
- nestjs-pino, 1 test: `module.spec.ts::...forRoot::should work properly with single value of httpPino property`,
  `diverged [time]`: `Date.now @ pino-http/logger.js:170` in one run vs `uncontrolled.io @ sonic-boom/index.js:622
  concurrent I/O` in the other: the order of a clock read and a concurrent write differs between serial and parallel.
  Honest (a real difference in recorded I/O order, reported, not hidden).
- Every other repository: 0. ironcurtain: all 7033 not identical on both engines for the same reason, `fs` run
  inputs (files the run itself writes, read outside the tests, differ between S and P: P1's item B). codex-multi-auth:
  trunk 8661 `fs` the same way; on the branch the verifier names other first causes (`api` 4359, `order` 2933,
  `other` 710, `fs` 214, `io` 209, `env` 170; 4752 NOT PROVEN): no test is identical on either engine.
- agentsys wall time: one round each, 23.54 s vs 21.20 s (ratio 1.110, bound 1.10). Reported as measured; not
  re-run or tuned to fit (rule).

## 5. Suites (AC4)

- `cd node && npm test` (engine venv first on `PATH` so `python3 -m detpy` works, as CI installs the wheel):
  branch c639629..7b75353 tree, 52 min: `# tests 984 # pass 976 # fail 4 # cancelled 3`, exit 1
  (`logs/npmtest.branch.log`); trunk checkout f67be4a3, 54 min: `# tests 975 # pass 968 # fail 3 # cancelled 3`,
  exit 1 (`logs/npmtest.trunk.log`). Failing top-level groups: trunk = jest "parallel lanes" (setup: "parallel
  refused ... Jest 30"; 3 tests cancelled), "repro options (vitest)" (`--det-order` test), "bun: Level 0 controls"
  ("two --det runs ..."), "node-test: adversarial" ("a file another test file wrote"); branch = the same four + (b).
- Python tests shared with Node (`release/python-tests.txt` `shared`, 53 files), `python -m pytest -q -p no:randomly
  -n 4 <files> -rfE`: branch (after 3db3da8) `12 failed, 941 passed, 39 skipped`; trunk checkout `12 failed, 941
  passed, 39 skipped`; the same 12 names (`logs/python-shared.*.log`). Before the `fenvix_js` fix the branch had two
  more (`test_run_dependent_id_is_reproduced_by_its_stable_id[vitest,jest]`, `logs/python-shared.branch-before-
  fenvix_js-fix.log`). `test_f01_gaps.py::test_first_run_after_a_checkout_or_an_edit_is_laid_out_like_later_runs`
  failed in one trunk run and one branch run and passed in others: unstable on both.
- LIGHT CI (`workflow_dispatch`, `depth: light`) on the branch: run 45269638341 (702bf489) failed `attacks`,
  `python (3.13, shard 3/4)`, `node (24, shard 3/4)` and **`smoke (node)`**; the trunk run on the same engine
  (45186293624, f67be4a3) failed `attacks`, `python (3.13, shard 3/4)`, `node (24, shard 0/4)`. `node 3/4` fails the
  two tests that fail on the trunk engine locally (`--det-order`, "a file another test file wrote"; the new test files
  move them from shard 0 to shard 3). `smoke (node)` was new: `det_traces_identical` failed with `run input clock
  differs` (two runs, two host epochs); fixed with the opt-out on the smoke's two runs (757ae01; locally the same two
  runs verify `277` identical, exit 0). Second LIGHT run 45276046330 (757ae016): failing jobs `attacks`, `python (3.13, shard 3/4)`, `node (24, shard 3/4)` (3, as the trunk's 3); `smoke (node)` and `smoke (python)` pass; `attacks`: `=== attacks: python rc=1, node rc=0 ===` (every Node attack passes, 60/60 in the verify-inputs file; the Python engine is unchanged); other shards cancelled by the matrix's fail-fast in both runs. No new failing job against the trunk's run on the same engine.

## 6. Not done, risks, next decisions

- Spec deviation: `node/src/deadline.js` changed (one line), forbidden by spec line 71, approved by the coordinator's
  decision of 2026-11-23 (D1 = A).
- AC2 codex-multi-auth: 69 flips after the approved fix, bound 60: missed by 9. Sample: 38/48 (bound 35 met).
- AC1 (b): still fails; its two shapes (`vi.waitFor` on the runner's real timers, a file written by a detached
  grandchild) are not observable by `sched.js`; with the 10 sampled flips above they are the cases still out of reach.
  The flip lists above and the proof table were measured before the fix (ironcurtain find, ddb73366; proof, 702bf489);
  only the codex-multi-auth sample and whole list were re-run after it, as decided.
- AC3 agentsys wall time 1.110 > 1.10 on one round.
- The customer path keeps the virtual day; ironcurtain flips there 72 -> 49 (spec: the next decision).
- `fenvix repro` through Python (not `detjs repro`): one epoch per driver session now; a repro of an id reported by
  an earlier, separate run whose name contains the date still matches only through masking (it reproduces, under the
  new session's id).
- Rollback: delete the branch; after a merge, revert it; each old default is one flag away (`--det-epoch=fixed`,
  `--det-tz=UTC --det-locale=C.UTF-8`, `--det-net=closed`).

## Files

`harness/det_host_values/`: this report; `optouts.txt`; `timers.py` / `timers.out.md`; `flips.py` /
`flips.out.md`; `customer_run.py`, `customer.py` / `customer.out.md`; `proof_run.sh`, `proof.py` / `proof.out.md`;
`data/` (raw rows, outcomes, verify reports, experiments); `logs/`.
