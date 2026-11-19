FAIL

# Review R-023b: claude/parallel-proof at a13e2dc (REPORT-2, marked PARTIAL)

Target: commit a13e2dc on `claude/parallel-proof`, report `sessions/2026-11-19-parallel-proof/REPORT-2.md`. It answers
review R-023 (`claude/review-r023`, `tests/test_review_r023.py`). The review tests are in `tests/test_review_r023b.py`
on `claude/review-r023b`. A failing test is a finding; a passing test is an attack that did not get through.

Environment: this container, root, 4 vCPU, Python 3.13.18, pytest 9.2.0, pytest-xdist 3.8.0, gVisor kernel. The engine
is `maturin develop --release` of a13e2dc in a fresh venv. Some tests change host files (/etc/resolv.conf, /etc/hosts,
site-packages, /dev/shm) and restore them; they skip when not run as root.

Labels: **MEASURED** = this review ran it, or read it from a committed raw file it names; **ESTIMATED** = derived, with
the derivation given; **DECLARED** = the report says so and no raw file shows it; **UNKNOWN** = not available.

## Verdict in short

* **The original R-023 cases are fixed.** `tests/test_review_r023.py` passes 17 of 17 (MEASURED, one run, 50 s).
* **New variants of the findings still get through.**
  * **F1:** a parallel entry is reused by another *parallel* session that places the test as serial does.
  * **F2:** an absent file that an earlier test creates gets through, and so does a reused writer whose output is gone.
  * **F3:** xdist's `worker_id` fixture gets through.
  * **F5:** `error` outcomes are not counted.
  * F4 holds under four new variants.
* **Every new cacheability rule of this round gives a wrong reuse**, serially and under `-n`:
  * **2a:** a `/dev/shm` flag, any file opened through `/proc/self/root/...`, and the CPU set read from
    `/proc/self/status`.
  * **2b:** a loopback name that glibc resolves through DNS.
  * **2c:** data served by a conftest listener in the controller, and a cross-worker relay through it. The listener
    match also ignores the address.
  * **2d:** a variable that `--tx popen//env:` sets in the workers.
  * **2e:** OS entropy that is not `os.urandom` (`os.getrandom`, `ssl.RAND_bytes`, `/dev/urandom` read at import),
    and a session fixture whose `--det-urandom` bytes come from the first test that requests it.
* **Absent inputs (3)**: all nine classes give a wrong reuse serially **and under `-n`** (18 tests). A cross-shard
  variant gives one more. `-n` is not worse than serial, and it is not better either.
* **Numbers (4)**: most numbers re-derive from the raw files, but 9 do not. Two In-short claims are false for the final
  engine: pydantic-ai "0 mismatches" and "both mixed-store directions". Several MEASURED blocks have no committed raw
  file.
* **PARTIAL items (5)**: they are honestly described, except prefect. Its blocker reason is masked by the order in
  which reasons are checked, and the report gives two contradictory causes.

FAIL rather than FIX: the soundness claim ("a test skipped only with proof") does not hold for code paths this round
added. Five new rules each have a demonstrated wrong reuse.

## Findings

All counts are MEASURED (`pytest tests/test_review_r023b.py -p no:randomly`): **50 failed, 11 passed, 3 skipped**.

