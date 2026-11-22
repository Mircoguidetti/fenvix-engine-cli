# Does parallel with proof work? Measurement on public repositories

Session `claude/parallel-measure`, 22 November 2026. Question: run a repository's existing suite in parallel and
prove the parallel result identical to the serial one. (1) Is the outcome identical, (2) how much faster, (3) does the
proof refuse where parallel really differs.

Labels: **MEASURED** (a run in `results.jsonl`, command in its `cmd` field), **DECLARED** (read from the repository at
the pinned commit, file and line given), **ESTIMATED**, **UNKNOWN**. Table: `TABLE.md`. Rerun: `RERUN.md`.

## Answer

On the four Node repositories of the plan measured here (serial-scan candidates whose CI runs serially on purpose;
engine trunk **bfaf70b4**; 4-vCPU container; 3 rounds; 2 and 4 workers):

* **(1) Identical outcome: 2 of 4** (nestjs-pino, agentsys: every test's outcome equal to the plain serial run in
  every round, MEASURED). On ironcurtain and codex-multi-auth the outcome maps differ (387 and 264-412 tests per round),
  most of it already in the engine's *serial* run, and in ironcurtain the parallel report drops 246 tests (below).
* **(2) Faster: 3 of 4** at 4 workers (nestjs-pino 1.93x, ironcurtain 2.97x, codex-multi-auth 2.37x the plain serial
  run; agentsys 0.69x, slower). In every repository the runner's own parallel mode without the engine is faster still
  (engine parallel / own parallel at 4 workers: 1.41, 3.68, 1.13, 1.49).
* **Proven identical: 0 of 4.** The engine called 0 tests identical on agentsys, ironcurtain and codex-multi-auth, and
  223 of 269 on nestjs-pino, in every round. Counting rule (coordinator): **0 rows count**.
* **(3) The proof refused wherever parallel differed: yes.** In no round of any repository did `fenvix verify` call a
  test identical whose outcome differed (checked: 1,338 identical verdicts, all on nestjs-pino, 0 with a differing
  outcome); every one of the 14 real order defects found (THEIRS) was refused, and for 13
  of them the parallel run reported the serial outcome. But the engine also refuses almost everything else: 16,764 of
  the 17,850 not-identical tests (94 %) are OURS (stable outcome in every run, plain and engine, serial, parallel and
  shuffled; refused anyway), and in each repository the same refusal appears when two *serial* runs are compared.

In one sentence: on these repositories parallel with proof is faster than serial on three of four but proven
identical on none, because the engine refuses for reasons that are not parallelism (run-level inputs, process ids,
files the suite writes itself) and on two of four its own runs change outcomes or drop tests.

## Per repository (trunk bfaf70b4, harness 18c5da5d)

| repo (runner) | DECLARED reason to run serially | plain serial | own parallel w4 | parallel with proof w4 | outcome map | engine verdict | boxes | counts |
|---|---|---|---|---|---|---|---|---|
| nestjs-pino 82d9219874 (Vitest 5.1.1) | `vitest.config.mts:24 fileParallelism: false` | 20.65 s | 7.57 s | 10.68 s, 1.93x | identical, 3/3 | 223/269 identical; 37-38 diverged, 8-9 not proven | OURS 46 | no |
| agentsys ce58913304 (Jest 30) | `jest.config.js:52 maxWorkers: 1` | 13.72 s | 5.39 s | 19.81 s, 0.69x | identical, 3/3 | 0/2,224 identical | OURS 2,224 | no |
| ironcurtain abf2b44c2e (Vitest 4.1.11) | `vitest.config.ts:45 fileParallelism: false` (a project) | 233.41 s | 69.56 s | 78.48 s, 2.97x | differs: 387 differ, 366 missing | 0/6,913 identical; 6,667 diverged, 246 missing | OURS 6,277, UNDECIDED 632, THEIRS 4 | no |
| codex-multi-auth b9886168aa (Vitest 5.0.5) | `package.json test = vitest run --maxWorkers=1`; `vitest.config.ts:40-46` (fixed OAuth port 1455, shared-port suites) | 386.34 s | 109.58 s | 163.22 s, 2.37x | differs: 264-412 differ | 0/8,660 identical; 8,658 diverged | OURS 8,217, UNDECIDED 434, THEIRS 10, ENV 6 | no |

All MEASURED medians of 3 rounds (`TABLE.md` has the 2-worker rows and every column). `--det` serial costs 1.07-1.65x
the plain serial run (nestjs-pino 1.26, agentsys 1.65, ironcurtain 1.07, codex-multi-auth 1.19).

