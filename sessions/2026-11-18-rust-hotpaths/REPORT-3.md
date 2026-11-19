DONE

# rust-hotpaths, round 3: fixes for review R-015b (G1-G3)

Branch `claude/rust-hotpaths`. Review: `claude/review-r015b`,
`sessions/2026-11-18-review-rust-hotpaths/REPORT-2.md` (verdict FIX 3). Its tests, `tests/test_review_r015b.py`, are
copied unchanged (54c5c1a).
Labels: MEASURED (numbers from runs named here), ESTIMATED (derived or inferred), unmarked = description.

**Result.** All three findings are fixed, one commit each. Every fix adds a refusal or an input; none adds a reuse.
All three changes are in the Python capture (`python/detpy/proofcache.py`, plus one field in `follow.Result`). No
Rust code changed, so the commits should merge cleanly with `claude/rust-hotpaths-2`.

## Tests: fail before the fix, pass after (MEASURED, this container, Python 3.13)

`pytest tests/test_review_r015b.py` (editable install, the Python capture reloaded at each commit):

| commit | G1[script] | G1[module] | G2 | G3 |
|---|---|---|---|---|
| 54c5c1a review tests on c9d306f | fail | fail | fail | fail |
| 7198773 G1 | **pass** | **pass** | fail | fail |
| 0007d42 G2 | pass | pass | **pass** | fail |
| ab2a069 G3 | pass | pass | pass | **pass** |

* At 54c5c1a every case fails at its last assertion: the cache hands back "passed".
* At HEAD, 3 more runs of the review file plus `tests/test_r015b_fixes.py` passed: 5 passed each time.

Suites:

* `pytest tests` at 7198773: 166 passed, 6 skipped, 2 failed (G2 and G3, the intended failures).
* `pytest tests` at HEAD: **169 passed, 6 skipped**, 0 failed. That is 164 from REPORT-2, plus the 4 review cases,
  plus 1 new test.
* `cargo test -p detpy-core` at HEAD: **49 passed**.

## G1: code run by a followed child and edited during the session

**Cause.** `collect_children` turns a child's reads into inputs at the end of the session, so it digests them then.
A file the child ran and that was then edited was recorded under its new content. F1's stat keys covered only the
parent process.

**Fix (7198773).** `Capture._changed_after_start` runs once per followed process tree at collection:

* It takes the files the tree read or executed (`r` / `x` ops).
* It skips files that are not inputs: special paths and `child_ignored` paths.
* It also skips files the tree itself wrote, and files the session wrote. Those keep their existing writers rules.
* If such a file is a regular file whose `ctime_ns` is not before the tree's first system call, every context
  credited with the tree is refused. The first system call comes from `strace -ttt` and gets 20 ms of slack for
  the kernel's coarse ctime clock. The refusal is a `spawn` flag, "`<detail> [<path> changed during the session]`".

`ctime` cannot be set back with `utime`. The check covers more than code: it covers every file the child read, both
scripts and data, since all of them were digested at the end. It refuses only when such a file changed after the
tree started.

**Test.** The review's two G1 cases (script, module).

## G2: a symlinked module pointed at another file

**Cause.** `_want` keys code on `realpath`, so the units go under the target, and the link itself was never an
input. Pointing the link elsewhere, for example with a checkout, left the old target's units unchanged. During a
session, `changed_code` resolved the link only at the end, so it named the new target.

**Fix (0007d42).**

* **The link becomes an input.** `_code_link` finds the first symlink inside the repository on a wanted code
  file's path: the module itself, or a linked directory. Links outside the root are resolved and ignored, such as
  a root reached through a linked path. When there is one, the content read through the link is a data input of
  the global import context, so it is an input of every test. A link pointed at a different file then misses.
* **F1 resolves at stat time.** `code_stat` now stores `(stat key, realpath)` from the moment the key is taken
  (`_code_key`). A link retargeted during the session reports the old target, which is the file whose units the
  test recorded.

**Cost.** Changing a symlinked module's link or content misses every test (ESTIMATED: symlinked modules are rare).

**Tests.**

* The review's G2 case.
* New: `tests/test_r015b_fixes.py::test_G2_symlink_pointed_elsewhere_during_the_session_refuses_on_the_old_target`.
  It fails without the fix (MEASURED: the test is cached instead of refused). With the fix it is refused with
  "source changed during the session: pkg/impl_1.py".

## G3: a doctest text file edited between collection and its run

**Cause.** The open hook took the F1 stat key only for `.py` files. A `--doctest-glob` file is parsed at
collection, and its `exec` event fires only when its first example runs.

**Fix (ab2a069).** The open hook now takes the stat key before the first read-only open of any file under the
root, skipping `_SKIP_PARTS` (`__pycache__`, `.git`, tool caches, `.detpy`).

* `record_session` is unchanged. It refuses only on changed files that are code inputs, here `t.whole` for the
  doctest file.
* A changed data file in the list is ignored. Data reads are digested at their first read, as before.
* Cost: one `stat` and one `realpath` per distinct file opened under the root, plus one `stat` each at record time.

**Test.** The review's G3 case.

## Commits

| commit | content |
|---|---|
| 54c5c1a | `tests/test_review_r015b.py`, copied unchanged |
| 7198773 | G1 |
| 0007d42 | G2, `tests/test_r015b_fixes.py` |
| ab2a069 | G3 |
| (this commit) | this report |