| # | severity | finding | tests (failing unless marked) |
|---|---|---|---|
| N1 | high | /proc, /sys, /dev reads in global contexts dropped as inputs: wrong reuse | `test_2a_conftest_import_reads_dev_shm[serial,n2]`, `test_2a_any_file_read_through_proc_self_root[serial,n2]`, `test_2a_pool_size_from_proc_self_status[serial,n2]`; passes: `test_2a_between_tests_hook_reads_dev_shm_into_the_environment[serial,n2]` |
| N2 | high | loopback-name lookups keyed by 4 resolver files, but glibc may answer through DNS | `test_2b_loopback_name_answered_by_dns_is_not_reused[serial,n2]`; control passes: `test_2b_hosts_file_change_is_seen[serial,n2]`; skipped: `test_2b_hostaliases_...` (libc ignores HOSTALIASES here) |
| N3 | high | controller listener = infrastructure: test-controlled and outside data flow through it; listener match ignores the address | `test_2c_data_served_by_a_controller_listener_is_an_input`, `test_2c_cross_worker_state_through_a_controller_listener`, `test_2c_listener_match_ignores_the_address[serial,n2]` |
| N4 | high | controller decides with its own snapshot; workers started by `--tx popen//env:` differ | `test_2d_variable_set_by_the_tx_spec_is_seen`; control passes: `test_2d_variable_set_by_a_worker_only_hook_from_a_recorded_file` |
| N5 | medium | entropy outside `os.urandom` is not observed; `--det-urandom` bytes of a session fixture depend on the first requester | `test_2e_os_getrandom_is_entropy[serial,n2]`, `test_2e_ssl_rand_bytes_is_entropy[serial,n2]`, `test_2e_dev_urandom_read_at_import_is_entropy[serial,n2]`, `test_2e_session_fixture_entropy_depends_on_the_first_requesting_test[serial]` (`[n2]` skipped: under loadfile the new test is on another worker) |
| N6 | high | absent inputs: wrong reuse in all nine classes, serial and `-n` | `test_3_failed_optional_import_later_satisfied`, `test_3_new_conftest`, `test_3_path_exists_of_a_file_created_later`, `test_3_namespace_package_gains_init`, `test_3_new_pth_file`, `test_3_zipimport_member_appears`, `test_3_zipimport_member_changes`, `test_3_ctypes_library_changes`, `test_3_ctypes_library_appears` (each `[serial,n2]`), `test_3_absent_input_across_worker_shards` |
| N7 | high | F1 variant: a parallel entry reused by a parallel session whose fresh verdict is the serial one | `test_f1v_parallel_entry_is_not_reused_by_a_parallel_session_that_places_the_test_like_serial` |
| N8 | high | F2 variants: an absent output of an earlier test; a reused writer whose output was consumed | `test_f2v_absent_file_created_by_an_earlier_test_is_not_reused[serial,n2]`, `test_f2v_reused_writer_whose_output_is_gone[serial,n2]`; passes: `test_f2v_reader_of_a_directory_another_test_changes_is_not_reused[serial,n2]` |
| N9 | medium | F3 variant: `worker_id` fixture readers are not checked against the plan | `test_f3v_worker_id_fixture_reader_is_not_reused_when_the_plan_moves_it` |
| N10 | low | F5 variants: fpcompare ignores `error` / `+teardown-error` outcomes; crosscheck does not report tests the run lost | `test_f5v_fpcompare_counts_an_error_caused_by_the_split[error,failed+teardown-error,passed+teardown-error]`, `test_f5v_fpcompare_counts_a_serial_error_hidden_by_the_split`, `test_f5v_crosscheck_counts_a_test_the_run_lost` |
| N11 | medium | report numbers: 9 mismatches; MEASURED without raw files; rows not labelled by run | none (raw-file audit below) |
| N12 | low | PARTIAL: prefect's blocker is described with two contradictory causes, and one is masked | none (log lines below) |
| — | holds | F4 stickiness under other changes | passes: `test_f4v_plan_stays_sticky_under_other_changes[new_file_in_middle,remove_middle_test,add_16_tests]`, `test_f4v_plan_stays_sticky_when_durations_move_within_noise` |

How each wrong-reuse test runs (`three_sessions`):
1. Two cache sessions record the test.
2. One input changes.
3. A fresh `--det` run gives the truth; it fails the test in every case reported here.
4. A cache run reuses the test as passed: wrong reuse.

## 1. F1-F6: re-run and new variants

* `tests/test_review_r023.py`: **17 passed** (MEASURED). REPORT-2's "17 passed" holds.

