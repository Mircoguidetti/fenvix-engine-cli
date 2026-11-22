# Engine investigation, 2026-11-22: where `--det` serial time goes, what breaks serial-vs-serial, skipped tests

Measure only: no engine code, test or harness file was changed. One counterfactual was run on a **scratch copy**
of `node/` (outside the repository) with one constant changed; it is labelled as such wherever used.

Labels: **MEASURED** (command given), **ESTIMATED** (derived, method given), **DECLARED** (read from code/docs,
file:line given), **UNKNOWN**.

## Setup (MEASURED)

* Engine: trunk `5a6463fd` (this branch's base), `cd node && npm run build`, `maturin build --release`; wheel
  installed into a Python 3.12 venv with pytest, pytest-xdist, numpy, scipy, matplotlib, pandas, py-spy.
* Machine: this session's container, `nproc` = 4. One measurement at a time, nothing else running.
* Repositories at the pinned commits: claudekit `f22a4f90` (`harness/serial_scan/candidates.json` on
  `claude/serial-scan`), sqlectron `b0f5e240`, networkx `6c1a31d1` (`harness/parallel_measure/specs.json`).
  claudekit: `npm install --ignore-scripts` (no lockfile; 12,342 files under node_modules). sqlectron:
  `npm ci` fails (lock out of sync, as session B found), `npm install --ignore-scripts`, then `npm rebuild sqlite3`
  (without the native binding 3 of 7 files fail to load in both plain and `--det`; with it the run matches the
  sessions' 42 traced tests and 5 diverged). networkx: `pip install --no-deps -e networkx`.
* Commands (from the repository directory; `$E` = engine checkout, `$C` = scratch engine copy):
  * plain: `npx --no-install vitest run [args] --no-file-parallelism`; pytest: `python -m pytest --doctest-modules
    --pyargs networkx -q -p no:cacheprovider --det-outcomes=...` (bare: same with `-p no:detpy`)
  * `--det` serial: `node $E/node/bin/detjs.js vitest run [args] --det --det-workers=1 --det-trace=S.jsonl`;
    pytest: `... --det --det-trace=S.jsonl`
  * serial noise: `python -m detpy.fenvix verify S1.jsonl S2.jsonl --json`
  * sqlectron args: `test/browser test/renderer test/common`
* Phase timestamps: `docs/investigation-2026-11-22/tl.py` stamps the first output line of each phase (vitest
  `RUN`, vitest `Duration`, `detjs: trace ...`) and the exit, 3 repetitions each. Raw rows:
  `claudekit-timeline.jsonl`, `sqlectron-timeline.jsonl`.
* The sessions' own verify JSONs and traces are not on `claude/parallel-measure{,-b,-c}` (only `measure.py`,
  `specs.json`, `table.py`, `RERUN.md`, `TABLE-b.md`), so every Q2 number below comes from my own two runs.

---

## 1. Where the time goes

### claudekit (vitest, 764 traced tests, 41 files). Means of 3 runs

| | plain serial | `--det` serial | `--det` serial, scratch copy with `HOLD_MAX_MS = 1` |
|---|---|---|---|
| wall, MEASURED | **6.36 s** (6.05 / 6.37 / 6.67) | **21.49 s** (21.64 / 21.56 / 21.27) | 8.91 s (8.63 / 9.16 / 8.95) |
| CPU of the process tree, MEASURED | 7.1 s | 11.1 s | 10.6 s |

Split of the +15.13 s (`--det` minus plain):

| share | seconds | % | label and how it was measured |
|---|---|---|---|
| **I/O ordering hold** (`node/src/ioorder.js`, below) | **12.58** | **83.1 %** | MEASURED: in-run time of `--det` minus the same with `HOLD_MAX_MS = 1` in a scratch copy (20.51 s vs 7.93 s, RUN→Duration). Idle time: CPU stays ~11 s in both |
| other per-test instrumentation | 2.23 | 14.7 % | MEASURED: in-run time of the scratch copy minus plain (7.93 s vs 5.71 s). CPU profile of the test worker (`--poolOptions.forks.execArgv=--cpu-prof`): engine JS 0.85 s (sites.js 0.31, deadline.js 0.15, ioorder.js 0.09, outside.js 0.06, …); vite-node `source-map.mjs` 1.10 s vs 0.14 s in plain, ESTIMATED as caused by the engine's stack captures (`sites.resolve` → `Error.captureStackTrace` → vite-node's `prepareStackTrace`) |
| deps hashing (`node/src/loaded.js`) | 0.29–0.38 | ~2 % | MEASURED standalone: `node deps_time.js $E <repo>` calls `depsInput` 3 times: 384 / 296 / 285 ms for 12,342 files (247 MB) |
| trace writing, plan, rest after vitest | ~0.1 | ~0.7 % | ESTIMATED: Duration→exit is 0.55 s under `--det` vs 0.13 s plain, minus deps hashing |
| engine start-up | −0.10 | −0.6 % | MEASURED: start→`RUN` 0.43 s vs 0.53 s plain (plain goes through `npx`; detjs starts node directly) |
| verify/merge | 0.16 | (separate command) | MEASURED: `fenvix verify S1 S2 --json` |

