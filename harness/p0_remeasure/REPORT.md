DONE

# P0 re-measure: agentic-qe and ironcurtain on the trunk engine

Engine (after): trunk `claude/release-1` e7338950262acc4bd24ed6d3af6a59e3f765a3af (contains the P0 merge 81f838c6;
`git merge-base --is-ancestor 81f838c6 <engine_commit>` true for every `after` row). Engine (before): bfaf70b4
(`engine_commit` = `bfaf70b48eae3073ec8d20f24e551984528d3648+modified` in every `before` row: the harness directory was
checked out from claude/release-1, the engine sources are bfaf70b4's). Machine: this container, nproc 4, Node v22.23.5.
Harness: `harness/parallel_measure/measure.py` of claude/release-1, unchanged. Checker:
`harness/p0_remeasure/check_p0.py` (17 tests in `test_check_p0.py`, `pytest harness/p0_remeasure/test_check_p0.py`: 17
passed). Per-run rows: `harness/p0_remeasure/results.jsonl`; measure.py's raw rows: `raw/before-results.jsonl`,
`raw/after-results.jsonl`. Nothing was written to `harness/parallel_measure/` or engine code.

## Verdict per repository (trunk engine, MEASURED)

| repo | engine runs | completed | C1 false green (runs) | C2 dropped (tests) | C2_runs | C3 missing from trace (tests) |
|---|---|---|---|---|---|---|
| ironcurtain | 9 (3 rounds) | 9 | **0** | **0** | **0** | **0** |
| agentic-qe | 3 (1 round) | 3 | **3** | **0** (status-backed runs: none) | **3** (`no status`) | **0** |

Commands (cwd `harness/parallel_measure` of the trunk checkout, `PM_WORK=/tmp/pm-p0`):

- ironcurtain: `python3 measure.py --spec specs.json --name ironcurtain --reps 3 --workers 2,4 --skip plain_par --out /tmp/pm-p0/after`
  (observed: 3 plain runs exit 1, 9 engine runs exit 1, 6 verify exit 1), then
  `python3 harness/p0_remeasure/check_p0.py /tmp/pm-p0/after ironcurtain --phase after` (observed: C1 0, C2 0, C2_runs 0, C3 0).
- agentic-qe, three calls in sequence with `--reps 1 --first-rep 1 --workers 2,4 --timeout 14400 --out /tmp/pm-p0/after`
  and `--skip plain_par,serial,par`, then `--skip plain_par,plain,par`, then `--skip plain_par,plain,serial`
  (observed: plain exit 1; engine serial exit 0; engine par w2 exit 0; engine par w4 exit 0; verify w2 exit 1; verify
  w4 exit -9), then `python3 harness/p0_remeasure/check_p0.py /tmp/pm-p0/after agentic-qe --phase after` (observed:
  C1 3, C2 0, C2_runs 3, C3 0).

C2 = 0 on agentic-qe is not evidence that nothing was dropped: none of its three runs has a user report (status) to
compare with P; all three are counted in `C2_runs` instead.

## Negative control: ironcurtain on the old engine bfaf70b4 (1 round)

| C1 (runs) | C2 | C3 (tests) |
|---|---|---|
| 0 | n/a: pre-P0 engine | **852** = 120 (serial) + 366 (w2) + 366 (w4) |

Command (`PM_WORK=/tmp/pm-p0-before`, cwd `/tmp/pm-p0-before/engine/harness/parallel_measure`):
`python3 measure.py --spec specs.json --name ironcurtain --reps 1 --workers 2,4 --skip plain_par --out /tmp/pm-p0-before/before`
(observed: plain exit 1, the three engine runs exit 1, verify exit 1 twice), then
`python3 harness/p0_remeasure/check_p0.py /tmp/pm-p0-before/before ironcurtain --phase before` (observed: C1 0, C3 852).

The checker sees the old "never started tests missing from the trace" defect on this suite: the old engine's serial
trace lacks 120 of the plain run's 7033 tests (110 plain-skipped, 10 plain-passed, e.g.
`test/argument-validation.integration.test.ts@@main::argument name validation -- real filesystem server::rejects snake_case parameter names with an actionable error`,
suites with a failing `beforeAll` in the engine run), each parallel trace lacks 366. On the trunk engine the same 120 /
366 tests are in the trace as `skipped` with `sched.never_started` (column never_started below) and C3 = 0. No false
green on the old engine here (every run exited 1).

## Per run

