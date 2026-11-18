FIX 4

# Review R-009b: cache with proof, step 1, fix round (last round)

Reviewer session, 2026-11-18. Engine at this branch's base: `claude/cache-proof-step1` up to `3e41ee0` (code at
`df409cb`; s1g ran on `e5f4ca2`, whose only change after `df409cb` is `tracks/cache-proof/run.json`). Inputs:
`review-input/REVIEW-R-009.md` (round 1, FIX 5) and `review-input/REPORT-2.md` (the author's fix round).

**Scope limit.** As in round 1, I worked from the engine repository only (no other repository attached, as
instructed). I did not read the brief, RULES.md or the step-1 instructions. I judged the claim as REPORT-2 words it.

Failing tests: `tests/test_review_r009b.py` on this branch (5 test cases, 4 findings). Each fails on `e5f4ca2`.
In every test the fresh `--det` run fails after the change (checked with a temporary variant that runs it first),
and the cache reuses the old pass "with proof". No GitHub Actions used.

## Verdict: FIX 4

| # | Finding | Severity | Test | Fails on |
|---|---|---|---|---|
| R1 | sqlite reads the real clock through the **schema**: a column default (`DEFAULT CURRENT_TIMESTAMP`), a trigger or a view. The statement trace sees only the text of the statement the test runs, so the context is not refused. The pass is reused after the deadline. | Medium (F4 claim: "sqlite in-process is refused") | `test_sqlite_clock_read_by_the_schema_is_refused` | 646e28e, 2180148, e5f4ca2 |
| R2 | An exclusive create (`O_CREAT\|O_EXCL`, `open(..., "x")`) records no input. Whether the path existed decides the result (lock file, pid file, "write the defaults unless the project has its own"). If the file appears, the old pass is reused. Commit-driven, **not bounded by max-age**. 970daef extends the hole from write-only to read-write exclusive creates. | Medium | `test_exclusive_create_that_fails_is_an_input[O_WRONLY]`, `[O_RDWR]` | O_WRONLY: all three; O_RDWR: only from 970daef |
| R3 | The Python start-up exemption is scoped on `!Py_IsInitialized()`. That is also true during **interpreter shutdown**: `Py_FinalizeEx` clears the flag before it tears the modules down. Every `__del__` or generator `finally` run at exit reads the real clock without being seen. | Medium (new with the clock library) | `test_python_child_clock_read_at_shutdown_is_refused` | 2180148, e5f4ca2 (646e28e: no clock library at all) |
| R4 | A child reads the real clock through **file timestamps**: it creates a file and reads its mtime (`stat`, `date -r`, `find -newer`, `tar`, `make`). There is no `clock_gettime` or `gettimeofday`, so the clock library sees nothing. The same holds for `stat /proc/<pid>` (process start time; `/proc/self` is skipped). | Medium (F4 claim: "a child that reads the real clock is refused") | `test_child_reading_a_file_time_it_just_set_is_refused` | 646e28e, 2180148, e5f4ca2 |

R1, R3 and R4 are bounded by `--det-cache-max-age` (30 days). Each still breaks a sentence of the claim as written
("sqlite ... refused"; "a child that reads the real clock ... refuses"; the exemption limited to start-up). Each
can be closed by a code change or by naming it in the claim with its bound (round 1's rule for F4). R2 has no
bound and needs a code change.

## 1. F1-F5: really fixed?

**F1, child lifetimes across tests: fixed for what I could construct.** Each tree carries [first, last] system
call time (`strace -ttt`, real clock). The timeline uses `proofcache._now = time.time`, bound at import; I checked
it is the real clock (the run id written to the receipts is the wall time). Every non-global context whose interval
overlaps the tree's lifetime gets the tree's inputs, writes and refusals. A tree still running at the end covers
everything after its start and is refused anyway. Capture starts in `pytest_load_initial_conftests`, before
conftests are imported, so a helper started by a conftest at import time is followed too. Probes:
* the reviewer's persistent `sh` shape passes;
* a `ProcessPoolExecutor` with spawn workers held in a module global: every context is refused ("a process was
  still running at the end of the session", the resource tracker). Conservative, no wrong reuse.
* Remaining (not a reuse error): a reused test does not start the helper that a re-run test needs. That shows up
  as a spurious failure, not as a wrong pass. The F1 side-effect class stays UNKNOWN, as REPORT-2 says.

**F2, `/dev/shm`: fixed.** `special()` returns None for `/dev/shm/...` (digest, writes tracked). In-process,
`read()` exempts `/dev/shm/` from the `proc` refusal. Both tests pass.

**F3, time zone and locale: fixed.** `tz_locale_identity()` sits in the configuration digest of every test. It
covers `TZ`, `TZDIR`, `LANG`, `LANGUAGE`, every `LC_*`, `/etc/localtime`'s content (symlink followed) and the zone
file `TZ` names (with `:` prefix and `TZDIR`). It reads `os.environ._data`, which raises no event. Not covered,
and acceptable for a single machine: the locale data itself (`/usr/lib/locale/locale-archive`). It matters once the
cache is shared between machines.

**F4, real clock: partly fixed.** What holds:
* `date`, `sh` builtins, Python's `time.time()` in a child, `openssl`, libstdc++ and JVM/V8-style clocks
  (all through libc's PLT) are refused;
* static, setuid and `env -i` children are refused through the missing marker;
* every Go binary I built is refused. The reason is accidental: the Go runtime reads
  `/sys/kernel/mm/transparent_hugepage/hpage_pmd_size` at start-up, which is a `proc` refusal. A **cgo** Go binary
  is dynamically linked, so ld.so loads the clock library and the marker is made. But Go reads the clock through
  the vDSO, never through libc. If a Go release stops reading that file, every dynamically linked Go child becomes
  a wrong reuse. Worth a sentence in LIMITS. I make no finding, since it cannot be shown today;
* sqlite `'now'`, `CURRENT_*` and argument-less date functions in the statement text are refused. Bound
  parameters are covered, because Python's trace callback receives the expanded SQL;
* max-age: `_run_time(run)` reads the run id, which is real UTC (`time.gmtime(_now())` with an explicit argument
  is not virtualised). An unreadable id gives age = now, so the entry expires. Correct.

Not holding: R1 (schema), R3 (shutdown) and R4 (file timestamps), above. In-process file timestamps
(`os.stat(p).st_mtime` after writing `p`) are reused the same way. I probed this; there is no committed test,
because this is LIMITS C7 at Level 0. The claim sentence should add "file timestamps" next to "real-clock reads in
C code other than sqlite".

**F5, `.git/` reads: fixed.** `_SKIP_DATA` drops `.git` from content reads only. Code-file discovery still uses
`_SKIP_PARTS`. The in-process assertion in `test_git_head_read_is_an_input` is unchanged and passes.

## 2. The changed line in `test_git_head_read_is_an_input`

**Sound. It hides no hole.** The changed assertion was about **cacheability before any change** (run 2, nothing
changed): "the git child is reused". It is now "reused, or refused with a reason naming the real clock". The F5
assertions that carry the soundness claim are untouched: after the new commit, neither test is reused, and both
fail fresh.
* If git is refused (git ≥ 2.22: trace2 reads `gettimeofday` in `common_main`, unconditionally), the post-commit
  "test_child not in reused" holds trivially. Nothing can be reused wrongly, so nothing is hidden.
* If a git build makes no clock read, the first branch applies. The child's `.git/` reads are then inputs, and the
  post-commit assertion checks them as before.

One caution for later rounds: do not exempt git's start-up read the way Python's was. `git commit`, `git log
--since` and `git gc` use the real clock for their results; commit timestamps change the SHA. The refusal
(98 tests in s1g) is the right cost.

## 3. New holes introduced by the fixes

* **Exclusive create (970daef): hole, R2.** The rationale "the file did not exist, so it is an output only" is
  true only when the open succeeds. The audit hook runs before the open and cannot know the outcome. In the
  strace parser, a failed exclusive open is still recorded as a read (good), but a successful one records no
  absence. Fix direction: record the path's **existence** at the time of the open as the input ("missing" when it
  succeeds), not its content. A `NamedTemporaryFile` with a fixed name is deleted at close, so it is missing again
  at the next check, and 970daef's problem (every reuse dropped) does not come back. Do the same in the strace
  parser for a successful `O_CREAT|O_EXCL`.
* **Python start-up exemption: hole, R3.** Fix: in the library, exempt only until the first time
  `Py_IsInitialized()` returns true. Keep a static `seen_initialized` flag, set it once the function returns 1,
  and never exempt after that.
* **`find_library` helpers (clock-exempt, still followed for files): holds.** Only `ctypes/util.py` frames from
  the standard library qualify (`_sites._classify`). The result is a path matched in the output, and the files are
  still inputs. The DECLARED label is right.
* **`uuid.getnode()` helpers (not followed, keyed on `/sys/class/net` listing plus each `address`): holds.** I
  checked that `_core.file_digest` reads sysfs content (distinct digests for `lo` and `eth0`). `uuid.uuid1()` also
  reads the real clock in C (`_uuid.generate_time_safe`, libuuid) in-process. That falls under the bounded "C code
  in-process" sentence.
* **Netlink rule: holds for `bind` and addressed sends.** An address-less `send` on a netlink socket that was
  never bound (the kernel autobinds) gives `fam is None`, and the parser skips it as "a connected socket". glibc's
  `getifaddrs`, iproute2, Go and pyroute2 all bind, so I could not build a realistic wrong reuse. Low: tighten it by
  matching the `-y` fd annotation (`NETLINK`) on `sendto` / `sendmsg`.
* **Clock library marker: holds.** `unmarked` is reset at every successful `execve` and cleared only by the
  constructor's `faccessat` on the marker path. A failed preload (wrong architecture, setuid, `env -i`) leaves it
  set. Forked children without exec inherit the library. The one gap is runtimes that bypass libc for the clock
  while linked to it (dynamically linked Go, see F4).

## 4. Headline numbers (s1g), re-derived

I used my own script over the 16 `tracks/cache-proof/results/s1g/home-assistant-*of16.json.gz`, not
`aggregate.py`. All files are engine `e5f4ca2`, 50/50 commits `ok` on every shard, and one epoch for the whole
walk.

| figure | REPORT-2 | re-derived | |
|---|---|---|---|
| time reused, median / mean (49 transitions) | 94% / 76% | 93.7% / 76.0% | OK |
| tests reused, median / mean | 97% / 78% | 97.0% / 78.1% | OK |
| r5's window, median / mean | 92% / 75% | 92% / 75% (commits 9..49: 41 commits, 40 transitions) | OK (the label counts commits, not transitions) |
| reuses checked (wrong, flaky) | 455,510 (0, 2) | 455,510 (0, 2); `n_reused_in_B` = `n_reused` | OK |
| flaky cases | mqtt `test_cleanup_triggers_and_restoring_state[hass_config0]`, shard 12, commits 10 and 26 | same | OK |
| commits that rerun everything | 7 / 49 | 7 / 49 | OK |
| cold / plain pytest, median (worst shard) | 1.48x (1.61-1.65x) | 1.478 (1.606-1.646) | OK |
| cold / `--det`; `--det` / pytest | 1.21x; 1.22x | 1.207; 1.225 (mean of the middle pair 1.224/1.225) | OK |
| refusals per commit | 270 of ~11,900 | 269.3 | OK |
| refusal split | 10,888 / 1,078 / 741 / 245 / 245 | same; subprocess 98 git + 49 `sh` clock + 49 `hostname` unshimmed + 49 `sh` no log | OK |
| shard 5 | 44% to 79% | 44.0% to 79.2%; other 15 shards within 0.8 points of s1d | OK |
| `ran_diff` | 1, insteon `test_get_ha_device_name` | shard 4, commit 34, same test | OK |

s1d and s1f re-derive the same way (s1d 86/73, 430,387 (0, 2); s1f 80/64, 374,443 (0, 1)).

Labels:
* the section heading "Re-measurement: home-assistant (run s1f; MEASURED)" should read s1g (or s1d/s1f/s1g): the
  table's bold column is s1g;
* "0 wrong in 455,510" is worded correctly as change-driven only. R2 is the one finding here that a commit could
  surface in such a walk. The others (R1, R3, R4) are time-driven, and this design cannot see them.

## 5. Engine suite

Full suite on the base engine (`pip install -e .`; Python 3.13.18, strace 6.8, gcc, go 1.24.7, git 2.43.0):
* without the review file: **149 passed, 6 skipped** (275 s). REPORT-2 has 148/7; the total is the same (155).
  Here the skips are `pytest_benchmark`, `time_machine`, `pytest_django` ×3 and the `uuid.getnode` test ("needs ip,
  sysfs"). I did not find which test is skipped in the author's environment and runs here;
* with `tests/test_review_r009b.py`: **5 failed, 149 passed, 6 skipped** (329 s). The 5 failures are exactly the
  review tests. Nothing else regresses.

## Required for approval

1. R1: refuse a context whose sqlite statement runs against a schema that reads the clock. Check
   `sqlite_master.sql` (main, temp, attached) for the same expressions: defaults, triggers, views and generated
   columns, cached by `PRAGMA schema_version`. Or name it in the claim with the 30-day bound.
   `test_sqlite_clock_read_by_the_schema_is_refused` passes, or the claim names it.
2. R2: an exclusive create records the path's existence as an input, in-process and in the strace parser. Both
   cases of `test_exclusive_create_that_fails_is_an_input` pass, and
   `test_exclusive_create_at_import_does_not_drop_every_reuse` still passes.
3. R3: the Python exemption ends for good once the interpreter has been initialised.
   `test_python_child_clock_read_at_shutdown_is_refused` passes.
4. R4: refuse a child that stats a file its own tree wrote (or `/proc/<pid>`), or name file timestamps (children
   and in-process) in the claim with the 30-day bound. `test_child_reading_a_file_time_it_just_set_is_refused`
   passes, or the claim names it.
5. Fix the s1f/s1g label. Add the dynamically linked Go note to LIMITS.
