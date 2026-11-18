DONE (F1-F5 fixed, each with a test that fails on 646e28e; engine suite green; home-assistant re-measured: 76% mean / 94% median, 0 wrong in 455,510 checked reuses). The step's cold-run target vs plain pytest is still missed: 1.48x.

# Cache with proof, step 1: fix round after review R-009 (FIX 5)

Engine repository fenvix-engine-cli, branch `claude/cache-proof-step1`.
* Fixes: 2180148 (F1-F5); 970daef (exclusive create, found while checking); df409cb (netlink, `uuid.getnode`, `find_library` helpers, found by the first re-measurement).
* Re-measurements, same 12% sample and 16 shards × 50 commits as s1d:
  * run `s1f` (run 44303725521, engine 99010e4), home-assistant plus structlog: intermediate, see below;
  * run `s1g` (run 44344295442, engine e5f4ca2), home-assistant: final.
* Results: `tracks/cache-proof/results/s1f/`, `s1g/`; aggregates `step1-fix1.md`, `step1-fix2.md`.
* Review: `sessions/2026-11-18-review-cache-proof-step1/REPORT.md`; the reviewer's tests are `tests/test_review_r009.py`, copied from `claude/review-r009-tests`.

## Required for approval: status

| # | Finding | Fix | Test (fails on 646e28e, passes on df409cb) |
|---|---|---|---|
| F1 | A child started by one test and used by a later test | Each followed process tree carries its lifetime (`strace -ttt`, real clock). Every test, fixture or collection context that ran during that lifetime gets the tree's inputs, writes and refusals, as the context that started it does. A tree still running at the end covers every later context. | `test_child_started_by_one_test_and_used_by_another` |
| F2 | `/dev/shm` skipped in children | `/dev/shm/...` is an ordinary file path (content digest, writes tracked), both in children and in-process. | `test_child_read_of_dev_shm_is_an_input_or_refused`; mine: `test_dev_shm_read_in_process_is_an_input` |
| F3 | `TZ` and `/etc/localtime` not in the key | These are now in the configuration digest of every test: `TZ`, `TZDIR`, `LANG`, `LANGUAGE`, every `LC_*`, `/etc/localtime`'s content, and the content of the zone file `TZ` names. | `test_timezone_read_by_c_is_an_input`; mine: `test_time_zone_file_content_is_configuration` |
| F4 | Real-clock reads outside the virtual clock | **Refused**, with one documented exemption and an expiry bound for what detpy cannot see; see below. | `test_real_clock_read_in_c_is_not_reused_after_it_moves`, `test_child_real_clock_is_not_reused_after_it_moves`; mine: `test_sqlite_statement_reading_now_is_refused_and_others_are_not`, `test_python_child_start_is_exempt_and_its_time_reads_are_refused`, `test_entry_older_than_max_age_is_not_reused` |
| F5 | `.git/` reads in the test process dropped | `.git/` is excluded only from code-file discovery. In-process reads under `.git/` are inputs (HEAD, the ref file, `packed-refs`, the index...). | `test_git_head_read_is_an_input` (one line changed, see below) |

**Engine suite:** 148 passed, 7 skipped (MEASURED, Python 3.13.18, strace 6.8, gcc). That includes the reviewer's 6 tests and my 9 new tests.
* The reviewer's 6 and my first 5 fail on 646e28e (MEASURED on a worktree).
* The exclusive-create test fails on 2180148.
* The netlink and `find_library`-clock tests fail on 970daef. Each of those is the commit before its fix (MEASURED).
* The `uuid.getnode` test needs the `ip` program and is skipped in this container. home-assistant's shard 4 exercises that path on CI (below).

### F4 in detail (the brief owner's choice: refuse, plus a bound)

