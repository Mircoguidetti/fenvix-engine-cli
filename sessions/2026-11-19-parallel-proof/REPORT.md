PARTIAL

# Parallel with proof: build steps P0-P3 (and parts of P5)

Branch `claude/parallel-proof`, created from `claude/rust-hotpaths-2` at 495c318; the design
(`docs/PARALLEL-PROOF-DESIGN.md`) and its measurement files (`tracks/parallel-proof/`) are taken over from
`claude/parallel-proof-design`. Built in the order of the design's section 5; every decision is Rust
(`crates/detpy-core/src/schedule.rs`, `trace.rs::merge_traces`, `proof.rs` shards and the cross-worker rule,
`verify.rs` placement class), the xdist glue is Python (`python/detpy/xdist.py`, hooks in `plugin.py` and
`proofcache.py`).

Labels: **MEASURED** = a run named here, raw files in `tracks/parallel-proof/build/`; **ESTIMATED** = derived, the
derivation is given. Machine for every run: this session's container, 4 vCPU, 15 GB, Python 3.12, pytest-xdist 3.8.0,
single runs one after another on an otherwise idle machine (the walk excepted, see P3). The design measured ±12 % between
two identical plain serial runs on this kind of machine; two plain `-n 4` runs here took 63.6 s and 74.0 s.

**PARTIAL because**: P0-P3 are built and tested, measured on esphome only (pydantic-ai is blocked by the capture
prerequisite of design 5, prefect's lockfile needs a newer uv than this container has, the other xdist repositories
were not run for time); the P3 walk covers 10 esphome commits, not 3 repositories x 50; the P0 Actions workflow is
written but was not triggered; P3's isolated audit reruns are not built; P4 is blocked (the shared-cache module of
`claude/shared-cache` is not on this base); of P5 only the `placement` class of `detpy verify` exists; P6-P8 are not
started.

## Exit numbers (esphome @ 141789d240, 14,446 tests, final engine, batch `esphome4`, MEASURED)

Selection as in the design (`--no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k
"not udp" --timeout=120`), `-n 4` with xdist's default `--dist load` (esphome's CI mode).

| variant | wall | vs plain `-n 4` (63.6 s) | old engine (design 1.3, same machine type) |
|---|---|---|---|
| plain serial | 160.9 s | 2.53x | 160-180 s |
| plain `-n 4` | 63.6 s / 74.0 s | 1 | 62-67 s |
| `--det` serial | 157.8 s / 158.5 s | 2.48x | 175-177 s |
| `--det -n 4`, first run (no durations yet) | 71.2 s | 1.12x | 80-82 s |
| `--det -n 4`, runs 2 and 3 (same plan) | 63.2 s / 66.3 s | 0.99x / 1.04x | 80-82 s |
| cold `--det-cache -n 4` | 84.0 s | 1.32x | 104 s |
| warm `--det-cache -n 4` (98 % reused) | 45.4 s / 44.6 s | **0.71x / 0.70x** | 81 s / 75 s (77 % reused) |
| cold / warm `--det-cache` serial | 211.6 s / 78.3 s | 3.33x / 1.23x | 232 s / 104 s |
| `-n 4` on the store a serial run wrote | 50.3 s (14,151 reused = every serial hit) | 0.79x | — (0 reused: config differed) |
| serial on the store `-n 4` runs wrote | 101.9 s (11,078 reused, 77 %) | — | — (0 reused) |

* **The gap to the customer's job is closed** (MEASURED): `--det -n 4` takes 63-66 s once durations are recorded
  against 63.6-74.0 s for plain `-n 4`; serial `--det` was 2.5x slower than plain `-n 4`. P2's target, `--det -n 4` <=
  plain `-n 4` x (`--det`/plain serial = 158.2/160.9 = 0.98) x 1.05 = 65.6 s (ESTIMATED from the 63.6 s plain run;
  73.0 s with the 74.0 s one): runs 2 and 3 meet it against the faster plain run within 1 %, the first run (unit costs)
  does not (71.2 s).
* **Warm parallel runs are faster than the customer's plain `-n 4`** (0.70x, MEASURED), with 98 % of the results reused
  (14,141-14,149 of 14,446; the serial warm run reuses 14,151-14,153: within 0.1 point, design target 1 point).
