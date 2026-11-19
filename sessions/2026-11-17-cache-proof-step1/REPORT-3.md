DONE (R1-R4 of review R-009b fixed in code, each review test fails before its fix and passes after; engine suite: 157 passed, 6 skipped). Not re-measured on home-assistant: the effect of the new refusals on the reuse share is UNKNOWN.

# Cache with proof, step 1: second fix round after review R-009b (FIX 4)

Engine repository fenvix-engine-cli, branch `claude/cache-proof-step1`, base `3e41ee0` (engine code `df409cb`, measured as `e5f4ca2` in s1g).
* Review: `claude/review-r009b`, `sessions/2026-11-18-review-cache-proof-step1/REPORT-2.md`.
* The reviewer's tests: `tests/test_review_r009b.py`, copied unchanged (commit 91c469b).
* One commit per finding, so the Rust-hotpaths session (`claude/rust-hotpaths-2`) can merge them one by one:

| commit | finding | files |
|---|---|---|
| 8fd14b4 | R3 | `python/detpy/follow.py` (clock library source) |
| 12f0af4 | R4 | `python/detpy/follow.py` (strace parser), `tests/test_proofcache_follow.py` |
| a7359b9 | R2 | `python/detpy/proofcache.py`, `python/detpy/follow.py`, `crates/detpy-core/src/proof.rs`, `crates/detpy-py/src/proofcache.rs`, `tests/test_proofcache_follow.py` |
| c872a13 | R1 | `python/detpy/proofcache.py`, `tests/test_proofcache_follow.py` |
| 2ded44f | LIMITS K1-K4 (dynamically linked Go, file timestamps) | `docs/LIMITS.md` |

The only Rust change is in R2: `Checker::observed` plus its binding `ProofCache.observed` (14 lines, no change to existing functions).

## Finding -> fix -> test

"Before" is the commit before the fix; "after" is the fix commit. Every run was MEASURED in this container (Python 3.13.18, sqlite 3.53.1, strace 6.8, gcc 13.3). On `3e41ee0` all 5 review cases fail (MEASURED, 5 failed in 70 s).