**N7 (F1).**
* The guard refuses parallel entries to *serial* sessions only. A parallel session reuses parallel entries
  (`Checker::check`, miss kind `placement` only when the session is serial).
* Case: polluter and victim.
  1. `-n 2 --dist loadfile` records the victim's pass; it ran alone in its worker.
  2. `-n 1` runs both tests in one worker. A fresh `-n 1` fails the victim, and so does the serial truth.
  3. The cache `-n 1` run reuses the pass. Neither truth gives this verdict.
* The same holds for any later `-n` run whose plan puts the polluter before the victim in one worker (`--det-plan`,
  another `-n`, another `--dist`).
* Fix: offer a parallel entry only to a session whose plan gives the test the same in-process predecessors, or refuse
  parallel entries everywhere until P5.

**N8 (F2).**
* `test_f2v_absent_file_created_by_an_earlier_test_is_not_reused`:
  * B asserts a file does not exist. A, earlier in the serial order, creates it once value.txt changes.
  * The persisted writer record holds only paths that exist at save. B's recorded "absent" matches when the session
    decides, and the turn-time recheck (`written_input`) does not cover a path that did not exist.
  * Serial and `-n` both reuse B.
* `test_f2v_reused_writer_whose_output_is_gone`:
  * A writes a spool file outside the repository; B reads it and deletes it (a queue, a lock file).
  * "Persist while the path exists" forgets the writer, because the path is gone at save.
  * Next session A is reused and writes nothing. B runs and fails with `FileNotFoundError`; a fresh session passes
    both (serial and `-n`).
  * Reusing a test whose side effect a later test consumes is the 1.4.5 class seen from the writer's side.
* Fix:
  * Keep written paths (and writers of absent paths) regardless of existence.
  * Do not reuse a writer while a running test reads a path the writer wrote.
* The directory-listing variant passes: listing a directory another test changes is not reused.

**N9 (F3).**
* `worker_id` (xdist fixture, `config.workerinput`) is not `PYTEST_XDIST_WORKER`, so `Checker::defer_worker` never
  sees it.
* A test asserting `worker_id == "gw0"`, recorded on gw0 and pinned by `--det-plan` to gw1, is reused; fresh it fails.
* `testrun_uid` and `request.config.workerinput` are the same class (not tested separately).

**F4.** Holds in four new variants, with at most 5 % of tests moved in each (MEASURED, binding):
* a one-test file sorting in the middle;
* removal of a test from the middle of a file;
* 16 tests added to one file;
* every duration moved by ±10 %.

**N10 (F5).**
* `det_outcome` produces `error`, `failed+teardown-error` and `passed+teardown-error`.
* `fpcompare.compare` compares with the literal `"failed"`, so:
  * a test that passes serially and errors in both parallel runs is an outcome difference, but not a "new failure
    caused by the split";
  * a serial `error` that the split turns into a pass is not a hidden failure.
* `crosscheck.compare` iterates over the run's outcomes only. A truth test missing from the run is not counted anywhere.
* The REPORT-2 numbers themselves are unaffected: there is no outcome difference other than pydantic-ai's one
  `failed`. The checks are blind to the class, though.

**F6.** 74.0 x 158.15 / 160.9 x 1.05 = 76.37 s (ESTIMATED, arithmetic). Correct.

## 2. The new cacheability rules

**N1, rule a (`record.rs:340-356`).** `pseudo()` drops every `/proc/`, `/sys/`, `/dev/` key from the global contexts:
start-up, between tests, import of shared modules and conftests. This drops ordinary inputs:
* **`/dev/shm` is a writable tmpfs.** A conftest reads a flag there at import and the test asserts on it. Change the
  flag: reused (serial and `-n`).
* **`/proc/self/root/<path>` is any file.** A conftest opens its configuration through that path, and the file stops
  being an input. Change it: reused. `/proc/self/cwd/...` and `/dev/fd/N` are the same.
