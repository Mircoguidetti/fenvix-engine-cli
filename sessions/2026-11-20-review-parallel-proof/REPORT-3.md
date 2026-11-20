FIX 7

# Review R-023c: claude/parallel-proof-3 at 72b2c654 (engine 21b57571, REPORT-3, marked PARTIAL)

Target: commit 72b2c654 on `claude/parallel-proof-3`, report `sessions/2026-11-19-parallel-proof/REPORT-3.md`. The
review tests are in `tests/test_review_r023c.py` on `claude/review-r023c`. A failing test is a finding; a passing test
is an attack that did not get through.

Environment: this container, root, Python 3.13.18, pytest 9.2.0, pytest-xdist 3.8.0. The engine is
`maturin develop --release` of 72b2c654 in a fresh venv. One test moves `/var/tmp` and restores it (root only).

Labels: **MEASURED** = this review ran it, or read it from a committed raw file it names; **ESTIMATED** = derived, with
the derivation given; **DECLARED** = the report says so and no raw file shows it; **UNKNOWN** = not available.

Not read: the brain repository (`prompts/REVIEWER.md`, `prompts/COMMON.md`, `RULES.md`, `DECISIONS.md`). The clone
needs credentials and adding the repository was refused by this session's permission classifier. The rules applied
are the ones in the task brief and in the two previous reviews in this repository. The coordinator should check the
verdict format against `RULES.md` ("Reviewer verdicts").

## Verdict in short

* **Gates re-run: the report's numbers hold.**
  * R-023b + R-023 + R-032b files: 107 passed, 21 skipped.
  * cargo: 113 + 1 passed.
  * Full suite: see "Gates".
* **The loosened rules give wrong reuses.** Each of the following fails serially and under `-n 2`:
  * the temporary-root exclusion;
  * the mtime caller exclusions: a time read behind a stdlib frame, behind an infrastructure frame, and through a
    descriptor;
  * the F3 `cdll` scope: libc reached through `ctypes.pythonapi`.
* **The carried-set rule leaks through infrastructure objects.** State left in the `pytest` module or in `request.config`
  connects no files. The result is a wrong reuse, serially and under `-n 2 --dist loadgroup`.
* **P4 ships entries without the store-level edges.**
  * Machine 2 adopts a writer whose output a running test consumes.
  * The consumer then fails, where a fresh run passes (serial and `-n 2`).
* **A test that runs because its own input changed runs without its reused predecessors.**
  * The in-process state those predecessors leave is missing.
  * The run gives a failure no fresh run gives (serial and `-n 2`).
  * The engine's own comment in `xdist.py` names this effect, but handles it only for tests withdrawn by the preds check.
* **An unreported verdict defect in the round's own raw files.**
  * On pydantic-ai, every `--det-cache -n` run (r3-p4) fails 2,856 tests that `--det -n` passes.
  * At least 2,812 of these failures are `BlockingError: Blocking call to os.path.abspath`, which the capture's
    `want()` raises inside the test.
  * Reproduced locally.
  * REPORT-3 does not mention it.
* **Report numbers.**
  * The walk table re-derives, except two median cells.
  * "10-13x" is 10.0-13.5x.
  * "0 wrong in 182 walk commits": 0 wrong holds, but the raw files hold 147 walk commits (177 with r3-p3), not 182. The round's raw files also show the pydantic-ai ran-mismatch class above,
    on runs that are not walks.

FIX rather than FAIL:
* The contract's one unacceptable defect, a wrong reuse, is shown here only through narrow, named mechanisms. Each has
  a local fix.
* The measured walks show 0 wrong reuses.
* Seven fixes are needed (numbered E1-E7 below).
* If the coordinator treats a wrong reuse in a rule *loosened this round* as FAIL, as R-023b did for N1-N5, E1-E3
  qualify.

## Gates (MEASURED, engine 21b57571)