### sqlectron (vitest, 42 traced tests, 7 files). Means of 3 runs

Plain re-measured once Electron's binary was present: the first plain runs went through
`node_modules/electron/index.js:9-16`, which tries to download the binary, takes ~11 s and fails 2 files. So
plain serial depends on install state, and the sessions' 4.96 s may be the run with 3 files failing to load
(UNKNOWN). Like-for-like:

| | plain serial | `--det` serial | scratch copy `HOLD_MAX_MS = 1` |
|---|---|---|---|
| wall, MEASURED | **6.52 s** (6.58 / 6.37 / 6.62) | **21.18 s** (21.12 / 21.12 / 21.30) | 9.35 s (9.47 / 9.29 / 9.30) |

| share of +14.66 s | seconds | % | how |
|---|---|---|---|
| **I/O ordering hold** | **11.97** | **81.7 %** | MEASURED, same method as claudekit. `test/browser/servers.test.ts` alone: 12.56 s under `--det`, 13 tests at 604–1219 ms each |
| deps hashing | 1.28–1.59 | ~9.5 % | MEASURED standalone: 1588 / 1362 / 1281 ms for 68,577 files (862 MB) |
| trace writing, plan, rest after vitest | ~0.1 | ~0.7 % | ESTIMATED: Duration→exit 1.67 s vs 0.13 s plain, minus deps hashing |
| other per-test instrumentation | 1.29 | 8.8 % | MEASURED: scratch copy in-run minus plain in-run |
| engine start-up | −0.14 | −1.0 % | MEASURED |
| verify/merge | 0.11 | (separate) | MEASURED |

### The mechanism behind the ~12 s in both Node repositories (DECLARED from code, MEASURED in the trace)

`node/src/ioorder.js` delivers a test's concurrent file operations in start order. A completion that arrives
before an earlier-started operation has been delivered is held, and a 200 ms real-time timer releases everything
(`HOLD_MAX_MS = 200`, line 27; `complete()` lines 153-168; `releaseAll(true)` lines 186-201). When the test calls
graceful-fs's `writeFile` (fs-extra and sqlectron's `src/browser/core/utils/index.ts:47` both go through it),
the engine tracks the outer `fs.writeFile#n`, and also the `fs.open#n+1`, `fs.write#n+2`, `fs.close#n+3` that
Node's own writeFile issues through graceful-fs's patched `fs.open` and friends. `nodeInternal()` (lines 99-112)
does not exclude them, because the first frame outside the engine is graceful-fs, not `node:internal/fs`. Each
inner operation is then held behind the outer one, which can only finish after them. So each one waits the full
200 ms: 3 × 200 ms = 600 ms per `writeFile`. The trace shows it. claudekit
`tests/unit/list-hooks.test.ts` "should show configured hooks with project source": `uncontrolled.io` at
`<deps>/graceful-fs/graceful-fs.js:138`, then `io.release fs.open#4`, `io.release fs.write#5`,
`io.release fs.close#6`. The test takes 615 ms under `--det` and ~5 ms plain, and tests with two config files
take 1215 ms. Each release also calls `STATE.onRealClock('a file operation was delivered out of start order (real
time decided)')` (line 196).