* **Determinism** (MEASURED, `fpcompare.json`): the plan of runs 2 and 3 is identical (digest `ecd8b83f`), every test ran
  on the same worker in both; fingerprints of the two parallel runs differ for 68 tests, 64 of which also differ
  between the two serial runs (59 `os.urandom`, LIMITS R5); 4 parallel-only differences (`test_log.py` colorama x2,
  `test_espidf_framework.py`, one lvgl menu test). The first run's plan differs from the second's (unit costs, then
  recorded durations); from then on the plan is sticky.
* **0 new failures caused by the split, 0 hidden failures** (MEASURED): the same 7 failures in every `--det` run,
  serial and parallel (4 root-only, 3 LIMITS C7 mtime tests, as in the design), 0 outcome differences on 14,446 tests.
* **Placement**: 32 tests (0.22 %) have a parallel fingerprint different from their serial one while the two serial
  runs agree, 29 of them in both parallel runs, 0 outcome changes; `detpy verify serial merged` now classifies them
  `placement` (32) next to `entropy` (59) and `thread` (6). The old dynamic scheduling had 50; the first version of the
  plan here, which placed single tests by LPT and so spread every module over every worker, had 175 (batch
  `esphome`), which is why one-test atoms are now merged into same-file chunks (P2).
* **0 wrong reuses** in the walk (P3, below).

## Per build step

### P0: harness (`harness/parallel_proof/`)

