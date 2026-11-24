# P1 design: the engine's run-level false alarms (phase 1)

Branch `claude/p1-false-alarms` (from `claude/release-1` e7338950). Phase 1 only: measurements, root causes,
proposed fixes. No engine change is committed; the counterfactuals below were scratch patches, applied for one
measured round each and reverted (`git status` clean after each). Labels: MEASURED (a committed file backs it),
DECLARED (read in the code, not measured), ESTIMATED, UNKNOWN.

## 0. Summary for the decision

| item | before, sum over the 6 repositories (round 1) | counterfactual (one round, its largest repository) | proposed fix | effort |
|---|---|---|---|---|
| A | 1,540 agentsys (+30 sqlectron, a different cause: §A.4) | agentsys: A 1,540 → 0; identical **0 → 1,540** (MEASURED) | A1: compare the value of a KEPT/proxy variable read outside any test between the two runs instead of marking every test NOT PROVEN | 1 day (A1); A2-A3 below |
| B | 15,695 (codex-multi-auth 8,661 `<tmp>`, ironcurtain 7,033 `<abs>`, claudekit 1) | codex-multi-auth: run-level 8,661 → 0, B 8,661 → 38; identical **0 → 0**: B hid A 4,354, C 532, F 216, D 27, order 2,933 (MEASURED) | B1: a read outside any test is scoped to the open test file, not the run; B2: a file this process wrote itself is no input when read back | 2.5 days |
| C | 38 (nestjs-pino 35, claudekit 2, agentsys 1) | nestjs-pino: C 35 → 0; identical **223 → 258** (MEASURED) | a per-test-file virtual pid, the same in the serial and the parallel run, distinct between concurrent workers | 1-1.5 days |
| D | 99 agentsys (+5 sqlectron, +27 codex-multi-auth hidden by B) | agentsys: D 99 → 0; identical **0 → 0** (A covers every agentsys test) (MEASURED) | **product decision** (§D): recommendation = option 3 | 0.5 day after the decision |
| E | 22 claudekit | claudekit: E 22 → 15; identical **555 → 557**; the 12 tests left by the E rule all also carry F's `uncontrolled.io` (MEASURED) | install `fsorder` and `outside` above `ioorder`, `fsorder` wrapping at install time | 0.5 day (after F) |
| F | 234 (claudekit 225, nestjs-pino 8, agentsys 1; sqlectron +8) | claudekit: F 225 → 12; identical **555 → 770**; `--det` serial 21.0 s → 13.5 s, parallel 21.3 s → 12.7 s (MEASURED) | a file operation started by another tracked operation (its call, or its internal continuation) is part of it: track the parent through `AsyncLocalStorage` | 1 day |

The decisive numbers for the 22 December verdict: A1 and F are the two largest MEASURED gains in tests that become
identical (1,540 and 215), C is small but complete (35 of 46 in nestjs-pino), B is the largest by count but frees no
test by itself in the two repositories it hits, because what it hides (§B, table B.2) is still there.

Order for phase 2. The spec's default (largest total in `before.json` first) is B, A, F, D, C, E. My
recommendation is **F, A1, C, E, B, D** (D after the decision): it front-loads the MEASURED gains and does E right
after F (E depends on it), and leaves the most intricate change (B, judge plus shell attribution) for when the others
are in. The coordinator decides.

## 1. How it was measured