| gate | REPORT-3 | this review | raw |
|---|---|---|---|
| `test_review_r023b.py` + `test_review_r023.py` + `tests/review_r032b` + `test_r032b_engine.py` | 107 passed, 21 skipped | **107 passed, 21 skipped** (321 s) | re-run here |
| `cargo test --release --workspace` | 113 + 1 | **113 + 1 passed**, 0 failed | re-run here |
| full suite (`pytest tests -p no:randomly`, without this review's file) | 820 passed, 29 skipped, 1 deselected | FULLSUITE | re-run here |

## Proven errors (failing tests in `tests/test_review_r023c.py`)

All counts are MEASURED: `pytest tests/test_review_r023c.py -p no:randomly`, RESULTCOUNT. Unless marked otherwise, each
test follows these steps:
1. Two cache sessions record the test.
2. One input changes.
3. A fresh `--det` run gives the truth; it fails the test.
4. The cache run reuses the pass ("reused after its input changed").

| # | area | finding | tests (each `[serial,n2]`) |
|---|---|---|---|
| E1 | 1, loosened | the temporary-root exclusion (`capture.rs:552 is_temp_root`, used at `:407`) drops kind checks of `/tmp`, `/var/tmp` and `$TMPDIR`. `os.path.isdir("/var/tmp")` is reused after `/var/tmp` is gone. The exclusion covers `z` (sized) checks too: `os.stat("/tmp")` | `test_1a_kind_check_of_a_temporary_root_is_an_input` |
| E2 | 1, loosened | mtime exclusions. `_user_stat_caller` returns False when the immediate caller is stdlib, and `_caller_kind()=="user"` is False when the first non-stdlib frame is pytest's. So a time read behind tarfile (`gettarinfo().mtime`), or behind pytest's `LocalPath.mtime()`, is not flagged. `os.fstat` and `os.stat(fd)` are not wrapped at all (`isinstance(path, int)` returns the plain result). Change: `os.utime` only, same bytes | `test_1b_time_read_behind_a_standard_library_frame`, `test_1b_time_read_behind_an_infrastructure_frame`, `test_1b_time_read_through_os_fstat`, `test_1b_time_read_through_os_stat_of_a_descriptor` |
| E3 | 1, loosened | F3 `cdll`: `CDLL(None)` from repository code is flagged, but `ctypes.pythonapi` is the same handle (`PyDLL(None)`, created by the stdlib at `import ctypes`). Its `access()`, `getenv()`, `time()` are libc. `access(flag, F_OK)` is reused after the file is deleted | `test_1c_libc_through_ctypes_pythonapi` |
| E4 | 1, not new | permission bits are in no key: a kind check records the kind, a stat the size. `os.access(p, X_OK)` is reused after `chmod -x`. This class predates the round; it is listed because R-032b F2 made `os.stat` keyed by size "for its own sake" and `st_mode` was left out | `test_1d_permission_bits_are_an_input` |
| E5 | 2 | carried-set leak through infrastructure: `INFRA_TOP` modules are no node of `reference_closure`. A writes state into the `pytest` module or into `request.config` from `value.txt`; B asserts on it. Neither file imports a library or holds a `DYNAMIC_MARKERS` word, and they share no repository file, so A is not carried into B. After value.txt changes, A runs and B is reused (serial; `-n 2 --dist loadgroup`, same worker) | `test_2a_state_left_in_an_infrastructure_object_is_carried[pytest_module-*, config_object-*]`; the attack through `print.__self__` (builtins without the word) **passes** |
| E6 | 3, P4 | the shared store ships `Store::tests` only. `written` and `edges`, which `_demote_writers_of_running_readers` uses to keep a writer running while its consumer runs (R-023b N8), stay on machine 1. Machine 2 (empty local store) adopts writer A from the shared store, skips it, and consumer B fails with `FileNotFoundError`; a fresh run passes both (serial and `-n 2 --dist loadfile`) | `test_3a_shared_writer_is_not_reused_on_a_machine_without_the_edge` |
| E7 | 4 | a running test without its reused predecessors. A sets state in a library module (`json.r023c_ready`); B needs it and reads its own `b.txt`. b.txt changes: B runs, A is reused, B fails; a fresh run passes both. The prefix/carried rules protect the reused side only. `xdist.py:416-420` demotes predecessors only for tests withdrawn by the preds check ("a reused one would not run, and its in-process effects would be missing") | `test_4a_predecessor_whose_state_a_running_test_needs_runs_too` |
| E8 | 5, verdicts | the capture changes ran verdicts. `CaptureCore::want` (`capture.rs:738-760`) and `code_link` (`:823`) call the current `os.path.abspath` and let any exception other than OSError/ValueError through into user code. Under blockbuster (pydantic-ai) every first sight of a code file inside an event loop raises `BlockingError` in the test | `test_5a_capture_does_not_call_a_guarded_os_path_abspath` (fresh `--det` passes, `--det-cache` fails) |

E8 is not a wrong *reuse*, but the round's raw files show its scale, and REPORT-3 does not mention it (MEASURED,
`tracks/parallel-proof/results/r3-p4-2026-11-20/pydantic-ai/`):

