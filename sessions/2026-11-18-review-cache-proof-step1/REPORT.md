FIX 5

# Review R-009: cache with proof, step 1 (skip on large repositories)

Reviewer session, 2026-11-18. Engine branch `claude/cache-proof-step1`, head `646e28e` (measurement s1d on
`6fcb575`; s1e (attrs, isort) on `353b2c5`; the code between `6fcb575` and the head is only the clock RLock and
`sys._getframe` binding, `24297e9`).

**Scope limit, read first.** I could not attach `Mircoguidetti/fenvix-brain-cli`: `add_repo` was denied by the
session's permission classifier ("Unauthorized Access"). So I did **not** read CLAUDE.md, prompts/REVIEWER.md,
prompts/COMMON.md, RULES.md, prompts/P-013-cache-proof.md, the step-1 instructions, REPORT.md or
INTERMEDIATE-1.md. I checked the report's figures as quoted in the review request against the run artifacts
committed in the engine (`tracks/cache-proof/results/`). I could not check its wording, its stated limits or the
brief's acceptance criteria. This file is written to the engine review branch, not to brain `main`.

Failing tests: `tests/test_review_r009.py` on engine branch `claude/review-r009-tests` (6 tests, all fail on
`646e28e`). No GitHub Actions used.

## Verdict: FIX 5

| # | Finding | Severity | Test |
|---|---|---|---|
| F1 | A followed child started by one test and used by a later test: the later test is reused with none of the child's reads as inputs | wrong reuse, new in step 1 | `test_child_started_by_one_test_and_used_by_another` |
| F2 | A followed child's reads under `/dev/shm` are skipped (in-process they are refused) | wrong reuse, new in step 1 | `test_child_read_of_dev_shm_is_an_input_or_refused` |
| F3 | `TZ` (read by C `getenv`) and `/etc/localtime` are not inputs: `time.localtime` results are reused under another time zone | wrong reuse | `test_timezone_read_by_c_is_an_input` |
| F4 | Real-clock reads outside the virtual clock (a child process, C code such as sqlite `'now'`) are neither refused nor bounded: results are reused after the real date passed a threshold | wrong reuse; known Level 0 limit (LIMITS S1, `follow.py` docstring) that the cache turns into permanent staleness | `test_real_clock_read_in_c_is_not_reused_after_it_moves`, `test_child_real_clock_is_not_reused_after_it_moves` |
| F5 | Reads under `.git/` in the test process are dropped (`_SKIP_PARTS`): a test whose expected value or IDs come from HEAD is reused as passed at a commit where it fails (the R-010 hole, still present in `--det-cache`) | wrong reuse | `test_git_head_read_is_an_input` |

Each test changes only what a fresh run would see, then asserts the cache does not reuse the old result. In every
case the fresh `--det` run fails and the cache reports the old pass "with proof".

## F5: reads under `.git/` (coordinator's extra check, from R-010)

The same hole exists in `--det-cache`, but only in the test process. `_SKIP_PARTS` contains `/.git/`, and
`Capture._ignored()` drops every in-process open of a path containing it. A test that reads `.git/HEAD` and the
ref it points to in its own process (a hand-rolled `git_sha()` helper, dulwich, pygit2 through Python file
reads) records no input for them. In `test_git_head_read_is_an_input`, after one new commit
(`git commit --allow-empty`, which changes only `.git/refs/heads/main`), `test_in_process` is **reused as
passed**, while a fresh run fails.

