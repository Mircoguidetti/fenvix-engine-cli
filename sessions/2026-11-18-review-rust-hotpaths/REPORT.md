FIX 4

# Review R-015: claude/rust-hotpaths (cache-with-proof hot paths in Rust)

Target: `claude/rust-hotpaths` at 3d20406; the base engine is 24b6d15, built separately to tell regressions from
pre-existing faults. Failing tests are in `tests/test_review_r015.py` on `claude/review-r015`.

| test | claude/rust-hotpaths | 24b6d15 |
|---|---|---|
| `test_F1_source_edited_during_the_run_is_not_reused` | **fails** | fails (pre-existing) |
| `test_F2_same_size_edit_with_a_restored_mtime_runs_the_new_code` | **fails** | fails (pre-existing) |
| `test_F3_venv_library_upgrade_runs_the_new_code` | **fails** | passes (**regression from #2**) |
| `test_F4_report_cold_over_plain_range_covers_every_committed_profile_shard` | **fails** | n/a (report) |
| `test_record_session_matches_reference_with_wider_scopes` (extra coverage) | passes | n/a |

Suites on `claude/review-r015`: `pytest tests` gives 158 passed, 7 skipped, and the 4 intended failures above.
`cargo test -p detpy-core` gives 49 passed. On `claude/rust-hotpaths` alone: 157 passed, 7 skipped; cargo 49 passed.

**Answer to the one question.** Three findings make the cache record, and then reuse, a result that the code it is
keyed on did not produce:

* F3 is new: change #2 opens it.
* F1 and F2 exist on the base too. #11 claims to close F2's class of fault ("Stale project bytecode ... correctness")
  but closes it only in part.

Nothing I tested in the other nine changes alters keys, receipts or decisions.

## Findings

### F1: a source edited while the session runs is recorded under its new content (wrong reuse; pre-existing)

The digests of a test's code inputs are taken at the end of the session, after the tests ran:

* `_plan`, then `_prefetch_facts`/`_facts_index`, then `_core.file_digest`.
* The import system opens a module's source only when no `.pyc` is used, and code files are not data inputs.

Scenario:

1. A test imports `pkg/mod.py` (`VALUE = 1`) and passes.
2. Before the session ends, the file is saved with `VALUE = 2`: an editor, `git checkout`, or `git pull` during a
   long run.
3. The entry records "passed" under the `VALUE = 2` digests.
4. The next `--det --det-cache` run reuses it, while a fresh run fails.

Reproduced on both engines, both with sources older than 2 s (loaded from `.pyc`) and with fresh ones (compiled from
source under #11).

Fix direction: take a stat key or digest of each repository code file when its module body is first executed (the
`exec` audit event already arms it). At record time, refuse (or do not record) tests whose code files changed since
then, for example with `why = "source changed during the session"`.

### F2: #11 only covers mtimes that are local write times (wrong result; pre-existing)

A timestamp `.pyc` is valid for `(int(mtime), size)`. `_drop_fresh_pycs` drops the bytecode of sources whose mtime
is within 2 s of `time.time()` at the precompile. A same-size edit whose mtime falls in the same second as the
compiled version is still served stale when the mtime is not the moment of writing:

* git-restore-mtime and similar CI steps set files to commit times, and rebased or scripted commits share seconds;
* bind mounts or NFS stamp files with another machine's clock (clock skew of more than 2 s);
* archives keep their stored mtimes.

The run sees a code change, so its "not reused: code" decision is right. It then executes the old bytecode and
records "passed" under the new content's digest. Every later reuse and every fresh `--det` run agree with that wrong
result, so the verification walk cannot see it.

Fix direction: validate project bytecode on more than `(int mtime, size)`. Options:

* a manifest written at the precompile, keyed per source by `(mtime_ns, ctime_ns, size, inode)`. `ctime` cannot be set
  by `utime`, so restored mtimes are caught. Drop a `.pyc` when its source's key differs.
* a digest per source compared at the next precompile.

Keep the 2 s drop for edits in the same jiffy.

### F3: #2 extends stale bytecode to installed libraries in a virtual environment (regression)

On 24b6d15, library directories inside a venv matched `_EXCLUDE` and were always compiled from source, so they could
not be stale. Since #2, they are compiled into the cache when their top-level stamp changes. `_drop_fresh_pycs` runs
for the project only.

Scenario:

1. A distribution is upgraded: its RECORD changes, so its runtime identity changes.
2. One of its modules has the same size and an mtime in the same second as before. Installers that keep archive
   mtimes or hard-link from a cache can do this, as can two installs within one second.

Then compileall keeps the old `.pyc`, and the test runs the old version's code under the new identity. The test
reproduces this with a real venv (`python -m venv`):

* 24b6d15 runs the new code (the test fails, as it should);
* the branch runs the old bytecode and records "passed".

The report treats #2 only as a set-layout question ("both are deterministic"). Stale bytecode is the risk that
matters.

Fix direction: give the library pass the same bytecode validation as F2. Alternatively, compile the library
directories with `--invalidation-mode checked-hash`, which costs a full recompile only when the stamp changes, plus
source hashing at import. Or revert #2 alone, as the report allows.

### F4: the report's numbers leave out a committed shard and use an earlier walk snapshot

These were re-derived from the raw JSON in `tracks/rust-hotpaths/`.

* **p3 home-assistant shard 5 exists and is missing.**
  * `results/p3/home-assistant-5of16.json` was committed at cdf0607 (18:19Z), before the report commit f547f00
    (18:44Z), which says the shard "had not finished".
  * Medians of 3 rounds: plain 54.0 s; `--det` 65.2 / 58.1 s; cold 73.3 / 64.8 s; warm 72.0 / 65.7 s.
  * With it, the cold/plain ratio for this branch is **1.20-1.41x** (not 1.27-1.41x) and for the base 1.36-1.57x
    (not 1.41-1.57x). `--det` / plain is 1.08-1.25x (not 1.14-1.25x). The verdict PARTIAL still holds.
* **The home-assistant walk row is the f547f00 snapshot, not HEAD.** The walk finished: w1 shard 4 is at 50
  commits, at 3d20406. At HEAD:

  | | report | HEAD |
  |---|---|---|
  | commits compared | 29 | 49 |
  | reused results, base / new | 213,929 / 213,918 | 374,443 / 374,425 |
  | reused test time | 61.3% / 62.1% | 63.7% / 64.6% |
  | commits with a different reuse count | 7 | 15 (1-2 results each) |

  Verified reuses (0 wrong, 1 flaky), cache run A and cold/plain (1.47x / 1.30x) are unchanged.
* **The stated reason for "29 commits" is wrong.** All 16 s1f shards were at 50 commits by f547f00. The limit was w1
  shard 4, at 30 commits.
* **Pygments.** w0 reached 51 commits only after the report (ff4e144), although the report calls it complete. In the
  pygments row, "verified 58,136" covers all w1 commits, while "reused 52,813" covers the 49 compared ones.
* **Labels.** The ratio columns and the cold/plain table are derived (ratios of medians) but sit under MEASURED. For
  home-assistant 10/16 (p3), a ratio of medians and the median of per-round ratios differ materially, because the
  medians come from different rounds:
  * base cold / `--det`: 0.99 (ratio of medians) vs 1.14 (median of per-round ratios). The report's "the base's
    cold run was faster than its own `--det` run" is an artefact of mixing rounds.
  * new cold / plain: 1.41 vs 1.36.

**Confirmed:**

* every value in the first profile table, and the profile rows of the cold/plain table: 5 rounds for click and
  pygments, 3 for home-assistant;
* the click and pygments walk rows;
* the engine of p2 is 58dddd1 and of w1 is f7501bf;
* p3 records acdfb95, a data-only merge of 3131a06 with identical `crates/` and `python/`;
* "cold" means an empty cache in both harnesses (`walk.py` deletes the cache directory before run C), so the
  cold/plain label is accurate.

## Checked, no finding

* **record_session (#3) against the reference loop.** I compared it rule by rule:
  * the context sets and global contexts (`g_ctx_all` order);
  * data-overlay semantics: `TestData` keeps `dict.update` order and values;
  * the `rw:` and `written` checks, and stale reuses;
  * env (encodable names sorted by code point, which equals UTF-8 byte order);
  * content, skeleton, hooks and units, and the doctest whole-file case;
  * cassette, the real-clock refusal, and the order of reported reasons.

  File facts are keyed by (path, content), so `file_of_ix` cannot alias two files. The new equivalence project adds
  inputs the author's test lacked, and gives identical decisions and canonical stores over four sessions (with a data
  change and env changes):
  * session-, package-, module- and class-scoped fixtures;
  * a subdirectory conftest;
  * a test module imported by another;
  * a session fixture writing a file read with and without the fixture;
  * environment enumeration and import-time env reads.

  One difference is only a failure mode: plan strings must be valid UTF-8 for serde. A lone surrogate, for example in
  a skip reason, loses the whole session's recording. The base raised for the same input inside `store.record`, so
  this is no regression.
* **tracer_prefixes (#1).**
  * A log whose tracer is gone cannot change.
  * A process still running when its tracer died leaves a log with no exit line, so parsing it gives "still
    running", which is refused.
  * Children forked after that descend from such a process.
  * So "every log complete" means nothing escaped tracing.
  * Misdetection (an unreadable `/proc/<pid>/cmdline`) only skips a wait, which can refuse but not wrongly reuse. An
    undecodable argument yields `None`, and then every log is waited for.
* **dist_identity (#7).** I checked the header rules against `email.feedparser` and the compat32 policy: the line
  regex, continuation lines, `lstrip(' \t')`/`rstrip('\r\n')`, the METADATA → PKG-INFO fallback for empty files, and
  decode errors. The only divergence: an **empty** `Name:` gives `""` on the Rust path and `"?"` on the fallback. Both
  are deterministic per distribution and the RECORD digest is part of the identity, so there is no reuse effect.
  I did not count it as a finding.
* **SocketScan (#5).** `fstat` gives the sockfs inode that `/proc` shows. The races (closes and reuses between the
  listing and `fstat`) are the same as in the old `readlink` code.
* **Hasher (#4).** It changes hashing only and does not change map semantics.
* **Env-read skip (#8).** It applies only when `_cur()` equals `ctx_ix[ctx]` (no import in progress) and the name is
  already in that context's set, so `env_read` would have done nothing.
* **Store-save skip (#9).** `merge_into` writes only touched entries plus `written`. With neither, the save could
  only compact, so skipping it leaves the store unchanged. Facts added during such a session are not saved, which
  costs time, not correctness.
* **File facts (#6).** Old vs new on 11,379 files (stdlib, `/usr/lib/python3/dist-packages`,
  `/usr/local/lib/python3.13/site-packages`), as module and as package: 0 differences.
* **#2 and set layout.** Within one engine, library bytecode is chosen the same way in every run. It changes only
  when a library directory's stamp changes, which changes the runtime identity too. No cross-identity reuse.

## Files

* `tests/test_review_r015.py`: F1-F4 (failing) and the extra equivalence test (passing).
* This report.