* **Pool size from `/proc/self/status`** (`Cpus_allowed_list`, which a cgroup or taskset sets):
  * runs 1-2 on CPUs {0,1}, run 3 on {0} (`sched_setaffinity` of the parent);
  * fresh: `'0' == '0-1'` fails; the cache reuses the pass.
  * This is the "cgroup CPU limits decide a pool size" case.
* **`/dev/urandom` read at import** is dropped too, and it is not `os.urandom`, so no `entropy` flag (N5).
* The `pytest_runtest_setup` variant (copy the flag into `os.environ`) is **not** reused. That attack did not get
  through.
* The justification ("could never match") holds for `/proc/self/fd` listings, not for the namespace in general.
* Fix: an allow-list of process-state paths (`/proc/self/fd`, `/proc/self/stat*`, `/proc/self/task`, ...) instead of
  three prefixes. Resolve `/proc/self/root`, `/proc/self/cwd` and `/dev/fd` to the real path. Keep everything else as
  data.

**N2, rule b (`capture.rs:1120-1128`).**
* `loopback_name` claims these names resolve to loopback "on every host". In this container `ip6-localhost`,
  `ip6-loopback` and `localhost.localdomain` do not resolve at all (MEASURED: `getaddrinfo` → `EAI_NONAME`;
  /etc/hosts has only `127.0.0.1 localhost`).
* With nsswitch `hosts: files dns`, glibc then asks the nameserver of `/etc/resolv.conf`, which is not among the four
  recorded files. The DNS answer is a network input recorded as nothing.
* Test setup: resolv.conf points to a local fake DNS server in both sessions. Only the server's answer changes
  (NXDOMAIN → 127.0.0.1). Fresh: the test fails; cache: reused (serial and `-n`).
* Control: the same change made in /etc/hosts is seen (not reused).
* Not demonstrated, by code reading only (ESTIMATED): `getaddrinfo` ordering under `AI_ADDRCONFIG` and RFC 6724 rules
  depends on the interfaces' addresses, which no file records. This container cannot add interfaces.
* Fix: treat a loopback name as loopback only after checking that it is in /etc/hosts (or `myhostname`). Otherwise
  keep the `dns` flag.

**N3, rule c (`sockcap.rs:109-125, 208-236`).** "The controller runs no test code" is false: every conftest's
`pytest_configure` and `pytest_sessionstart` run in the controller.
* **Controller-served data:** a conftest starts a listener in the controller that serves `value.txt`, and a test in a
  worker reads from it. Change value.txt: reused.
* **Cross-worker relay:** test A (gw0) sends `value.txt` to the controller's store and test B (gw1) reads it. No file
  is written, so the cross-worker write rule never fires. Change value.txt: A runs, B is reused.
* **Address ignored (serial too):** `own_listener` matches by port and "is loopback" only. The session process (or
  the controller) listens on 127.0.0.1:P, while another process serves on 127.0.0.2:P. A test reading 127.0.0.2:P is
  cached as talking to itself. The address-blindness predates this round; extending the owner set to the controller
  widens it.
* Fix:
  * Compare the exact local address.
  * Count a controller listener as infrastructure only when a known plugin opened it, from the plugin's own frame;
    otherwise as a connection.

**N4, rule d (`xdist.py:312-318`).**
* `--tx` is in `_VOLATILE_OPTIONS`, so it is not in the configuration digest.
* `--tx 2*popen//env:R023B_TXMODE=on` starts every worker with the variable. The controller's snapshot at
  `pytest_xdist_setupnodes` does not have it, so an entry recorded with the variable absent matches.
* Fresh: `assert 'on' is None` fails; the cache reuses the pass.
* The control passes: a worker-only `pytest_configure` that sets a variable from a recorded file is seen.
* Fix: add the `env:` items of the tx specs to the snapshot, or take the snapshot from a worker.

