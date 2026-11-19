FIX 3

# Review R-015b: claude/rust-hotpaths after the R-015 fixes (last round)

Target: `claude/rust-hotpaths` at 7019e96. Its engine code is b757657; later commits are results, docs and the
review input. The engine before the fixes is 3d20406, built separately to tell regressions from pre-existing faults.
Failing tests are in `tests/test_review_r015b.py` on `claude/review-r015b`.

| test | claude/rust-hotpaths (fixes) | 3d20406 (before the fixes) |
|---|---|---|
| `test_G1_code_run_by_a_child_and_edited_during_the_session_is_not_reused[script]` | **fails** | fails (pre-existing) |
| `test_G1_code_run_by_a_child_and_edited_during_the_session_is_not_reused[module]` | **fails** | fails (pre-existing) |
| `test_G2_symlinked_module_pointed_at_another_file_is_not_reused` | **fails** | fails (pre-existing) |
| `test_G3_doctest_text_file_edited_between_collection_and_its_run_is_not_reused` | **fails** | fails (pre-existing) |

On both engines, every test fails at its last assertion: the cache hands back "passed". The preconditions hold first:
the session that recorded the result passed, and a fresh `--det` run of the code on disk fails. On the fixes, 3 extra
runs gave the same 4 failures each time.

Suites (MEASURED, this container, Python 3.13.18):

* `pytest tests` on `claude/review-r015b`: **163 passed, 7 skipped, plus the 4 intended failures**.
* Without the new file: 163 passed, 7 skipped. REPORT-2 says 164 passed and 6 skipped. The total is the same (170).
  The skips depend on the environment: pytest_benchmark, time_machine, pytest_django (3), "needs ip, sysfs", numpy.
* `cargo test -p detpy-core`: **49 passed**.

**Verdict.** The four R-015 fixes are real. They are not just test-shaped:

* checked-hash bytecode is written for the stdlib, site-packages and the project, and the import system checks it;
* the in-process refusal covers every code input that `record_session` assembles;
* the report corrections re-derive correctly.

None of the three findings below is a regression from the fixes. Each one is a wrong reuse of the same class as F1
or F2: a result recorded under code that did not produce it. REPORT-2 says this class is closed: "Code read with no
`open` event and no module body run is not covered; I know of no such path for repository code". Child processes,
symlinked modules and doctest text files are three such paths.

## Findings

### G1 (Medium, pre-existing): code run by a followed child is digested when the session ends

`Capture.collect_children` turns strace logs into inputs at the end of the session. `child_read` calls `read`, which
digests the file then, unless an in-process read already hashed it. Code a child read, then edited before the session
ends, is therefore recorded under its new content. F1's stat keys (`code_stat`) cover only the parent process.

Scenario (the test):

1. `test_tool` runs `python tool.py` (`print("A")`) and asserts its output. Two variants:
   * the script run as a program;
   * `python -c "import tool"` with an explicit `env=` (no detpy bytecode cache).
2. While the session runs, `tool.py` is saved as `print("BB")`.
3. The entry records "passed" under `tool.py`'s new digest.
4. A fresh `--det` run fails, and `--det --det-cache` reuses "passed".

When the child imports a project module with the inherited environment, the checked-hash `.pyc` from detpy's cache is
also a data input. The next precompile rewrites it, so the entry misses. That protection is accidental. It does not
cover:

* a script run as a program (`__main__` never comes from a `.pyc`);
* children with their own environment;
* non-Python programs and data files that children read.

Fix direction: strace `-ttt` gives the time of each read. At collection, treat a child-read path whose `ctime_ns` is
later than the child's first read of it as changed, and refuse the contexts credited with it. `ctime` cannot be set
back. Alternatively, digest and stat each tree's reads when its process exits, then compare the stat keys at record
time, as F1 does.

### G2 (Medium, pre-existing): a symlinked module is keyed on its target; changing the link reuses the old code's result

`Capture._want` resolves `co_filename` with `os.path.realpath` and records units under the target, for example
`pkg/impl_1.py` for `pkg/mod.py -> impl_1.py`. The link itself is never an input: the import system's open of
`pkg/mod.py` is an `import` read, which is not recorded.

git stores symlinks. A checkout that points `pkg/mod.py` at `impl_2.py` leaves `impl_1.py`'s units unchanged, so the
entry is reused while the code on disk is `impl_2.py`. This needs no edit during the session. Changing the link during
a session also escapes F1:

* `changed_code` resolves the path at the end, to `pkg/impl_2.py`;
* the test's units are in `pkg/impl_1.py`, so the test is not refused.

Fix direction: when `realpath(abspath(f)) != abspath(f)` for a wanted code file, add each symlink on the path as an
input of the contexts that ran that code, for example with a readlink dep. Also give F1 the resolved path when the
stat is taken, not at the end.

### G3 (Medium, pre-existing): a doctest text file edited between collection and its run

F1's stat key is taken:

* at the first read-only `open` of a **`.py`** file under the root, or
* when a module body first runs.

pytest's doctest plugin parses a `--doctest-glob` text file at collection. The file's first example runs (and fires
the `exec` event that takes the stat) only when its turn comes, possibly the whole session later. An edit in between
is not seen, and the whole-content input (`t.whole`) is digested at the end.

