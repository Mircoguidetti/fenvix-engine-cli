{{STATUS}}

# Parallel with proof, round 3: P4, P5, SQLite clock, speed, absent inputs, review R-023b

Branch `claude/parallel-proof-3` (from `claude/parallel-proof` at a13e2dc). Final engine: **{{ENGINE}}** (code identical
to 16c3794; later commits add results and this report only). Review R-023b's tests (`tests/test_review_r023b.py`,
from `claude/review-r023b` e9e6c16) were merged unchanged and are this round's gate.

Labels: **MEASURED** = a run named here with its committed raw file; **ESTIMATED** = derived, derivation given;
**DECLARED** = read from a repository's configuration or said by another session, no raw file here; **UNKNOWN** = not
available, what was checked is said.

{{PARTIAL_BECAUSE}}

## Gates (MEASURED, final engine, this container: 4 vCPU, Python 3.13.18, pytest 9.2.0, xdist 3.8.0)

| gate | result | raw file |
|---|---|---|
| `tests/test_review_r023b.py` (review R-023b) + `tests/test_review_r023.py` | **77 passed, 4 skipped**, 0 failed (on a13e2dc: 50 failed, 11 passed, 3 skipped, per the review) | `tracks/parallel-proof/gates/r3/review-r023b-and-r023.txt` |
| full Python suite (`pytest tests -p no:randomly`, without `-n`) | **721 passed, 12 skipped**, 0 failed (1 deselected: `test_review_r017.py::test_h2_...`, the pre-existing failure REPORT-2 names; it reads a tracks file no change here touches) | `tracks/parallel-proof/gates/r3/pytest-full-summary.txt`, `pytest-full-tail.txt` |
| `cargo test --release` (workspace) | **101 + 1 passed**, 0 failed (REPORT-2: 94) | `tracks/parallel-proof/gates/r3/cargo-test.txt` |

The 4 skips of the review file are the review's own conditions (`HOSTALIASES` ignored by libc here; the `[n2]` variant
of the session-fixture test, which the review marks as not applicable under `loadfile`).

## Item 1: P4, shared cache (Rust store, Rust runtime identities)