| # | Finding | Fix | Test | Before | After |
|---|---|---|---|---|---|
| R1 | sqlite reads the real clock through the schema (a column default, a trigger, a view) | Refuse any statement that may evaluate the schema on a connection whose schema may read the clock (see below) | `test_sqlite_clock_read_by_the_schema_is_refused` | fails (a7359b9) | passes (c872a13) |
| | | | mine: `test_sqlite_schema_reading_the_clock_is_refused_wherever_it_was_defined` (attached database's trigger; definition made by a fixture on the same connection; a clean schema still reused) | fails | passes |
| R2 | An exclusive create records no input | The path's state before the open is an input, in-process and in the strace parser | `test_exclusive_create_that_fails_is_an_input[O_WRONLY]`, `[O_RDWR]` | both fail (12f0af4) | both pass (a7359b9) |
| | | | mine: `test_child_exclusive_create_is_an_input` (strace parser) | fails | passes |
| | | | kept: `test_exclusive_create_at_import_does_not_drop_every_reuse` (970daef) | passes | passes |
| R3 | The Python start-up exemption also covered shutdown | Exempt only before the interpreter has ever been seen initialised and while it is not finalising | `test_python_child_clock_read_at_shutdown_is_refused` | fails (91c469b) | passes (8fd14b4) |
| | | | kept: `test_python_child_start_is_exempt_and_its_time_reads_are_refused` | passes | passes |
| R4 | A child reads the real clock through file timestamps it just set, or `/proc/<pid>` | A child's stat by path of a file its tree wrote earlier, or of `/proc/<pid>`, is a real-clock read | `test_child_reading_a_file_time_it_just_set_is_refused` | fails (8fd14b4) | passes (12f0af4) |
| | | | mine: `test_child_process_start_time_is_a_real_clock_read` | fails | passes |

### R1: sqlite schema (c872a13)

* Each connection made through `sqlite3.connect` gets a small state object: its database files (main, plus every `ATTACH`) and whether a definition it ran reads the clock. The state holds no reference to the connection: `sqlite3.Connection` has no weak references, and a cycle would delay closing it.
* A definition (`CREATE`, `ALTER`) whose text reads the clock was already refused in its own context. It now also marks the connection, which covers temporary and not yet committed definitions, and later contexts that use the same connection (a fixture's connection).
* For a database file, the schema is read from `sqlite_master` over a separate read-only connection (`file:...?mode=ro`, which the audit hook does not take as the test's read). It is memoised on the identity (inode, size, mtime) of the file and of its `-wal` file, so a schema changed by another connection or process is read again. A schema that cannot be read refuses.
* Refused: any statement except transaction control, `PRAGMA`, `ATTACH`/`DETACH`, `DROP`, `VACUUM`, `ANALYZE`, `REINDEX`, on a connection whose schema has a clock expression anywhere (the reviewer's simpler option). Conservative: a `SELECT` from a table whose only clock expression is an insert default is refused too.
* Reason in the receipts: `sqlite: the schema of <file> (<object>) may read the real clock (...)`.

### R2: exclusive create (a7359b9)

* In-process: for `O_CREAT|O_EXCL` (any access mode) and mode `"x"`, the path is read before the open: `"missing"`, or the content it then fails on.
* strace parser: a successful `O_CREAT|O_EXCL` open is recorded as the path's absence (new op `a`, recorded as `"missing"` whatever the path's state when the logs are read). A failed one stays a read, as before.
* 970daef's case. A `NamedTemporaryFile` held in a module global is created at import time, before the reuse decision. Its recorded `"missing"` would be compared with the file that the same import has just created again, so nothing would be reused.
  * For a path whose first exclusive create in the session found it missing, and which this session's code then created before the decision, the checker is seeded with `"missing"` (`ProofCache.observed`). The recorded dependency is compared with what that code saw.
  * The stale check skips such a path, unless something wrote it after the decision.
  * If the path existed at that import-time create, nothing is seeded, the current file is compared, and the entry is not reused.
* This is not bounded by max-age, and it is now closed by code.

### R3: Python shutdown (8fd14b4)

* The library keeps a static `py_seen_initialized`. It is set the first time `Py_IsInitialized()` returns 1, and after that no read is exempt.
* A read while the flag is false is also not exempt if `Py_IsFinalizing()` (3.13+) or `_Py_IsFinalizing()` (3.7-3.12) returns true. `Py_FinalizeEx` sets finalizing before it clears `initialized`, which covers a child that read no clock between start-up and exit, as in the review's test.
* If neither symbol exists (Python before 3.7), nothing is exempt: such children are refused.

### R4: file timestamps in children (12f0af4)

* Each process's trace records the first time (`strace -ttt`) it wrote each path and every successful stat by path (`stat`, `lstat`, `newfstatat`, `fstatat64`, `statx`).
* Across the tree's logs, a stat of a path the tree wrote at or before that time refuses: "reads the real clock (the time of a file it wrote: ...)". This covers `stat -c %Y`, `date -r`, `find -newer`, `make`, `ls -l` and Python's `os.path.getmtime`.
* A stat of `/proc/<pid>`, `/proc/self`, `/proc/thread-self` (and their `task/<tid>`) refuses as a process start time.
* Exempt programs: `rm`, `rmdir`, `mkdir`, `ln`, `chmod`, `chown`. `rm -r` stats what it removes, and the existing `test_child_own_temporary_files_are_not_inputs` showed it.
* Not covered, so named in the claim with the bound (round 1's rule):
  * `fstat` on a descriptor. Python's `open()` fstats every file it opens, so counting it would refuse every Python child that writes a file.
  * File timestamps read in the test process (`os.stat(p).st_mtime` after writing `p`; LIMITS C7). There is no audit event for `os.stat`.

## Other items of the review

* **s1f/s1g label.** REPORT-2's heading "Re-measurement: home-assistant (run s1f; MEASURED)" should read "Re-measurement: home-assistant (runs s1d, s1f, s1g; MEASURED; final s1g)". REPORT-2 is not on this branch, so the correction is recorded here.
* **Dynamically linked Go:** LIMITS K3 (2ded44f).
* **Netlink address-less send (Low):** not changed.

## Engine suite

Full suite at c872a13 (`pip install -e .`, `pytest tests/`): **157 passed, 6 skipped** in 463 s (MEASURED).
* 157 = R-009b's base of 149 + the 5 review cases + my 3 new tests (`test_child_process_start_time_is_a_real_clock_read`, `test_child_exclusive_create_is_an_input`, `test_sqlite_schema_reading_the_clock_is_refused_wherever_it_was_defined`).
* The 6 skips are the same as the reviewer's: `pytest_benchmark`, `time_machine`, `pytest_django` x3, `uuid.getnode` (needs `ip`).
* `cargo test -p detpy-core`: 47 passed.
* Before/after per finding: each review test was run with `python/` checked out at the commit before its fix and at the fix commit, with the current extension module. The extension only adds `ProofCache.observed`, which older Python code does not call.

## Final claim wording

> Proof of reuse, except: real-clock reads in C code inside the test process other than sqlite (OpenSSL's certificate validity, libuuid, database drivers), and file timestamps read in the test process or through a child's `fstat` on a descriptor, both bounded by `--det-cache-max-age` (30 days); and two declared standard-library exemptions (`ctypes.util.find_library`'s helpers, `uuid.getnode()`'s helpers). sqlite's real-clock reads in statements and in the schema (defaults, triggers, views) are refused, as are a child's real-clock reads, its stat of a file its process tree wrote or of `/proc/<pid>`, and every real-clock read of a Python child after start-up, shutdown included. "0 wrong in N checked reuses" means no commit-driven wrong reuse observed, not that the proof holds.

## Not done, and effects not measured

* **No re-measurement.** home-assistant was not re-run after these fixes. Each fix only adds refusals or inputs, so the 0-wrong figure cannot get worse, but the reuse share may fall (UNKNOWN):
  * R1 refuses every statement on a database whose schema has a clock default (whether home-assistant's recorder schema has one: UNKNOWN);
  * R2 makes a test that leaves a fixed-name temporary file behind (`--det-urandom`) miss in the next session;
  * R4 refuses a child that stats a file it wrote (a shell `[ -f ]` included).
* The reviewer's other notes stay as REPORT-2 lists them (machine-shared cache, ELF interpreter, locale data).
