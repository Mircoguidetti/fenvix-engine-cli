# Phase A: are the 12 Python cache attack failures real? (release-1 6e79a62c)

Spec "false greens on release-1", Phase A steps 1-5. No cache code was changed in Phase A.

## Evidence

| | GitHub runner | this session's container |
|---|---|---|
| where | release-1.yml run **45577065513** (push of 6e79a62c), job `attacks (py 3.13, node 24)` id 139078912752, conclusion `failure` | `git worktree` of 6e79a62c, CPython 3.13.18, Node 22.23.5, kernel 6.18.44-fc-v880, engine built locally (`maturin build --release`, manylinux_2_34; CI builds manylinux_2_28 with zig) |
| command | `python3 tests/attacks.py` (all 12 Python attack files, `-q -rfE`) | `python3 -m pytest -v -p no:randomly -p no:cacheprovider -rfE tests/test_review_r056_pycache.py` |
| result | `12 failed, 152 passed, 7 skipped in 607.00s`; node half 60/60 | `12 failed, 21 passed in 273.92s` |
| failures | all 12 in `tests/test_review_r056_pycache.py`, no other file | the same 12 |

The nightly run 45606263407 (schedule, same sha) also concluded `failure`; its log was not read (the push run is
the first run on 6e79a62c). The per-test assertions of the CI run were read from the job log (line numbers of
`tests/test_review_r056_pycache.py`: `_check` line 79 is the cached-run assertion, line 78 the precondition; W8 line
227; W11 `_same_outcome` line 235).

## Table

`precondition` = the uncached `--det` run did not give the outcome the test names (not reproduced);
`cached-pass` = uncached `--det` fails the victim, the cached run passes it (a false green). Two tests fail on
another assertion, named in the row.

| # | test | GitHub runner (run 45577065513) | container (6e79a62c) | class | cause, with evidence | EC2 relevance |
|---|---|---|---|---|---|---|
| 1 | `test_w3_file_size_read_through_posix[posix.stat(...) == 4-serial]` | FAILED, `cached-pass` (line 79): `reused 2 result(s) with proof, ran 0`, exit 0 | FAILED, `cached-pass` (same message) | REAL | the cache records file metadata through a wrapper it binds over `os.stat/lstat/access/readlink` in every module except `posix` (`python/detpy/_proof.py:477`, `rebind` skips `posix`/`nt`, line 490); `posix.stat` is the unwrapped original, so the size read is not in the test's record. The core table calls `posix.stat` `Recorded` (`crates/detpy-core/src/provable.rs:1746`), so the sensor raises no gap either | yes: code defect, independent of the machine |
| 2 | `...[posix.stat(...) == 4-n2]` | FAILED, `cached-pass` (`reused by the controller: 2`) | FAILED, `cached-pass` | REAL | as 1, under `-n 2` | yes |
| 3 | `...[posix.lstat(...) == 4-serial]` | FAILED, `cached-pass` | FAILED, `cached-pass` | REAL | as 1 (`posix.lstat`) | yes |
| 4 | `...[posix.lstat(...) == 4-n2]` | FAILED, `cached-pass` | FAILED, `cached-pass` | REAL | as 1 | yes |
| 5 | `test_w3_file_existence_read_through_posix_access[serial]` | FAILED, `cached-pass` | FAILED, `cached-pass` | REAL | as 1 (`posix.access`; marker file removed, test reused) | yes |
| 6 | `test_w3_file_existence_read_through_posix_access[n2]` | FAILED, `cached-pass` | FAILED, `cached-pass` | REAL | as 5 | yes |
| 7 | `test_w3_file_mtime_read_through_posix_stat` | FAILED, `cached-pass` | FAILED, `cached-pass` | REAL | as 1 (mtime moved with `os.utime`) | yes |
| 8 | `test_w4_pwd_read_through_posix_environ` | FAILED, `cached-pass` | FAILED, `cached-pass` | REAL | `PWD` is on `ENV_ALLOWLIST` (`_proof.py:866`), so it is outside the process key; a read through `os.environ` is recorded per test, a read through `posix.environ` (bytes keys) is not (R-056 report, W4) | yes |
| 9 | `test_w5_kernel_release[platform.release()]` | FAILED, `cached-pass` (warm run under `setarch x86_64 --uname-2.6`) | FAILED, `cached-pass` | REAL | `process_identity` (`_proof.py:906`) keys the host name (`uname().nodename`) but not the kernel release; `posix.uname` is `Input` in the core table (`provable.rs:1749`) but its value is in no key | yes: a shared or remote cache read on a runner with another kernel (image update, instance type), with no `setarch` needed |
| 10 | `test_w5_kernel_release[posix.uname().release]` | FAILED, `cached-pass` | FAILED, `cached-pass` | REAL | as 9 | yes |
| 11 | `test_w8_c_seeded_random_is_controlled_or_refused` | FAILED on its own assertion (line 227): `reused while fresh --det runs read ['VALUE 0.0455...', 'VALUE 0.4650...']`; warm run `reused 1 result(s) with proof` | FAILED, same assertion (`0.7227...`, `0.4266...`) | REAL (wrong reuse) | `_random.Random()` with no seed seeds itself from OS entropy in C; `--det` controls `random.Random()` (Python) but not the C type, so fresh `--det` runs differ and the cache freezes one outcome | yes |
| 12 | `test_w11_object_addresses_match_uncached_det` | FAILED on its own assertion (line 235): uncached `--det` **passed**, `--det-cache` **failed** (`[5,4,2,1,0,3] != [3,4,2,0,1,5]`, `ran 1`, not reused) | FAILED, same direction (`[1,0,2,4,5,3] != [3,2,0,4,5,1]`) | REAL (wrong outcome, a false RED, not a false green) | the cached run's own allocations shift object addresses, so the iteration order of a set of default-hash objects differs from uncached `--det` | yes (both directions possible in principle; the measured one is red) |

No `precondition` failure in either environment: there is no `NO-REPRO`. No result differs between the two
environments, so there is no environmental cause to name (step 3 empty) and no `ENV`. No `UNKNOWN` is left.

## Remedies proposed (A-fix waits for the coordinator; spec gate note 6)

| family | tests | proposed remedy (spec order: key, record, refuse) | needs a decision? |
|---|---|---|---|
| W3 | 1-7 | **record**: bind the cache's recording wrapper over `posix.stat/lstat/access/readlink` too, so a direct `posix` call is recorded like `os.*`; the import system's own probes stay infrastructure (the wrapper's `_reaches_user` frame walk). If that is not clean (import-time cost, the finder), fallback **refuse**: the sensor reports a call of the unwrapped original from user code as a gap, so the test is neither stored nor reused (a category refusal: measured share first) | no for record; yes if it falls back to refuse |
| W4 | 8 | **record**: a read through `posix.environ` recorded per test like `os.environ`, so a changed `PWD` refuses reuse | no |
| W5 | 9-10 | **key**: add `uname()` sysname, release, version, machine to `process_identity` | no (cost: one cold cache per kernel change) |
| W8 | 11 | **design choice, not taken here** (spec rule 7): (a) control: seed `_random.Random()` from the `--det` seed (fresh runs equal, reuse kept; a reference bound before the session escapes); (b) refuse: the sensor reports an unseeded `_random.Random()` from user code as a gap (never reused) | **yes** |
| W11 | 12 | **design choice**: not a false green (the cached run is red where uncached `--det` is green; the rule "never pass what uncached fails" is not broken). Options: (a) accept and document as a known false red; (b) make cached runs allocate like uncached ones (no known cheap way); (c) change the attack's yardstick. Not fixed here unless the coordinator decides | **yes** |