| run | failures | crosscheck `ran_mismatches` |
|---|---|---|
| `det-n-a` | 1 | 0 |
| `cache-n-cold` | — | 2,850 |
| `cache-n-warm` | 2,856 | 2,855 |
| `cache-n-warm@2` | — | 2,809 |
| `cache-n-warm@3` | — | 2,798 |
| `cache-x` | — | 2,798 |

* `cache-n-warm` exceptions: 2,198 `CostCalculationFailedWarning: ... BlockingError: Blocking call to os.path.abspath`,
  614 `BlockingError ... os.path.abspath`, and 19 more inside exception groups.
* The "not cached: outcome 2,856" line of `summary.jsonl` hides them as ordinary failures.
* E8 counts as one of the seven fixes; E4 is counted with E2, in the same `os.stat` wrapper.

Fixes, one per finding:
* **E1:** keep the kind of the temporary roots as an input; it is one cheap dependency. Or exclude only the failed
  `mkdir` write, which was the stated motivation.
* **E2:** time-flag any `os.stat`/`lstat`/`fstat` result whose time fields reach code that is not detpy, whatever the
  immediate frame. Wrap `os.fstat` and `os.stat(int)`. Keep pytest's assertion-rewrite exclusion by its exact
  function (`_pytest.assertion.rewrite`), not by the infrastructure class.
* **E3:** treat `ctypes.pythonapi` / `PyDLL(None)` attribute access from repository code like `CDLL(None)`. One way is a
  `cdll` flag on `ctypes` `_FuncPtr` creation from a repository frame.
* **E4:** add the mode bits to `s:`/`z:` dependencies (`file:<size>:<mode>`).
* **E5:** make the `pytest` module and the config/request objects a node. Simplest: any test using `request`, or
  importing `pytest`, reaches `LIB_NODE`, as `_pytest` state is shared like a library's.
* **E6:** ship the writer records with each pushed entry, and the edges as documents. Or never adopt a shared entry
  whose test wrote a path.
* **E7:** when a test runs, run its in-process predecessors that reach it (the carried set computed for it) in the
  session too, as `xdist.py` already does for preds-withdrawn tests.
* **E8:** call the real `os.path.abspath`/`realpath`, bound at import (as `_sites._real_getcwd` does). Or catch every
  exception in `want`/`code_link`.

## Attacks that did not get through (passing tests)

* `test_2a_state_left_in_an_infrastructure_object_is_carried[builtins_without_the_word-*]`: state written into the
  builtins module through `print.__self__`, read as a bare builtin name. Not reused.
* Code reading, no test written:
  * P4 `import_entry` rejects a candidate whose `nodeid`, config, runtime or lookup key differs, or whose recomputed
    key differs. `adopt` runs the same `Checker::check` (placement guard included) as for a local entry.
  * No path was found where a fetched candidate passes a check the local entry would fail. The defect is what the
    shared store *omits* (E6), not what it accepts.

## Risks (not demonstrated; the cheapest deciding test for each)

* **R1. Concurrent pushes to one key log on a network filesystem.** `append_line` relies on `O_APPEND` single-write
  atomicity. Torn lines are dropped by checksum, so a lost line only costs reuse, but two jobs could both believe
  they pushed.
  * Deciding test: 2 jobs × 200 pushes to one key over NFS/9p; count lines against pushes.