* Engine: trunk `claude/release-1` **e7338950** (contains P0 81f838c6: `git merge-base --is-ancestor 81f838c6
  e7338950` true). `engine_commit` in every before row is e7338950262acc4bd24ed6d3af6a59e3f765a3af; counterfactual
  rows say `9012e9f…+modified` (measure.py's marker for a modified engine).
* Setup: `harness/p1/setup.sh` (run once, `FENVIX=/home/user/fenvix-engine-cli PM_WORK=/tmp/pm-p1`; exit 0).
* Loop (detached, nothing else running; started 13:11 UTC, ended 14:16 UTC on 2026-11-23, 4 vCPU):
  `cd $FENVIX/harness/parallel_measure && nohup sh -c 'for r in agentsys codex-multi-auth ironcurtain nestjs-pino
  claudekit sqlectron; do python3 measure.py --spec specs.json --name $r --reps 2 --workers 4 --skip plain_par
  --timeout 7200 --out $PM_WORK/p1-before; done' > $PM_WORK/p1-before.log 2>&1 &`
* Every count comes from `fenvix verify S1 P1w4 --json` of that repository, e.g. `/tmp/pm-p1/venv/networkx/bin/python
  -m detpy.fenvix verify /tmp/pm-p1/p1-before/claudekit/S1.jsonl /tmp/pm-p1/p1-before/claudekit/P1w4.jsonl --json`
  (exit 1: not every test identical), the `cmd` of each `verify` row in `harness/p1/data/before/<repo>/results.jsonl`.
* Tally: `python3 harness/p1/tally.py /tmp/pm-p1/p1-before <repo> --json harness/p1/before.json --e-dir
  harness/p1/data/before/<repo>/E`. It reproduces every count from the committed files alone
  (`python3 harness/p1/tally.py harness/p1/data/before <repo>`: checked equal for all six). Files over 1 MB are
  gzipped; `tally.py` reads them.
* **Deviation (sqlectron).** Its spec install line verbatim (`npm install --ignore-scripts …`) leaves `sqlite3`
  without its native binding: 3 of 7 test files fail to load (`Could not locate the bindings file`), 14 tests run,
  verify calls all 14 identical. The earlier engine rows had 42-43 tests. I measured it a second time after `npm
  rebuild sqlite3` (2 rounds, same command, `--out $PM_WORK/p1-before-sqlrebuilt`, recorded in `setup.sh`): 43 tests.
  Both are committed (`data/before/sqlectron/`, `data/before/sqlectron-rebuilt/`); the table shows both.
* Not measured: ironcurtain has no counterfactual (the B round went to the larger codex-multi-auth); the combined
  effect of two fixes (E with F, D with A) is UNMEASURED (budget of 6 rounds); the after measurement of phase 2 gives it.

## 2. Before table (round 1, S1 against P1w4, 4 workers)

`tally.py` categories, first match wins (header of `harness/p1/tally.py`). `run-level`: tests whose divergence is a
differing run input other than an environment variable (it makes every test diverge and hides the rest).

| repository | tests | identical | not identical | A | B-tmp | B-abs | C | D | E | F | noise | other | run-level |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentsys | 2,224 | 0 | 2,224 | 1,540 | 0 | 0 | 1 | 99 | 0 | 1 | 583 | 0 | 0 |
| codex-multi-auth | 8,663 | 0 | 8,663 | 0 | 8,661 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 8,661 |
| ironcurtain | 7,033 | 0 | 7,033 | 0 | 0 | 7,033 | 0 | 0 | 0 | 0 | 0 | 0 | 7,033 |
| nestjs-pino | 269 | 223 | 46 | 0 | 0 | 0 | 35 | 0 | 0 | 8 | 3 | 0 | 0 |
| claudekit | 814 | 555 | 259 | 0 | 1 | 0 | 2 | 0 | 22 | 225 | 9 | 0 | 0 |
| sqlectron (spec install, 14 tests load) | 14 | 14 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sqlectron (`sqlite3` rebuilt) | 43 | 0 | 43 | 30 | 0 | 0 | 0 | 5 | 0 | 8 | 0 | 0 | 0 |

Source: `harness/p1/before.json`, `harness/p1/before-sqlectron-rebuilt.json`; engine_commit e7338950 in every row.

Round 2 (S2 against P2w4, `before-round2.json`) agrees within a few tests: agentsys A 1,536 / noise 587;
claudekit E 24 / F 221 / noise 11; nestjs-pino noise 4 (222 identical); every other cell equal.

**Serial against serial** (`verify_serial_noise2w1.json`, S1 against S2; per item, how many of its tests are not
identical there either):

| repository | A | B-tmp | B-abs | C | D | E | F | noise | other |
|---|---|---|---|---|---|---|---|---|---|
| agentsys | 1,540 | 0 | 0 | 1 | 99 | 0 | 1 | 583 | 0 |
| claudekit | 0 | 1 | 0 | 2 | 0 | 20 | 225 | 9 | 0 |
| codex-multi-auth | 0 | 8,661 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| ironcurtain | 0 | 0 | 7,033 | 0 | 0 | 0 | 0 | 0 | 0 |
| nestjs-pino | 0 | 0 | 0 | 35 | 0 | 0 | 8 | 3 | 0 |
| sqlectron (rebuilt) | 30 | 0 | 0 | 0 | 5 | 0 | 8 | 0 | 0 |

Almost every A-F false alarm also shows between two serial runs (all but 2 of claudekit's 22 E tests): they are not about parallelism.

**Caveat on `noise` (agentsys).** The literal rule counts a test as noise when the serial pair calls it not
identical. In agentsys A makes every test NOT PROVEN in the serial pair too, so the 583 are not evidence of noise:
for 274 of them the serial pair's own verdict is an A-F false alarm (A 265, D 6, F 3), and the other 309 differ
between the two serial runs for reasons outside P1 (child processes, in-test reads of KEPT variables, extra
`os.tmpdir` events). `before.json` keeps the literal count and the split (`noise_whose_serial_pair_verdict_is_A_F`).

**What the two run-level repositories hide.** Classifying the serial pair the same way (`before-serial-pair.json`)
shows what is behind B, where there is no run-level difference:

| repository (S1 vs S2) | A | B-tmp | C | D | E | F | other |
|---|---|---|---|---|---|---|---|
| codex-multi-auth | 4,375 | 36 | 551 | 27 | 5 | 213 | 3,456 (order 2,933, env 208, fs 148, …) |
| ironcurtain | (S1 vs S2 is run-level too: B-abs 7,033) | | | | | | |

**Restated codex-multi-auth A and C (plan review finding 7), from these rows.** In S1 vs P1w4 every test is B
(run-level `file:<tmp>/.codex/accounts.json`), so A and C are 0 there. Behind it (serial pair, and the B
counterfactual's S1 vs P1w4): A = **4,375** (4,354 in the counterfactual), and the A entries **do include an exit
call**: `not_proven_outside_tests` = `api:process.reallyExit, env:*, env:HTTPS_PROXY, env:NO_PROXY, env:OLDPWD, env:PWD,
env:SHLVL, env:TEMP, env:TMP, env:TMPDIR, env:_, env:https_proxy, env:no_proxy` in S1 and P1w4 alike. C =
**551** (532 in the counterfactual), all `process.pid @ lib/storage/file-lock.ts:148` — so the earlier "704" was
of the right kind, the count is 551 here.

## 3. Counterfactuals (one round each, `--reps 1 --workers 4 --skip plain,plain_par`)

Run by `run-cf.sh <item> <repo>` (scratchpad, not committed): `git apply <item>.patch`, the measure command with
`--out $PM_WORK/cf-<item>`, `git checkout -- node/src`. Results: `harness/p1/counterfactual.json` and
`harness/p1/data/counterfactual/<item>/`. Six rounds in total (the budget).

| item | repository | patch (in words) | identical before → after | item count before → after | uncovered (net effect) |
|---|---|---|---|---|---|
| A | agentsys | no NOT PROVEN mark for a KEPT/proxy variable read outside any test; its digest logged instead | 0 → **1,540** | 1,540 → 0 | the 684 left: D 99, C 1, F 1, other 583 (child 84, env 177, fs 18, other 303, beyond-trace 1) |
| B | codex-multi-auth | a path the process itself created (mkdir, mkdtemp, writeFile, …) or anything below it is no run-level entry | 0 → 0 | 8,661 → 38 (run-level 8,661 → 0) | A 4,354, C 532, F 216, D 27, E 1, other 3,495 (order 2,933) |
| C | nestjs-pino | `process.pid` / `ppid` recorded as a constant symbol (the test still saw the real pid) | 223 → **258** | 35 → 0 | F 7, other 4 |
| D | agentsys | entropy controlled by default (`urandom: true`) | 0 → 0 | 99 → 0 | A 1,542 (A covers every test) |
| E | claudekit | `fsorder` and `outside` installed after `ioorder`, `fsorder` capturing `fs` at install | 555 → **557** | 22 → 15 | F 222; the 12 tests still matching the E rule all carry `uncontrolled.io` |
| F | claudekit | an operation begun inside a tracked operation's synchronous call, or from `node:fs` itself, is not tracked | 555 → **770** | 225 → 12 | E 14, C 2, B 2, other 14; all 12 F left at `<deps>/graceful-fs/graceful-fs.js:54` |

Timing (MEASURED, claudekit, `wall_s` of the rows): `--det` serial 21.69 / 21.05 s and parallel 20.95 / 21.61 s
before; 13.47 s and 12.65 s with the F patch; plain serial (no engine) 7.00 / 6.53 s.

## A. Environment variables read outside any test

### A.1 Root cause

What the measurement shows is not the `env_read_outside_tests` path the spec names first (it produced 0
`input-differs` in all six repositories: no variable had a different value between the two runs) but its sibling,
`not_proven_outside_tests`:

* `node/src/controls.js:124-129` (`noteOutside`): a read outside any test of a variable for which `unproven()` is true
  (`controls.js:99-104`: a KEPT one, `volatile.KEPT` minus the pinned ones (`controls.js:98`), or a proxy variable
  while the network is closed), by the project's own code (`projectSite`), is written as `env:<NAME>` to
  `<run dir>/npout/<pid>.txt` (`noteNotProven`, `controls.js:112-123`); `*` for an enumeration
  (`Object.keys(process.env)` and the like) when any KEPT variable exists.
* `node/src/session.js:416` puts them in the header as `not_proven_outside_tests`.
* `crates/detpy-core/src/verify.rs:868-875` collects them from every run and `provable::judge_record` makes **every
  test** NOT PROVEN, the divergence written by `outside_not_proven` (`verify.rs:510-530`): "outside any test the run
  read sources that are not controlled (…)".

agentsys: `env:*, env:HTTPS_PROXY, env:NO_PROXY, env:OLDPWD, env:PWD, env:SHLVL, env:TEMP, env:TMP, env:TMPDIR, env:_,
env:https_proxy, env:no_proxy` in S1 and P1w4 → 1,540 tests NOT PROVEN for that alone. The values never differed: the
counterfactual logged each variable's digest per process (`data/counterfactual/A/envdig/`): every named variable has
**one digest across all 6 processes** (serial and parallel). The enumeration `*` has **6 different digests, one per
process**: the full environment contains per-process variables (`JEST_WORKER_ID`, `DETJS_*`, …). MEASURED.

The false alarm: "this value is not a run input" (true: it differs between CI machines, so the cache must not reuse
a test across runs) was turned into "no test of the run can be proven", although `verify` compares two given runs and
can compare the value itself.

### A.2 Proposed fix (A1)

* `controls.js` `noteOutside`: for an `unproven()` variable, write `env:<NAME>=<digest of NAME=value>` (16 hex, as
  `runInputs` does) instead of `env:<NAME>`; for `*`, the digest of the sorted `NAME=value` lines of the environment
  **without** the engine's and the runner's per-process variables (`volatile.patterns()` prefixes `DETJS_`, `DETPY_`,
  `VITEST_`, `JEST_WORKER`, `PYTEST_XDIST_`, and `OWN_ENV`): the same exclusion `runInputs` (`session.js:270-301`)
  applies, so the enumeration digest is the same in every process of one machine (the counterfactual shows it is not
  without the exclusion).
* Header: the entries stay in `not_proven_outside_tests` with the `=digest` suffix (a reader that does not know the
  suffix still sees `env:<NAME>…`, kind `env`), so the Python shell and older traces are unaffected.
* Judge (`verify.rs`, in `verify()` before the per-test loop): for each `env:<NAME>=<d>` entry, if every run has the
  entry for `<NAME>` with the same set of digests, it is **discharged for this comparison**: it is removed from the
  `not_proven_outside` list passed to `judge_record` and `not_proven_divergence`. If the digests differ (or one run has
  no entry for that name), the entry is not discharged and, in addition, every test gets `input-differs` naming the
  variable (the existing `input_differs` path, `verify.rs:1048-1066`, `read.all = true`). Entries without a digest
  (older traces, the Python shell) are never discharged: today's verdict.
  Fail-safe added before the merge (founder decision D1 = C, 2026-11-24): an entry is discharged only when every
  compared run used one worker (`meta.parallel.workers` 1), since a run's entries are one set and do not say which
  worker saw which value; the per-worker comparison is a follow-up.
* The cache keeps today's rule: `judge_record` for the cache is called with the undischarged list (the cache has no
  second run to compare with). No change to `crates/detpy-core/src/provable.rs`.

Why a real difference is still caught: a different value is a different digest, so the entry is not discharged and
every test is `input-differs` (and still NOT PROVEN through the undischarged entry). A value that changes inside one
run (two digests in one run, e.g. a test setting `TMPDIR`) is a set of digests: equal sets only if both runs saw the
same values.

### A.3 Regression tests

* `node/test/p1-a-env-outside.test.js` (node:test runner fixture, the `review-r055.test.js` pattern): a test file reads
  `process.env.TMPDIR` and enumerates `Object.keys(process.env)` at module scope; two `--det` runs (serial and
  `--det-workers=2`) with the same `TMPDIR` → verify `stable` for both tests. Trunk: NOT PROVEN (red).
* Real difference (acceptance 2): the same project, `TMPDIR` set to two different directories in the two runs, the
  test writing the value it read → verify reports the tests `input-differs` or NOT PROVEN, never `stable`.
* `verify.rs` unit tests: equal digests → stable; different digests → input-differs naming the variable; an entry
  without a digest → NOT PROVEN (today's verdict kept).

### A.4 The other A rows (not covered by A1)

* **A2, `env_read_outside_tests` (the spec's case): latent, 0 measured.** `verify.rs:956-961` counts every name in
  it as read by every test (`read.names.extend(outside)`), so one differing variable read at module scope of one file
  makes every test of the run `input-differs`. Not triggered here (no differing variable). Proposed with B1 (§B.2):
  the name is recorded with the test file open at the read and scoped to it. Effort included in B1.
* **A3, `api:process.reallyExit` (codex-multi-auth).** After A1 it alone keeps 4,354 codex-multi-auth tests NOT PROVEN
  (DECLARED: it is the only non-env entry). The calling site is UNKNOWN (candidate: `lib/shutdown.ts:48`
  `process.exit(0)`); one diagnostic run in phase 2 locates it. Possible rule: an exit call ends the process, so no
  test of that process runs after it; if it is the last thing the process did (no test began after it), it is no gap
  for any test. Not proposed until the site is known. Effort 0.5 day.
* **sqlectron's 30 A tests are not an environment read**: `native:/…/sqlite3/build/Release/node_sqlite3.node`, a
  native addon loaded outside any test. The tally rule (`not-proven` + "outside any test") puts it under A. It is the
  general rule's native-addon gap, not a P1 false alarm; listed so that it is not read as A1's gain.

### A.5 Risks

* Attribution: A1 attributes nothing; it compares the value. The only relaxation is "same value in both runs → no
  mark", which is exactly what `verify` proves for every other run input.
* The enumeration digest must exclude only per-process engine/runner variables. Excluding a project's variable would
  hide a difference; the exclusion list is `volatile.patterns().prefixes` + `OWN_ENV`, already the run-input rule.
* KEPT variables read **inside** a test keep `uncontrolled.env` (agentsys: 117 tests NOT PROVEN that way in S1 vs P1w4; codex-multi-auth 208 in S1 vs S2):
  not P1. The same comparison could discharge them; out of scope unless the coordinator adds it.

### A.6 Effort: 1 day (shell, judge, VERIFY-CONTRACT.md section 1, tests). A3 +0.5 day.

## B. Files the run itself writes, recorded as inputs read from outside

### B.1 Root cause

* `node/src/outside.js:63-83` (`byProjectOutside`) and `85-95` (`noteFile`): a read or stat of a file outside the
  project while no test runs (module scope, `setupFiles`, `beforeAll` / `afterAll` hooks) by project code is written to
  `<run dir>/filesout/<pid>.txt`; `session.js:415` puts it in `files_read_outside_tests`.
* `verify.rs:374-390` (`compared_inputs`) turns each path into a run input `file:<path>`; a set that differs makes
  **every test of the run** diverge (`verify.rs:904-909`, "the runs did not have the same inputs").
* Paths are normalized by `node/src/sites.js:20-30`: under `os.tmpdir()` the first component is dropped
  (`<tmp>/.codex/accounts.json` for `$TMPDIR/cma-test-home-XXXXXX/.codex/accounts.json`); anywhere else only the
  basename is kept (`<abs>/HEAD`, `<abs>/112b41…`).

codex-multi-auth (MEASURED): `test/helpers/global-sandbox.ts:19` (a `setupFiles` entry, run before each test file)
`mkdtempSync(join(tmpdir(), "cma-test-home-"))` and points `HOME` / `CODEX_HOME` there; a later read outside any
test stats `<tmp>/.codex/accounts.json` and `auth.json` (`stat:missing`). The entries are in S1 and S2 but not in
P1w4 (round 2: the other way round, `<tmp>/openai-codex-accounts.json`): **the same "missing" answer, present in one
run's header and absent from the other's** → `file:` input differs → 8,661 of 8,663 tests diverge. The counterfactual
log (`data/counterfactual/B/skipped/`) shows the entries in 3 processes, every one under a `cma-test-home-*` directory
the process had created itself.

ironcurtain (DECLARED from the header, not counterfactual-tested): 53 `<abs>` entries per run, all under directories
its tests create: hard-coded `/tmp/ironcurtain-roots-bridge-{a,b,policy}-<pid>` (the **pid in the name**: §C),
`ic-enrich-*-XXXXXX` temp directories, and a git repository (`.git/HEAD`, `COMMIT_EDITMSG`, object files such as
`<abs>/112b41ad…`) whose object names differ between runs because `git commit`, a child process, uses the real
clock. 139 `file:` inputs differ between S1 and P1w4 → 7,033 tests diverge.

### B.2 Proposed fix

* **B1, scope (judge + shell).** An entry read outside any test while a test file is open (`STATE.fileId` set:
  module scope, its hooks, the runner's per-file setup files) is recorded with that file:
  `{"path", "digest", "file": <fileId>}`. Entries with no file open (the main process, `globalSetup`) keep today's
  run-wide rule. `verify.rs`: a `file:`-input that differs and carries a `file` applies only to the tests of that file
  (by nodeid prefix) — **plus**, when the shell cannot show module isolation between files of one process (Vitest
  `isolate: false`, or a pool that runs several files in one module graph), every test that ran after it in the same
  process, in either run. `env_read_outside_tests` names get the same `file` scope (A2). The header field stays a
  sorted array; entries without `file` are run-wide (Python, older traces).
* **B2, the process's own writes (shell).** `outside.js` records, per process, the paths its JavaScript wrote
  (`writeFile*`, `appendFile*`, `copyFile*`, `open` with a write flag then `write`, `rename` destination) with the
  digest of the bytes written, and the directories it created (`mkdir*`, `mkdtemp*`). A read outside any test of a
  file this process wrote, whose bytes equal what it wrote, is no input (the bytes are this process's own output);
  a `stat` of a path inside a directory this process created and into which no child process of it could have
  written (no child started since the creation) answers from that knowledge and is no input either. Anything else —
  a file written by a child process (ironcurtain's git objects), by another worker, or by an earlier run (the
  hard-coded `/tmp` paths survive between runs) — stays an entry, scoped by B1.

What `verify` decides: B1 narrows a differing entry from every test of the run to the tests of the file that read
it; B2 removes only reads of bytes the same process produced. For codex-multi-auth the entries are B2's case (the
sandbox directory created by the same process, `stat:missing`, no child): no entry in either run. For ironcurtain
B1's case: a differing git object read in a hook of one test file diverges that file's tests only.

Why a real difference is still caught: a file the run did not write keeps its digest in the trace, scoped to the
file whose code read it; module scope and hooks run only for that file's tests, and where modules are not isolated
the scope extends to every later test of the process. A file written by another worker or by a child process is not
B2's case. The bytes of a file this process wrote are recorded at the write, so a reader that sees different bytes
from what was written (a concurrent writer) is not discharged.

### B.3 Regression tests

* `node/test/p1-b-outside-scope.test.js`: two test files; file a's `beforeAll` creates a temp directory, writes a
  file with content that differs between the runs (e.g. a counter of the process) and reads it back; file b reads
  nothing. Serial vs `--det-workers=2`: b's tests `stable`, a's tests `stable` with B2 (own write read back).
  Trunk: every test of both files diverges (red).
* Real difference (acceptance 2): file a's `beforeAll` reads a file outside the project the run did not write, whose
  bytes differ between the two runs → a's tests diverge (or NOT PROVEN), b's are `stable`; on the trunk both diverge.
* `verify.rs` unit tests for the scoped `file:` input (applies to the file's tests only; an unscoped entry applies to
  all; the non-isolated rule extends it to the later tests of the process).

### B.4 Risks

* **A read that one test's outcome depends on must never be hidden.** B1 never drops an entry, it narrows its scope to
  the tests that can have observed it; the non-isolated-process rule is there because module state (and
  `process.env`, written at module scope) can carry from one file to the next in one process. If the shell cannot tell
  whether files are isolated, it must use the wide scope.
* B2 discharges a read only when the same process produced the bytes and they are unchanged; the risk is a writer the
  wrappers do not see (native code, a child process, a `FileHandle` path not wrapped). The child-process condition and
  the "bytes equal what was written" check cover the cases seen; a missed writer leaves an entry (today's verdict),
  never a false identical, as long as the check compares the bytes read with the bytes written.
* The counterfactual dropped created paths entirely (an upper bound for B2): MEASURED 8,661 → 38 on codex-multi-auth.
  B1's scoped count for ironcurtain is UNMEASURED (no round left).

### B.5 Effort: 2.5 days (B1 1.5: shell fields, judge scope, contract; B2 1; tests).

## C. `process.pid` observed, not controlled

### C.1 Root cause

`node/src/facts.js:122-133`: `process.pid` and `process.ppid` become getters that record `process.pid` with a digest
of the **real** value (`recQuietSafe(`process.${n}`, value)`, line 129) whenever a test reads them. Serial and parallel
runs have different processes, so the event differs in every test that reads the pid. MEASURED sites:
`<deps>/@nestjs/common/services/console-logger.service.js:265` (34 of nestjs-pino's 35: the logger prints
`[Nest] <pid> -`), `<deps>/signal-exit/index.js:15` (claudekit 2), `lib/storage/file-lock.ts:148` (codex-multi-auth
551 behind B: the lock file records the owner pid). The engine itself uses the real pid for per-process files and
names: `controls.js:85` (`process:${pid}`), `:121` (`npout/<pid>.txt`), `:138` (`envout/<pid>.txt`), `:283` (the part
header's `pid`), `session.js:150` (`run-<pid>`), `:503`, `outside.js:93` (`filesout/<pid>.txt`).

### C.2 Proposed fix

A **virtual pid per test file**: while a test file is open in a process, test code reads `process.pid` = `V(file)`,
where `V` is a pure function of the run's test-file list and the file (e.g. `4194304 + 1 + index of the file in the
sorted list of all test files of the run`: above Linux's largest `pid_max`, so it is never another live process's
pid). Rule for values that must be distinct across concurrent workers and identical between the serial and the
parallel run of the same test: **the value is a function of the test file, never of the process**; two workers never
run the same file at the same time, so their values differ; the same file gets the same value in every run.

* `process.ppid`: a constant (`4194304`).
* `process.kill(V(file), sig)` from that process → `process.kill(REAL_PID, sig)`; a cross-process table
  `<run dir>/vpid/<V>.txt` → real pid lets another process of the run reach it (`kill(V, 0)` liveness checks in lock
  files, codex-multi-auth's case).
* The engine reads `REAL_PID`, captured in `state.js` before any patch, at the seven places listed in C.1.
* Outside a file (the main process, `globalSetup`): the real pid, recorded as today.
* Recorded event: `process.pid` = `V(file)` (a digest of it): equal in serial and parallel.

Why a real difference is still caught: the value the test sees is exactly what is recorded, and it is a function of
run inputs (the test-file list, which `verify` already compares via the executed order and `inputs.code`). Two runs
that select different files can give a file a different `V`: the event differs and the test diverges. A test whose
outcome depends on the real pid can no longer see it (that is the control), the same way `Date.now()` is virtual.

Cheaper alternative (what the counterfactual measured): keep the real pid for the test and record a symbol. It
removes the same 35 nestjs-pino false alarms (MEASURED) but the proof becomes weaker: a test whose control flow
depends on the numeric pid without changing its events or outcome would be called identical. Not recommended.

### C.3 Regression tests

* `node/test/p1-c-virtual-pid.test.js`: a test logs `process.pid` and writes `/tmp/x-${process.pid}`; serial vs
  `--det-workers=2` → `stable`; two test files run concurrently get different values (no path collision). Trunk:
  diverged (red).
* Real difference (acceptance 2): run 2 adds a test file that sorts before it, so the file's `V` changes, and the test
  fails when `process.pid` is odd → verify: diverged.
* `process.kill(process.pid, 0)` from the test and from a second process of the run (through the table) succeeds.

### C.4 Risks

* Collisions (spec): addressed by the per-file rule (distinct across concurrent workers) and by values above
  `pid_max` (no collision with a real process).
* Native code (`getpid(2)` from an addon) and child processes (`child.pid` is real, `$PPID` in a child is the real
  parent pid) still see real pids: unchanged from today (children are already `uncontrolled.child`).
* Libraries that cache `process.pid` at import (signal-exit) see the value of the file that imported them; with
  module isolation per file that is the file's own value; without it, the first file's value (the same in both runs,
  since the first file of a process differs only by scheduling — DECLARED, checked by the after measurement).

### C.5 Effort: 1-1.5 days.

## D. Random bytes observed unless `--det-urandom` (open product decision)

### D.1 Root cause

`node/src/session.js:69` `urandom: false` by default; `config.js:49` reads it back. With it off, `seeds.js:212-218`
(`randomBytes`), `:223-233` (`randomFillSync`), `:235-255` (`randomInt`) return real OS entropy and record it as an
`entropy` event with its digest (`observe`, `seeds.js:263-267`): every run differs. HELP `session.js:37` says the
flag is "NOT for crypto". MEASURED sites: `lib/utils/atomic-write.js:22` (agentsys 87: a random temp-file suffix),
`lib/state/workflow-state.js:180` (agentsys 10: ids), `src/browser/core/crypto.ts:16` (sqlectron 4: an encryption
IV), `<deps>/uuid/dist/rng.js:18` (sqlectron 1).

### D.2 Options (the coordinator decides with the founder)

| option | MEASURED gain (D false alarms removed) | crypto risk |
|---|---|---|
| 1. keep observed by default (today) | 0 | none added |
| 2. on by default under `--det`, opt-out `--det-urandom=off` | agentsys 99 (all hidden by A until A1 lands), sqlectron 5 of 43, codex-multi-auth 27 (behind B); claudekit, nestjs-pino 0 | every `randomBytes` in the test process is deterministic per test, **including protocol nonces** (`seeds.js:213`: with the flag on, the nonce path is skipped) and IVs/keys a test generates; a test that checks cryptographic properties (two keys differ, a nonce is fresh across runs) can pass vacuously or behave differently from production |
| 3. on by default, real bytes kept for named crypto calls | same as 2 for the sites measured (none of them is a protocol nonce or native key generation) | protocol nonces (the existing `protocolNonce()` list) and native key generation (`generateKeyPair*`, already observed) stay real; application code calling `randomBytes` for its own IV or key (sqlectron `crypto.ts:16`) becomes deterministic per test under `--det` |

Gain after A1 lands, agentsys: UNMEASURED (the D counterfactual ran with A in place: 99 → 0 but identical 0 → 0).

**Recommendation: option 3.** It removes every D false alarm measured (none of the measured sites is a protocol
nonce), keeps the bytes that protocols need fresh, and keeps an opt-out. The bytes stay recorded as events, so a test
whose outcome depends on them still diverges when the seed (a run input) differs. The residual risk — application
crypto made deterministic under `--det` — is a test-only effect; HELP and `docs/NODE.md` must say it plainly ("under
--det, crypto.randomBytes & co. return a per-test deterministic stream; protocol nonces and key generation stay real;
--det-urandom=off for tests of cryptographic randomness").

### D.3 Regression tests

* `node/test/p1-d-entropy-default.test.js`: a test uses `crypto.randomBytes(16)` for a temp name; serial vs
  `--det-workers=2`, no flag → `stable` (trunk: diverged). Option 3: a TLS/ws nonce stays real (an `entropy` event
  kept as today).
* Real difference: two runs with different `--det-seed`, the test failing on one byte value → diverged; and
  `--det-urandom=off` on both runs → diverged (today's verdict).

### D.4 Risks: as in the table; plus agentsys's atomic-write temp names become per-test deterministic: two concurrent
tests have different seeds (per test id), so their names differ; the same test in serial and parallel gets the same
name, which is the point. Effort 0.5 day after the decision.

## E. `fs.stat` / `readdir` recorded at real completion

### E.1 Root cause (confirmed)

`node/src/controls.js:37-38` install `fsorder` and `outside` before `controls.js:54` installs `ioorder`, so
`ioorder`'s wrapper is the outer one: the callbacks that record (`fsorder.js:62` `event('fs.readdir', …)` inside the
real callback; `outside.js:179-197`, the `stat`/`lstat`/`access` wrappers' `done`) run at the **real** completion, before
`ioorder` (`ioorder.js:154-171`, `complete`) holds the delivery for start order. In addition `fsorder.js:15-22`
captures `fs.readdir` & co. at **require time** (`controls.js:14`), so `fsorder` calls the original functions and
never goes through `ioorder` at all. claudekit's 22 E tests have equal sorted stat/readdir events and a different
order (`data/before/claudekit/E/events.json`). MEASURED.

### E.2 Proposed fix

Install `fsorder` and `outside` after `ioorder` (`controls.js`), and make `fsorder.installProcess` capture the
functions it wraps at installation (the `ioorder` ones). The recording callbacks then run when `ioorder` delivers, in
start order; the recorded events are unchanged (same op, same value), only their order is the program's. `verify` is
unchanged.

Why a real difference is still caught: the values are recorded as before; only the order in which equal events are
written follows start order, which is the order the test's callbacks already observe (Level 1). A completion
released by the 200 ms hold (`io.release`) is still recorded and still NOT PROVEN.

Counterfactual: E 22 → 15, identical 555 → 557 (MEASURED). The 12 tests left matching the E rule all carry
`uncontrolled.io` (F): their stats are delivered by the hold or overlap path; the F counterfactual alone took E from
22 to 14. E's full gain is therefore E + F, UNMEASURED; implement E after F.

### E.3 Regression test: `node/test/p1-e-fs-order.test.js` (in-process, a stub under `fs.stat` / `fs.readdir` that
completes two calls in reverse order; under the controls, the recorded events are in start order). Red on the trunk.
No real-difference test is needed beyond the existing ones: E changes no value. A different stat value still
diverges: the regression test also checks it.

### E.4 Risks: the wrapper order changes which wrapper sees which call first (`outside`'s `existsSync` / `statSync`
are synchronous: unchanged); `fsorder`'s glob wrappers already capture at install. Effort 0.5 day.

## F. One awaited call seen as overlapping operations

### F.1 Root cause (confirmed)

`node/src/ioorder.js:116-133` (`begin`) starts a tracked operation whenever a wrapped `fs` function is called while a
test runs, and marks the test `uncontrolled.io` as soon as two are pending (`:126-131`). It skips only calls made by
Node's internal fs code (`nodeInternal`, `:99-113`: `node:internal/fs/…` frames). Two engine-internal nestings are not
skipped:

1. **`facts.js:266-281`**: the engine's own `fs.promises.mkdtemp` (deterministic names) calls `fs.promises.mkdir`
   (`:274`), which is `ioorder`'s wrapper: one `await fs.mkdtemp(…)` is `fs.mkdtemp#0` and `fs.mkdir#1`, overlapping.
   claudekit `tests/utils/test-helpers.ts:16` (`await fs.mkdtemp(path.join(os.tmpdir(), prefix))`): 115 of the 225.
   The trace shows `uncontrolled.io @ tests/utils/test-helpers.ts:16`, `io.complete fs.mkdir#1`, `io.complete
   fs.mkdtemp#0` (MEASURED, `doctor.test.ts::…::should pass validation with complete setup`).
2. **`node:fs` itself**: callback `fs.writeFile` calls the exported `fs.open`, then `fs.write` / `fs.close` from its
   callbacks (`node -e` on Node 22.23.5: `fs.writeFile` source calls `fs.open(`). The frame is `node:fs`, not
   `node:internal/fs/`, so they are tracked: `writeFile#0` pending, `open#1` overlaps; `write#2` is begun from
   `open`'s callback and queued behind `writeFile#0`, which cannot complete before it: a self-deadlock until the
   200 ms hold (`HOLD_MAX_MS`, `:27`) releases it as `io.release` (`:187-200`). That is the investigation's ~12 s hold
   (P2 item 1). sqlectron `src/browser/core/utils/index.ts:47` (`fs.writeFile(filename, data, cb)`): its 8.

The F rule matches the investigation's examples: 13 of claudekit's 225 F tests are in `tests/commands/doctor.test.ts`,
and the example test above is one of them.

### F.2 Proposed fix

An operation is a child of the tracked operation in whose call, or in whose internal continuation, it starts; a
child is not tracked (it is part of its parent, which stays tracked). In `ioorder.js`:

* an `AsyncLocalStorage` holding the running tracked operation: `wrapCallback` / `wrapPromise` call `real` inside
  `als.run(op, …)`; `begin()` returns null when `als.getStore()` is a pending operation of the same test;
* the user's callback and the promise settlement are delivered outside it (`als.exit()` around `deliver`), so the
  test's next operation, started from its own callback, is tracked again;
* `nodeInternal()` also accepts `node:fs` frames (the counterfactual's rule), cheap and enough for the synchronous case.

The counterfactual used only the synchronous depth and the `node:fs` frame: F 225 → 12, identical 555 → 770, serial
21.0 s → 13.5 s (MEASURED). The 12 left are all `uncontrolled.io @ <deps>/graceful-fs/graceful-fs.js:54`: graceful-fs
replaces the global `fs.close` with its own wrapper, so `writeFile`'s internal `close` is called from a user-land frame
in `writeFile`'s internal continuation. The `AsyncLocalStorage` rule covers it (DECLARED; that is why the fix is not
the counterfactual's rule alone).

Why a real difference is still caught: operations the test itself starts concurrently (two `readFile` in
`Promise.all`, two connections) are not children of each other: each starts in the test's context, not inside a
tracked call, so they are tracked, overlap, and the test stays `uncontrolled.io` / NOT PROVEN with `io.complete`
events, exactly as today. Only an operation that cannot be observed separately — the steps of one call — stops being
counted as concurrency.

nestjs-pino's 8 F (`uncontrolled.io @ <deps>/superagent/lib/node/index.js:958`, an HTTP request to the app under
test) are a different shape, a connection overlapping with another pending operation: not covered by the
counterfactual (it ran on claudekit), cause UNKNOWN; possibly real concurrency. The after measurement will show
whether the fix moves them.

### F.3 Regression tests

* `node/test/p1-f-nested-io.test.js`: under `--det`, a test does `await fs.promises.mkdtemp(...)`, `fs.writeFile(p,
  d, cb)`, `fs.appendFile`, and `writeFile` with graceful-fs loaded: no `uncontrolled.io`, no `io.release`, and the
  test takes less than the hold (200 ms). Trunk: `uncontrolled.io` and `io.release` present (red).
* Real difference (concurrency still seen): `await Promise.all([fs.promises.readFile(a), fs.promises.readFile(b)])` →
  still `uncontrolled.io` + `io.complete` events, NOT PROVEN.

### F.4 Risks and the I/O hold (P2 item 1)

* An operation wrongly taken for a child would hide real concurrency; the `als.exit()` around delivery is what
  prevents the test's own follow-up operations from inheriting the parent. The real-difference test above guards it.
* Side effect on P2's hold, MEASURED with the counterfactual on claudekit: `--det` serial 21.69 / 21.05 s → 13.47 s,
  parallel 20.95 / 21.61 s → 12.65 s (plain serial 7.00 / 6.53 s). No other P2 work.

### F.5 Effort: 1 day.

## 4. What the measurement found that is not P1

Listed so the coordinator can route them; not part of this design.

* codex-multi-auth: **2,933 order divergences** between S1 and P1w4 and between S1 and S2 (reason `order`): the
  serial run's in-process predecessor order differs between two serial runs.
* KEPT variables read inside tests (`uncontrolled.env`): agentsys 117 NOT PROVEN (S1 vs P1w4), codex-multi-auth 208 (S1 vs S2).
* Child processes (`uncontrolled.child`): agentsys 84; extra `os.tmpdir` events present in one run only (agentsys
  351 diverged with reason `other`, first differing event `os.tmpdir`).
* sqlectron: a native addon loaded outside any test makes all 43 tests NOT PROVEN (counted under A by the rule).
* sqlectron's spec install line leaves `sqlite3` unbuilt (`specs.json` is Lane-owned: `harness/parallel_measure/` is
  not touched here).

## 5. Files

* `harness/p1/setup.sh` — the setup (with the sqlectron deviation).
* `harness/p1/tally.py` — the classification.
* `harness/p1/before.json`, `before-round2.json`, `before-serial-pair.json`, `before-sqlectron-rebuilt.json`,
  `before-sqlectron-rebuilt-serial-pair.json` — the tallies.
* `harness/p1/counterfactual.json` — the six counterfactual tallies.
* `harness/p1/data/before/<repo>/` — `results.jsonl` (the repository's rows), every `verify*.json`, the header line of
  each `S<i>.jsonl` / `P<i>w4.jsonl` (`*.header.json`), `E/events*.json`.
* `harness/p1/data/counterfactual/<item>/` — the same for each counterfactual round, plus the A digest log
  (`A/envdig/`) and the B skip log (`B/skipped/`).