### networkx (pytest, 11,039 traced tests)

| run | wall, MEASURED | outcome |
|---|---|---|
| bare (`-p no:detpy`, run first, cold caches) | 151.7 s | 1 failed, 10220 passed, 85 skipped, 741 xfailed |
| plain (`--det-outcomes`) | **139.7 s** | same |
| `--det` serial S1 under `py-spy record -r 50 --native` | 682.7 s | same (profiler overhead included) |
| `--det` serial S2, no profiler | **564.4 s** (4.04x plain) | same |
| `--det` serial, `FENVIX_NO_PROVABLE_SENSOR=1` | **151.6 s** | same (verdict refused by design, timing only; switch DECLARED at `docs/REPORT-verifier-rule.md:235`) |

| share of +424.7 s | seconds | % | how |
|---|---|---|---|
| **provable sensor**: `sys.monitoring` CALL callback on every call (`python/detpy/provable.py:406-407`, `Sensor._on_call`) plus its audit hook | **412.8** | **97.2 %** | MEASURED counterfactual: S2 minus the sensor-off run. py-spy: `Sensor._on_call` on the stack in 49.6 % of samples, `check_native` 2.2 %, `_on_audit` 2.1 %, Rust `sysmon::audit_hook` 4.8 % (the C-level dispatch into the callback is partly attributed to callers, so the counterfactual is the number to use) |
| everything else in `--det`: start-up (precompile 0.013 s, header `precompile_s`), Level-0 controls (osstate 3.7 %, `level0_end`/`end_test` 2.8 % of samples), deps/code inputs, trace writing (220 MB) | 11.9 | 2.8 % | MEASURED as a total (sensor-off minus plain); split UNKNOWN. py-spy shows Rust `BufWriter` flush at 0.1 % |
| deps hashing | ≈0 | – | DECLARED: Python hashes only the modules that were loaded, not site-packages (`python/detpy/_level0.py:651-661`; header: `deps` = 588 files, `code` = 580 files) |
| verify/merge | 5.83 | (separate) | MEASURED: `fenvix verify S1 S2 --json` on two 220 MB traces |

This contradicts the engine's own cost claim. `docs/REPORT-verifier-rule.md:231` measured the sensor at
**+3.0 %** on a 24-test suite; on networkx it is **+296 %** of plain.

Hypothesis check (`node/src/loaded.js:5-6`, "every file is hashed on every run"): **confirmed, but small.**
It holds for Node (12,342 and 68,577 files re-read and digested each run). It costs 0.3 s (2 %) and 1.3–1.6 s
(9.5 %) of the overhead, not the ~15 s. Python does not do it.

---

## 2. What breaks serial-vs-serial

Two `--det` serial runs, then `fenvix verify S1 S2 --json`, all MEASURED. Per-group lists with the first
differing events: `docs/investigation-2026-11-22/<repo>-verify-serial-vs-serial.txt` (made by `vsum.py`).

| repo | tests | identical | diverged | not proven | order identical |
|---|---|---|---|---|---|
| claudekit | 764 | 507 | **25** (sessions saw 21: the count itself varies run to run) | 232 | yes |
| sqlectron | 42 | 0 | **5** | 37 | yes |
| networkx | 11,039 | 0 | **0** (fingerprints all equal) | **11,039** | yes |

### A. Engine nondeterminism (the engine records something that is not stable)