`status` is the run's `detjs: status:` line (from = log) or `meta.status` (from = meta). P = tests of the round's plain
run, S = sum of the status, D = distinct test ids in the trace. verify = the round's `fenvix verify S P --json` row:
its `verdict` field is null in every row (the JSON output of this engine has no `verdict` key); the exit code is given
in brackets and the summary is in `results.jsonl` (`verify_summary`; every verified pair: identical 0, all tests
`diverged`, reason `fs`). Reported, not gated.
### ironcurtain, after

totals: {"runs": 9, "completed": 9, "not_completed": [], "C1": 0, "C2": 0, "C2_runs": 0, "C3": 0}

| run | exit | wall_s | status (from) | P | S | D | C1 | C2 | C2_runs | C3 | NOT PROVEN files | never_started | verify verdict (exit) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| serial w1 r1 | 1 | 213.76 | failed=226 not_proven=0 passed=6684 skipped=123 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | - | 120 | - |
| par w2 r1 | 1 | 134.28 | failed=407 not_proven=32 passed=6257 skipped=337 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | test/docker/workflow-runtime-deps.integration.test.ts (it ran 0 of its 2 test(s)); test/escalation-scenarios.test.ts (it ran 34 of its 52 test(s)); test/mcp-roots-race.integration.test.ts (it ran 0 of its 3 test(s)); test/pty-web-escalation.integration.test.ts (it ran 0 of its 4 test(s)); test/sandbox-integration.test.ts (it ran 49 of its 54 test(s)) | 366 | None (1) |
| par w4 r1 | 1 | 116.85 | failed=407 not_proven=39 passed=6257 skipped=330 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | test/argument-validation.integration.test.ts (it ran 0 of its 4 test(s)); test/docker/workflow-runtime-deps.integration.test.ts (it ran 0 of its 2 test(s)); test/escalation-scenarios.test.ts (it ran 34 of its 52 test(s)); test/mcp-roots-race.integration.test.ts (it ran 0 of its 3 test(s)); test/pty-web-escalation.integration.test.ts (it ran 0 of its 4 test(s)); test/roots-expansion-bridging.integration.test.ts (it ran 0 of its 3 test(s)); test/sandbox-integration.test.ts (it ran 49 of its 54 test(s)) | 366 | None (1) |
| serial w1 r2 | 1 | 211.59 | failed=226 not_proven=0 passed=6684 skipped=123 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | - | 120 | - |
| par w2 r2 | 1 | 122.12 | failed=407 not_proven=7 passed=6257 skipped=362 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | test/argument-validation.integration.test.ts (it ran 0 of its 4 test(s)); test/roots-expansion-bridging.integration.test.ts (it ran 0 of its 3 test(s)) | 366 | None (1) |
| par w4 r2 | 1 | 76.5 | failed=407 not_proven=0 passed=6257 skipped=369 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | - | 366 | None (1) |
| serial w1 r3 | 1 | 216.19 | failed=226 not_proven=0 passed=6684 skipped=123 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | - | 120 | - |
| par w2 r3 | 1 | 161.6 | failed=408 not_proven=0 passed=6256 skipped=369 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | - | 366 | None (1) |
| par w4 r3 | 1 | 127.58 | failed=408 not_proven=0 passed=6256 skipped=369 (log) | 7033 | 7033 | 7033 | 0 | 0 | 0 | 0 | - | 366 | None (1) |

### agentic-qe, after

totals: {"runs": 3, "completed": 3, "not_completed": [], "C1": 3, "C2": 0, "C2_runs": 3, "C3": 0}

| run | exit | wall_s | status (from) | P | S | D | C1 | C2 | C2_runs | C3 | NOT PROVEN files | never_started | verify verdict (exit) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| serial w1 r1 | 0 | 3394.99 | none (no status) | 30765 | None | 30765 | 1 | no status | 1 | 0 | - | 277 | - |
| par w2 r1 | 0 | 3094.59 | none (no status) | 30765 | None | 30765 | 1 | no status | 1 | 0 | - | 277 | None (1) |
| par w4 r1 | 0 | 2615.05 | none (no status) | 30765 | None | 30765 | 1 | no status | 1 | 0 | - | 277 | None (-9) |

### ironcurtain, before

totals: {"runs": 3, "completed": 3, "not_completed": [], "C1": 0, "C2": null, "C2_runs": null, "C3": 852}

| run | exit | wall_s | status (from) | P | S | D | C1 | C2 | C2_runs | C3 | NOT PROVEN files | never_started | verify verdict (exit) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| serial w1 r1 | 1 | 223.3 | none (no status) | 7033 | None | 6913 | 0 | n/a: pre-P0 engine | None | 120 | - | 0 | - |
| par w2 r1 | 1 | 113.43 | none (no status) | 7033 | None | 6667 | 0 | n/a: pre-P0 engine | None | 366 | - | 0 | None (1) |
| par w4 r1 | 1 | 89.67 | none (no status) | 7033 | None | 6667 | 0 | n/a: pre-P0 engine | None | 366 | - | 0 | None (1) |

