FIX 6

# Review R-023: claude/parallel-proof (P0-P3)

Target: `claude/parallel-proof` at 302d52b, report `sessions/2026-11-19-parallel-proof/REPORT.md`, design
`docs/PARALLEL-PROOF-DESIGN.md`. Review tests: `tests/test_review_r023.py` on `claude/review-r023` (17 tests: 10 fail
= findings, 7 pass = attacks that did not get through). Environment: Python 3.13.18, pytest 9.2.0, pytest-xdist
3.8.0, `maturin develop --release` of 302d52b in a fresh venv (the report used Python 3.12).

## Verdict in short

* **The cross-worker write rule holds for what it covers.** Five write channels (`os.replace`, `os.rename`,
  `shutil.copyfile`, `os.open`/`os.write`, sqlite) in another worker: the reader is never reused (a2, 5 pass).
* **But a result recorded under `-n` is reused by a serial run when the two runs give different results (F1).** The
  design's own interim guard for this is not built, and the walk cannot show the gap: it used separate stores.
* **The design's 1.4.5 wrong reuse is still there, serially and under `-n` (F2).** The report's test for it passes
  only because it deletes the outside file before session 3.
* **The plan is not sticky when a test is added (F4).** One appended test moves about half of the existing tests to
  another worker, while the plan still says `sticky`.
* **Numbers**: every exit-table and walk number re-derives from `tracks/parallel-proof/build/`, with one exception:
  the 74.0 s target is 76.4 s, not 73.0 s (F6). The `fpcompare` "hidden failures" check has a defect (F5).
  "Closed the gap" is within noise, not shown (observation O1).
* **Rust boundary**: four decisions are still made in Python (R1-R4). F3 is one of them.

## Findings

### F1 (high): results recorded under `-n` are reused serially when the serial result differs

Tests: `test_a1_parallel_entry_of_a_placement_victim_is_not_reused_serially` and
`test_a8_env_set_by_a_test_in_another_worker_is_not_reused_serially`, both failing.

* a1: polluter `test_a` appends to a module list; victim `test_b` asserts the list is empty. A fresh serial `--det`
  run fails the victim. A `--det-cache -n 2 --dist loadfile` run passes it, because the victim runs in the other
  worker, and records it. The next serial `--det-cache` run **reuses the victim as passed** (`reused 2, ran 0`).
* a8: the same thing through a recorded input. Test A sets `os.environ["DETPY_R023_FLAG"]`; B asserts it is unset.
  Under `-n` B records "variable absent". That matches a serial session's *start* environment, so the serial session
  reuses B as passed. Fresh serial: B fails.

The design (2.5) makes cross-mode reuse sound only with P5, and until then requires that "an entry carries
`placement: serial | parallel` and a serial session does not reuse a parallel entry whose test has a recorded
`placement` divergence". There is no such field anywhere: `grep placement` in `proof.rs`, `proofcache.rs`,
`proofcache.py` and `xdist.py` finds nothing related. The report says instead "a parallel entry is offered to serial
runs and vice versa on equal keys (as P3 specifies); the walk is the evidence that this made no wrong reuse on
esphome". The walk cannot be that evidence. `walk_n.py:89-91` gives A-par `cache-par` and A-ser `cache-ser`: no
serial run ever read a parallel entry, and no parallel run ever read a serial one. The report's mixed-store rows
(`cache-x-n` 14,151 reused, `cache-y-ser` 11,078 reused) were never compared with a truth run. On esphome, 32 tests
have a parallel fingerprint different from their serial one (`fpcompare.json`). A serial run that reuses their
parallel entries reports a fingerprint that a serial run never produces.

Fix: build the interim guard (an entry carries its placement; a serial session does not reuse parallel entries,
at least for tests with a placement divergence), or keep the stores apart until P5. Then give the mixed-store rows
a truth comparison.

### F2 (high): the design's 1.4.5 wrong reuse is still there (serial and `-n`)

Tests: `test_a4_reader_of_another_tests_file_is_not_reused_when_the_file_survives[0|2]` fail; the truth runs
`test_a4_truth_session_3_fails_b[0|2]` pass. Hook variant: `test_a3_..._hook_...[0|2]` fail.

This is the design's scenario exactly. A writes `value.txt` to a file outside the repository; B (another file, so
another worker under `--dist loadfile`) reads it and asserts `x`; three sessions; `value.txt` changes to `y` before
session 3.

1. Session 1: B is dropped by the rule ("1 dropped by the cross-worker write rule").
2. Session 2: A is reused, so it does not run and writes nothing. B runs with no writer in the session and is
   recorded.
