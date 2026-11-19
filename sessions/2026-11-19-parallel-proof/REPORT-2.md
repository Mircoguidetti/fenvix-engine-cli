PARTIAL

# Parallel with proof: review R-023 fixes (FIX 6), re-measurement

Branch `claude/parallel-proof`. Merged first: `origin/claude/review-r023` (the reviewer's `tests/test_review_r023.py`
and report) and `origin/claude/rust-hotpaths-2` at d470b59 (R-017b and N5 fixes, REPORT-R2c). Engines measured:
**b795295** (the R-023 fixes: local esphome batch `esphome5`, Actions run 44509602787 `r023-p0`, re-run `r023-p0b`)
and **ddaffac** (plus the follow-up's speed and cacheability fixes: Actions `r023-p0c`, `r023-p0d`). Each table says
which.

Labels: **MEASURED** = a run named here with its raw file; **ESTIMATED** = derived, derivation given; **DECLARED** =
read from a repository's configuration; **UNKNOWN** = not available, what was checked is said.

**PARTIAL because**: P4 (shared cache) is not built; P5 beyond the `placement` class is not built; mlflow could not be
measured validly; the moto and litellm walks ran before the cacheability fixes (0 reuse, vacuous); litellm-vertex and
prefect are at 1.04x plain `-n 4`, just outside the noise; prefect's cache stays at 0 % (SQLite's clock).

## In short

* **F1-F6 fixed, R1-R4 moved to Rust.** `tests/test_review_r023.py` (unchanged): 10 failed before, 17 passed after.
* **Soundness (MEASURED)**: every reused and every ran result of every cache row was compared with fresh serial
  `--det` runs: **0 mismatches** on esphome (local and Actions, incl. both mixed-store directions), litellm-vertex,
  moto, prefect and pydantic-ai (no cache there); 0 new failures caused by the split, 0 hidden failures (prefect: 8
  tests flaky between the two serial runs themselves, counted apart).
* **Speed (MEASURED, repeated, final engine on Actions)**: `--det -n 4` against plain `-n 4`: esphome **1.00x**,
  pydantic-ai **1.02x** (both inside the plain runs' range), litellm-vertex **1.04x** and prefect **1.04x** (just
  outside the range; were 1.25x / 1.2x), moto **0.54x** (virtual clock). The 1.2x was ours: no assertion-rewrite
  cache for pytest < 9.2, so every `--det` worker re-rewrote every test module (fixed). The remaining few seconds are
  the re-exec's second plugin load (not fixed). Warm `--det-cache -n 4` against plain `-n 4`: esphome **0.72x**,
  litellm-vertex **0.58x** (99.9 % reused, was 0 %), moto **0.17-0.22x** (96.6 % reused, was 0 %), all three runs each.
  "Closed the gap" is not claimed beyond these ranges (O1).
* **Cache blockers, per repository**: litellm's (pytest-socket's `localhost` lookup, pytest-rerunfailures' channel
  to the controller, conftest-set variables, a `/proc/self/fd` listing at import) made cacheable soundly in this
  round, plus `--det-urandom`; moto's after `--det-urandom` are a Docker daemon probe and `/proc` reads (85 tests);
  prefect's is its SQLite schema (SQLite's own clock and `randomblob`, not virtualised: 0 % reuse); pydantic-ai is
  blocked by the capture prerequisite of design 5. mlflow's jobs are not valid (collection errors, no serial truth).
* P3 walks (50 commits each): **esphome 446,878 reused, 0 wrong**; moto and litellm 0 reuse in that run (before the
  cacheability fixes and without `--det-urandom`: vacuous).
* One flaky parallel verdict (pydantic-ai, a blockbuster lock check in a thread, same plan passed in run c): not the
  split, not the cache; reported, not fixed.

## Per finding: change, test before / after

Baseline (before this session's changes, engine of c436a4d = 302d52b + the reviewer's tests + REPORT-R2c merge, Python
3.13.18, pytest 9.2.0, xdist 3.8.0): `tests/test_review_r023.py` **10 failed, 7 passed** (the same 10 as the review:
a1, a3 x2, a4 x2, a5, a6 x2, a7, a8). After: **17 passed**, three consecutive runs; the file is unchanged
(`git diff 8ffbaaa -- tests/test_review_r023.py` is empty).

### F1: results recorded under `-n` reused serially