What changed: `variants.py` (runs the variants of design 1.3 one after another in a repository and appends one JSON
line per variant: wall, return code, pytest summary, cache and plan lines; copies the plan), `fpcompare.py` (serial
noise, parallel noise, placement, outcome differences, new failures caused by the split, hidden failures, identity
of the plans and of the per-test workers, first differing source), `synth.py` (the 20-test synthetic project: a
polluter/victim pair, a writer/reader pair through a file outside the repository, a fixed-port pair), `walk_n.py`
(P3's walk), `.github/workflows/parallel-proof.yml` (one job per repository from `tracks/parallel-proof/run.json`).
The per-worker trace shim of the design (`xd_pertrace.py`) is no longer needed: the engine writes per-worker traces.

Tests: `tests/test_harness_parallel_proof.py` (2): synthetic project, two serial and two `-n 2 --dist loadfile` runs:
serial noise 0, parallel noise 0, identical plans, placement = 1 exactly when the plan separates the victim from its
polluter (and `detpy verify` then names the polluter as lost predecessor), 0 outcome differences; under the cache the
reader of the other test's file is never reused.

Measured: the variants above (batches `esphome`..`esphome4`). Not done: the workflow was not triggered (no
`run.json` pushed), so no Actions numbers and no run over the rest of the xdist set; the design's 1.4 reproduction
on pydantic-ai was not repeated (see "Not done").

### P1: per-worker traces, controller merge (`trace.rs`, `xdist.py`, `plugin.py`)

What changed:
* A worker (`config.workerinput`) writes `<trace>.gwK.jsonl` (header `meta.worker`); the controller no longer opens
  a trace of its own and, at session end, merges the workers' traces in Rust (`trace::merge_traces`): header with
  `meta.plan` and `order` = the session's serial order, test lines in serial order with `worker` and `worker_index`
  and `index` = the position among the executed tests (as a serial run numbers them), footer with the order digest,
  the plan digest and `missing` (tests of a worker that died). A cut last line of a killed worker is tolerated.
  Serial traces are byte-for-byte the old format (the new fields are skipped when absent; tested).
* The `UserWarning: detpy: pytest-xdist is not supported under --det` is gone (it aborted pydantic-ai and prefect
  under `filterwarnings = error`).
* Record mode (`--det-record`): each worker writes `cassette.gwK.json`, the controller merges them into the cassette.
* `--det-outcomes` from the controller carries the order, the fingerprints (from the merge) and the plan.
* `LIMITS.md` O1 rewritten.

Tests (`tests/test_parallel_proof.py`): one trace per worker and a merged trace with every test once, `worker` set, in
serial order (today's engine: the header-only `"collection": "failed"` file); merged fingerprints equal serial ones;
byte-identical merge from the same worker traces (also a Rust test); no warning under `filterwarnings = error`; a
worker killed by `os._exit` leaves `missing`, its replacement runs the rest of its list (`gw1`), and the crash is in
`meta.parallel.crashed`. Rust: merge order, missing/unreadable workers, serial lines without worker fields.

Measured (esphome, every `-n 4` run): merged trace covers 14,446 of 14,446 tests (design: 0 tests today).

### P2: the fixed plan (`schedule.rs`, `DetScheduling` in `xdist.py`)

What changed:
* `detpy_core::schedule::plan`: atoms from `--dist` (`load`/`worksteal`: one test; `loadscope`: module or class;
  `loadfile`: file; `loadgroup`: `xdist_group`, else one test), costs = median of the last 3 recorded durations
  (`.detpy/durations.json`, written by the controller of every `-n` run; else the cache entry's duration; else the
  median of the known ones, else 1 s) summed in integer microseconds, LPT with ties broken by the atom key's digest,
  sticky (previous atom -> worker kept while the makespan is at most 10 % + 1 s above LPT's), per-worker lists in
  serial order, plan digest. `chunk_test_atoms`: for one-test atoms, consecutive tests of the same file travel
  together, at most `ceil(tests / (workers x 8))` per chunk, boundaries from the collection only (see placement above:
  175 -> 32 on esphome; module fixtures are set up once per chunk instead of once per worker).
* `DetScheduling`: xdist's scheduler protocol; after all collections it decides reuse (P3), plans and sends every
  worker its whole list with one `send_runtest_some` followed by `shutdown`; no refill, no stealing; a crashed
  worker's remaining list goes to its replacement (never a rebalance). `--dist each` keeps xdist's own scheduler
  (header line).
* Under `--dist loadgroup` the workers no longer append `@group` to node ids (the ids stay the serial ids for traces
  and cache keys); each worker writes its groups to `.detpy/xdist-groups.gwK.json` for the controller's atoms.
* `testrun_uid` derived from (seed, selected paths, `--dist`, N) unless `--testrunuid` is given.
* `.detpy/plan.json` (lists, atoms, every test's worker); `--det-plan=FILE` replays an assignment under `-n`
  exactly; `--det-plan=FILE --det-plan-worker=gwK` runs worker K's list serially in one process with its
  `PYTEST_XDIST_*` variables and `worker_id` / `testrun_uid` fixtures.

Tests: Rust property tests (same input -> same plan; any permutation of the input gives the same assignment; lists
are subsequences of the serial order covering every test once; atoms never split, for every mode; makespan within
LPT's (4/3 - 1/3m) OPT bound against an exhaustive OPT on 200 random small instances; stickiness kept within the
tolerance, dropped beyond it, kept within the absolute slack on tiny suites; chunks consecutive, same-file, bounded,
independent of durations, never touching group atoms). pytester: two runs give identical per-worker lists and
fingerprints; lists are subsequences of the serial order; `loadgroup` groups on one worker with serial ids;
`loadscope`/`loadfile` units never split; `testrun_uid` stable across runs with different output options, changes
with the seed; `--det-plan-worker` replays each worker's list serially with the same fingerprints (the worker-id
reader included); `--det-plan` replays the assignment under `-n`; without `-n` nothing changes (no plan file,
trace format as before).

Measured: see exit numbers (wall, plan identity, fingerprints).

### P3: the cache with proof across workers (`proof.rs`, `session.rs`, `proofcache.rs`, `proofcache.py`)

What changed:
* **Decided once, in the controller**, before the plan: `changed_code_files` + facts + `check` of every collected id
  (`decide_controller`); the verification draw is seeded by (seed, order digest, configuration digest), so two runs
  on the same inputs verify the same tests. Hits are reported by the controller (synthesised setup/call/teardown
  reports) and never sent to a worker; misses and verified hits are planned.
* **Workers only record**: no decision in a worker; each writes a shard (`<cache>/shards/<run>.gwK.json`: its entries,
  touched ids, the fixture contexts of its tests, every path key it wrote with the writer contexts) and its summary
  into `workeroutput`.
* **Cross-worker write rule, one merge** (`proof::merge_shards`, Rust): the writers of all workers are united; an
  entry that read a path (or listed a directory) another test or a fixture the test does not use wrote, in any worker,
  is dropped ("reads a file another test or fixture wrote in another worker"); a reused result whose input the session
  wrote is dropped from the store; then all shards are merged into the store once under the directory lock; shards
  are removed. The result is independent of the order the workers finished in (tested).
* **Keys equal to serial keys**: xdist's options (`loadgroup`, `maxprocesses`, `maxworkerrestart`, `testrunuid`,
  `looponfail`, `distload`, ...) and `--det-plan*` are volatile; `_` and `PYTEST_XDIST_*` are outside the
  whole-environment digest (read by name they stay inputs); the controller checks `PYTEST_XDIST_WORKER` against the
  worker the test had in the previous (sticky) plan, `_COUNT` and `_TESTRUNUID` against this run's. Two causes found
  on the way and fixed: (a) workers have the rootdir on `sys.path` once more, so `importlib.metadata` listed the project's
  own distribution twice and the runtime digest differed in every worker (every warm entry missed with `runtime`):
  distribution parts are now de-duplicated; (b) a popen worker inherits its controller's C-level environment, where
  readline put `COLUMNS=80 LINES=24` (plain xdist workers have them too): every test missed on `env: *`; the
  controller now passes its own values and the worker restores them before anything reads the environment.
* Receipts and the summary come from the controller (one file, every test), with a line on the merge.

Tests (pytester): the design's wrong reuse (A writes a file outside the repository in worker 0, B reads it in worker
1, `value.txt` then changes): B is never cached, and fails in session 3 as serially; serial and `-n 2` sessions
take the same decisions (the worker-id reader excepted, by design); two `-n 2` sessions write identical receipts; a
store written under `-n` serves a serial run; the verification sample is the same in two parallel runs; shards are
merged and removed; whole-environment readers are reused under `-n`; workers see the controller's `COLUMNS/LINES`.
Rust: the rule (own writes and used fixtures credited, startup/import/collection contexts credited, listings), shard
order independence, removal of touched-absent entries, stale hits, the whole-environment exclusions.

Measured (esphome, batch `esphome4`): see the exit table. Cold `-n 4`: 14,141 entries recorded, 28 dropped by the
cross-worker rule; warm: 14,141 and 14,149 reused (98 %), 9 dropped by the rule per run. Cross-mode: a parallel run
on the serial store reuses all 14,151 serial hits; a serial run on the parallel store reuses 11,078 (77 %): the
3,071 misses are `env`, the tests that enumerate `os.environ` (enumeration reads every variable by name, and a
worker's `PYTEST_XDIST_*` are not set serially: a real difference, not a key defect).

Walk (`walk_n.py`, esphome, 10 consecutive first-parent commits 34b24d0c .. 141789d2, oldest first, caches kept across
commits; every reused result compared with a fresh serial `--det` run at the same commit, mismatches re-run serially):

| commit | `-n 4` wall | reused (of tests) | serial wall | reused | `--det` serial (truth) | mismatches / wrong |
|---|---|---|---|---|---|---|
| 0 34b24d0c (cold) | 107.2 s | 0 / 14,432 | 226.2 s | 0 | 163.6 s | 0 / 0 |
| 1 5c061f9e | 46.8 s | 14,125 | 81.4 s | 14,136 | 160.7 s | 0 / 0 |
| 2 cfa27cea | 79.1 s | 0 / 14,437 (code 14,126) | 218.2 s | 0 (code 14,137) | 165.4 s | 0 / 0 |
| 3 bc6fb708 | 49.2 s | 13,917 / 14,439 | 84.9 s | 13,928 | 163.0 s | 0 / 0 |
| 4 dbf6af2f | 47.0 s | 14,141 | 80.4 s | 14,151 | 166.4 s | 0 / 0 |
| 5 84dea807 | 46.0 s | 14,140 | 75.0 s | 14,150 | 167.7 s | 0 / 0 |
| 6 9bf2bbc2 | 84.5 s | 0 / 14,446 (code 13,472, data 669) | 226.2 s | 0 (same) | 190.0 s | 0 / 0 |
| 7 773afa0b | 50.0 s | 14,140 | 81.4 s | 14,151 | 166.1 s | 0 / 0 |
| 8 c4df1b16 | 47.5 s | 14,147 | 78.5 s | 14,158 | 168.3 s | 0 / 0 |
| 9 141789d2 | 89.2 s | 0 / 14,446 (code 14,138) | 257.0 s | 0 (same) | 170.1 s | 0 / 0 |

**0 wrong reuses** (MEASURED): 84,610 results reused under `-n 4` and 84,674 serially, every one compared with the
serial `--det` truth at its commit: 0 mismatches in either mode (so no B' rerun was needed). **Reuse share**: 58.59 %
under `-n 4` against 58.64 % serially over the same commits (0.05 point; design target: within 1 point; three of the
ten commits change code every test depends on and reuse nothing in either mode, for the same reasons). The
parallel/serial difference is 10-11 tests per warm commit, all of them `new` (no entry): about 9 per run are the
entries the cross-worker write rule drops (a test reading a file another worker's test wrote), the rest are not
recorded under `-n` for the same reason in the cold run. Warm `-n 4` walls 46.0-50.0 s against
75.0-84.9 s serial warm and 63.6-74.0 s plain `-n 4` (batch `esphome4`). Commits 0-2 ran while the engine's full test
suite ran on the same machine: their walls are inflated (not used above). Raw: `build/esphome/walk-n4-10commits.json.gz`.

### P4: shared cache from the controller

Not built: the shared-cache client (`remote_cache.py`, `claude/shared-cache`) is not on `claude/rust-hotpaths-2`,
the base of this branch. What P3 prepared for it: every decision and the single store merge happen in the controller;
workers never touch the store, so pull-before-decide and push-after-merge have one place each.

### P5: the proof (partial)

Built: `detpy verify` classifies a divergence `placement` when exactly one of the two traces is a merged parallel
trace and the test lost serial in-process predecessors in its worker (they are listed, at most 20); entropy and
thread divergences keep their class (Rust test; synthetic polluter/victim through the harness test; esphome: 32).
`fpcompare` counts serial noise, placement, new failures caused by the split and hidden failures per repository.
Not built: the `tmp_path` counter normalisation (it changes serial fingerprints: kept out of this change), the
serial fingerprint per entry and the parallel-vs-serial comparison at record time, the serial-equivalent rerun,
`parallel-proven`/`parallel-unproven` tags, together-edges. Until then a parallel entry is offered to serial runs
and vice versa on equal keys (as P3 specifies); the walk is the evidence that this made no wrong reuse on esphome.

### P6-P8

Not started.

## Rules check

* Determinism: same plan, same per-worker order, same results on runs 2 and 3 (MEASURED above); the first `-n` run of
  a checkout plans on unit costs and its plan differs from the next one's.
* Cache correct across workers: keys (equal to serial except the worker-id reads), receipts (from the controller,
  identical across two runs, tested), verification (deterministic draw, compared in the controller), cross-worker
  write rule; audit reruns in isolation: not built.
* 0 wrong reuses in the walk; 0 new failures caused by the split (esphome, 14,446 tests, 0 outcome differences).
* The serial path without `-n`: unchanged in behaviour and trace format (tests; full suite of the engine: 534 passed, 9 skipped, 1 failed under load: `test_capture_sessions_match_reference` session 5 counted 2 instead of 3 child entropy draws while the walk ran on the same 4 cores; it passed 2 of 2 times alone afterwards, and an earlier full run of this branch (parallel tests excluded) had 512 passed, 9 skipped, 0 failed; the 23 parallel tests and 2 harness tests pass). Three changes
  reach serial cache keys and invalidate existing stores once: xdist's options are volatile (they were in the
  configuration digest of every session where xdist is installed), `_` and `PYTEST_XDIST_*` left the
  whole-environment digest, duplicate distribution entries count once. The reference implementation used by the
  equivalence tests (`tests/rust_hotpaths_ref`) got the same three changes.

## Not done, and what blocks it

* pydantic-ai: the design's prerequisite (2,769 failures under `--det-cache` from the capture's audit hook in the
  asyncio loop thread, empty store) is not fixed here; `--det -n 4` alone was not re-measured for time.
* prefect, litellm, moto, mlflow: not run (prefect needs uv >= 0.13.4; the others for time). The Actions workflow is
  the way to run them.
* P3 walk: 10 commits of one repository instead of 50 commits of three.
* P3 isolated audit reruns; P4; most of P5; P6-P8.
* Blacksmith runner: not available.