3. Session 3: A runs (`data: tests/value.txt`) and writes `y`. B was decided before that and is **reused as
   passed**. A fresh session 3 fails B.

The engine prints `WARNING reused tests/test_b_reader.py::test_b_reads, but this session then wrote its input ...:
entry dropped`. The entry is dropped after the fact, but the session's verdict is already wrong. The same happens
serially. Root cause: written paths outside the repository are not kept across sessions (design 1.4.5: "never for
absolute paths"), so once the writer is a hit, the reader looks writer-free.

The report says this attack is fixed: "B is never cached, and fails in session 3 as serially". Its test
(`tests/test_parallel_proof.py::test_cross_worker_write_is_never_reused`) does `shared.unlink()` before session 3.
B then misses because its recorded content no longer matches, not because of the rule. The test's assertion on
session 2 also passes trivially (B is `new` there, not reused); the gap is that B is *recorded* there.

Fix: persist writer contexts for every path a test wrote, absolute paths included, as the store already does for
repository-relative paths. Remove the `unlink` from the report's test.

### F3 (medium): a worker-id reader is checked against the previous plan, not this run's

Test: `test_a5_worker_reader_is_not_reused_when_the_plan_moves_it` fails.

`proofcache.py:470` / `_xdist_prev_workers` (`proofcache.py:768`) give the checker each test's worker from the
*previous* `.detpy/plan.json`, filtered by worker count only (not by `--dist`, not by `--det-plan`). A test that
asserts it runs on `gw0` is recorded on gw0. The next run, with `--det-plan` pinning it to gw1, reuses it as passed.
A fresh run with the same plan fails it (`assert 'gw1' in ('gw0', None)`). The same gap opens when `--dist` changes
between runs with the same `-n`. The decision is in Python (see R1).

### F4 (medium): the plan is not sticky when a test is added

Tests: `test_a6_adding_one_test_keeps_the_other_tests_placement` (binding) and
`test_a6_pytester_adding_one_test_moves_existing_tests` (pytester) fail.

`chunk_test_atoms` sets the chunk cap to `ceil(len(ids) / (workers x 8))` and names each chunk after its first test.
Setup: 8 files of 48 tests on 4 workers (cap 12), then one test appended to the last file (cap 13). Chunk boundaries
and keys shift in every file, so the previous `atom -> worker` map no longer applies:

* binding with unit costs: **196 of 384** existing tests change worker (more change their in-process predecessors);
* pytester with real durations: **158 of 384**;
* both times the plan reports `sticky: true`.

The report's claims "sticky", "chunk boundaries from the collection only", and "the chunks (and the sticky plan over
them) stay put from run to run" hold only while the test count stays the same. Each moved test changes its
in-process predecessors, which is what placement differences come from.

There is a second gap. Under `--det-cache`, `ids` is the list of misses (`xdist.py:325-336`), not the collection. A
re-run miss is chunked and placed differently from its cold run. So "boundaries from the collection only" is not
true under the cache.

Fix: compute boundaries that do not shift with the count (e.g. by file and a fixed chunk size, or anchored to
content). Test stickiness under additions and removals.

### F5 (low): `fpcompare` misses a failure hidden in the second parallel run

Test: `test_a7_fpcompare_counts_a_failure_hidden_in_either_parallel_run` fails.

`hidden_failures` (`fpcompare.py:62-63`) checks only `pa`. Take a test that fails in both serial runs, fails in
parallel run a and passes in parallel run b. It is an outcome difference, but it is not counted as hidden. On
esphome the committed counts (7 failed in every `--det` run) give no sign that this changed the result. But
"0 hidden failures" comes from this function, and the traces it ran on are not committed (see O2).

### F6 (low): one target number is wrong

The report says: "P2's target ... = 65.6 s (ESTIMATED from the 63.6 s plain run; 73.0 s with the 74.0 s one)". Re-derived
with the report's own ratio: 74.0 x (158.15 / 160.9) x 1.05 = **76.4 s**, not 73.0 s. The 65.6 s figure is right
(65.64). The error understates the target, so the conclusion does not change.

## Rust boundary (founder decision 2026-11-18): decisions still in Python

* **R1** `proofcache.py:768 _xdist_prev_workers` and `xdist.py:351-358`: which worker a test is expected on, and
  which previous plan counts (workers only / workers and dist). F3 comes from this.
* **R2** `xdist.py:339-346`: whether the previous plan is used at all, and `--det-plan` replay mapping
  (`_replay`, `xdist.py:389-411`: worker parsing, the out-of-range check).