| what | result |
|---|---|
| port of `claude/shared-cache`'s client onto the Rust store | `crates/detpy-core/src/shared.rs` (new): content-addressed documents (address = SHA-256 of the document's exact bytes, checked on every read), one *entry* document per test with its code-file facts as separate *file* documents, an append-only key log per lookup key (test id, configuration digest, runtime digest) with a checksum per line, a run log with each run's receipts document. Fetch, validation, import, adoption and push selection are Rust; the binding (`ProofCache.shared_fetch / shared_adopt / shared_push`) and `--det-cache-shared=DIR` (or `DETPY_CACHE_SHARED`) are the interface |
| runtime identity | the Rust runtime identity of the store (`identity.rs`), extended with `.pth` files and `sys.path` (root as `<root>`, `runtime_with_paths`); `runtime_id.py` (Python) is not brought over |
| the service decides nothing | a fetched candidate becomes a store entry only if `Checker::check` accepts it exactly like a local entry (code, data, environment, configuration, runtime, epoch, placement guard); otherwise the local entry stays |
| `-n` and CI jobs | the controller fetches before its decision and pushes after the merge of the workers' shards; workers never talk to the shared store; separate jobs share it through the directory (a mounted volume or a synchronised path) |
| receipts | a reused result adopted from the shared store has `"origin": "shared:<document address>"` in its receipt; each run's receipts file is pushed as a document with a run line |
| transport | the directory transport only. The HTTP service of `claude/shared-cache` (`cache_service.py`) was **not** ported: its documents are addressed over re-canonicalised JSON, this store addresses exact bytes |
| adversarial tests, Rust (`shared::tests`, MEASURED: `cargo test`) | 7 pass: round trip; **a poisoned entry from another runtime** filed under the reader's key → rejected `foreign`; **partial upload** (entry and key line present, file document absent) → `incomplete`, nothing imported; truncated document → `corrupt`; **torn key line** (crashed writer) dropped, log stays readable; tampered entry whose stored key does not match its inputs → `key-mismatch`; **concurrent writers** 8 threads x 25 pushes, 200 key lines, 0 torn, every entry fetchable; **clock skew**: candidates ordered by log position, a later push from a machine whose clock is a year behind comes first |
| adversarial tests, pytest (`tests/test_parallel_proof_round3.py`, MEASURED locally) | 6 pass: second machine reuses everything the first pushed, serial and `-n 2`, every reuse equal to a fresh serial `--det` run, receipts name the origin; a change after the push is checked like a local entry (1 reused, 3 run); entries of another configuration refiled under this key → `foreign 4`, 0 reused; file documents deleted (partial upload) → `incomplete`, every test runs; 4 concurrent jobs: lines = entries pushed, 0 torn, a fifth job reuses all 4 |
| not done | a two-machine run on Actions (P4's measurement in the design) was not run; trust is the store's access control: a writer with access can forge an outcome under a valid key (the key does not cover the outcome, as in the local store) |

## Item 2: P5 (parallel vs serial proof) and the F2 first-discovery gap

| what | result |
|---|---|
| proof | at the controller's merge, each parallel entry is compared with the stored entry of the same test: **same key and fingerprint equal to a stable serial fingerprint** (fingerprint includes the outcome) → `placement: parallel-proven`, `serial_fp` kept; **same key, other fingerprint** → diverged: not stored, the serial entry stays; no stable serial fingerprint → unproven (`parallel`). A serial entry whose key was recorded serially twice with different fingerprints is marked `serial_noise` and proves nothing (`proof.rs prove`, `merge_shards_with`) |
| F1 guard relaxed where proven | `Checker::check`: a serial session reuses `parallel-proven` entries; unproven parallel entries stay refused to serial sessions |
| N7 (review): parallel entries in parallel sessions | an unproven parallel entry is reused by a parallel session only when this run's plan gives it the **same planned in-process predecessors** (reused tests included, as a serial entry's are its serial prefix; `Entry::preds`, set at the merge from the plan, `ProofCache.preds_check`); a withdrawn one runs after those predecessors (they run too) |
| F2 first discovery | the workers' shards carry every test's read paths (any outcome). After every worker finished, the controller finds readers of a path a test on another worker wrote with no wait in this plan (`proof::racy_readers`). Under `--det-cache -n` the workers' reports are held until the run loop ends; a racy reader whose cross-worker writers all come before it in the serial order runs again in a fresh worker after them, in the serial order, and that run's reports replace its own (first report dropped). A reader with a cross-worker writer *after* it cannot be rerun into the serial view (the file holds the later write): reported **UNSETTLED** (summary line, merged trace `parallel.unsettled`); every racy pair becomes a data edge |
| related hole closed | the plan's waits: for an edge whose writer comes after the reader in the serial order (on another worker) the writer now waits for the reader (`schedule.rs`, Rust test `round3_a_writer_after_its_reader_waits_for_the_reader_across_workers`) |
| tests (MEASURED locally) | proven entries serve a serial session (6 of 6 reused); an unproven one does not; first-session reader gets the serial verdict (passes, as the serial truth) where it read the stale file before; later-writer reader reported unsettled, next session the writer waits and both pass; review `test_f1v_*` passes |
| remaining (stated) | the rerun gives the serial view only for writers that overwrite the file; an UNSETTLED verdict is reported, not corrected; held reports remove the live progress of `--det-cache -n` (they all appear at the end of the run loop); the proof needs a serial fingerprint under the same key, so a pure `-n` CI has no proven entries until a serial session (or `--det-cache-verify` in -n after one) records them. Proven/diverged/unproven counts per repository: {{P5_COUNTS}} |