**nestjs-pino.** The only blocker left on the trunk is `process.pid`: 35-36 tests diverge at a `process.pid` read inside
NestJS's own logger (`<deps>/@nestjs/common/services/console-logger.service.js:265`), which differs in every process;
the engine records it but does not control it. 7-8 more are not proven for uncontrolled I/O readiness (superagent), 2
for fs, 1 for a proxy/CI variable read by `debug`. Outcome stable in all 13 runs of every one of the 46.

**agentsys.** 1,668 tests are refused for one run-level cause: environment and proxy variables (`env:*`, `HTTPS_PROXY`,
`NO_PROXY`, `PWD`, `SHLVL`, `TMPDIR` ...) read *outside any test*, which makes every test of the run not proven; 355
diverge on an `os.tmpdir` event present in one run and absent at the same position in the other
(`event #2: [outcome] outcome = passed <> [other] os.tmpdir @ __tests__/pipeline.test.js:30`); entropy 99, child 82,
fs 18. Parallel with proof is slower than plain serial (19.81 s vs 13.72 s at 4 workers; Jest's own 4 workers: 5.39 s).

**ironcurtain.** Every test diverges on one run-level input: files the suite writes under hard-coded `/tmp` paths
named with the process id (`test/mcp-roots-race.integration.test.ts:41` `/tmp/ironcurtain-roots-race-a-${process.pid}`,
`test/argument-validation.integration.test.ts:32`), git repositories created and deleted by the tests; the engine
records files read outside the project as an input of the whole run (`file:<abs>/<git object>`), so all 6,667 executed
tests diverge. `hardcoded_tmp=yes` is recorded in the engine runs, `no` in the plain runs (why the plain runs leave
nothing in `/tmp`: UNKNOWN; the tests may clean up only when they pass). 206 tests pass in plain Vitest and fail under
the engine's *serial* run. 246 tests are missing from the parallel report (engine finding 4); 120 are in no engine
trace at all (engine finding 5).

**codex-multi-auth.** Every test diverges on one run-level input: a file the suite itself writes in the temporary
directory during the run (`file:<tmp>/api-routes.json differs: "stat:file size=274" vs <not recorded>; also
file:<tmp>/openai-codex-accounts.json`), seen in one run and not the other. Its stated reason to run serially, the
fixed port 1455, caused no extra failure in the 6 timed plain parallel runs (2 and 4 workers): 6 failed in each, the same 6-7
  environment failures as plain serial (no IPv6 `::1`, a missing copied file).

## Real defects found (THEIRS), all reproduced without the engine

`bugs/<repo>.md`: test, plain runs where it failed and passed, the engine's cause and first differing event, the plain
command that reproduces it. Nothing was published or reported to anyone.

* **codex-multi-auth, 10.** 7 order-dependent tests that fail in both shuffled plain runs (`test/storage.test.ts`
  import/export (5) and `clearAccounts removes discovered backup artifacts`, `test/repair-commands.test.ts`
  `runVerifyFlagged ...`); 3 that failed once in 7 plain runs (`codex-bin-wrapper` stress test "expected 5 to be less
  than 5", `codex-manager-cli` concurrent refresh, `runtime-transcription-proxy`). For all 10 the parallel run reported
  the serial reference outcome (condition 4: yes).
* **ironcurtain, 4.** `docker-agent-adapter` Agent Registry (2) and `llm-metrics-retention-runtime` fail in both shuffled
  plain runs; `proxy-integration` "lists initial domains" failed in one. The last is among the 246 tests the parallel
  report drops (condition 4: no).
* nestjs-pino, agentsys: none.

## Engine findings (no engine code changed; fixes described, not written)

1. **`.vitest-cache` counted as an installed dependency** (`node/src/loaded.js:13`): every Vitest 5 run diverged on
   `deps`, serial vs serial included (nestjs-pino 269/269 on 5a6463fd). Fixed on the trunk by another session (bfaf70b4).
2. **Run-level inputs refuse every test of the run.** Environment variables read outside any test (agentsys 1,668;
   codex-multi-auth 4,295 on 5a6463fd), and files *the run itself writes* in the temporary directory or under a
   hard-coded path (codex-multi-auth 8,658; ironcurtain 6,667). The refusal is at run granularity: one read outside any
   test makes all tests not identical. A per-test attribution of these inputs (or excluding files the run created
   itself) is the fix this data asks for.
3. **`process.pid` observed, not controlled** (nestjs-pino 36 of the 46).
4. **The one-lane hazard re-run ran 0 tests and is still what is reported** (ironcurtain, every round, before and after
   the temp-dir fix): "detjs: trace .detjs/hazard-rerun-<pid>/rerun.jsonl: 0 tests" and "detjs: parallel: the one-lane
   re-run is what is reported for main|<136 files>: 0 failed of 0 test(s)"; 246 tests in 6 of those files vanish from the
   parallel report (plain: all passed; serial reference: 143 passed, 103 failed). `fenvix verify` marks them missing, so
   they are never called identical, but the run itself presents an empty re-run as clean. Likely cause, UNKNOWN (not
   verified): the re-run's file selection by Vitest project (`main|<file>`) matches no test.
5. **Tests absent from every engine trace**: 120 ironcurtain tests (integration files: auto-approver-integration 25,
   escalation-scenarios 18, apple-container, uid-remap ...) are in no `--det` trace, serial or parallel; plain Vitest
   runs and passes them.
6. **The engine changes outcomes in serial**: ironcurtain 206 tests pass plain and fail under `--det` serial;
   codex-multi-auth 382 on 5a6463fd (434 UNDECIDED on bfaf70b4: outcome stable in every plain run, different under the
   engine). Whether each is an engine defect or a test that depends on a source the engine pins: UNDECIDED.
7. **An `os.tmpdir` read recorded in one run and not the other** at the same position (agentsys 355).
8. **Docs vs code**: `docs/NODE.md:230` says `--det` is serial by default; `node/src/parallel.js:62` makes it parallel
   with the machine's CPUs. The first yaml measurement used `--det` as its serial reference and was thrown away; the
   harness now passes `--det-workers=1`.
9. Python (data only, 5a6463fd): unaudited native extensions make nearly every test not proven (networkx: native
   5,066, placement 5,592 of 11,039; attrs: `hypothesis._native` 1,385 of 1,412), serial vs serial included; parallel
   was slower than plain serial on both (0.64x, 0.22-0.31x).

## What was measured, and how

* **Engine.** Every row of `results.jsonl` names its `engine_commit`: `origin/claude/release-1` only when the engine
  sources of this checkout equal it. Final set: **bfaf70b4** (nestjs-pino, agentsys, ironcurtain, codex-multi-auth).
  Earlier sets, kept apart in `data/earlier/` and not used for the verdict: 5a6463fd with the first harness
  (networkx, attrs, and invalid yaml rows), 5a6463fd before and after the D13 harness fixes, ironcurtain on bfaf70b4
  before the D18 temp-dir fix. d83f58fe was built and discarded when the trunk moved before any row was kept.
* **Invocation.** Node: `node node/bin/detjs.js vitest run|jest --det --det-workers=1` (serial reference) and
  `--det --det-workers=N` (parallel), then `python -m detpy.fenvix verify S P --json`. Python: `pytest --det` and
  `pytest --det -n N`, same verify.
* **Baselines.** Plain serial: the runner directly (`npx --no-install vitest run --no-file-parallelism` / `npx jest
  --runInBand`, JSON report, plus a harness reporter that names Vitest projects). The runner's own parallel mode
  (`--maxWorkers=N`), no engine, timed every round.
* **State.** Before every run: tree reset to the pinned commit, fresh empty `TMPDIR=/tmp/pm-<repo>`; new entries in
  the real `/tmp` recorded per row. Engine state round 1 cold, rounds 2-3 warm, per kind and worker count.
* **Classification** (`classify.py`): THEIRS = outcome differs between plain runs (3 plain serial, 2 plain 4-worker,
  2 plain shuffled); ENV = failure message names this container (no IPv6 `::1`, missing copied file); UNDECIDED =
  stable in plain, different under the engine, or missing; OURS = stable everywhere, refused anyway.
* **Machine.** 4 vCPU, Intel(R) Xeon(R) Processor @ 2.10GHz, 16 GB; one measurement at a time; CPU busy share sampled
  1 s before each run: no run above 80 % (no NOISY row).
* **Repositories not measured.** react-confirm-alert (Vitest browser mode, Playwright browsers not installed, refused
  for parallel by detjs); claudekit, sqlectron, wind-comic and the other serial-scan candidates (given to sessions B and
  C by the coordinator); the Go candidates (Python and Node only); nhsuk-frontend (Puppeteer). faker and mpmath were
  prepared and dropped (Node only, founder D14).
* **Leftovers.** codex-multi-auth's suite leaves `slow-router.mjs` child processes running (idle, 0 % CPU); they were
  left alone.
* **Engine code**: not changed by this session.