* **R3** `xdist.py:_costs` (377-386): the cost precedence (history median, else cache duration, else unknown). Only
  the median is in Rust (`sched_cost_of`).
* **R4** `proofcache.py:466-480`: the expected `PYTEST_XDIST_WORKER_COUNT`/`TESTRUNUID` values for the check, and the
  verification seed. It is Python `random.Random` over a Python string, not `derive_seed` as design 2.5 says.
  Crash handling (`xdist.py:214-222`, the orphan list to the replacement) is policy in Python too.

## Numbers re-derived (`tracks/parallel-proof/build/esphome/esphome4/summary.jsonl`, `fpcompare.json`, walk json)

| claim | committed data | |
|---|---|---|
| plain serial 160.9, plain `-n 4` 63.6 / 74.0, `--det` serial 157.8 / 158.5 | same | ok |
| `--det -n 4` 71.2 / 63.2 / 66.3; ratios 1.12 / 0.99 / 1.04 | 71.2 / 63.2 / 66.3; 1.119 / 0.994 / 1.042 | ok |
| cold / warm `--det-cache -n 4` 84.0 / 45.4 / 44.6; 0.71x / 0.70x | same; 0.714 / 0.701 | ok |
| reused 14,141 / 14,149; 28 and 9 dropped; recorded 14,141 | same | ok |
| serial cache 211.6 / 78.3, reused 14,151-14,153 | 211.6 / 78.3; 14,151 recorded, 14,153 reused | ok |
| x-n 50.3 s, 14,151 reused; y-ser 101.9 s, 11,078 (77 %), env 3,071 | same (76.7 %) | ok |
| plan digest `ecd8b83f` in runs 2 and 3 | det-n-b, det-n-c and cache-n-cold all `ecd8b83f` | ok |
| target 65.6 s / 73.0 s | 65.6 / **76.4** | F6 |
| placement 32, in both 29; parallel noise 68; serial noise "64 ... 59 urandom" | 32; 29; 68; serial noise **66** (entropy 59, time 5, fs 2) | the 64-of-68 overlap and the 4 parallel-only names are not in committed data |
| walk: per-commit walls and reuse, 84,610 / 84,674, 58.59 % / 58.64 %, 0 mismatches | same | ok (commit 6 serial is code 13,482, not "same") |
| labels | MEASURED rows have raw files; 65.6 s is labelled ESTIMATED | ok |

## Observations (not counted)

* **O1 "the gap is closed"**: there are 2 plain `-n 4` runs (63.6 / 74.0 s, 16 % apart) and 2 sticky `--det -n 4`
  runs (63.2 / 66.3 s), in one batch. Against the mean plain (68.8 s) they are 0.92 / 0.96x; against 63.6 s they are
  0.99 / 1.04x; the noise is ±12 %. The earlier batch `esphome3` (engine before b1d25d0, same machine) had
  `--det -n 4` at 72.7 / 75.7 / 78.2 s against plain 63.1 s (1.15-1.24x), and the report does not mention it. What
  the data supports is "within run-to-run noise of plain `-n 4`", not "≤". The warm-cache claim (0.70x, about 20 s
  below either plain run) is clear of the noise.
* **O2 "0 new failures caused by the split, 0 hidden failures"**: the counts re-derive (7 failed in every `--det`
  run, serial and `-n`, cache or not; 4 in plain runs; `fpcompare.json` 0 / 0 / 0). The per-test traces are not
  committed, and the `-n` tails are cut to 25 lines (4 of the 7 failing names visible), so the identity of the 7 can
  be checked only for the serial runs. Combined with F5, this is evidence of counts, not of names.
* The cross-worker rule's 28 / 9 drops on esphome and the five channels in a2 show the rule works. Its weak point is
  the gap between sessions (F2), not between workers.
* Port conflicts were not turned into a test: failures are never stored (`failed-before`), so a conflict can only
  produce a fresh failure, not a wrong reuse.

## Suites

* `cargo test --release`: **81 passed**, 0 failed.
* `pytest tests` (without `test_review_r023.py`): **563 passed, 8 skipped, 1 failed**:
  `test_review_r017.py::test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does` (`AttributeError`
  reading `pygments-0of1.json`). This is the same pre-existing failure the report names; it is not caused by this branch.
* `tests/test_review_r023.py`: 10 failed (F1: a1, a8; F2: a3 x2, a4 x2; F3: a5; F4: a6 x2; F5: a7), 7 passed (a2 x5,
  a4 truth x2).