## Item 3: SQLite's clock and randomness under Level 0 (prefect)

| what | result |
|---|---|
| change | `crates/detpy-py/src/sqlvirt.rs` (new), glue `detpy/sqlvirt.py`: every connection made through `sqlite3.connect` under Level 0 gets per-connection overrides of `date`, `time`, `datetime`, `julianday`, `unixepoch`, `strftime`, `timediff`, `current_date`, `current_time`, `current_timestamp` (column defaults included) and `random()`, `randomblob(N)`. A `'now'` time value (or a missing one) becomes the virtual wall clock at ms precision, read once per statement (the connection's trace starts each statement), and the call is evaluated by SQLite's own built-in on a private helper connection (exact semantics). `random`/`randomblob` draw from a SplitMix64 stream seeded per test. Clock reads are Level 0 events (`sqlite.<function>`; the cache then keys the epoch), draws are `random` events. The cache's statement trace sits behind the connection's own; a virtualised connection is not flagged `rclock` |
| tests (`tests/test_sqlite_virtual.py`, MEASURED locally) | 5 pass: identical rows and values in every `--det` run (serial, `-n 2`, `-n 3`), different without `--det`; a schema with `DEFAULT CURRENT_TIMESTAMP` and `randomblob` ids is cached and every reuse equals a fresh serial run (serial and `-n 2`); one statement's `'now'`s are one instant; explicit dates keep SQLite's semantics; a changed epoch is a miss only for the tests that read `'now'`. The real-clock refusal is kept for unvirtualised connections (`--det-disable=time`: four existing tests run that way now) |
| prefect reuse after (Actions {{RUN}}) | {{PREFECT_REUSE}} |
| N12 (review) | REPORT-2's prefect blocker was described twice, inconsistently: `uncacheable()` returns the *first* reason and `rclock` precedes `spawn`/`connect`, so "real clock 2,418" could hide a connection to prefect's API server. With the clock virtualised, the remaining reasons are visible in this round's run: {{PREFECT_BLOCKERS}} |

## Item 4: speed (re-exec before the other plugins; prefect's extra time)

| what | result |
|---|---|
| change | the re-exec now happens in detpy's own `pytest_addoption` (called as detpy registers, while pytest loads the entry points) instead of `pytest_load_initial_conftests`, with the options rebuilt from `invocation_params.args`, `PYTEST_ADDOPTS` and the ini `addopts` (`plugin.py _early_reexec`). Plugins that register after detpy are imported once (test: a `PYTEST_PLUGINS` plugin is imported by 1 process, before by 2). Plugins pytest loaded *before* detpy are still imported twice (entry-point order is not ours). Anything unusual (nested session, worker, unparsable options) leaves the decision to the old place. A plugin the user blocked (`-p no:randomly`) is never re-blocked (two review-b1 tests) |
| `--det -n 4` vs plain `-n 4` after (Actions {{RUN}}) | {{SPEED_TABLE}} |
| prefect's extra time (phase times, `harness/parallel_proof/phasetimes.py`, variants `*-pt`) | {{PREFECT_PHASES}} |

## Item 5: moto's Docker probe stays uncached

| what | result |
|---|---|
| expectation | a connection to `/var/run/docker.sock` is a real outside input: those tests stay uncached, nothing else does |
| measurement (Actions {{RUN}}, `moto/cache-*.outcomes.json.gz`, not-cached ids with reasons) | {{MOTO_DOCKER}} |

## Item 6: mlflow

| what | result |
|---|---|
| cause of the earlier collection errors | our selection lacked the CI's `--ignore=tests/examples --ignore=tests/evaluate --ignore=tests/genai --ignore=tests/docker` (DECLARED: mlflow `.github/workflows/master.yml` COMMON_ARGS, recorded in `tracks/parallel-proof/CI-FACTS.md`); those directories import the extras the group's install lacks. Fixed in `run.json` (`--requires-ssh` left out: no SSH server on the runner) |
| measurement (Actions {{RUN}}) | {{MLFLOW}} |

## Item 7: walks on the final engine (50 commits, 5 shards each, truth = fresh serial `--det` per commit)

Each shard walks 10 consecutive first-parent commits with its own cache, starting cold at its first commit (5 cold
commits per repository instead of 1). Reuse by test time = sum of the truth run's per-test time of the reused tests /
sum over all tests (durations now in the outcomes file).

{{WALKS}}

## Item 8: pydantic-ai's flaky parallel verdict

| what | result |
|---|---|
| reproduced (MEASURED locally, pydantic-ai 62e7b66, `uv sync --all-extras`) | `test_one_capability_serves_runs_on_several_event_loops_and_threads`: **3 of 15** serial `--det` runs fail, **0 of 15** plain: not the split |
| cause | traceback of the failing run: `pydantic_ai/_uuid.py uuid7` → `with _lock_v7:` → detpy `_TimedLock.__enter__` → `acquire` → blockbuster's wrapper → `BlockingError`. `_lock_v7` is a module-level `threading.Lock()` created under `--det`, so it is Level 0's `_TimedLock`. A plain `with lock:` enters through the lock type's `__enter__` slot, which blockbuster does not wrap; `_TimedLock.__enter__` called the Python-visible `acquire`, which it wraps. Blockbuster raises only when the acquire would block (`lock.locked()`), i.e. when two of the test's four threads contend for the lock: timing |
| fix | `_TimedLock.__enter__` enters the real lock through its `__enter__` (no timeout in a `with`, nothing for the virtual clock to do; no event was recorded there) |
| after (MEASURED locally) | **0 of 25** `--det` runs fail; `tests/test_timed_lock_enter.py` (2 tests) |
| on Actions ({{RUN}}) | {{PAI}} |

## Item 9: absent inputs (and review R-023b N6)

| what | result |
|---|---|
| coordination | the serial fix landed on `claude/dep-verdict-abjcfw` (e4660e8). That branch is on the pre-Rust-move engine (merge base 3e41ee0, 2026-11-18; its capture is the Python `Capture`), so merging it would bring the Python capture back against DECISIONS 2026-11-18. Its rules were ported 1:1 onto the Rust capture instead, so there is one implementation per lineage (the coordinator was told) |
| rules (Rust) | existence and kind checks (`os.stat/lstat/access`, recorded `s:<kind>`); module lookups (a finder in front of `sys.meta_path`, only when the immediate importer is user code: `proof::import_candidates`); pytest's `conftest.py`/`__init__.py` lookups from the root to the test (`proof::collection_candidates`); zip archives read by the import system; libraries newly mapped (`/proc/self/maps`, baseline = inputs of every test); `ctypes.dlopen` names (a path's kind, the loader cache for a bare name); `.pth` files and `sys.path` in the runtime identity. A kind check never replaces a content or listing dependency of the same path |
| tests (MEASURED locally) | dep-verdict's `test_proofcache_import_lookups.py` (12 cases) and review R-019c's `test_cache_stale_reuse.py` (15 cases), copied unchanged, each run **serially and with `-n 2`**: 54 of 54 pass (e9/e10 write to the shared venv: run without an outer `-n`). Review R-023b `test_3_*` (9 classes x serial/`-n 2`) and `test_3_absent_input_across_worker_shards`: pass |
| cost | data dependencies per test on the engine's own test project: about 19 (an earlier version that recorded lookups of lazy standard-library imports: about 375) |
| remaining (stated) | a lookup started by the standard library (a lazy stdlib import) is not an input: a user file that would shadow such a module is not seen |