* **Children.** strace cannot see reads through the vDSO. So every followed child gets a small clock library in `LD_PRELOAD`, compiled once with `cc` into the cache directory.
  * The library turns the child's real-time reads into system calls that strace records: `CLOCK_REALTIME`, `_COARSE`, `_ALARM`, `TAI`, `gettimeofday`, `time` and `timespec_get`. Monotonic clocks keep the vDSO.
  * Its constructor makes a marker call. A program that ran without it is detected: static binaries, Go programs, setuid programs, or a child that dropped `LD_PRELOAD`.
  * A child that reads the real clock, or a program that ran without the library, refuses the contexts it is credited to (see F1).
  * If no C compiler is available, every followed child is refused, with that reason.
* **Exemption: Python start-up.** Python's `time` module reads the real clock once while the interpreter initialises, to compute the zone offsets. Reads made before `Py_IsInitialized()` is true are not counted. Their effect, the current UTC offset, depends on `TZ` and the zone file, which F3 keys. Without this exemption every Python child would be refused.
* **In-process sqlite.** `sqlite3.connect` installs a statement trace. A statement that may read the real clock refuses its context: `'now'`, `CURRENT_TIMESTAMP`/`DATE`/`TIME`, and `date()`, `time()`, `datetime()`, `julianday()`, `unixepoch()` or `strftime(fmt)` without a time value. Limit: a trace callback set by the test itself replaces detpy's.
* **Bound for the rest.** `--det-cache-max-age` (default 30 days, real clock): an entry recorded longer ago is never reused (miss reason `expired`). This bounds the real-clock reads in C that detpy does not see (OpenSSL's certificate validity, database drivers).
* **Exemptions, both DECLARED from the calling standard-library code:**
  * the helpers of `ctypes.util.find_library` (their real-clock reads do not refuse);
  * `uuid.getnode()` helpers (not followed; keyed on the machine's network identity).
* **Claim wording:** "proof, except real-clock reads in C code other than sqlite inside the test process, which are bounded by 30 days, and two declared standard-library exemptions".
* **Consequence for git children.** `git` reads the real clock when it starts (one `gettimeofday` inside `main`, computing the offset of trace2's clock). So every test that runs git is refused. The reviewer's `test_git_head_read_is_an_input` expected the git child to be reused on the second run, before any commit. I changed that one line to accept either a reuse or a refusal whose reason names the real clock. The F5 assertions are unchanged: no reuse after the new commit, and both tests fail fresh.

### Found while re-measuring (fixed, 970daef)

An exclusive create (`O_CREAT|O_EXCL`, mode `"x"`) was recorded as a read of the file.
* How it showed up: `ctypes.util.find_library`'s gcc fallback creates a `NamedTemporaryFile` at import time, and under `--det-urandom` its name is the same in every run. So every test had that path as an input, and the next session, which creates the file again, dropped every reused result as stale.
* Effect, MEASURED locally on home-assistant shard 0, where libturbojpeg is not in the linker cache: after a full-reuse run, 441 of 441 entries were dropped.
* Why s1d did not show it on home-assistant: on CI, `libturbojpeg0` is in the linker cache, so there is no gcc fallback. pylint's pyenchant does take the gcc fallback on CI; the effect on pylint's s1d numbers is UNKNOWN (pylint was not re-measured).
* Now an exclusive create is an output only, in-process and in the strace parser. Test: `test_exclusive_create_at_import_does_not_drop_every_reuse`.

### Found by the first re-measurement (s1f; fixed in df409cb, re-measured in s1g)

s1f gave home-assistant **64% mean / 80% median** (MEASURED), below s1d. Two import-time children were refused by the new F4 rule, and each refusal covered every test of its shard:
* `gcc` from `asyncssh/crypto/pq.py:185`, which calls `ctypes.util.find_library("oqs")`: on GitHub's runner gcc reads the real clock (69,972 test results refused, shard 5);
* `ip` from `pyezvizapi/constants.py:16`, which calls `uuid.getnode()` (29,106, shard 4).

What that exposed and how it is fixed:
* **A hole, closed: netlink.** `ip link` reads the kernel's interfaces over netlink with `bind` and an address-less `send`, and the parser skipped both. Any netlink use by a child is now network (refused). The hole has existed since patch 0009; s1d therefore reused tests whose import-time `uuid.getnode()` read the MAC address through `ip` (one shard; the MAC address does not change on one runner, so no wrong reuse was possible in the walk).
* **`uuid.getnode()` helpers** (`ip`, `ifconfig`, `arp`...) are no longer followed. Their result is this machine's MAC address, so the input is the machine's network identity: the `/sys/class/net` listing and each interface's `address`. This is the same pattern as find_library's `ldconfig -p`.
* **`find_library` helpers** (gcc, ld, objdump) are still followed for their file inputs, but their real-clock reads do not refuse: `find_library` returns the path of a library file matched in their output. This exemption is DECLARED from `ctypes/util.py`, not proven.

### Also fixed

Waiting for strace logs at the end of the session used `time.monotonic` / `time.sleep` at call time, which Level 0 had virtualised. The wait was a busy loop with virtual timeouts. It now uses real clocks bound at import.

## Re-measurement: home-assistant (run s1f; MEASURED)

Run **s1g** (final): 16 of 16 shards succeeded, 50 of 50 commits each, 49 transitions.

| measure | s1d (before) | s1f (F1-F5 only) | **s1g (all fixes)** |
|---|---:|---:|---:|
| time reused, median / mean | 86% / 73% | 80% / 64% | **94% / 76%** |
| on r5's 41-commit window, median / mean | 86% / 72% | 79% / 63% | **92% / 75%** |
| reuses checked (wrong, flaky) | 430,387 (0, 2) | 374,443 (0, 1) | **455,510 (0, 2)** |
| commits that rerun everything | 7 / 49 | 7 / 49 | 7 / 49 |
| cold / plain pytest, median (worst shard) | 1.47x | 1.47x | **1.48x** (1.61-1.65x) |
| cold / `--det`, median | 1.20x | 1.20x | **1.21x** |
| `--det` / plain pytest, median | 1.22x | 1.22x | 1.22x |

* **Why s1g is above s1d (MEASURED per shard).** The mean share of 15 shards is within 1 point of s1d. Shard 5 goes from 44% to 79%: in s1d, asyncssh's import-time `find_library` created its `NamedTemporaryFile` in every session, and the exclusive-create bug dropped shard 5's reused results as stale (970daef).
* **The 2 flaky cases.** Both are the same test, `tests/components/mqtt/test_sensor.py::test_cleanup_triggers_and_restoring_state[hass_config0]`, at commits 10 and 26 of shard 12. Cached pass, fresh fail, second fresh pass. This test was also the flaky one in s1d and s1f.
* **Remaining refusals** (summed over 49 transitions; 270 tests per commit of about 11,900, 2.3%):
  * reads a file another test wrote: 10,888 (`tests/testing_config/.HA_RESTORE_RESULT` 6,027, `known_devices.yaml` 3,822, `content` 931, `tts` 108);
  * `/proc`, `/sys`, `/dev` content: 1,078 (`/proc/stat` 637 + 98 + 49, `/sys/class/tty/ttyS0/type` 196, `/proc/self/cgroup` 49, `/proc/net/psched` 49);
  * failed outcome: 741;
  * host name lookup: 245;
  * subprocess: 245, of which:
    * `git` reads the real clock: 98;
    * `sh` from `shell_command` reads the real clock: 49;
    * `hostname` (datadog) is a program the clock library cannot load into: 49;
    * `sh` left no trace log: 49.
* **structlog (s1f):** 100% / 73%, 34,465 checked, 0 wrong; unchanged from s1d (MEASURED).
* **Not re-measured:** pylint and the 12 libraries. The fixes add refusals (real clock in children, netlink, sqlite `'now'`) and also remove the stale-drop bug, so their shares may move either way (UNKNOWN).

## Report wording the reviewer asked for

* **"0 wrong" means change-driven verification only.** The fresh run B is a separate `pytest --det` process without the cache, at the same commit and epoch, minutes after the cache run, on the same runner. It detects wrong reuses caused by a commit that changes an input. It cannot detect holes driven by the environment, the real time or the order of tests (F1 to F4 are of that kind): A and B share the time zone, `/dev/shm`, the live processes and nearly the same real time. So "0 wrong in N checked reuses" means "no commit-driven wrong reuse observed", not "the proof holds". The reviewer's tests are now the evidence for the environment and time holes.
* **The cold-run cost splits into 1.22x × 1.20x (s1d, MEASURED).** On home-assistant the cold run is 1.47x plain pytest:
  * `--det` alone costs 1.22x plain pytest (re-exec, precompile of the project, Level 0 patches);
  * the cache's capture and recording cost 1.20x on top of `--det`.

  The 1.25x target is nearly used up by Level 0 before the cache adds anything. Whether the target was meant against plain pytest or against `--det` is for the brief owner. Against `--det`, the cache meets it (1.20x).
  
  Fairness (reviewer's notes, accepted): the cold run follows A and B at the same commit, so the fixed-seed bytecode cache and its stamps (outside the cache directory) are warm. A first run on a fresh CI machine also pays the stdlib and site-packages precompile (7.9 s per run on home-assistant's venv, MEASURED locally).
* **home-assistant's walk never moved the epoch.** Its 50 commits span 11.5 hours (2026-11-16 21:07 to 2026-11-17 08:34 +01:00), so one epoch held for every step. The epoch window is exercised only by the libraries whose walks span months (structlog, attrs, arrow, click, jinja, marshmallow...). The jinja `epoch_diff` (`test_caches_template_based_on_mtime`) also differs at step 0, where both epochs are equal. It is flaky (file mtime against the virtual clock), not evidence about the epoch.
* **flask, click and arrow** percentages come from the commits whose full run worked: 16, 43 and 49 of 51 (`run-failed` at the others, as in r5).
* **home-assistant's `ran_diff` of 1 in s1d** (`esphome/test_dashboard.py::test_dashboard_unsupported_version`, commit 36: executed in the cache run, a different outcome in B). The esphome dashboard tests differ in the same way in s1d (`test_dashboard_unsupported_version`) and s1f (`test_dashboard_supports_update`), at different commits. s1g has 1 such case, in insteon (`test_get_ha_device_name`). Executed tests only (no reused test is involved); ESTIMATED flaky. These walks cannot tell flakiness from a missing side effect of a skipped test: the reviewer's F1 side-effect class remains a possibility (UNKNOWN).

## Limits that stay (named, with the fix that would close each)

* A trace callback set by the test replaces detpy's sqlite statement trace (F4 in-process).
* Real-clock reads in C code other than sqlite in the test process: bounded by `--det-cache-max-age` (30 days), not proven.
* Followed children see `LD_PRELOAD` (the clock library) in their environment. A test that compares a child's whole environment would see it (ESTIMATED rare).
* Children that are static binaries, Go programs or setuid programs are refused. find_library's `ldconfig -p` keeps its special case: its input is `/etc/ld.so.cache`, because ldconfig is static.
* The reviewer's flagged-but-not-refuted notes stay as they were. They matter once the cache is shared between machines:
  * the ELF interpreter is not in the trace;
  * reads of this interpreter's stdlib and site-packages by a child are covered by the runtime identity, not by file content;
  * the machine shape (`/proc/cpuinfo`, cgroups) is skipped;
  * child entropy is counted, not controlled.
* Whole-environment inputs across CI jobs (REPORT.md "What blocks").

## Links

* Engine: branch `claude/cache-proof-step1`, commits 2180148, 970daef, df409cb.
* Runs: s1f https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44303725521 ; s1g https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44344295442
* Main files: `python/detpy/follow.py` (clock library, timestamps, `/dev/shm`), `python/detpy/proofcache.py` (lifetime crediting, sqlite trace, expiry, tz/locale identity, `.git`, exclusive create), `python/detpy/plugin.py` (`--det-cache-max-age`), `tests/test_review_r009.py`, `tests/test_proofcache_follow.py`.
* Aggregates: `tracks/cache-proof/results/step1-fix1.md` (s1f), `step1-fix2.md` (s1g).
