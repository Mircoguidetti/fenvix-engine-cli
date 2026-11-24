DONE

# P0 big trace: no false green on big traces (stream the trace, fail closed, bounded verify)

Branch `claude/p0-big-trace` from `origin/claude/release-1` f67be4a3 (not merged). Machine: this container, nproc 4,
15 GB RAM, Node v22.23.5, Python 3.12 (venvs), rustc stable. Spec: the session prompt (founder decision D1 A,
2026-11-23).

## Changes to tests, validators, CI, thresholds (rule 3, before any result)

- No existing test was removed, skipped or weakened. No existing test file was edited.
- `release/python-tests.txt`: two lines added, `shared tests/test_runner_node_p0.py` and
  `shared tests/test_verify_write.py`. Reason: `release/shard.py` refuses an unclassified test file; both exercise code
  Node uses (runner/fenvix-run's Node path; `fenvix verify`), hence `shared`.
- `node/src/parallel-rerun.js accountRerun` (a pure function with its own tests) now also reads `r.never_started`; a
  record given with `events`, as `node/test/parallel-rerun-account.test.js` gives them, is read as before. That test
  file is unchanged and passes.
- No CI step, timeout, tolerance, threshold, snapshot or suppression pragma was changed.

## Commits (in order)

| commit | content |
|---|---|
| 91ad4e4 | golden corpus generator (`#[test] #[ignore] golden_corpus_generate` in `verify.rs`) + 60 cases of fixtures in `crates/detpy-core/tests/golden/`, generated on the unmodified f67be4a3 verifier; no verify logic change |
| 5a1e3b1 | Rust: `RecordSource`, `MemTrace`, `FileTrace`, `SlimRecord`, `judge_slim`; `tests/golden_verify.rs` |
| d2adbf8 | Node: `src/trace-lines.js`, streamed readers, `recordUnknown`, fail-closed paths, `finishRerun`, raw line copies, the item 5 fix |
| bcfe275 | runner tests (criterion 5); `harness/p0_remeasure/` copied from `origin/claude/p0-remeasure` 6b18711c |
| 7e6cc5b, bbcd0f8 | report draft; re-measure rows |
| 73c0ae5 | `fenvix verify` / `detpy verify` write the report as it is serialized (`_core.verify_write`); `tests/test_verify_write.py` |

## What changed

1. **One streaming reader** `node/src/trace-lines.js`: `forEachLine` (1 MiB chunks, split on byte 0x0A, one decoded
   line at a time, `\r` stripped from the text but counted in the byte length, read errors thrown, a line over 256 MiB
   throws `DETJS_TRACE_LINE_TOO_LONG`), `firstLine`, `readLineAt` (+ `readLineBytes`), `copyRange`.
2. **Readers streamed**: `stampStatus` (header from line 0, body copied byte for byte with `copyRange`; exclusive
   create, mode, real path and rename kept; a `\r` at the end of the header line kept; a failed write or rename now
   THROWS; an unreadable trace returns null, as before, so `test/status-line.test.js` is unchanged), `partIds`,
   `partNotes`, `realEntropyTests`, `repro.traceTests`, `isolate.readTrace`, `verify-explain.readTrace`,
   `parallel-rerun.readTrace` (header in full, per test `{nodeid, outcome, never_started, offset, length}`).
   `writeRecordParts` copies each record's raw line from t1 or t2 instead of `JSON.stringify(r)`.
3. **Fail closed**: `exit-status.recordUnknown(cause)` (sticky; sets the recorded status to
   `{internalError: true, cause}` and `process.exitCode = 2`; prints `detjs: status: unknown (<cause>): exit 2, NOT
   PROVEN`). Called when `stampStatus` returns null or throws, when a part's ids cannot be read, when
   `native.mergeTraces` returns a non-empty `skipped` (session, parallel wrapper `finishRerun`, isolate), and when the
   wrapper cannot read a trace pass 1 wrote (`main`, and `finishRerun` when given no t1). Pass 2 unchanged: an
   unreadable re-run trace is NOT PROVEN, exit 1. `repro.afterMerge` writes no outcomes file for an unreadable trace
   and says why. `runner/fenvix-run`: no code change.
4. **Bounded verify (Rust)**: `verify(&[Trace], labels)` keeps its signature and runs `verify_sources` over
   `MemTrace` (borrowed); `verify_paths` / `verify_paths_ignoring` run it over `FileTrace` (strict `read_trace`
   semantics: same `Parse { line }` numbering, UTF-8, format and version checks). The core holds one `SlimRecord` per
   test (every scalar field, `events_len`, `events_fingerprint`, `first_uncontrolled`, env reads, line offset/length)
   and loads two full records only where `diff_records` compares events, dropping them before the next test.
   `provable::judge_slim` holds the rule; `judge_record` builds a `SlimRecord` and calls it (`cache.rs` unchanged).
5. **Bounded verify output** (beyond the spec's Rust item, needed for criterion 7): on the agentic-qe pair every test
   diverges on 537 run inputs, so the REPORT is 1.17 GB (each test's description names them all). `fenvix verify`
   held it as a Rust String, a Python str and a `json.loads` tree: 7.06 GB RSS after item 4. `_core.verify_write`
   streams the JSON or text report to `sys.stdout` in ~1 MiB chunks cut at UTF-8 boundaries and returns only the
   summary for the exit code; `fenvix verify` and `detpy verify` use it. Output bytes unchanged (`cmp` on S1/P1w4;
   `tests/test_verify_write.py`). `verify_with` is kept. Report format unchanged.

## Item 5: why vitest returned 0 with failed tests (MEASURED, FIXED)

`tests/global-teardown.ts` of agentic-qe 9a42d9eb (its vitest `globalSetup`), function `teardown`:
`const timer = setTimeout(() => process.exit(0), 5000); timer.unref();`. Under detjs vitest runs inside the detjs
process (`node/src/vitest/cli.js` createVitest + start), so after the tests detjs merges and stamps the trace while
that timer is pending; native modules keep the process alive and 5 s later `process.exit(0)` sets the exit code to 0,
after detjs had decided 1 (`process.exit(code)` overrides `process.exitCode`). Reproduced on a 1-test vitest project
with that teardown and a live handle: f67be4a3 printed `detjs: status: failed=1 ...` and exited **0** (a false green
independent of trace size). Fix (13 lines, `node/src/exit-status.js` `guardExit`): once a status is recorded (or
unknown), an `'exit'` listener re-applies `runExit({...recorded, runnerCode: <code being exited with>})`; it can only
raise the code. Test: `node/test/big-trace.test.js` "vitest exit 0 (item 5)" passes, and fails with the listener
disabled (checked by mutation).

## Acceptance criteria

| # | criterion | result | evidence |
|---|---|---|---|
| 1 | `stampStatus` on a >600 MiB trace with 3 failed | MET | 640 records, 671 MB; `readFileSync(utf8)` throws `ERR_STRING_TOO_LONG` on it; `stampStatus` = `{failed:3, not_proven:0, passed:637, skipped:0}`, `runExit(...runnerCode 0) === 1`, header equal to the old one plus `"status":{...},`, sha256 of everything after line 1 unchanged. 6.4 s |
| 2 | rename failure throws; through `bin/detjs.js` exit 2 + unknown line | MET | unit: throws on the 671 MB trace, trace unchanged, no temp file (2.2 s). `bin/detjs.js vitest run --det --det-workers=1` with `NODE_OPTIONS=--require test/fixtures/big-trace-hook.js` (`BIG_TRACE_HOOK=rename`): exit 2, `detjs: status: unknown (the trace ... could not be read back or stamped: meta.status not written into ...: injected rename failure ...): exit 2, NOT PROVEN`, no counts line; same project without the hook: exit 0 |
| 3 | parallel wrapper: unreadable first trace gives 2; >600 MiB hazard path | MET | through `bin/detjs.js --det-workers=2` with an injected EIO on the wrapper's read of pass 1's trace: exit 2 + unknown line; `finishRerun` on a t1 that is not JSON: 2; `finishRerun` with a 671 MB t1 holding a hazard and a t2: re-run path ran (`meta.hazard_rerun.complete`), 640 of 640 tests in the merged trace, every record line equal to its source line except `index` (7.4 s); `writeRecordParts` parts byte-identical (CRLF and non-ASCII) |
| 4 | skipped part at the 3 `mergeTraces` sites gives 2 + unknown line | MET | session (`bin/detjs.js`, `BIG_TRACE_HOOK=merge-skip`), isolate (`--det-isolate`, same hook, children not faulted), parallel wrapper (`finishRerun` with a record the Rust merge refuses): exit 2 and `detjs: status: unknown (unreadable trace parts, their tests are not counted: ...)` |
| 5 | runner tests, no runner change | MET | `tests/test_runner_node_p0.py`: header without `status` + detjs exit 0 gives job exit 1 ("wrote no status in"); `detjs verify` killed by SIGKILL gives `verify_status: null`, `verify_exit: -9`, job not green. 2 passed |
| 6 | golden against f67be4a3 | MET | first commit 91ad4e4 = generator + fixtures only. 60 cases: every `verify(&[...])` call of the `verify.rs` tests (3-run case included), the 3 r058 integration pairs, `all_diverge` (300 tests, serial vs parallel, every test diverges), `env_list_truncated_mark_tampered` (env diffs + `env.list`, uncontrolled event past truncation, fingerprint not matching its events, footer `late` input). `tests/golden_verify.rs`: `verify` over in-memory traces, `verify_paths` and `verify_paths_ignoring` over temp copies equal the fixtures byte for byte (labels set to run0, run1, ...). A mutation (env.list ignored) makes it fail |
| 7 | re-measure | MET | below |
| 8 | no test removed/skipped/weakened; profiles | MET | see rule 3 section; every new test states `protects=...; fails_when=...; no_claim=...` |

### Criterion 7: re-measure (MEASURED)

Commands as `REPORT.md:21-43` of `origin/claude/p0-remeasure` (cwd `harness/parallel_measure`, `PM_WORK=/tmp/pm-p0`,
repos at the pinned commits, `npm ci --ignore-scripts` + `npm rebuild ...` for agentic-qe), one exception: the
agentic-qe plain run was in the first call with `--skip plain_par,par` (plain + serial), then `--workers 2 --skip
plain_par,plain,serial`, then `--workers 4 --skip plain_par,plain,serial`, all `--reps 1 --first-rep 1 --timeout
14400 --out /tmp/pm-p0/after`; ironcurtain `--reps 1 --workers 2,4 --skip plain_par`. Then
`python3 harness/p0_remeasure/check_p0.py /tmp/pm-p0/after <repo> --phase after`. The script is
`harness/p0_big_trace/remeasure.sh` (as run). Checker rows: `harness/p0_big_trace/results.jsonl`; measure.py rows:
`harness/p0_big_trace/raw/after-results.jsonl`. The Node test suite and the Python suites ran on the machine at the
same time for part of the agentic-qe runs (busy_before_pct is in the raw rows; wall times are not gated).

| repo | run | exit | wall_s | status line | C1 | C2 | C2_runs | C3 |
|---|---|---|---|---|---|---|---|---|
| agentic-qe | plain | 1 | 1773 | - | | | | |
| agentic-qe | serial w1 | **1** | 4469 | `failed=168 not_proven=0 passed=30303 skipped=294` | 0 | 0 | 0 | 0 |
| agentic-qe | par w2 | **1** | 5941 | `failed=273 not_proven=10 passed=30198 skipped=284` (480 files re-run in one lane) | 0 | 0 | 0 | 0 |
| agentic-qe | par w4 | **1** | 5259 | `failed=276 not_proven=10 passed=30195 skipped=284` (498 files re-run in one lane) | 0 | 0 | 0 | 0 |
| ironcurtain | serial w1 | 1 | 263 | `failed=226 not_proven=0 passed=6684 skipped=123` | 0 | 0 | 0 | 0 |
| ironcurtain | par w2 | 1 | 152 | `failed=407 not_proven=32 passed=6257 skipped=337` | 0 | 0 | 0 | 0 |
| ironcurtain | par w4 | 1 | 124 | `failed=407 not_proven=39 passed=6257 skipped=330` | 0 | 0 | 0 | 0 |

Checker totals: agentic-qe `{"runs": 3, "completed": 3, "C1": 0, "C2": 0, "C2_runs": 0, "C3": 0}` (before the fix:
C1 3, C2_runs 3); ironcurtain `{"runs": 3, "completed": 3, "C1": 0, "C2": 0, "C2_runs": 0, "C3": 0}`. No agentic-qe
engine run exits 0; `grep -c "detjs: status: unknown"` = 0 in both `runs.log` (the traces were read, not failed
closed). Traces: S1 1,204,933,810 B, P1w2 1,206,210,742 B, P1w4 1,206,595,402 B; every merged trace 30765 tests.
The hazard re-run path ran on both parallel runs (it was skipped before), each with 10 NOT PROVEN tests the re-run
did not account for.

`fenvix verify S1.jsonl P1w4.jsonl --json` under `/usr/bin/time -v` (cwd `/tmp/pm-p0/after/agentic-qe`):

| engine | exit | wall | Maximum resident set size |
|---|---|---|---|
| f67be4a3 (REPORT of p0-remeasure) | -9 (OOM kill) | - | 10.3 GB at the kill |
| after item 4 (bounded trace reading) | 1 | 27.3 s | 7,058,592 kB (report held 3x) |
| after item 5 of "What changed" (73c0ae5) | **1** | **18.2 s** | **1,337,552 kB** (gate: 2 GB) |

Both outputs are byte-identical (`cmp`), 1,170,231,250 bytes: 30765 tests, all `diverged`, reason `fs` (files read
outside tests differ between S1 and P1w4: 537 run inputs), as in the p0-remeasure report. measure.py's own verify
rows (old CLI path, bounded trace reading): w2 exit 1 in 43 s, w4 exit 1 in 36 s.

## Commands run (rule 4)

| command | result |
|---|---|
| `cargo test -p detpy-core -p detpy-node` | all ok: lib 197 passed, 1 ignored (the generator); `golden_verify` 1 passed; r058 integration 3+1+3+3 passed |
| `cargo test -p detpy-core --lib golden_corpus_generate -- --ignored` (on f67be4a3 code, commit 1) | 1 passed, fixtures written |
| `cd node && npm ci && npm test` | 997 tests: 989 pass, 4 fail, 3 cancelled (children of a failed suite), 1 skipped; 78m41s. Failures, each also failing on f67be4a3 (worktree with its own native build, same command per file): `jest: parallel lanes` (Jest 30 parallel refused), `repro options (vitest)` --det-order, `bun: Level 0 controls`, `node-test: adversarial` "a file another test file wrote". One more failed only for the environment: `customer-nodetest` "a flaky test becomes a defect" (`python3 -m detpy.fenvix`: no module detpy for the system Python); with `PYTHONPATH=python` the file passes 4/4 |
| `node --test test/big-trace.test.js` | 13 passed; the whole file 25.6 s before the item 5 test (each >600 MiB test under 8 s) |
| `node --test test/trace-lines.test.js` | 9 passed |
| Python shared suite (CI LIGHT: the 4 shards of `release/shard.py --only shared release/python-tests.txt`, wheel installed + `_core` copied into `python/detpy`, `--deselect` of R-017 H2 as in release-1.yml) | before 73c0ae5: 721 passed, 19 skipped, 1 failed: `tests/test_packaging.py::test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs`, also failing on f67be4a3. After 73c0ae5 (new wheel): 782 passed, 19 skipped, 1 failed, the same `test_packaging` test (40m47s; the count rose by the 61 new `test_verify_write.py` tests) |
| `python3 tests/attacks.py` (every attack, Python and Node) | node rc 0 (60 passed); python rc 1: 157 passed, 2 skipped, 12 failed, all in `tests/test_review_r056_pycache.py` (Python bytecode cache); the same file on f67be4a3: 12 failed, 21 passed. After 73c0ae5: identical (python 157 passed, 2 skipped, 12 failed in `test_review_r056_pycache.py`; node 60 passed) |
| `pytest tests/test_runner_node_p0.py tests/test_verify_write.py` | 2 passed; 62 passed |
| re-measure (criterion 7) | as above |

Not run: the CI jobs that build manylinux wheels with zig, the per-OS/per-Python matrices, the nightly FULL Python
suites (python-product files), and the Go/JVM workflows (no Go or JVM code changed).

## What I verified, reused, could not check (rule 5)

- Verified by running: every row of the tables above.
- Reused: `harness/p0_remeasure/check_p0.py` and its test file unchanged from `origin/claude/p0-remeasure`; the
  "before" numbers (10.3 GB OOM kill, exit 0 runs) are that report's.
- Not checked: Node 24/26 (only Node 22 here); a real run whose trace has a line over 256 MiB (unit-tested with a
  lowered limit).
- The fail-closed tests inject faults (hook file, a record the Rust merge refuses); they do not reproduce a natural
  disk error.

## Follow-ups (out of scope, listed per the spec)

- Python readers that load a whole trace: `python/detpy/xdist.py:672`, `python/detpy/repro.py:90,264,366`,
  `python/detpy/fenvix_js.py:251` (memory only, no false green).
- `node/src/playwright/cli.js:104` and `node/src/parallel.js:120` `readReplay` (fail loudly, not quietly).
- `detjs verify` (Node, `native.verify` returns the whole report as a string; `JSON.parse`): same 1.2 GB report
  problem as `fenvix verify` had; not on the customer path measured here.
- The verify report repeats the full list of differing inputs in every test's description (37 KB x 30765 tests);
  a format change (naming them once) would cut the report ~1000x. Report format was out of scope.
- No change to the trace format, the report format, the runner, the console or the App. Rollback: revert the merge.

## Addendum 2026-11-24: merge of claude/release-1, /review, suites on the final head

Coordinator request: merge `origin/claude/release-1` (ae5ccba: harness/control_arm and harness/parallel_measure only,
no engine file) into this branch with an ordinary merge (95afbd7, no rebase or force-push), run gstack `/review`
against `claude/release-1`, fix its findings with tests, and re-run the suites. Not merged into `claude/release-1`:
that waits for the founder's authorization in this session.

### /review (3 passes; specialists: testing, maintainability, security, performance, simplification; Claude adversarial each pass)

Fixed, each with a test that fails before the fix (62af0ac, 16c4b28):

| finding | fix | test |
|---|---|---|
| `session.js` `order.push(...partIds(p))`: a part with > ~100k ids overflows the stack and a clean run exits 2 | `partOrder`, one push per id | 150 000-test part (`Maximum call stack size exceeded` before) |
| `parallel-rerun.js` same spread in the splice | `spliceRecords`, one push per record | 150 000-test hazard file |
| text-mode `verify_write` held the 1.2 GB report 4-5 times (2.45 GB measured) | `verify::render_text_to` streamed through the chunk writer; writer takes large writes 1 MiB at a time | chunks of at most ~1 MiB reach Python, both modes |
| (pass 2) after a failed stdout write, text mode resent a growing buffer (quadratic) | writer latches the failure; `verify_write` checks it | a raising writer gets exactly 1 call, both modes |
| `FileTrace::full` re-opened the path and could compare another test's events if the trace changed after the scan | scanned handle kept; per-record line digest; nodeid + fingerprint + digest checked | records swapped in place; events changed under the same fingerprint (complete and truncated) |
| `finishRerun` made its temp dir before the trace's directory existed | directory created first | trace path in a directory that does not exist |
| untested fail-closed branches (unreadable part; trace not readable back) | none needed | 2 `bin/detjs.js` tests, both fail on f67be4a3's session.js |

Auto-fixed: stale comment (`judge_slim`), misplaced doc comment. Left open (Low, never green): an exception from
`sys.stdout.write`, `KeyboardInterrupt` included, reaches Python as `RuntimeError` (exit 2 with one line instead of an
interrupt). Left with reasons: exit guard folds codes like 130 to 1 (`runExit`'s rule everywhere); partial stdout before
exit 2 on a write failure; no golden case with non-empty `ignore_env` or duplicate ids; `stampStatus` on a header without
`meta` (pre-existing); `readLineAt` (spec'd); `remeasure.sh` paths (record of what ran). Gate edits: 3 listed, 3 kept
(the spec'd `#[ignore]` generator; the check_p0 pragmas copied from claude/p0-remeasure).

`fenvix verify S1 P1w4` on 16c4b28: `--json` 1,342,548 kB, 19.6 s; text 1,341,296 kB, 19.2 s; exit 1; both outputs
byte-identical (`cmp`) to the earlier outputs.

### Suites on 16c4b28

| command | result |
|---|---|
| `cargo test -p detpy-core -p detpy-node` | all ok: lib 199 passed, 1 ignored; golden_verify 1; r058 3+1+3+3 |
| `cd node && npm test` | 1002 tests: 994 pass, 4 fail, 3 cancelled, 1 skipped, 64 min. Failures: the 4 base failures (`jest: parallel lanes`, `repro options (vitest)`, `bun: Level 0 controls`, `node-test: adversarial`); `customer-nodetest` "a flaky test..." failed for the environment only and passes 4/4 with `PYTHONPATH=python` |
| Python shared suite (LIGHT, 4 shards, release-1.yml's deselect) | 785 passed, 19 skipped, 1 failed: `test_packaging::test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs` (base failure) |
| `python3 tests/attacks.py` | node 60 passed; python 157 passed, 2 skipped, 12 failed, all `tests/test_review_r056_pycache.py` (base failures) |