## Review R-023b: findings and fixes

| finding | fix | test |
|---|---|---|
| N1 global /proc /sys /dev reads dropped | only this process's own state (`/proc/<self|pid|thread-self>/{fd,fdinfo,task,stat,statm,io}`: flag `pstate`) is left out of global contexts; `/proc/self/root|cwd/...`, `/proc/<..>/fd/N`, `/dev/fd/N` are resolved to the file (an ordinary input); every other read counts (data, or `proc`: uncacheable) | `test_2a_*` 8 pass |
| N2 loopback names answered by DNS | a loopback name is keyed by the resolver files only when `/etc/nsswitch.conf` puts `files` first and `/etc/hosts` lists the name; otherwise the `dns` flag | `test_2b_*` pass |
| N3 controller listener as infrastructure; address ignored | the controller's sockets are no longer the worker's own; an own listener must hold the exact address connected to (or be a wildcard listener) | `test_2c_*` 4 pass |
| N4 `--tx popen//env:` | the specs' `env:` items join the workers' snapshot; a variable the specs set differently matches no recorded digest | `test_2d_*` pass |
| N5 entropy outside `os.urandom`; first requester | `os.getrandom` and `ssl.RAND_bytes` go through the urandom stand-in (observed; controlled with `--det-urandom`); `/dev/urandom` reads are `proc`; wider-scoped fixtures draw from their own stream | `test_2e_*` 6 pass |
| N6 absent inputs | item 9 | `test_3_*` pass |
| N7 parallel entry reused by a parallel session | item 2 (planned predecessors) | `test_f1v_*` passes |
| N8 absent output of an earlier test; reused writer whose output is consumed | the existence checks cover the first; a reused writer is demoted while a reader of its output (data edge) runs in the session | `test_f2v_*` 6 pass |
| N9 `worker_id` fixture | `worker_id` / `testrun_uid` in a test's fixture closure are reads of `PYTEST_XDIST_WORKER` / `_TESTRUNUID` (the worker one checked against the plan) | `test_f3v_*` passes |
| N10 fpcompare / crosscheck | every outcome that is not a pass is a failure in fpcompare; crosscheck lists the truth's tests the run lost (`lost`) | `test_f5v_*` 5 pass |
| N11 REPORT-2 numbers | corrections below | — |
| N12 prefect's blocker | item 3 | — |