| channel | count | example test | first differing event (run A / run B) | cause |
|---|---|---|---|---|
| `fs.stat` order | claudekit 12 diverged | `tests/commands/doctor.test.ts::doctor command::validation failures::should fail when settings.json contains invalid JSON` | event #24 `fs.stat <tmp>/.claude/settings.json\|file size=16` / `fs.stat <tmp>/.claude/hooks\|dir` | DECLARED: `outside.js` is installed at `controls.js:38`, below `ioorder.js` (`controls.js:54`). So `onStat` records in `done` (`outside.js:180-195`) in the **real completion order**, before ioorder puts deliveries into start order. The values are the same; the order is real-time |
| `fs.readdir` order | claudekit 3 diverged | `tests/unit/loaders/agent-loader.test.ts::AgentLoader::constructor::should initialize successfully when agent directories exist` | event #10 `fs.readdir <tmp>/.claude\|1\|585b…` / `fs.readdir <tmp>/src\|1\|585b…` | same layering: `fsorder.js` installed at `controls.js:37`, records at completion (`fsorder.js:48`) |
| `io.release` (hold timer decides) | claudekit 17, sqlectron 13 tests carry it | `test/browser/servers.test.ts::servers::.getAll::should load servers from file` | (marks these tests NOT PROVEN, `uncontrolled.io` at `graceful-fs.js:138`) | DECLARED, section 1: one awaited `writeFile` counted as concurrent with its own inner open/write/close |
| `uncontrolled.io` on code that awaits sequentially | claudekit ~211 more not-proven | `tests/commands/doctor.test.ts::…::should pass validation with complete setup` | `uncontrolled.io @ tests/utils/test-helpers.ts:16`, completions `fs.mkdtemp#0`, `fs.mkdir#1` | ESTIMATED engine-side: line 16 is `await fs.mkdtemp(...)` (fs-extra → graceful-fs), so the overlap is probably one logical operation tracked twice (wrapper on wrapper). Not proven by a counterfactual (UNKNOWN until checked) |

### B. A real uncontrolled source in the test

| channel | count | example test | first differing event | note |
|---|---|---|---|---|
| entropy: `crypto.randomBytes` | sqlectron 4 diverged | `test/browser/servers.test.ts::servers::.add::should add new server with ssh` | event #11 `crypto.randomBytes @ src/browser/core/crypto.ts:16` `16:6a6c…` / `16:6322…` | the run banner says `entropy=observed (--det-urandom to control)`. The engine can control it with a flag that `measure.py` does not pass |
| entropy: `crypto.randomFillSync` (uuid) | sqlectron 1 diverged | `…::.add::should add new server` | event #11 `<deps>/uuid/dist/rng.js:18` `256:f809…` / `256:3681…` | same |
| pid | claudekit 2 diverged | `tests/integration/setup-embedded-hooks.test.ts::…::Installation types::should handle user-only installation` | event #523 `process.pid @ <deps>/signal-exit/index.js:15` `6d61e3dadb16` / `8421099d8209` | the real pid is recorded (hashed), not virtualized |
| child-process timing (`git`) | claudekit 7 diverged (5 + 2) | `tests/integration/workflow.test.ts::…::should handle force reinitialize workflow` | event #83 `child.exit @ cli/lib/project-detection.ts:653 = 0\|` / `fs.stat <tmp>/vite.config.js\|missing` | a real race between a child's exit and fs completions. The fs side is recorded in completion order (A, row 1), so fixing A narrows this to the child itself |
| fs time (`mtimeMs` of a file written in the test) | claudekit 1 diverged | `tests/lib/components.test.ts::…::Caching::should invalidate cache when forced` | event #32 `fs.stat.mtimeMs @ cli/lib/filesystem.ts:330` `+0.00390625` / `+0` | DECLARED by design: `fstime.js:19-21` |
| child process, NOT PROVEN | claudekit 2 (+1 with io) | `tests/unit/self-review.test.ts::…` | `uncontrolled.child execFile git rev-parse --show-toplevel @ cli/hooks/utils.ts:93` | declared gap |
| env (CI-volatile variable) | claudekit 1 | `tests/colors.test.ts::…::should enable colors by default in TTY` | `uncontrolled.env @ tests/colors.test.ts:18` | declared gap |
| thread | networkx 1 | `networkx/utils/tests/test_decorators.py::TestArgmap::test_lazy_compile_thread_safety` | `uncontrolled.thread @ test_decorators.py:531` | declared gap |

### C. Native / unaudited