The test collects `test_wait.py` and `z_doc.txt`. While `test_wait` waits, the file is changed from `>>> 1 + 1\n2` to
`... 3`. The session passes, a fresh run fails, and the cache reuses "passed".

Fix direction: take the stat key at the first read-only open of any file that is later a test module or the
`co_filename` of an executed module body, not only `.py` files. For example, keep the stat of every read-only open
under the root, and keep those that turn out to be code. Or compare each code file's `ctime_ns` with the time of
its first read.

## Item 1: the fixes

**Checked-hash bytecode (F2/F3).** Verified in code and by experiment:

* `_pycompile.py` writes `CHECKED_HASH` pycs through `py_compile`. `py_compile` hashes the bytes it compiles, so a
  race with an edit cannot pair a hash with other code.
* The skip compares the full 16-byte header: magic, flags = 3, and the source hash.
* The driver is used for libraries and for the project. `stamps-v3` forces one recheck of every library directory.
* The exec'd interpreter has `PYTHONPYCACHEPREFIX` set and looks only there, so stale in-tree `__pycache__` files are
  never used.
* `--check-hash-based-pycs` keeps its default, under which a checked pyc is checked.

Coverage by location:

| where | status |
|---|---|
| project | precompiled |
| site-packages / venv libraries | precompiled; an in-place edit without a stamp change fails the hash check and compiles from source |
| editable installs | modules under the root are the project. A mapping outside the root and outside site-packages is never precompiled and always compiles from source, so it cannot be stale. |
| namespace packages | entered by the walk like any directory |
| symlinked directories | not entered, as with `compileall`; their modules always compile from source |
| zipapps / zip imports | not precompiled. `zipimport` checks hash pycs itself. Zip-imported code was never an input (pre-existing, stated in REPORT-2). |

**Refusal for code changed during the session (F1).** `code_changed` in `record.rs` covers every code input that
`record_session` assembles:

* `pre_ix` and global whole files, through `g_changed_all`;
* `g_units`, filtered by `in_scope` / conftests exactly as the units are;
* per-context units and whole files;
* `t.whole`;
* skeleton and hooks from `loaded_order`, at `seen_at <= index`.

The open hook stats before the read. A write between that stat and the read is a refusal, which is the safe side.
The holes are G1-G3, outside the in-process `.py` path.

Two windows are not findings:

* **The root reached through a symlinked path.** The open hook compares the unresolved path with the resolved
  `root_sep`, so the stat falls back to the `exec` event. The window is the compile time.
* **Preloaded modules.** These are stat-ed at capture start, after pytest read them. The window is the start-up time.

## Item 2: new holes and determinism

* **No new wrong-reuse hole from the fixes.** The precompile only replaces how bytecode is validated. F1 only adds
  refusals. G1-G3 fail identically on 3d20406.
* **Same code objects (MEASURED).** I compiled one module of 400 functions with set-literal membership tests
  (`frozenset` constants, colliding short strings) under `PYTHONHASHSEED=0` and loaded it three ways. The
  `frozenset` iteration orders:
  * timestamp pyc and checked-hash pyc: **identical** (digest `7531cf6a51f9ca41`), since marshal writes the same
    code;
  * fresh compile from source: different (`9d65025361b7116b`), as `reexec.py` documents.
* **No determinism regression.** A module runs from a fresh compile only when its source no longer matches its
  pyc:
  * Before: a timestamp mismatch. That also covered touched but unchanged files, and #11 compiled every project file
    fresher than 2 s from source in that run and loaded it from bytecode in the next.
  * Now: only a content mismatch, so fresh-vs-pyc layout changes between runs are rarer than before.
* **Engines interleaved in one job.** `profile.py` keeps one bytecode cache per engine (`pyc-<engine>`). The base's
  `compileall` (timestamp) and the new driver (hash) therefore do not convert each other's pycs between rounds.

## Item 3: overhead numbers (p5-r015), re-derived from the raw JSON

All walls are medians of `walls` in `tracks/rust-hotpaths/results/p5-r015/*.json`. The engine is b757657 for every
project. Confirmed:

* every wall in the table: plain, `--det`, cold and warm, base and new;
* the home-assistant per-round `--det` walls: 35.23 / 34.67 / 35.05 and 32.47 / 32.47 / 30.91;
* cold/`--det` 1.09x / 1.13x (per-round 1.10x / 1.16x);
* the record phases: facts 1.40-1.46 s, assemble 0.39 s, save 0.21 s;
* the store and receipt equivalence counts: click 2 store diffs (data inputs: cached `.pyc` files read by a child),
  pygments 0 (noise 10), home-assistant 0;
* the local supplement: pygments `--det` 1.11x / 1.11x, cold 1.30x / 1.28x, warm 4.60 / 4.38 s.

The "no added overhead" conclusion holds.

Label nits (Low; they do not count):

* **pygments base `--det`/plain.** 21.41 / 19.48 = 1.099, while the median of per-round ratios is 1.115. The
  difference is 0.016, above the report's own 0.01 bracket rule, so it should read "1.10x (1.12x)".
* **home-assistant base `--det`/plain.** 35.05 / 28.85 = 1.2149, so it should read 1.21x, not 1.22x. The median of
  per-round ratios is also 1.215.

## Commits

| commit | content |
|---|---|
| (this branch) | `tests/test_review_r015b.py` (G1-G3, 4 failing tests), this report |