Cost of N1 (ESTIMATED from the rule): a project whose start-up reads other `/proc`, `/sys` or `/dev` paths than this
process's own state is uncacheable for every test again (REPORT-2 had made such reads global non-inputs). litellm's
import-time `/proc/self/fd` listing stays allowed (`pstate`).

### N11: REPORT-2 corrections (from the review's raw-file audit; this report does not re-derive them)

* "0 mismatches ... pydantic-ai" and "0 new failures caused by the split" hold for r023-p0 only; on the final engine
  (r023-p0c) pydantic-ai had 1 ran mismatch and 1 "new failure" (the flaky verdict of item 8, now explained).
* pydantic-ai 1.02x is the median convention; det run b (89.1 s) is below the fastest plain run, so not "inside the
  range".
* "both mixed-store directions" were measured only locally (esphome5); Actions ran `cache-x` only.
* litellm warm is 0.59x (40.7 / 69.5), not 0.58x.
* esphome5 has no crosscheck for cache-n-cold, cache-n-warm@2, cache-ser-cold, det-n-a.
* esphome walk: 16 code commits at 113.8-116.2 s, commit 18 is a data commit, commit 0 the cold start (165.0 s); moto
  walk maximum 71.5 s; esphome reuse 97.9-98.0 %; "all four" should read "all five".
* The litellm local phase table, the litellm local after-fix numbers, litellm's per-reason counts, pydantic-ai's 2,769
  failures and the gate counts had no committed raw file: DECLARED, not MEASURED. This round commits its gate outputs
  (`tracks/parallel-proof/gates/r3/`) and its per-run outcome files.
* The esphome walk of REPORT-2 ran before the rules N1-N4; this round's walk (item 7) is on the final engine.

## Not done, and why

{{NOT_DONE}}