* **R2. Other infrastructure state than E5:** `pytest.stash`, `config.cache` (with cacheprovider on), hypothesis'
  database, `_pytest` monkeypatch leftovers (`monkeypatch` is a marker, `MonkeyPatch.context` used through `request`
  is not).
  * Deciding test: E5 with `request.config.stash[key]` and with `config.cache.set/get` and cacheprovider on.
* **R3. A proven (P5) entry reused by a serial session after a predecessor is reused.** Proof is per key; E7's
  mechanism applies to a proven entry's predecessors as well.
  * Deciding test: E7 recorded in `-n 2`, proven by a serial session, then b.txt changed in a serial run.
* **R4. Mtime through other stdlib helpers:** `filecmp.cmp(shallow=True)` (mtime and size equal → True without reading),
  `zipfile.ZipFile.write` (date_time), `logging.handlers.TimedRotatingFileHandler`, `linecache.checkcache`. These are
  the same mechanism as E2; `filecmp` is the one with a likely real-world verdict.
  * Deciding test: E2 with `filecmp.cmp(a, b)` on two same-size files whose contents differ and whose mtimes are set
    equal, then different.
* **R5. A pure `-n` CI never proves entries.** REPORT-3 states this as a cost; it is not a soundness risk.

## Report numbers (item 5 of the brief)

Re-derived from `tracks/parallel-proof/results/r3-p4-2026-11-20/*-walk50-s*/walk.json`. Warm = commits that are not
`shard_first`. Reuse by time = Σ `a_par.reused_time_s` / Σ `b.test_time_s` over warm commits.

| repository | commits (warm) | reused, warm | by time | ≥50 % | wrong | flaky | carried/recorded | a_par warm median | truth median |
|---|---|---|---|---|---|---|---|---|---|
| esphome | 50 (45) ✓ | 0 / 647,556 ✓ | 0.0 % ✓ | 0 ✓ | 0 ✓ | 0 ✓ | 334,722 / 83,297 ✓ | 529.6 ✓ | 135.6 = warm median (all: 134.45) |
| litellm-vertex | 50 (45) ✓ | 0 / 187,973 ✓ | 0.0 % ✓ | 0 ✓ | 0 ✓ | 0 ✓ | 0 / 0 ✓ | 838.9 ✓ | 105.1 = warm median (all: 104.9) |
| moto | 47 (42) ✓ | 22,348 / 104,335 = 21.4 % ✓ | 19.4 % ✓ | 6 ✓ | 0 ✓ | 0 ✓ | 55,944 / 55,944 ✓ | **162.2 ≠ 161.55** (162.2 is the all-commit median) | **197.4** = all-commit median (warm: 197.65) |

* "0 wrong reuses in 182 walk commits" does **not** re-derive.
  * The committed r3-p4 walk files hold 50 + 50 + 47 = **147** commits, with 0 wrong reuses (MEASURED).
  * Adding the r3-p3 moto walks (3 shards x 10 commits, 0 wrong, engine e1f4527) gives 177, not 182.
  * The claim holds as "0 wrong", but the count does not, and 147 is the only number for the final measured engine.
* The median columns mix conventions: warm for esphome and litellm, all commits for moto. The labels say "warm median"
  and "median". The differences are small (≤ 0.7 s).
* "10-13x slower cached runs" (`summary.jsonl`, `cache-n-warm*` wall / `det-n-*` wall):
  * litellm: 873.1-1,043.1 s vs 77.3-87.5 s, i.e. **10.0-13.5x**;
  * pydantic-ai: 1,797.8-1,882.4 s vs 141.0-158.0 s, i.e. **11.4-13.3x**;
  * so "10-13x" holds when rounded down.
* The esphome/litellm walk "4-8x" is 529.6/135.6 = **3.9x** and 838.9/105.1 = 8.0x.
* Prefect: `cache-n-*` "ran" is 2,441-2,581 for 2,438 tests: the F2 reruns. "0 recorded" holds in every variant.
* Item 8 "0 outcome differences between serial and parallel `--det`" holds (`det-n-*` `ran_mismatches` 0). It is true
  only of `--det`: see E8 for `--det-cache`.