## Runs not completed

None: all 12 trunk engine runs and all 3 old-engine runs exited 0 or 1 with a trace. (Not an engine run: the
agentic-qe round-1 `fenvix verify S1 P1w4 --json` was killed with exit -9: the kernel log shows a memory-cgroup
OOM kill of a python process with 10.3 GB RSS at that time; its `verify1w4.json` is `{"unparsed": ""}`.)

## agentic-qe serial w1 r1: C1 = 1, C2_runs = 1 (no status)

- Command: `(cd /tmp/pm-p0/repos/agentic-qe && node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --bail=0 --det --det-workers=1 --det-trace=/tmp/pm-p0/after/agentic-qe/S1.jsonl)`, exit **0**, 3394.99 s.
- Trace: 30765 records, 168 `failed`, 30303 passed, 294 skipped; header `meta` has no `status` and no `hazard_rerun`.
  Vitest's own summary in the block: `Tests  168 failed | 30303 passed | 294 skipped (30765)`, `Test Files  63 failed | 1399 passed | 34 skipped (1496)`.
- Status line in the block: `detjs: status: not written (the trace /tmp/pm-p0/after/agentic-qe/S1.jsonl could not be read back)`.
- First failure line of the block: ` FAIL  tests/unit/mcp/handlers/memory-share-collisions.test.ts > knowledge sharing collision resistance (memory) > retains two different findings admitted in the same millisecond`.
- Failed tests (first of 168, `bad_record_ids` in results.jsonl has 20):
  `tests/benchmarks/mincut-performance.test.ts::MinCut Performance Benchmarks::Health Monitor::should handle 1000 health checks per second`,
  `tests/benchmarks/success-rate-benchmark.test.ts::ADR-051 Success Rate Benchmark::ONNX Embeddings::should benchmark embedding generation`.

## agentic-qe par w2 r1: C1 = 1, C2_runs = 1 (no status)

- Command: `(cd /tmp/pm-p0/repos/agentic-qe && node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --bail=0 --det --det-workers=2 --det-trace=/tmp/pm-p0/after/agentic-qe/P1w2.jsonl)`, exit **0**, 3094.59 s.
- Trace: 30765 records, 275 `failed`, 30196 passed, 294 skipped; no `meta.status`, no `meta.hazard_rerun`.
- Block: `detjs: status: not written (the trace /tmp/pm-p0/after/agentic-qe/P1w2.jsonl could not be read back)` and
  `detjs: parallel: the first run's trace ../../after/agentic-qe/P1w2.jsonl could not be read back; no one-lane re-run, its exit code 0 stands`.
  The block also has 8 `detjs: PLACEMENT ...: lane predecessor ... died` lines and CROSS-WORKER hazard lines (so a
  hazard re-run would have been due) but no NOT PROVEN line.