* **Change** (the design's interim guard, 2.5, in its strict form). A store entry has a `placement` field
  (`proof.rs` `Entry::placement`, not part of the key). A worker's shard marks every entry it recorded
  `placement: "parallel"` (`proofcache.rs` `save_shard`), and so does a `--det-plan-worker` replay (one worker's
  list in one process). `Checker::check` refuses a parallel entry to a serial session: miss kind `placement`
  ("recorded in a worker of a parallel (-n) session: not offered to a serial session until the parallel-vs-serial
  proof (P5)"). The guard covers every parallel entry, not only the tests with a recorded placement divergence: no
  divergence record exists before P5, and a8 shows that one can exist without a fingerprint ever being compared
  (the entry's input "variable absent" matches a serial session's start). A parallel session still reuses serial
  entries (a serial result is the result the claim promises) and parallel ones.
* **What it costs**: the serial run on a store written only by `-n` reuses nothing the first time; it records serial
  entries, which both modes reuse afterwards (measured below, mixed-store rows).
* **Tests**: a1, a8 fail before, pass after. Updated in `tests/test_parallel_proof.py` (they asserted the unsound
  behaviour): `test_a_store_written_under_n_is_not_reused_serially_and_receipts_are_stable` (serial on the `-n`
  store: 0 reused, all `placement`; a second serial run reuses all; `-n` on that store reuses the serial entries)
  and `test_whole_environment_readers_are_reused_under_n`. New: `test_plan_worker_replay_records_parallel_entries`;
  Rust `r023_f1_a_serial_session_does_not_reuse_a_parallel_entry`.
* **Mixed-store truth comparison**: see the measurement section (`crosscheck.py`).

### F2: the design's 1.4.5 wrong reuse (reader decided before a writer of the same session writes its input)

Four changes, so that the verdict is the serial verdict, not only the entry dropped afterwards:

1. **Writers persist, absolute paths included** (`record.rs`, `proofcache.rs save_shard`, `proof.rs persist_written`):
   every path a session wrote is kept in `Store::written` with its writer contexts while the path exists (a path that
   is gone is pruned at save: temporary files have fresh names and would only grow the store). The design's scenario
   (A writes outside the repository, A reused in session 2) now finds the writer in the store, so B is never
   recorded and runs (and fails) in session 3, serially and under `-n`.
2. **Serial: the reuse is re-checked at the test's turn** (`CacheSession.recheck_hit`, `CaptureCore.written_input`):
   when an earlier test of the same session (or a fixture the entry did not use) already wrote one of the reused
   result's inputs, the reuse is withdrawn and the test runs (miss `written: <path> was written by <writer> earlier in
   this session`). This covers a writer with no history at all (a new test, or a test whose code changed to write the
   file), which (1) cannot know. Entries now keep their fixture contexts (`Entry::fixtures`) so that a session fixture
   the test itself used is not a foreign writer (also in the existing stale-entry rule).
3. **`-n`: hits are settled after the run** (`xdist.py Controller.all_finished`, `proof.rs hits_with_written_inputs`):
   the controller reports reused results only once every worker has finished; a hit whose input a test that comes
   before it in the serial order wrote in this session (from the workers' shards) is withdrawn and run again in an
   extra worker (xdist's own replacement-worker mechanism, `DSession._clone_node`), so it reads what the serial
   order gives it. If no worker can be added, the test is reported as an error, never with its recorded outcome.
4. **`-n`: a reader waits for its writer on another worker** (`schedule.rs ControllerPlan::waits`, `xdist.py
   Barrier`): the merge (and the serial record) note data edges (writer test, reader test) in the store; the next
   plan makes a reader that runs this time wait, before it starts, for each such writer that also runs, comes earlier
   in the serial order and sits on another worker. This removes the race the review's a3/a4 tests ran into (B read
   the stale file before A rewrote it: a timing-dependent verdict that plain xdist also has). No deadlock: every
   worker runs its list in the serial order and only waits for earlier tests. The edges do not merge atoms: a2 requires
   A and B on different workers.

* **Remaining gap (stated, not fixed)**: in the *first* session in which a test reads a file a test on another
  worker writes (no edge yet, both run), the reader's verdict is the parallel one (timing-dependent, as in plain
  xdist); the entry is dropped and the edge noted, so from the next session on the verdict is the serial one.
* **Tests**: a3[0], a3[2], a4[0], a4[2] fail before, pass after. `tests/test_parallel_proof.py::
  test_cross_worker_write_is_never_reused` no longer deletes the outside file. New:
  `test_reuse_is_withdrawn_when_a_new_earlier_test_writes_its_input[0|2]` (a writer with no history; serial and -n;
  truth run included), `test_reader_waits_for_its_writer_on_another_worker` (writer sleeps 0.5 s; the reader fails as
  serially); Rust `r023_f2_written_paths_outside_the_repository_persist_while_they_exist`,
  `r023_f2_hits_whose_input_an_earlier_test_wrote`, `r023_merge_notes_data_edges`,
  `r023_waits_only_across_workers_for_an_earlier_writer`.

### F3: a worker-id reader checked against the previous plan

* **Change**: the plan covers **every collected test**; reused tests get a worker at cost 0 and are not sent
  (`schedule.rs controller_plan`). The controller's check no longer compares `PYTEST_XDIST_WORKER` before the plan:
  the recorded value is kept (`Checker::defer_worker`, `worker_reads`) and compared with the worker **this run's plan**
  gives the test (`Checker::worker_check`); a mismatch withdraws the reuse and the test runs on exactly that worker.
  `_xdist_prev_workers` is gone. A `--det-plan` replay is this run's plan, so a5's pinned test is checked against gw1.
* **Tests**: a5 fails before, passes after. New: Rust `r023_f3_worker_reads_are_checked_against_this_runs_plan`,
  `r023_previous_plan_counts_only_for_the_same_workers_and_dist`; pytester `test_previous_plan_of_another_dist_is_ignored`.

### F4: the plan is not sticky when a test is added

* **Change** (`schedule.rs chunk_test_atoms`): chunk boundaries no longer derive from `ceil(tests / (workers x 8))`.
  The target size is that number rounded up to a power of two (it changes only when the suite doubles or halves, or
  N changes); a same-file run of at most the target is one chunk; a longer run is cut before a test whose id digest
  is 0 modulo the target (content-defined, expected size = target) or when the chunk would reach twice the target.
  A cut depends on the test's own id, so adding or removing a test changes at most its own file's chunk(s). The
  second gap (chunks computed over the misses under `--det-cache`) is closed by F3's change: the plan, its chunks
  and the workers are computed over the whole collection.
* **Tests**: a6 (binding) and a6 (pytester) fail before (196 / 158 of 384 moved), pass after (0 moved in the binding
  test). New: Rust `r023_f4_chunks_do_not_move_when_tests_are_added_or_removed` (40 random suites, one test added or
  removed anywhere: no chunk of another file changes), `r023_f4_adding_one_test_keeps_every_other_test_on_its_worker`
  (end and middle of a file), `r023_controller_plan_places_every_test_and_sends_only_misses`; pytester
  `test_removing_one_test_keeps_the_others_placement`.

### F5: `fpcompare` hidden failures

* **Change**: a failure is hidden when a serial run fails the test and *either* parallel run does not (was: only run a).
* **Test**: a7 fails before, passes after.

### F6: the 74.0 s target

* The target with the 74.0 s plain run is **76.4 s** (74.0 x 158.15 / 160.9 x 1.05), not 73.0 s; corrected below
  in the re-measured table, where every target is recomputed from the new runs.

### Decisions moved to Rust (R1-R4)

| | was (Python) | now (Rust) |
|---|---|---|
| R1 which worker a test is expected on | `_xdist_prev_workers` (previous plan, workers only) | the plan's `assign` for every collected test (`controller_plan`), `Checker::worker_check` |
| R2 previous plan used or not; `--det-plan` replay mapping | `xdist.py make_plan`, `_replay` | `previous_atoms` (same workers, same `--dist`, not a replay), `replay_assignment` (format, `gwK` parsing, out-of-range) |
| R3 cost precedence | `xdist.py _costs` | `cost_precedence` (history median, else cache duration, else median of the known misses; hits 0) |
| R4 expected `_COUNT`/`_TESTRUNUID`; verification seed; crash split | `decide_controller` (env dict, `random.Random`), `remove_node` | `ProofCache.begin_controller`, `CacheSession.controller_verify_seed` (`derive_seed(seed, "detpy-cache-verify:<order digest>:<config digest>")`, SplitMix64 draw in `decide`), `crash_split` |

`xdist.py` keeps the xdist protocol, the file reads, the report synthesis and the barrier files (glue).

## Measurements: esphome (batch `esphome5`, MEASURED)

esphome @ 141789d240, 14,446 tests, selection as before (`--no-cov tests --ignore=tests/integration
--ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120`), `-n 4` with esphome's default `--dist load`.
Machine: this session's container, 4 vCPU, 15 GB, Python 3.12.3, pytest-xdist 3.8.0; variants run one after another,
interleaved (plain serial, plain `-n 4`, `--det -n 4`, `--det` serial, repeated), on an otherwise idle machine.
Raw: `tracks/parallel-proof/build/esphome/esphome5/summary.jsonl` (one line per run, the variant name is the run id;
`@K` = repetition K), log tails `*.tail.txt`, plans `*.plan.json.gz`, `fpcompare.json`, `*.crosscheck.json`.

| variant | runs (wall) | median | spread | reuse | vs plain `-n 4` median (65.4 s) |
|---|---|---|---|---|---|
| plain serial | 186.1 / 162.0 / 160.4 s | 162.0 s | 16 % (first run high) | — | 2.48x |
| plain `-n 4` | 65.4 / 70.7 / 63.4 s | 65.4 s | 11.5 % | — | 1 |
| `--det` serial | 155.0 / 158.9 s | 157.0 s | 2.5 % | — | 2.40x |
| `--det -n 4`, first run (unit costs, no durations yet) | 85.9 s | — | — | — | 1.31x |
| `--det -n 4`, runs 2 and 3 (recorded durations) | 62.7 / 60.7 s | 61.7 s | 3.3 % | — | 0.94x |
| cold `--det-cache -n 4` | 79.8 s | — | — | 0 (14,149 recorded) | 1.22x |
| warm `--det-cache -n 4` | 47.6 / 47.0 / 46.2 s | 47.0 s | 3.0 % | 14,149 of 14,446 = 97.9 % | **0.72x** |
| cold / warm `--det-cache` serial | 201.4 / 72.3 s | — | — | 0 / 14,158 = 98.0 % | 3.08x / 1.11x |
| `-n 4` on the serial store (`cache-x`) | 47.6 / 49.8 s | — | — | 14,158 = 98.0 % | 0.73x / 0.76x |
| serial on the `-n 4` store (`cache-y`), then again | 200.2 / 72.4 s | — | — | 0 (14,149 `placement`, 297 `new`) / 14,158 | — |

* **P2 target** (design 5: `--det -n 4` <= plain `-n 4` x (`--det` / plain serial) x 1.05), ESTIMATED from the rows
  above: ratio 157.0 / 162.0 = 0.969 (medians); target 66.5 s against the median plain `-n 4` run (64.5 s against the
  fastest, 71.9 s against the slowest). Runs 2 and 3 (62.7, 60.7 s) meet it against all three plain runs; the first
  run of a checkout (unit costs, 85.9 s) does not.
* **Observation O1 ("closed the gap")**: `--det -n 4` with recorded durations is 60.7-62.7 s, plain `-n 4` is
  63.4-70.7 s in the same batch. The difference of the means (4.8 s) is smaller than the spread of the plain runs
  alone (7.3 s), with 2 and 3 runs. What the data supports: **`--det -n 4` is within the run-to-run noise of plain
  `-n 4` (not slower in any of these runs); it is not shown to be faster.** The previous report's wording "the gap is
  closed" is withdrawn in favour of this sentence. The earlier engine batches (esphome3: 72.7-78.2 s against 63.1 s
  plain) were before the chunked plan.
* **Warm cache**: 46.2-47.6 s against 63.4-70.7 s plain `-n 4`: 15.8 s below the fastest plain run, twice the plain
  spread; 0.72x of the median. This is clear of the noise (three runs each).
* **Reuse share**: warm `-n 4` 14,149 against warm serial 14,158 (0.06 point; design target: within 1 point). The 9
  tests are those the cross-worker write rule drops in every `-n` run (`9 dropped` in each warm run).
* **Plan determinism** (MEASURED, plan files): runs 2 and 3 of `--det -n 4`, the cold cache run, the three warm runs
  and both `cache-x` runs have the same plan digest `d9cbe597`, the same lists and the same worker per test: the plan
  is now a function of the collection and the durations only, not of which results the cache reuses (F3/F4). Run 1
  (unit costs) has `6c007af5`; run 2 replaced it (not sticky: the costs changed from units to durations), from run 3
  on the plan is sticky.

### Truth comparison of every cache row (review F1, `harness/parallel_proof/crosscheck.py`, MEASURED)

Truth: the two fresh serial `--det` runs of the batch (`det-serial-a`, `det-serial-b`; 0 tests whose outcome differs
between them). Every reused result and every result that ran is compared with the truth outcome of the same test.

| run | reused | reused ≠ truth | ran | ran ≠ truth |
|---|---|---|---|---|
| warm `-n 4` (`cache-n-warm`, `@3`) | 14,149 | 0 | 297 | 0 |
| warm serial (`cache-ser-warm`) | 14,158 | 0 | 288 | 0 |
| `-n 4` on the serial store (`cache-x`, `@2`) | 14,158 | 0 | 288 | 0 |
| serial on the `-n 4` store (`cache-y`) | 0 | — | 14,446 | 0 |
| serial on that store again (`cache-y@2`) | 14,158 | 0 | 288 | 0 |
| `--det -n 4` runs 2 and 3 (no cache) | — | — | 14,446 | 0 |

**0 mismatches** in every row. The serial run on the store `-n 4` wrote reuses nothing (14,149 misses `placement`):
the price of F1's guard on this repository is one serial cold run (200.2 s) the first time a serial session meets a
store that only parallel runs wrote; the second serial run reuses 98 %. A parallel run on a serial store reuses
everything the serial run does.

### Fingerprints (`fpcompare.json`: serial a/b against `--det -n 4` b/c, MEASURED)

| | esphome5 | esphome4 (previous report) |
|---|---|---|
| tests in all four traces | 14,446 | 14,446 |
| serial noise (two serial runs differ) | 67 | 66 |
| parallel noise | 65 | 68 |
| placement (serial runs agree, a parallel run differs) | 35, all 35 in both parallel runs | 32, 29 in both |
| outcome differences / new failures caused by the split / hidden failures (F5-corrected count) | 0 / 0 / 0 | 0 / 0 / 0 |
| plans and per-test workers identical between the two parallel runs | yes / yes | yes / yes |

The 7 failures are the same in every `--det` run (serial, `-n`, cache or not), the 4 in every plain run, as in the
previous batches. Placement moved from 32 to 35 with the new chunk boundaries (power-of-two target: chunks of up to
512 tests instead of 452 on this suite); 0 of them change an outcome.

## Measurements: the xdist set on GitHub Actions (P0, run 44509602787)

Triggered by `tracks/parallel-proof/run.json` (commit f0dc2ad, engine b795295): GitHub-hosted `ubuntu-latest` (4 vCPU),
one job per repository, variants one after another on the same runner; results committed by the workflow under
`tracks/parallel-proof/results/r023-p0-2026-11-19/<repo>/` (summary.jsonl = one line per run, crosscheck.json per
cache / `-n` run, fpcompare.json, plans, log tails). Selections: run.json (DECLARED from each repository's CI:
CI-FACTS.md; one shard or group where the CI splits).

### esphome on Actions (same selection as the local batch), MEASURED

| variant | runs (wall) | median | vs plain `-n 4` median (81.0 s) |
|---|---|---|---|
| plain serial | 160.0 / 141.5 s | 150.8 s (mean) | — |
| plain `-n 4` | 79.6 / 82.7 / 81.0 s | 81.0 s | 1 |
| `--det` serial | 163.5 / 143.0 s | 153.3 s (mean) | — |
| `--det -n 4` a (unit costs) / b / c | 90.4 / 82.3 / 82.5 s | 82.4 s (b, c) | 1.02x (b, c) |
| cold `--det-cache -n 4` | 109.1 s (14,150 recorded) | — | 1.35x |
| warm `--det-cache -n 4` | 53.2 / 52.9 / 53.2 s | 53.2 s | **0.66x** |
| cold `--det-cache` serial (14,161 recorded); `-n 4` on that store | 185.0 s; 54.3 s (14,161 reused) | — | — ; 0.67x |

* P2 target (ESTIMATED): 81.0 x (153.3 / 150.8) x 1.05 = 86.5 s; runs b and c (82.3, 82.5 s) meet it, run a (unit
  costs, 90.4 s) does not.
* `--det -n 4` against plain `-n 4`: 82.3-82.5 s against 79.6-82.7 s: **inside the plain runs' range, 2 % above their
  median: within noise, not faster** (same reading as locally).
* Warm: 52.9-53.2 s against 79.6-82.7 s: 26 s below the fastest plain run, 0.66x, three runs each, clear of the noise.
  Reuse 14,150-14,151 of 14,446 under `-n 4` against 14,161 serially (0.07-0.08 point).
* Truth: crosscheck 0 mismatches in every row (reused and ran), fpcompare 0 outcome differences, 0 new failures
  caused by the split, 0 hidden failures. 3 failures in every `--det` run (the 3 LIMITS C7 mtime tests; the 4
  root-only failures of the container do not occur on the non-root runner), 0 in plain runs.
* fpcompare (parallel a against b, see the litellm note): placement 42, parallel noise 100 (run a's unit-cost plan
  against run b's). The local batch, which compares b with c, is the stickiness measurement (35 / 65, plans identical).

### litellm, shard `llms-vertex-ai` (`tests/unit/llms/vertex_ai`, `-n 4 --dist loadscope` as its CI), MEASURED

| variant | runs (wall) | vs plain `-n 4` median (64.3 s) |
|---|---|---|
| plain serial | 129.9 / 100.8 s | — |
| plain `-n 4` | 65.5 / 63.8 / 64.3 s | 1 |
| `--det` serial | 144.9 / 108.6 s | — |
| `--det -n 4` (a: unit costs; b, c: durations) | 81.5 / 80.1 / 81.2 s | 1.25x |
| cold / warm x3 `--det-cache -n 4` | 116.9 / 117.0, 115.2, 117.1 s (reuse 0 %) | 1.8x |
| cold `--det-cache` serial; `-n 4` on that store | 151.8 s; 115.4 s (reuse 0 %) | — |

* **The cache records nothing on this shard, serially and under `-n`**: "not cacheable: network connection 4,180"
  (serial: "host name lookup 4,180"), plus 1 failure. Every test opens a connection or a lookup (the log shows a
  tracing client dropping traces to `localhost:8126`); a test that touches the network is never cached (by
  design). So the warm rows are a full run: they show the capture's cost under `-n` (115-117 s against 80-81 s for
  `--det -n 4`), not a reuse share. The cause per test is UNKNOWN beyond the log line (the traces are not uploaded).
* **`--det -n 4` misses P2's target here**: target = 64.3 x (126.8 / 115.4) x 1.05 = 74.2 s (ESTIMATED, means of the
  two serial runs each); the three runs take 80.1-81.5 s, 1.25x plain `-n 4`, beyond the plain runs' 2.7 % spread.
  Unlike esphome, the first run (unit costs) is not slower than the others, so the plan's balance is not the cause
  that run 1 points to; the cause is UNKNOWN (candidates: per-worker start-up of `--det` on a 60 s job, `loadscope`
  atoms against the plan). Not fixed in this session.
* **Truth**: every run's outcomes (crosscheck against the two fresh serial `--det` runs): 0 mismatches; 0 outcome
  differences, 0 new failures caused by the split, 0 hidden failures (fpcompare). The same 1 failure (a blocked DNS
  lookup, Level 0's network policy) in every `--det` run; 0 in plain runs.
* fpcompare in this run compares parallel run a (unit costs) with run b (durations): their plans differ by
  construction, so its "placement 1,300 / parallel noise 430" mixes two plans and is not a stickiness or placement
  measure. The workflow now compares b with c (fixed after this run was triggered; it applies to the next run).

### moto, the `-n 4 --dist loadscope` group of its Makefile (2,501 tests), MEASURED

`./tests/test_batch ./tests/test_dynamodb ./tests/test_ec2 tests/test_s3/ ./tests/test_sqs -m "not requires_clean_slate"`,
`MOTO_CALL_RESET_API=false` (DECLARED, Makefile).

| variant | runs (wall) | vs plain `-n 4` median (169.7 s) |
|---|---|---|
| plain serial | 398.0 s | — |
| plain `-n 4` | 170.5 / 167.4 / 169.7 s | 1 |
| `--det` serial | 245.0 / 221.4 s | — |
| `--det -n 4` | 89.0 / 88.8 / 89.1 s | **0.52x** |
| cold / warm x2 `--det-cache -n 4` | 101.8 / 97.0, 96.4 s (reuse 0 %) | 0.57-0.60x |
| cold `--det-cache` serial; `-n 4` on that store | 231.9 s; 97.3 s (reuse 0 %) | — |

* `--det` is faster than plain here, serially (221-245 s against 398 s) and under `-n 4` (89 s against 167-171 s,
  three runs each, spread under 2 %): moto's tests wait in real time (batch jobs, retries) and Level 0's virtual
  clock does not. This is the clock, not the plan.
* **8 tests fail under every `--det` run and pass plain** (`test_batch_jobs.py` x5: timestamps equal under the
  virtual clock, jobs that a background thread never advances; `test_dynamodb_resource_policy.py` x3: two revisions
  created at the same virtual millisecond). Same 8 serially and under `-n`: a Level 0 limit (virtual time read
  across threads / written into data, LIMITS C7 class), not caused by the split. Not fixed here.
* **The cache records nothing**: "not cacheable: os entropy (not controlled; use --det-urandom)" for 1,934-2,458 tests
  (uuid4 request ids), the rest network or a C-extension socket, plus the 8 failures. So 0 % reuse is moto's inputs, not
  the parallel cache; with `--det-urandom` it would differ (not run). Serial noise between the two serial runs: 2,205
  of 2,501 (the same entropy).
* **Truth**: crosscheck 0 mismatches in every run; fpcompare 0 outcome differences, 0 new failures caused by the
  split, 0 hidden failures (parallel runs a and b, see the litellm note on the pairing).
* The moto walk (50 commits) will therefore measure only the `-n 4` verdict against the serial truth per commit,
  with no reuse.

### pydantic-ai, the design's subset (8,072 tests, `-n 4 --dist loadgroup`), no cache variants, MEASURED

| variant | runs (wall) | vs plain `-n 4` median (140.1 s) |
|---|---|---|
| plain serial | 328.9 s | — |
| plain `-n 4` | 140.1 / 136.9 / 140.5 s | 1 |
| `--det` serial | 335.4 / 280.7 s | — |
| `--det -n 4` a (unit costs) / b / c | 180.1 / 170.4 / 165.9 s | 1.18-1.22x (b, c) |

* `--det -n 4` **misses P2's target** here: 140.1 x (308.1 / 328.9) x 1.05 = 137.8 s (ESTIMATED; one plain serial
  run); runs b and c take 165.9-170.4 s. The planned makespan of runs b/c is 91-96 s (recorded durations), so about
  75 s of each run is outside the tests the plan balances (start-up, collection in 4 workers, the controller's merge);
  which part is UNKNOWN (not profiled). The design measured `--det -n 4` at 139-140 s on this subset with xdist's own
  scheduling (another engine, local machine).
* Verdicts: 2 failed in every `--det` run (serial and `-n`: the two LIMITS failures of design 1.4.6), 0 in plain runs;
  crosscheck 0 mismatches against the serial truth (8,072 tests); fpcompare 0 outcome differences, 0 new failures
  caused by the split, 0 hidden failures. Serial noise 5,446 of 8,072 (`os.urandom`, as in the design).
* The cache variants were not run: the capture prerequisite of design 5 (2,769 failures under `--det-cache`) is not
  fixed on this branch.

### prefect, group 1 of 8 (SQLite, `--dist worksteal`), re-run `r023-p0b-2026-11-19`, MEASURED

The first run (44509602787) was not valid: 2,431 of 2,438 tests errored in every variant, plain pytest included,
because prefect's `hosted_api_server` fixture starts `uvicorn` by command name and the workflow did not put the venv's
`bin` on `PATH` (a harness defect, fixed in 82331c6). The re-run (same engine):

| variant | runs (wall) | vs plain `-n 4` median (171.2 s) |
|---|---|---|
| plain serial | 507.2 s | — |
| plain `-n 4` | 173.4 / 171.2 / 169.5 s | 1 |
| `--det` serial | 509.4 / 467.4 s | — |
| `--det -n 4` a (unit costs) / b / c | 257.7 / 205.3 / 207.0 s | 1.20-1.21x (b, c) |
| cold / warm x2 `--det-cache -n 4` | 246.5 / 246.1, 242.4 s (reuse 0 %) | 1.42-1.44x |
| cold `--det-cache` serial; `-n 4` on that store | 540.9 s; 247.8 s (reuse 0 %) | — |

* `--det -n 4` **misses P2's target**: 171.2 x (488.4 / 507.2) x 1.05 = 173.1 s (ESTIMATED; one plain serial run);
  runs b and c take 205-207 s (1.2x), beyond the plain runs' 2 % spread. Cause UNKNOWN (not profiled).
* **The cache records nothing** (every test `new` again in every warm run; recorded 0): prefect's autouse session
  fixture starts an API server subprocess that every test talks to over loopback, and a test that connects is never
  cached (design 5.1 predicted it). 0 % reuse is prefect's inputs, not `-n`.
* Verdicts: plain runs fail 6 tests; `--det` runs fail 20 (serial b, every `-n` and cache run) and 28 in the first
  serial run. The 8 extra failures of serial run a are `tests/_internal/concurrency/*` timeout tests ("DID NOT RAISE
  CancelledError") that pass in serial run b and in all parallel runs: serial noise, not the split. The 14 failures
  `--det` adds over plain are the same serially and under `-n` (a Level 0 limit on this suite: not analysed here).
* Truth: crosscheck 0 mismatches in every run (the 8 tests whose two serial runs disagree are counted apart as flaky
  in the truth); fpcompare 0 new failures caused by the split. fpcompare first reported those 8 serially flaky tests
  as 7 "hidden failures": its rule counted a test that fails in *one* serial run. A hidden failure now has to fail in
  both serial runs (`serial_failure_noise` lists the others); with that rule the hidden failures here are 0
  (ESTIMATED from the per-run failure lists: the traces are not uploaded, so `fpcompare.json` was not recomputed).

### mlflow, parallel group 1 of 6: **not a valid measurement** (twice)

Re-run `r023-p0b-2026-11-19` (CI extras, Python 3.12): serial collection still aborts (57 collection errors: modules
the group imports that its extras do not install), so there is again no serial truth; under `-n 4` 78-110 errors.
plain `-n 4` 615-793 s, `--det -n 4` 757-773 s, 88-89 failed under `--det -n 4` against 55 in plain `-n 4`; the cache
records nothing (the job reports no reason line). mlflow is left out of the conclusions; to make it valid, the job
needs mlflow's full CI image (its `requirements/` sets per flavour), which this workflow does not reproduce.

First run:

The job ran, but its install was incomplete: `uv sync --group test --group build` without extras leaves out modules
the selected test files import (optuna, boto3/botocore, kubernetes, azure, fastmcp, starlette's httpx2;
`logs-tail.txt`). Serially, collection errors abort the run (76 errors, 0 tests); under `-n 4` the 106 collection
errors are reported and the rest runs. The cache variants did not start: this job used Python 3.11 (mlflow's CI
version), and `--det-cache` needs 3.12 (`sys.monitoring`). What the files show (MEASURED, not comparable to serial):
plain `-n 4` 499.4 / 379.5 / 293.3 s (spread 70 %: the runner was not steady), `--det -n 4` 499.6 / 383.6 / 384.7 s;
**80 failed under `--det -n 4` against 53 in plain `-n 4`** (27 more), with no serial `--det` truth to tell a Level 0
limit from a split effect (the crosschecks compare with an empty truth and say nothing). To redo: install the
extras its CI installs, Python 3.12 for the cache rows.

## P3 walks on Actions (50 consecutive first-parent commits each, `-n 4` cache walk, truth = a fresh serial `--det` run per commit)

`harness/parallel_proof/walk_n.py --modes a_par --deadline-s 18000`; raw `results/r023-p0-2026-11-19/<repo>-walk50/walk.json`.

| repository | commits walked | reused (sum) | wrong reuses | `-n 4` wall per commit | truth wall per commit |
|---|---|---|---|---|---|
| moto (`-n 4` group, 2,480-2,501 tests) | 50 of 50 (f1057262 .. 96f50b1a) | **0** | 0 (vacuous) | 64.5-70.9 s (cold 113.3 s) | 151.8-171.9 s |
| **esphome** (14,331-14,446 tests) | **50 of 50** (149b9280 .. 141789d2) | **446,878 of 719,448 = 62.1 %** | **0** (0 mismatches against the truth at any commit) | 58.4-64.4 s warm (32 commits, median 62.0 s); 113.8-165.0 s at the 18 commits that change code every test depends on | 148.4-152.1 s |
| litellm vertex shard (4,165-4,181 tests) | 50 of 50 (a41f124b .. 17e6ea8c) | **0** | 0 (vacuous) | 101.5-111.8 s (cold 155.5 s) | 99.9-109.3 s |

* esphome: every one of the 446,878 reused results equals the outcome of a fresh serial `--det` run at its commit.
  18 of the 50 commits change code every test depends on (`code`, e.g. `esphome/core`), so nothing is reused there,
  in parallel as serially (same reason). On the other 32 the `-n 4` cache run takes 58-64 s against 148-152 s for
  the serial truth run on the same runner. Commit 4 misses 2,460 whole-environment readers (`env`): the runner's
  environment changed between two commits of the job (cause UNKNOWN, one commit). The serial cache walk was left out
  (`--modes a_par`) to fit the job's time; the local 10-commit walk of the first report and the Actions variants
  give the serial reuse share (within 0.1 point).
* litellm: the same (no entry is recorded: every test touches the network). There the `-n 4` cache run is as slow as
  the serial `--det` truth run (~106 s each): the capture's cost under `-n` on this shard.
* moto: nothing is reused at any commit (every miss is `new`: no entry is ever recorded, above), so the walk proves
  nothing about reuse there; it shows the parallel cache runs 50 commits without an error. The walk compares *reused*
  results with the truth only, so the `-n 4` verdicts of the tests that ran are not checked per commit by it (the
  variant runs' crosscheck does that, 0 mismatches).

## Follow-up in the same round: why `--det -n 4` was 1.2x on three repositories, and what blocks the cache

### Where the extra time went (litellm-vertex, local, MEASURED)

Per-process phase times from `/proc/uptime` (a `-p` plugin, `harness`-free: `phasetimes.py` in the session's work
directory), `--det -n 4` against plain `-n 4`, same machine, alternating runs:

| phase | plain `-n 4` | `--det -n 4` before | `--det -n 4` after the fix |
|---|---|---|---|
| controller to its session start | 5.5-5.8 s | 8.6-8.8 s | 8.2-8.7 s |
| each worker's collection | 2.2-2.5 s | **7.5-8.0 s** | 2.7 s |
| tests (first to last, per worker) | 32-39 s | 34-38 s | 33-41 s |
| whole run (wall) | 65.2-66.9 s | 76.9-77.5 s | 67.6-72.4 s |

* **Cause 1 (ours, fixed): no cache of pytest's assertion rewrite on pytest < 9.2.** litellm (pytest 9.0.3),
  pydantic-ai and prefect (9.1.1) use pytest's timestamp pycs; detpy kept rewritten test modules only for pytest >= 9.2
  (checked-hash pycs), and `--det` runs with `PYTHONDONTWRITEBYTECODE=1`, so pytest's own cache was never written
  either: every `--det` session, and every `-n` worker, re-parsed and re-rewrote every test module and conftest
  (py-spy: `_rewrite_test` 35 % of a warm `--det` collection). esphome (pytest 9.2) and moto were not affected, which
  is why they were at parity. Fix (`plugin.py _cache_rewritten_tests`): for pytest < 9.2 detpy writes its own format
  (header, SHA-256 of interpreter magic + source, marshalled code) under the same configuration-keyed name, read only
  when the hash matches (a same-size, same-mtime edit is rewritten: review R-015's case); and in a re-executed `--det`
  process (controller, workers) the cache is installed when detpy is imported, before pytest imports the other
  plugins' modules (they are rewritten too). `--det` collection of the shard: 21 s -> 15.3 s (plain 12 s).
  Tests: `tests/test_rewrite_cache_own_format.py` (3: written, loaded, a same-size same-mtime edit runs the new code,
  keyed on the rewrite configuration, a corrupt file is rewritten); the existing rewrite-cache, R-015, R-017b tests.
* **Cause 2 (ours, not fixed): the re-exec loads every plugin twice in the controller.** `--det` re-executes the
  interpreter from `pytest_load_initial_conftests`, after pytest has imported every entry-point plugin; on litellm
  (logfire, ddtrace, ...) that is about 2.8 s per run, once (workers do not re-exec). Re-executing earlier needs the
  options before pytest parses them (ini `addopts`, `PYTEST_ADDOPTS`): left as a stated cost.
* **Plan balance**: the planned makespan matches the measured test phase within a few seconds (litellm 37-39 s
  planned, 33-41 s measured); the last worker finishes 4 s after the first. Not the cause of the 1.2x.

### Re-measured on the final engine (Actions, `r023-p0c-2026-11-19` and `r023-p0d-2026-11-19`, engine ddaffac, MEASURED)

Same runners and selections as above; `--det-urandom` in every `--det` variant of litellm-vertex, moto and prefect
(`det_args` in run.json; also in their serial truth runs). Three runs of plain and `--det -n 4`; the `--det -n 4` column
uses runs b and c (run a plans on unit costs, a checkout's first run).

| repository | plain `-n 4` | `--det -n 4` (b, c) | ratio (median) | warm `--det-cache -n 4` | reuse | vs plain | mismatches |
|---|---|---|---|---|---|---|---|
| esphome | 67.0 / 71.6 / 68.8 s | 68.5 / 69.5 s | **1.00x** | 49.9 / 49.5 / 49.8 s | 14,149-14,151 (97.9 %) | **0.72x** | 0 |
| litellm-vertex | 68.4 / 69.5 / 71.1 s | 72.3 / 72.7 s | **1.04x** (was 1.25x) | 40.3 / 40.7 / 40.7 s | 4,178 of 4,181 (99.9 %; was 0 %) | **0.58x** | 0 |
| moto (`-n 4` group) | 163.1 / 162.7 / 162.3 s | 86.9 / 88.2 s | **0.54x** | 35.8 / 27.1 / 29.7 s | 1,794, then 2,416 of 2,501 (96.6 %; was 0 %) | **0.17-0.22x** | 0 |
| pydantic-ai (no cache) | 101.1 / 89.3 / 92.4 s | 89.1 / 100.0 s | **1.02x** (was 1.2x) | — | — | — | 0 reused; 1 ran (below) |
| prefect (group 1) | 172.4 / 181.9 / 177.3 s | 185.8 / 183.4 s | **1.04x** (was 1.2x) | 230.4 / 225.8 / 226.9 s | 0 (sqlite schema, below) | 1.28x | 0 |

* **Target "within the noise of plain `-n 4`"**: met on esphome and pydantic-ai (inside the plain range); moto is
  faster (virtual clock). litellm-vertex and prefect are at **1.04x**: 3 s (litellm) and 7 s (prefect) above the plain
  median, 1.2-1.6 s and 1.5-3.9 s above the slowest plain run, i.e. **just outside** the plain range with three runs
  each. The measured remaining cost on litellm is the re-exec's second plugin load (2.8 s locally, cause 2 above);
  prefect was not profiled. Not fixed.
* prefect's verdicts: 6 failures in plain runs, 20 in every `--det` run but the first serial one (28: the 8
  `tests/_internal/concurrency` timeout tests that fail only there, serial noise as before; fpcompare now lists 7 of
  them under `serial_failure_noise`, 0 hidden failures, 0 new failures caused by the split).
* Truth: crosscheck 0 mismatches for every reused result in every repository, both mixed-store directions included.
  Plans and per-test workers identical between runs b and c in all four (fpcompare). Outcome differences: 0 on
  esphome, litellm, moto; **1 on pydantic-ai**: `tests/models/test_batch_runs.py::test_one_capability_serves_runs_on_
  several_event_loops_and_threads` failed in `--det -n 4` run b with blockbuster's `BlockingError('Blocking call to
  lock.acquire')` and passed in runs a and c and in both serial runs. Runs b and c have the identical plan and the
  same worker for every test, so it is not placement: a thread-timing failure (the class of design 1.4.6 / LIMITS C4:
  a lock taken in a thread blockbuster watches). fpcompare's "new failures caused by the split" counts it (its rule
  compares outcomes only); classified here as a flaky verdict of one parallel run, no cache involved. Not fixed.
* moto's remaining misses (MEASURED detail lines): docker SDK connecting to `/var/run/docker.sock` (between tests in
  one worker in the cold run: 620 tests of that worker; then per test), `/proc/self/task/<tid>/children` reads in a
  test, a C-extension socket left open by an xunit class fixture. The cold `-n 4` run records 1,833 entries against
  2,410 serially (the between-tests docker probe taints one worker's tests); the next warm run records the rest.
* The cross-mode row changed: a `-n 4` run on a serial store reuses 0 (litellm) / 312 (moto) of the serial entries:
  whole-environment readers miss (`env`), because the controller now decides with its workers' start environment
  (the conftest-set variables), which a serial session's start environment does not have. Serial entries still
  serve a parallel run where no whole-environment read is involved (esphome: 14,161).

### What blocks the cache, per repository (MEASURED: the detail lines of the runs)

| repository | blocking input (count) | where | made cacheable soundly? |
|---|---|---|---|
| litellm-vertex | host name lookup of `localhost` (4,180, serial) | pytest-socket's `socket_allow_hosts(LOOPBACK_HOSTS)` in `tests/unit/conftest.py:248`, between tests (every test) | **yes, fixed**: a lookup of an RFC 6761 loopback name (`localhost`, `*.localhost`, `localhost.localdomain`, `ip6-localhost`, `ip6-loopback`) is answered by the host's resolver files, so it records reads of `/etc/hosts`, `/etc/nsswitch.conf`, `/etc/host.conf`, `/etc/gai.conf` instead of the `dns` flag (Rust `capture.rs`, `sockcap::loopback_name`; the Python reference got the same rule) |
| litellm-vertex | network connection (4,180, `-n` only) | pytest-rerunfailures connects every worker to its status server in the xdist controller (`pytest_rerunfailures.py:466`, start-up) | **yes, fixed**: a listener held by the worker's own `--det` controller is session infrastructure (the controller runs no test code); a connect to it counts like one to a listener of the worker itself (`sockcap::set_xdist_controller_pid`). Connects to `localhost` by name now count as loopback too |
| litellm-vertex | os entropy (4,180) | uuid4 in start-up code | **with `--det-urandom`** (the existing option; never for crypto tests) |
| litellm-vertex | whole environment `*` (4,180, `-n` only) | the conftest sets two variables at import (`tests/unit/conftest.py:133-134`): the workers start with them, the controller decided with its own start environment | **yes, fixed**: the controller decides with the environment its workers start with (snapshot at `pytest_xdist_setupnodes`) |
| litellm-vertex | data `/proc/self/fd` (4,180, `-n`) | `prometheus_client` lists the open descriptors at import time | **yes, fixed**: `/proc`, `/sys`, `/dev` reads of code that runs for every test (start-up, between tests, import) are not data inputs, as their `proc` flag already was not (Rust `record.rs` and the reference); a test's own `/proc` read still makes it uncacheable |
| moto | os entropy (1,934-2,458) | uuid4 request ids | with `--det-urandom` |
| moto | docker SDK connect to `/var/run/docker.sock` (between tests in one worker, then per test), `/proc/self/task/<tid>/children` reads, a C-extension socket left open by an xunit fixture | MEASURED detail lines of `r023-p0d` | no: a connection to the Docker daemon is a real outside input; left as is (85 tests stay uncached) |
| prefect | real clock read outside the virtual clock (2,418) | the SQLite schema prefect creates at import (`aiosqlite/core.py:63`, import time): `CREATE TABLE flow (id CHAR(36) DEFAULT (lower(hex(randomblob(4)) ...` and timestamp defaults evaluated by SQLite itself (`sqlcap`: a schema that may read the real clock) | no: SQLite's own clock and `randomblob` run outside Level 0; caching would need a virtual clock inside SQLite (overriding its date/time functions per connection): not done |
| pydantic-ai | not measured | the capture prerequisite of design 5 (blockbuster, 2,769 failures under `--det-cache`) | no |

After the fixes, litellm-vertex locally (MEASURED, `--det --det-urandom`): cold `--det-cache -n 4` 98.9 s (4,180 of
4,181 recorded, 1 failure), warm 39.2 / 39.0 / 39.5 s with **4,178 of 4,181 reused** (99.9 %), against plain `-n 4`
65.9 / 66.6 s (0.59x); every reused result equals a fresh serial `--det --det-urandom` run (crosscheck: 0 mismatches,
three warm runs).

Diagnostics: a worker's "not cacheable" detail (where the reason was found) now reaches the controller's summary
(`CacheSession.worker_summary` / `merge_worker`); before, `-n` runs reported the reason class only.

## Gates

* `tests/test_review_r023.py`: unchanged (`git diff 8ffbaaa -- tests/test_review_r023.py` empty); **17 passed** (three
  consecutive runs; also in the full suite). Before this session's changes: 10 failed, 7 passed.
* `cargo test --release` (workspace): **94 passed**, 0 failed (81 before + 13 new `r023_*` tests).
* Full Python suite (`pytest tests -p no:randomly`, Python 3.13.18, pytest 9.2.0, xdist 3.8.0, run without `-n`:
  inner serial sessions must not inherit an outer worker's `PYTEST_XDIST_WORKER`), on the final engine (ddaffac):
  **589 passed, 8 skipped, 1 failed**. The failure is `test_review_r017.py::test_h2_report_says_ci_never_sees_tmp_name_
  exhaustion_but_p8_does`, the pre-existing one the review names (it reads `tracks/rust-hotpaths/results/p8/pygments-
  0of1.json`, which no change here touches). (Before the follow-up: 586 passed, same 1 failure.)
* Tests changed for the follow-up's deliberate policy changes: `test_proofcache.py::test_name_lookup_and_c_level_
  sockets_are_never_cached` and the equivalence suites' `test_dns` now look a non-loopback name up through `_socket`
  (past Level 0's guard, which blocks such lookups before the audit event: a blocked lookup is configuration, and
  cacheable), and a `localhost` lookup is expected to be cached; the Python reference (`tests/rust_hotpaths_ref`)
  got the loopback-name rule and the global `/proc` rule, so the store-equivalence tests compare the same semantics.

## Not done, and why

* **Walks after the cacheability fixes**: the moto and litellm walks (50 commits each) ran on b795295 without
  `--det-urandom` and reused nothing; a walk on ddaffac with `--det-urandom` would measure their reuse and wrong
  reuses (not run: about 5 hours per repository on a runner). esphome's walk is unaffected by the follow-up's
  changes except that whole-environment and `/proc` handling now match the workers.
* **mlflow**: no valid measurement (two attempts; collection errors abort the serial runs).
* **litellm-vertex and prefect at 1.04x** plain `-n 4`: the re-exec loads every plugin twice in the controller
  (about 2.8 s on litellm); re-executing before pytest loads plugins would need the options before pytest parses
  them. prefect's extra 7 s not profiled.
* **prefect's cache**: SQLite evaluates `randomblob` and its date/time defaults outside the virtual clock; making it
  cacheable needs SQLite date/time functions under Level 0 (per connection). Not done.
* **pydantic-ai's flaky verdict** (blockbuster lock check in a thread, one of three parallel runs): not done.
* **P4 (shared cache)**: not built. `claude/shared-cache`'s client (`remote_cache.py`, 668 lines, with
  `cache_service.py` and `runtime_id.py`) reads and injects the Python store dict and uses Python runtime identities
  that the Rust move removed from this base; porting it is its own change. Nothing in it was brought over.
* **P5** beyond the `placement` class: not built (F1's guard stands in until then).
* **F2 first-discovery gap** (stated above): the first session that sees a cross-worker writer/reader pair with no
  edge yet gives the reader the parallel verdict.
* **litellm `--det -n 4` at 1.25x plain `-n 4`**: measured, cause not found.
* Blacksmith runner: not available (UNKNOWN numbers).