**N5, rule e (`--det-urandom`, `seeds.py`).**
* `os.getrandom` and `ssl.RAND_bytes` are neither controlled nor observed. A test that draws from them is cached
  without `--det-urandom`, although the design forbids caching OS entropy. This class predates the round. The report's
  "never for crypto tests" assumes entropy comes through `os.urandom`.
* **First requester:** under `--det-urandom` the stream is re-seeded per test from the node id. A session fixture's
  bytes come from the stream of the first test that requests it.
  * A new test file that sorts first and requests the fixture changes the value an unchanged later test sees
    (MEASURED: 7372326639584184075 → 465912585698556387).
  * The later test is reused as passed; fresh it fails (serial).
  * The same applies to `random` in session fixtures.

## 3. Absent inputs under `-n` (N6)

Every class the sibling review found broken serially is also broken under `-n 2`, the same way. All 18 fail with
"reused after its input changed", and the truth fails the test:

| class | change made between sessions |
|---|---|
| failed optional import | the module appears beside the test |
| new conftest | `tests/sub/conftest.py` with a failing autouse fixture |
| `os.path.exists` | the file is created |
| namespace package | gains `__init__.py` |
| `.pth` | a new `.pth` in site-packages adds a path that has the module |
| zipimport: member appears | the zip gains the module |
| zipimport: member changes | `V = 1` → `V = 2` inside an imported zip: not even an absent input, a changed one |
| ctypes: library changes | the loaded `.so` is rebuilt to return 2 |
| ctypes: library appears | a `.so` that failed to load now exists |

* **Worker split:** `test_3_absent_input_across_worker_shards` puts the absent-input reader on gw1 and the creator on
  gw0. The reader is reused.
* The split does not make these worse, because the controller decides with the merged store. It does not help either:
  the post-run check `hits_with_written_inputs` covers only paths recorded as inputs that exist, so a created path is
  never matched.

## 4. Numbers re-derived from the committed raw files (N11)

The raw files are `tracks/parallel-proof/build/esphome/esphome5/` and
`tracks/parallel-proof/results/r023-p0{,b,c,d}-2026-11-19/` (summary.jsonl, crosscheck, fpcompare, plans, walk.json),
all read by this review.

**Match (MEASURED):**
* the esphome5 local table: every wall, median, spread, ratio and reuse;
* targets 66.5 / 64.5 / 71.9 s;
* plan digests `d9cbe597` / `6c007af5`;
* fpcompare 67/65/35 and 0/0/0;
* every r023-p0 and p0b number, including targets 86.5 / 74.2 / 137.8 / 173.1 s;
* final-table ratios as median(b,c) / median(plain): 1.003 / 1.043 / 0.538 / 1.023 / 1.041;
* warm ratios 0.724, 0.167-0.220, 1.280;
* the walk: 446,878 of 719,448 = 62.1 %, 0 wrong, 50/50 commits, warm 58.4-64.4 s (median 61.95), truth
  148.4-152.1 s, commit 4 `env` 2,460;
* every claimed reuse count (14,149 / 14,158 / 0 then 14,158 / 4,178 / 1,794 then 2,416 / 312);
* engine attribution: `git diff ddaffac 0b9f63b` touches only the workflow, run.json and the report.

**Do not match:**