- First failure line of the block: none (the block's last 8000 characters hold no FAIL line); first failed records:
  the same two benchmark tests as the serial run.

## agentic-qe par w4 r1: C1 = 1, C2_runs = 1 (no status)

- Command: `(cd /tmp/pm-p0/repos/agentic-qe && node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --bail=0 --det --det-workers=4 --det-trace=/tmp/pm-p0/after/agentic-qe/P1w4.jsonl)`, exit **0**, 2615.05 s.
- Trace: 30765 records, 270 `failed`, 30201 passed, 294 skipped; no `meta.status`, no `meta.hazard_rerun`.
- Block: `detjs: status: not written (the trace /tmp/pm-p0/after/agentic-qe/P1w4.jsonl could not be read back)` and
  `detjs: parallel: the first run's trace ../../after/agentic-qe/P1w4.jsonl could not be read back; no one-lane re-run, its exit code 0 stands`;
  7 PLACEMENT lines, CROSS-WORKER hazard lines, no NOT PROVEN line.
- First failure line of the block: none in the block; first failed records: the same two benchmark tests.

## Cause of the agentic-qe false green (MEASURED, no fix made)

The three agentic-qe traces are 1,205,271,095 (S1), 1,205,895,986 (P1w2) and 1,206,267,862 (P1w4) bytes. `stampStatus`
(`node/src/session.js` line 484) reads the whole trace with `fs.readFileSync(tracePath, 'utf8')`; on Node v22.23.5
that throws for this file:
`node -e "require('fs').readFileSync('/tmp/pm-p0/after/agentic-qe/S1.jsonl','utf8')"` → `ERR_STRING_TOO_LONG Cannot create a string longer than 0x1fffffe8 characters`
(536,870,888). `stampStatus` then returns null, `session.finish` prints `status: not written`, no counts are recorded,
and the exit decision rests on the runner's code, which was 0 although the trace holds 168 / 275 / 270 failed records
(the parallel wrapper likewise cannot read the first trace, skips the hazard re-run and keeps exit 0). The ironcurtain
traces (about 36 MB) are read and are correct. Any suite whose trace exceeds about 512 MiB is affected. Per rule 5 the
engine is not changed here; the fix is a separate decision.

## ENV notes

No run exited 0 because of an environment failure. ironcurtain: the plain run fails 20 tests (18 `Cannot find package
'@provos/memory-mcp-server/prompts'`, a workspace package not built with `npm ci --ignore-scripts`; 2 assertions); the
engine runs fail 226 (serial) / 407-408 (parallel), mostly MITM / docker / CA suites, outside the P0 counts (every run
exit 1). agentic-qe: the plain run fails 80 tests; one names the network (`tests/unit/learning/embedder-endpoint-client.test.ts`:
`connect ECONNREFUSED 192.0.2.1:65000` where a timeout was expected) and counts in C1 like the others since those runs
exited 0. The agentic-qe plain run started at 22.4 % CPU busy (the checker ran on ironcurtain during its first second;
below measure.py's 80 % NOISY mark); every other run started at or below 1.5 %.

## Traces read by the checker (sha256; traces are not in git)

- after ironcurtain S1.jsonl: `cd99ec215b80b43ef15e73f4e9c94cf1fad8a1ef9fee964b7ea2d51018c09cd0`
- after ironcurtain P1w2.jsonl: `7c1a407ef342430333cbe46b1896b965efd5e92253d1c8174d54d7e2f9c1ec32`
- after ironcurtain P1w4.jsonl: `75cbb555e90aae14f758e2c93c3f2b6ed3919f172a1eabb10b6ad6a2c5359722`
- after ironcurtain S2.jsonl: `50d9f47cd3dc434a96f85320ddc2b0e05462436e90787b1f20089f5f1533a4b7`
- after ironcurtain P2w2.jsonl: `2f3b4d6b95153cf38b7491c80c86681ed851eaab20982e5463bd85479410e9ed`
- after ironcurtain P2w4.jsonl: `14b8e57a90161522685eb231c1f1ba56d02e97b9e2f7935f2b317fabca24dfa7`
- after ironcurtain S3.jsonl: `71972a9110de72961b55a5606cef9364e4422a482bc95c05d32bf22a35b1e870`
- after ironcurtain P3w2.jsonl: `82a2e0f6ba4f1ddeb4f500d5d8d19be861b7c983198ce9a71850eb5d1e74d89b`
- after ironcurtain P3w4.jsonl: `1203eea18fe3899bc1542473b665e626d798f3aa9e5a6024b3dbdf3620e1aee8`
- before ironcurtain S1.jsonl: `a55c200542946a9dbc254efe96cd40472270f47ab78481f9d7d2cf4662f846fc`
- before ironcurtain P1w2.jsonl: `98ca550357726d7f2b60d1852aacdae44f4b9ddaaf45155e25bda2e3fc22ec55`
- before ironcurtain P1w4.jsonl: `37ea667fbbe76529a62da967f014398ab2bfb809b50c0d4f84ed82d73ac48aca`
- after agentic-qe S1.jsonl: `e0d4794edafb7ce74d4f50bd576e73bee1e7c85445affc27e79f6b4f7d185c1d`
- after agentic-qe P1w2.jsonl: `9ccf5151eba504d87549f9f72324ee0b6889cc9fa602b4fa88822b20b91e8a53`
- after agentic-qe P1w4.jsonl: `13eda8c2bf75f9d371dc0cb131f1f39b7f507f42ddffff76f628e478d4a78224`

## Assignment line

On the trunk engine, ironcurtain meets all three numbers (C1 = C2 = C2_runs = C3 = 0 over 9 completed runs), but
agentic-qe has C1 = 3 (all three completed engine runs exit 0 with 168 / 275 / 270 failed tests) and C2_runs = 3 (no
status line, `status: not written`, because the 1.2 GB trace cannot be read back into a Node string).

Assignment P0 re-measure: NOT MET (agentic-qe on the trunk engine: C1 = 3 runs and C2_runs = 3 runs, all three engine runs exit 0 with failed tests and no status; ironcurtain: all 0)