| channel | count | example | detail |
|---|---|---|---|
| native extension loaded, not audited | **networkx 10,039**, sqlectron 29 | `networkx/algorithms/approximation/__init__.py::networkx.algorithms.approximation` | networkx: 150 distinct `native:` entries, 63 in **every** test (numpy `_multiarray_umath`, matplotlib `_path`/`ft2font`/`_image`, `PIL._imaging`, `kiwisolver._cext`, …), loaded at import, outside any test. sqlectron: `native:…/sqlite3/build/Release/node_sqlite3.node` read outside any test, so every test of the run is NOT PROVEN |
| api not accounted for (calls into native code) | networkx 999 (1,000 tests carry ≥1), claudekit 1 | `networkx/algorithms/approximation/density.py::…densest_subgraph` | 141 distinct, top: `numpy…_make_extobj` (509 tests), `numpy…_array_converter(.wrap)` (478), `scipy.sparse._sparsetools.coo_tocsr` (425), `…csr_has_canonical_format` (373), `numpy…_unique_hash` (326). Header `not_proven_outside_tests` lists more numpy APIs. claudekit: `api:tty.isatty` |

On networkx every fingerprint is equal across the two runs, so the verdict "identical" is blocked only by C (plus
1 thread).

---

## 3. Skipped tests

**MEASURED:**

| repo | runner says | trace has | missing from trace |
|---|---|---|---|
| claudekit | 814 tests, 51 skipped | 764, 1 skipped | **50**, all skipped: `tests/hooks/integration.test.ts` 26, `tests/integration/cli-show.test.ts` 19, `tests/config/vitest-configs.test.ts` 3, `tests/unit/agents/registry-grouping.test.ts` 2 |
| sqlectron | 43 tests, 1 skipped | 42, 0 skipped | **1**: `test/browser/config.test.ts::config::.prepare::should include id for those servers without it` |
| networkx | 11,039 items (77 skipped) + 8 module-level skips in the summary | 11,039, 77 skipped | **0** (the 8 module-level skips have no test item in either map) |

**DECLARED: why, from code.** The vitest shell records a test only from `onBeforeRunTask`
(`node/src/vitest/shell.js:182-202`). A skipped test that reaches the hook is recorded as `skipped` (line 201).
That is the one present in claudekit, `it.skip` at `vitest-configs.test.ts:63` inside a running `describe`.
Vitest does not call the hook for tests inside `describe.skip` (`integration.test.ts:172…`, `cli-show.test.ts:101`)
or inside a suite whose tests are all skipped (sqlectron `config.test.ts:17-19`), so those never reach the trace.
`writeCapture` (`shell.js:28-31`) does add "tests that never reached the runner hooks (skipped by a failing
hook, filtered) … as skipped", but only to the **cache capture**, not to the trace. No document says the trace
leaves skipped tests out (`docs/TRACE.md`, `docs/VERIFY-CONTRACT.md`, `docs/NODE.md:75` says the outcomes JSON
holds `skipped`). pytest records them (networkx: equal maps).

**Verdict:** a Node-side **bug, not by design**. Recording depends on how the skip is written (`it.skip` in a
running suite vs `describe.skip`), the cache already handles the same tests, and pytest has no such gap. It does
not make serial-vs-serial verify fail, because both traces omit the same tests (`TRACE.md:92`: `missing` = not
in every trace).

**`measure.py`:** `compare_outcomes` marks a row identical only if `set(a) == set(b)`. `runner_outcomes` keeps
`pending/todo/skipped` (normalised to `skipped` by `norm`), so every row with a static `describe.skip` reads "not
identical" for tests that ran in neither. Until the engine is fixed, the comparison should treat
"skipped in plain and absent from the trace" as agreeing and report that count in its own column. It should not
drop them silently, because a test the plain run *ran* and the trace lacks must still count as a difference.
Nothing changed here, as asked.

---

## What to build or fix, ranked

(a) = parallel-with-proof faster than plain serial; (b) = verdict "identical".