The child path holds: `git rev-parse HEAD` run through `subprocess` is followed, and `child_ignored()` does not
use `_SKIP_PARTS`. Its `.git/` reads become inputs, so `test_child` re-ran and failed as it should. That covers
prefect's `tests/utilities/test_dockerutils.py` shape *when it shells out to git*. A library that reads `.git/`
in the test process (dulwich, `setuptools_scm`'s fallbacks, version helpers that parse `.git/HEAD`) is not
covered.

Fix: drop `.git` from `_SKIP_PARTS` for content reads (keep it only for code-file discovery, line 228). Or turn
a `.git/` read into an input of the reading context. The digests are cheap: `.git/HEAD` plus the one ref file,
or `packed-refs`. Objects are content-addressed, so a changed SHA always comes with a changed ref.

## 1. Subprocess handling (home-assistant 0% to 73%)

What holds. I read `follow.py` and the `collect_children` / `_audit` paths in `proofcache.py`, and probed them:

* the executable, PATH candidates before it (as missing), a shebang interpreter, and every file the tree
  opens, stats, executes or lists are inputs. The existing tests cover a changed data file, a changed imported
  module and a changed program;
* inherited environment means the whole environment is an input (`*`). With an explicit `env=`, the env-building
  code reads `os.environ` through the recorded `__iter__`/`__getitem__` (`dict(os.environ)`, `.copy()`, `.items()`
  all record `*`);
* `preexec_fn` chdir: strace 6.8 with `-y` annotates `AT_FDCWD</path>`, and the parser follows it (checked);
* a child's write followed by an in-process read in a later test is refused ("reads a file another test or
  fixture wrote: out.txt", probed);
* `os.fork`, `os.system`, `posix_spawn` are still refused. The multiprocessing forkserver's per-process
  `connect` to its Unix socket is refused (the listener is closed in the parent);
* an unknown syscall, unparsed line, network use or a still-running process refuses the context.

**F1: cross-test attribution (hole).** A child's reads are attributed to the context that *spawned* it. A
process kept alive across tests, such as a lazily created helper in a module global (a persistent shell, a
language server, a `ProcessPoolExecutor` with spawn workers, a pexpect session), does work for later tests over
pipes. That work raises no event in the later test, so the later test is recorded with **none** of those reads.
In the test: `test_a` starts `sh`, `test_b` asks it to `cat data.txt`, `test_c` closes it. Change `data.txt`
and `test_b` is reused as passed; a fresh run fails. (In that second run `test_c` is also reused, so the shell is
never closed and the session waits for its log. Reuse also drops side effects other tests rely on.)
Fix direction: a test (or fixture) context that runs while a followed process started by a *different* context
is alive is not cacheable, or that process's reads are credited to every context that ran during its lifetime.
Detection only needs the live pids of `fo.spawns` at each context switch.

**F2: `/dev/shm` (hole).** `follow.special()` returns `skip` for `/dev/shm/*`, the same as `/dev/null`. But
`/dev/shm` is a tmpfs of ordinary files, and in-process `Capture.read()` refuses any `/dev/` content read as
`proc`. A child that `cat`s a `/dev/shm` file is reused after the file changes. Fix: treat `/dev/shm/...` as
ordinary paths (digest, writes tracked) in both the child path and the in-process path. Refusing it is also fine.

Not refuted, but flagged for the brief:

* the ELF interpreter (`ld.so`) is loaded by the kernel and never appears in the trace. Shared libraries
  opened by `ld.so` do appear;
* `child_ignored()` drops this interpreter's stdlib and site-packages paths for *any* child, including a
  different interpreter or tool reading them. The runtime digest covers distributions by RECORD/metadata, not by
  file content: an in-place edit of an installed file is invisible, the same as in-process;
* `/proc/cpuinfo`, `/proc/meminfo`, `/sys/fs/cgroup/` and `/sys/devices/system/cpu/` are skipped as "machine
  shape" and are not part of the key. A child printing `nproc` is reused on a different machine. This matters
  once the cache is shared between machines (`claude/shared-cache`);
* child entropy is counted, not controlled (documented). A child whose output depends on randomness is
  reused as whichever outcome was recorded.

## 2. Epoch / clock (structlog)

The fixed cache epoch is sound for code that reads the **virtual** clock. Every reader gets the `time` flag,
the epoch is in its key, and the same epoch replays the same virtual times. `time.localtime/gmtime/ctime/
strftime/asctime`, `clock_gettime` and `datetime.now/utcnow` are all virtualised. The real-time leaks are a
different matter:

**F4: real clock outside detpy (hole).** A followed child reads the real clock (vDSO, invisible to strace), and
so does C code in-process (sqlite `strftime('%s','now')`, OpenSSL certificate validity, database drivers). Such
a test gets no `time` flag, so neither the epoch nor any real-time bound enters its key, and its result is reused
indefinitely. The two tests set a deadline 3 s in the future, record a pass, wait past the deadline, and the
cache reuses the pass while a fresh run fails. Level 0 lists this as limit S1, and `follow.py` says "not
recorded". But under the cache the effect is no longer one non-deterministic run: a stale verdict persists.
The epoch-window change makes this worse in one specific way. Before, every commit moved the epoch and
re-ran the clock readers. Now a test that compares the virtual clock with a real-time value (file mtimes,
LIMITS C7; a child's time; an OpenSSL validity check on a certificate minted with `datetime.now()`) keeps
its result for up to 30 days of HEAD movement, and for unlimited real time if HEAD does not move. Fix (choose
and state in the claim): give every entry a real-time expiry (for example the same window, measured on the
real clock at recording time). Also refuse contexts whose followed children or known C clock users
(`sqlite3` functions, `ssl` handshakes) could read real time. At minimum, the report and the claim must say
"proof modulo real-clock reads outside the virtual clock, bounded by N days".

**F3: time zone (hole).** `TZ` is read by C `getenv`/`tzset`, not through `os.environ`, so it is never
recorded. `time.localtime(0)` and `datetime.fromtimestamp(...)` change with it. With `TZ=UTC` the test is recorded;
with `TZ=Asia/Tokyo` it is reused as passed, but a fresh `--det` run fails (`'09' == '00'`, checked). The
same holds for `/etc/localtime` (opened in C, no audit event) and the locale variables
(`LC_*`/`LANG`, used by `strftime`/`locale`). Fix: put `TZ`, `/etc/localtime`'s digest and the locale variables in
the runtime/config digest (cheap, applies to every test), or record them on every local-time conversion.

Measurement note: the walk never moved the epoch for home-assistant. Its 50 commits span 11.5 h
(2026-11-16 21:07 to 2026-11-17 08:34 +01:00), one epoch for all 50 steps. Projects whose walk crossed the
30-day window (arrow, click, jinja, marshmallow, ...) did move it. The `epoch_diff` column (B at the cache
epoch vs H at the HEAD epoch) found only jinja's `test_caches_template_based_on_mtime`. That test already
differs at step 0 where both epochs are equal, so it is flaky (mtime vs virtual clock), not epoch evidence.

## 3. Do 73% / 86% and 0 wrong recompute?

Yes. I recomputed with my own script over the 31 result files (s1d without attrs/isort, plus s1e), not with
`aggregate.py`. I also regenerated `aggregate.py`'s table, which matches `step1-final.md` row for row.

* home-assistant: 16/16 shards, 50/50 commits ok on every shard, 49 transitions. Share of test time skipped:
  **median 85.9%, mean 72.5%**. Reported 86% / 73%: OK.
* verified reuses: **808,109** in total (home-assistant 430,387), every reused test present in B
  (`n_reused_in_B` = `n_reused`). **0 wrong, 2 flaky.** Reported figures: OK.
* The 2 flaky cases (both home-assistant, both cached `passed`, fresh `failed`, second fresh `passed`):
  * commit 31, shard 12: `tests/components/mqtt/test_sensor.py::test_cleanup_triggers_and_restoring_state[hass_config0]`;
  * commit 46, shard 4: `tests/helpers/test_intent.py::test_validate_then_run_in_background`.
  Both match the verdict rule (`fresh2 != fresh`): a failure that does not reproduce. Neither is a reuse error.
* `ran_diff` (executed in A, different outcome in B): home-assistant 1
  (`esphome/test_dashboard.py::test_dashboard_unsupported_version`, commit 36). The report should say whether
  this is flakiness or a reused test that no longer sets state (the F1 side-effect class).

**Is the check independent of the cache?** Partly. B is a separate `pytest --det --det-urandom` process with no
`--det-cache` (no store, no capture, no follower), at the cache run's epoch. Its outcomes are compared with A's
reused outcomes, and every mismatch is re-run (B2). That makes the check independent of the store and the key
logic. It is **not** independent of the environment: A and B run minutes apart, on the same runner, same TZ,
same `/dev/shm`, same live processes. So F1 to F4 cannot appear as "wrong" in this design. Change-driven holes
can (a commit edits an input). Environment-, time- and order-driven holes cannot. "0 wrong in 808,109" supports
"no commit-driven wrong reuse observed". It does not support "the proof holds". The report should say so.

Other notes on the table: flask has only 16 of 51 commits ok (35 `run-failed`), click 43, arrow 49. Their
percentages come from those commits only.

## 4. Is the 1.47x cold cost fair?

The number recomputes: at the 6 sampled commits (0, 10, 20, 30, 40, 49), summed over 16 shards, cold /
plain pytest = 1.47, 1.47, 1.47, 1.47, 1.47, 1.48 (per-shard range 1.34 to 1.69). It splits into **`--det` alone
1.22x** plain pytest and **capture/record 1.20x** on top of `--det` (record about 89 s over 16 shards). The
1.25x target is therefore almost entirely used by Level 0 before the cache adds anything. The report should state
the split, and say whether the target was meant against plain pytest or against `--det`.

Fairness:

* fair: same runner and units. The cold cache directory is created fresh, so `distributions.json` and the
  facts memo are cold;
* favourable to the cache: C runs after A and B at the same commit, so the fixed-seed `.pyc` prefix and
  `stamps.json` (outside the cache directory, `reexec.pyc_cache_dir`) are warm. A first run on a fresh CI
  runner also pays the stdlib + site-packages precompile (7.9 s per run per `8748d787`). The OS page cache is
  warm too, but equally for P0;
* P0 (plain pytest) is a single run per sample, and `plain_walls` are 2 `--det` runs. The spread is small
  (1.47 to 1.48 at commit level), so this does not change the figure.

## 5. Engine suite

`pytest` at `646e28e` (Python 3.13.18, strace 6.8, local release build): **134 passed, 6 skipped** in 360 s.
This matches the commit message. With the review tests: the 6 in `tests/test_review_r009.py` fail, as intended.

## Required for approval

1. F1: refuse (or credit) tests that run while another context's followed process is alive. Test 1 passes.
2. F2: `/dev/shm` content is an input or a refusal, in children and in-process. Test 2 passes.
3. F3: `TZ`, `/etc/localtime` and the locale variables are in the key. Test 3 passes.
4. F4: a real-time bound on reuse, or a refusal, for real-clock reads outside the virtual clock. Tests 4 and 5
   pass, or the claim names the limit and its bound. The brief owner decides which.
5. F5: in-process `.git/` reads are inputs. Test 6 passes; the existing tests still pass (the cache directory and
   `.detpy/` stay excluded).
6. Report wording: "0 wrong" is change-driven verification only (section 3). Give the 1.47x split (1.22 x 1.20).
   State that home-assistant's walk never moved the epoch.