| REPORT-2 claim | raw file shows |
|---|---|
| In short: "0 mismatches ... pydantic-ai"; "0 new failures caused by the split" | final engine: `r023-p0c/pydantic-ai/det-n-b.crosscheck.json` `ran_mismatches` = 1 and `fpcompare.json` `new_failures_caused_by_split` = 1. True only for the earlier r023-p0 run; the body (L471-476) says so, the summary does not |
| pydantic-ai 1.02x "inside the plain runs' range" | plain 101.1 / 89.3 / 92.4 s; det b 89.1 s is below the fastest plain run, so outside the range. 1.02x needs the median convention: mean/mean 1.00x, with run a 1.08x |
| final engine "both mixed-store directions included" | no `cache-y` run on Actions in any round (p0c, p0d: `cache-x` only); both directions exist only locally (esphome5) |
| litellm warm **0.58x** | median 40.7 / 69.5 = 0.586 → 0.59x; the other rows use median/median |
| "every reused and every ran result of every cache row was compared" | esphome5 has no crosscheck for cache-n-cold, cache-n-warm@2, cache-ser-cold, det-n-a |
| esphome walk: "18 commits that change code ..., 113.8-165.0 s" | 16 code commits at 113.8-116.2 s; commit 18 (6b82e127) is a `data` commit (14,075 misses); commit 0 is the cold start (165.0 s) |
| moto walk 64.5-70.9 s | maximum 71.5 s (commit 19, 4f1c78f9) |
| esphome reuse 97.9 % | 14,149-14,151 of 14,446 = 97.9-98.0 % (cosmetic) |
| "identical ... in all four" | five repositories in that round; all five identical (wording) |

**MEASURED with no committed raw file (should be DECLARED):**
* the litellm local phase table (`phasetimes.py` is not in the repository; 21 → 15.3 s, py-spy 35 %, 2.8 s);
* "After the fixes, litellm-vertex locally" (98.9 s, 39.0-39.5 s, 0.59x, its three crosschecks);
* in the blocker table "MEASURED: the detail lines", litellm's "os entropy 4,180", "whole environment 4,180" and
  "/proc/self/fd 4,180" are in no committed file;
* pydantic-ai's 2,769 failures;
* the gate counts (589/8/1, 94 cargo tests, 17 passed ×3; the 17 is re-measured here).

**Labels:**
* The final table does not say which rows come from `r023-p0c` (esphome, pydantic-ai) and which from `r023-p0d`
  (litellm-vertex, moto, prefect).
* Derived values under MEASURED headings carry no ESTIMATED label: O1's 4.8 s / 7.3 s, "about 75 s" (actual 69.6-79.1
  s), and "twice the plain spread" (15.8 s against a 7.3 s spread).

## 5. Are the PARTIAL items honestly described?

* **P4 (shared cache)**: honest. `claude/shared-cache` has `remote_cache.py` (668 lines, MEASURED), `cache_service.py`
  and `runtime_id.py`; nothing was brought over.
* **P5 beyond placement**: honest that it is not built.
  * The interim guard is weaker than "stands in until then" suggests: parallel sessions reuse parallel entries (N7).
  * The guard is per session mode, not per placement.
* **moto Docker**: honest. The detail lines (`/var/run/docker.sock`, `/proc/self/task/<tid>/children`, xunit socket)
  are in `r023-p0d/moto/summary.jsonl` `not_cached_detail`.
* **mlflow**: honest. The crosschecks have an empty truth, and the report says so.
* **Walks after the fixes**: honest that they were not run.
  * The esphome walk ran on b795295, before the rules N1-N4.
  * So "esphome 446,878 reused, 0 wrong" says nothing about this round's rules.
* **prefect SQLite clock (N12)**: not fully honest.
  * `uncacheable()` (`record.rs:124`) returns the *first* reason, and `rclock` comes before `spawn` and `connect`. The
    logged "real clock 2,418" (`r023-p0d/prefect-g1/summary.jsonl` and `r023-p0b/prefect-g1/logs-tail.txt:294`)
    therefore hides any spawn or connect behind it.
  * REPORT-2's p0b section blames a loopback API-server subprocess ("a test that connects is never cached"), which its
    own p0b log line contradicts. The follow-up section blames SQLite only.
  * "Making it cacheable needs SQLite date/time functions under Level 0" is at best necessary; whether it is
    sufficient is UNKNOWN.

## What would change the verdict

Fix N1-N4 (the round's rules), N6, N7 and N8, then make the failing tests in `tests/test_review_r023b.py` pass.
Re-run the moto/litellm/esphome walks on the fixed engine with `--det-urandom`, and correct the In-short claims of N11.