1. **Fix the self-deadlock in `ioorder.js`.** Don't track an operation started from inside another tracked
   operation's call (or don't order an operation behind an ancestor that cannot complete first). **Saves
   12.6 s of 21.5 s on claudekit and 12.0 s of 21.2 s on sqlectron** (MEASURED counterfactual: `--det` serial
   8.9 s / 9.4 s vs plain 6.4 s / 6.5 s). For (a) this is the gate: sqlectron's `servers.test.ts` is one 12.5 s
   file, so detjs' own estimate at 4 workers is 13.05 s with the hold and 0.76 s without
   (`detjs: serial run` line, ESTIMATED by the engine), against 6.5 s plain. For (b) it removes 17 + 13 `io.release`
   NOT PROVEN tests and the "real time decided" release.
2. **Make the Python provable sensor cheap** (an identity-set fast path in front of `_on_call`, caching per code
   object, or `DISABLE` for monomorphic sites with a polymorphism check, against the trade-off in
   `REPORT-verifier-rule.md:127-156`). **Up to 413 s of 564 s on networkx** (MEASURED with the sensor off:
   151.6 s). With the sensor, even perfect 4-way parallelism (564 / 4 = 141 s, ESTIMATED) cannot beat plain
   serial at 139.7 s. Without it, 151.6 / 4 ≈ 38 s (ESTIMATED, before worker start-up). Effect on (a): decisive for
   every Python suite of this kind. On (b): none.
3. **Audit the common native extensions** (numpy core, scipy sparse/linalg, matplotlib, PIL, kiwisolver;
   node-sqlite3), or allow them on a declared, versioned list. **Turns networkx from 0 / 11,039 identical into up
   to 11,038 identical** (MEASURED: every fingerprint already equal; the only other cause is 1 thread test), and
   sqlectron's 29 native NOT PROVEN. The largest effect on (b) of anything here.
4. **Record `fs.stat`/`readdir` events at ordered delivery, not at completion.** Install `outside.js` and
   `fsorder.js` above `ioorder.js`, or record from ioorder's deliver. Removes claudekit's 15 fs-order
   divergences (MEASURED count) and narrows the 7 child-vs-fs ones. (b) only. Time: none.
5. **Find and stop the false `uncontrolled.io` on sequential awaits** (`test-helpers.ts:16`: one fs-extra
   `mkdtemp` seen as two overlapping operations). Up to ~211 more of claudekit's 232 NOT PROVEN (ESTIMATED, not
   yet proven by a counterfactual). (b) only.
6. **Pass `--det-urandom` in `measure.py`, or make it the default under `--det`.** Removes sqlectron's 5
   divergences, all of them (MEASURED count, entropy). Virtualize `process.pid`: claudekit 2. (b) only. Time:
   UNKNOWN, small.
7. **Record skipped tests the runner never hands to the hooks** (reuse `writeCapture`'s loop for the trace).
   Makes outcome maps equal: claudekit 50, sqlectron 1 (MEASURED). (b) for the harness's outcome check. Time:
   none.
8. **Cache the node_modules digest** across runs, keyed by an inode/ctime/size listing with a full re-hash on any
   change, or hash in the worker in parallel with the tests. Saves 0.3 s (claudekit) and 1.3–1.6 s (sqlectron)
   per run (MEASURED cost). (a): small but fixed per run, so it matters most on small suites. The engine's note
   says mtime proves nothing under npm's fixed 1985 mtime, so the key must not rely on mtime alone.
9. **Cut stack-capture cost under vitest** (`sites.js` 0.31 s plus vite-node source-map remapping it triggers,
   ~0.96 s ESTIMATED on claudekit). Use a structured `prepareStackTrace` that bypasses vite-node's remapper, or
   capture lazily. Up to ~1.3 s of the remaining 2.2 s in-run overhead on claudekit. (a) only.
10. **Separate cost to keep in view:** `fenvix verify` on networkx takes 5.8 s for two 220 MB traces (MEASURED).
    It is paid on every parallel-with-proof run, on top of the parallel wall time.

Not measured here: nestjs-pino's 1.24x (no writeFile-heavy file is known to me; UNKNOWN). Parallel `--det` runs
were not repeated, by scope.
