FIX 16

# R-025b · Last review of the Go track (P-021, branch `claude/go-l0` at 05a7dfa)

Reviewer session, 2026-11-19 (runs between 22:29 and 23:00 UTC). Target: `claude/go-l0` at 05a7dfa, report `sessions/2026-11-18-go-l0/REPORT-2.md`, which answers R-025 (`sessions/2026-11-19-review-go/REPORT.md`, FIX 17). Branch of this review: `claude/review-r025b` = target + review tests + this file.

Environment: this session's container (4 CPUs, Linux 6.18, Go 1.24.7, go1.22.12 through `GOTOOLCHAIN`, strace, gcc, cargo, taskset, prlimit, unshare, root). Labels: MEASURED / ESTIMATED / DECLARED / UNKNOWN.

## Verdict: FIX 16

- **All 17 R-025 findings are fixed** (MEASURED: every `TestR025` test passes, `review_r025_check.py` exits 0). R1 is mostly done (one new boundary finding, R2).
- **Skip with proof still gives wrong reuses: 9 new ways** (C1-C3, P1, A1, F1b, F2b, F5b; one robustness hang, R1b). Each is a test that fails on 05a7dfa: the key says "reuse with proof" and the fresh run of the same state fails. Four of them come from the new virtual-day clock: the key holds the day, but real time still reaches the test inside the day.
- **Skip mode breaks tests, MEASURED in the walks (S1):** 8 tests fail in fenvix's own fresh run in 15 to 50 of 50 commits under skip-r5 (0 to 1 of 50 under skip-r4) and pass alone under plain `go test`. REPORT-2 does not mention them; the walk classifies them as "flaky".
- **`--det`: 2 findings** (D2b, D3b): two more idioms broken by `--det`, two more uncontrolled entropy sources, and a start message that contradicts the report.
- **Numbers: 2 findings** (N4, N5). The telegraf rows cover 33.2% of telegraf's test time. The coverage gain 56.0% → 70.0% is 62.7% → 70.0% like for like; the rest comes from quic-go losing 139 `--det` results to a `--det` timeout, which the aggregate mislabels as "both arms stopped".
- **Rust boundary (R2)** and **the nightly real-clock run (NC)**: one finding each.
- **Held:** every absent-input attack (14 cases), TZ and `/etc/localtime`, `init()` clock, static helpers, `GOFLAGS`, module graph, abstract unix sockets, two D1 variants.

"0 wrong reuses in every walk" is correct as a count (re-derived). It does not cover the clock findings, for two reasons:
- the walk verifies a reuse against a fresh fenvix run under the same virtual clock, so a test the virtual day makes pass cannot be seen failing;
- the C findings need real time to pass between record and check within one UTC day.

## How to reproduce (on `claude/review-r025b`)

```bash
cargo build -p fenvix-go --release
cd go && go test ./cmd/fenvix-go -run 'TestR025_' -v    # R-025: all pass (D3_Go122 needs go1.22.12 already downloaded, see nits)
go test ./cmd/fenvix-go -run 'TestR025b' -v               # this review: the findings fail, the held attacks pass (~2 min; avoid 23:58-00:01 UTC)
cd .. && python3 harness/go/review_r025b_check.py          # N4, N5, S1, Q3 from the committed data (exit 1)
```

Fixtures:
- `go/testdata/fixtures/review-r025b`: skip key, one package per scenario;
- `review-r025b-det`: `--det`;
- `review-r025b-mod`: module graph.

Tests: `go/cmd/fenvix-go/review_r025b_test.go`, `review_r025b_det_test.go`. The method is R-025's: `--skip-verify` runs every test, and the decision report says whether the key would have reused it.

## 1. Gates of REPORT-2, re-run (MEASURED, this container)

| gate | REPORT-2 | this review |
|---|---|---|
| `go clean -cache && go test ./cmd/fenvix-go -run TestR025 -v` | 36 PASS | 35 PASS and `TestR025_D3_Go122` SKIP on a cold toolchain; PASS once go1.22.12 is downloaded (nit 1) |
| `python3 harness/go/review_r025_check.py` | exit 0 | exit 0 |
| `cargo test -p detpy-core -p fenvix-go` | 44 + 15 | 44 + 15 passed |
| `go test -count=1 ./...` (review-b tests excluded) | all ok | all ok (cmd/fenvix-go 90.5 s) |
| skip tables skip-r4/r5/r6 (`aggregate.py skip`) | section 4 | every cell reproduced (terraform "other" 2.4 = code-or-config 0.1 + other 2.3) |
| flaky-r8 (`aggregate.py flaky`) | 70.0%, 704 of 1,006; +5.5% over 20 | reproduced; the comparison and one label are wrong (N5) |
| skip-r4 clock table (47.4 / 51.0 / 23.3 / 14.0) | MEASURED | reproduced |
| `timestamppb` 13,293 s; `/proc/1/stat` 4,667 s | MEASURED | not reproduced exactly (nit 3) |

## 2. Findings

### 2.1 Skip with proof: wrong reuses and a hang (MEASURED, Go 1.24.7, strace capture)

| # | test (`review_r025b_test.go`) | change between record and check | wrongly reused (fresh outcome) | why the key misses it |
|---|---|---|---|---|
| C1 | `TestR025b_C1_FileAgeIsRealTime` | none: 4 s pass, same UTC day. The test checks `time.Since(stat(testdata/stamp).ModTime()) < 3s` (a TTL, lock or freshness check) | `TestStampIsFresh` (failed) | D2's mtime shift adds (virtual − real) **at test start**, so the age the test sees is real elapsed time. The key holds the mtime and the day, and neither moves. |
| C2 | `TestR025b_C2_RealClockBesideVirtual` / `TestGoHelperClock` | none: the tolerance is exceeded 2 s after record, same day | `TestGoHelperClock` (failed) | A Go helper built with cgo is dynamically linked, so `dynamically_linked()` keys it as a reusable child. But the Go runtime reads the clock through the vDSO, not libc: `LD_PRELOAD` does not reach it, and its clock is real (MEASURED: `child go (dyn) 1795127385…` = 22:29:45 while the test's clock read 00:00:00). Any Go tool built with cgo (or with `-linkmode=external`) behaves like this. |
| C3 | same test / `TestCgoClock`, `TestRawSyscallClock` | same | both (failed) | `clock_gettime` called from C (cgo), and a raw `SYS_clock_gettime`, read the real clock inside the test process. Skip mode no longer treats any clock read as an input (only the day), so these reads reach the outcome with nothing in the key. Plain `go test` passes all three with a tolerance of seconds. Under fenvix they pass only up to that tolerance after 00:00 UTC (broken the rest of the day), and are reused all day. |
| P1 | `TestR025b_P_ProcessAttributes` (3 cases) | started through `taskset -c 0`; `umask 002`; `prlimit --nofile=1024:1024` | `TestTwoCPUs`, `TestCreatedMode`, `TestOpenFilesLimit` (all failed) | Process attributes the binary inherits are in no key: CPU affinity (`runtime.NumCPU`, the default GOMAXPROCS), umask and rlimits. Neither is uid. `/proc/self/limits`, `/status`, `/cgroup` and `/mountinfo` carry them, and `classify` drops all of `/proc/self` as process-private. This covers a restored or shared cache on another runner type, and any CI change of container settings. |
| A1 | `TestR025b_A1_CgoGetenv` | `R25B_CMODE=1` set; the variable is read by C `getenv` | `TestDefaultMode` (failed) | F7 keyed only the `LD_`, `GLIBC_` and `MALLOC_` families. Any C library reads its own variables below the `os.Getenv` hook (`OPENSSL_CONF`, `PGHOST`, `KRB5_CONFIG`…). `e:*` (the whole environment) is keyed only when the test starts a program. |
| F1b | `TestR025b_F1b_WriteByAnotherPackage` | package `a` rewrites `../shared/state.txt` v1→v2 while package `b`'s test runs (skip mode keeps `go test`'s parallel packages); the next commit has v2 | `TestReadsShared` (failed) | F1's fix applies to inputs a previous entry recorded. An input first seen takes its value after the run when **its own** strace log saw no change. Another process (a sibling package, a daemon, a container) can change it in between: b's entry holds v2, a content b never read. |
| F2b | `TestR025b_F2b_FileOwner` | `chown nobody testdata/conf` | `TestConfigOwnedByMe` (failed) | The metadata value is type, mode, size and mtime; uid and gid are not in it. |
| F5b | `TestR025b_F5b_NetlinkInterfaces` | the check runs in a new network namespace (`unshare -n`): a runner without that interface | `TestHasNonLoopbackInterface` (failed) | `net.Interfaces` and `net.InterfaceAddrs` query the kernel over netlink. `sockaddr()` parses inet and unix addresses only, so an `AF_NETLINK` `sendto` is dropped silently, and the machine's network configuration is no input. |
| R1b | `TestR025b_R1b_FifoInputHangs` (robustness) | none: the record run itself | — | The test polls a named pipe with `O_NONBLOCK` and passes at once. `content_value` then does `std::fs::read` on the FIFO (after the run for a first-seen input, before the binary for a recorded one), which blocks with no writer: fenvix-go never finishes (killed after 60 s). The same applies to any FIFO or character device an input path names outside `/dev`. |

Fix directions:
- **C1:** shift only mtimes at or after the test's real start (files the run wrote, which are outputs, not inputs). Leave pre-existing inputs unshifted: their age against the fixed virtual day is then a function of keyed values.
- **C2:** a Go program is "static" for the clock whatever its linking: detect `.go.buildinfo` and keep `exec:`.
- **C3:**
  - preload the shim into the test binary itself when it is dynamically linked (cgo);
  - add `clock_gettime`, `gettimeofday` and `time` to the strace set: a raw call is visible there, and should become unkeyed `clock:`;
  - say at start in skip mode what the virtual day does not reach (today only `--det` prints its limits, and that message is stale: D2b).
- **P1:**
  - put the affinity mask, umask, rlimits, uid/gid and capabilities in `static_parts` (the shell can read them before the start);
  - key `/proc/self/{limits,cgroup,mountinfo}` by content instead of dropping them.
- **A1:** when the test binary is dynamically linked or cgo is on, key `e:*`.
- **F1b:** either run `-p 1` in skip mode, or give a first-seen input `?` (rerun next time) instead of a post-run value.
- **F2b:** add uid and gid to `meta_value`.
- **F5b:** treat netlink requests as an input, either keyed by the interface list or address table (computed by the core before the start) or as `unkeyed:netlink`.
- **R1b:** value non-regular files by type and metadata only, never by reading them.

### 2.2 Skip mode breaks tests: MEASURED from the walks (S1)

`harness/go/review_r025b_check.py` (S1) lists the tests that fail in fenvix's fresh run in at least 10 commits of skip-r5 and at most 2 commits of skip-r4. skip-r4 and skip-r5 are the same commits and the same runner type; skip-r5 adds the virtual day, the child clock and the `/proc` changes.

| repository | test | fenvix fresh failures, skip-r4 → skip-r5 (skip-r6) | plain `go test` alone |
|---|---|---|---|
| telegraf | stackdriver `TestCounterCacheDayRollover` | 1/50 → 50/50 (50/50) | 3/3 pass, at 42 commits (walk's go-rule checks) |
| telegraf | stackdriver `TestUpdateCounterCacheEntry` | 1/50 → 50/50 (50/50) | 3/3 pass, at 42 commits |
| telegraf | postfix `TestGather` | 0/50 → 50/50 (50/50) | 3/3 pass, at 47 commits |
| telegraf | phpfpm `TestPhpFpmTimeout_From_Fcgi` | 0/50 → 50/50 (50/50) | 3/3 pass, at 43 commits |
| terraform | e2etest `TestMetaBackend_GetStateStoreProviderFactory` | 0/50 → 49/49 | 3/3 pass, at 31 commits |
| prometheus | tsdb `TestTombstoneCleanFail` | 0/50 → 44/50 | 3/3 pass (fenvix "flaky" ×4) |
| prometheus | tsdb `TestDBReadOnly_AppendV2` | 0/50 → 34/50 | 3/3 pass (fenvix "flaky" ×7) |
| prometheus | scrape `TestScrapeLoopCache` | 0/50 → 15/50 | 3/3 pass (fenvix "flaky" ×7, go ×9) |

- A CI that adopts skip mode gets these failures: the fenvix run is the CI run. `TestCounterCacheDayRollover` is a date test.
- The cause per test is UNKNOWN. Plausible causes:
  - every test's clock restarts at 00:00 UTC, so process-level state from an earlier test lies in the future;
  - D2b-like mixes of real and virtual time.
- REPORT-2 reports "broken by `--det`" for the flaky rounds but has no "broken by skip mode" count. The 18 prometheus "flaky" reuses in its table are these tests: they fail under fenvix in 15 to 44 of 50 commits. The verdict "flaky" comes from plain reruns that do not run under the virtual clock, the same blind spot as R-022.
- The go-rule "flaky" count rose from 8 (skip-r4) to 226 (skip-r5) for the same reason. REPORT-2 does not mention it.

Fix: count broken-by-skip-mode (fails under fenvix, passes plain) in the walk and in the report. Find the cause of each of the 8; the per-test clock restart is the first suspect.

### 2.3 `--det` (MEASURED, 10 plain and 10 `--det` seed-0 runs, `review_r025b_det_test.go`)

| test | plain (10) | `--det` seed 0 (10) | finding |
|---|---|---|---|
| `TestTimerChannelThenSleep` (NewTimer 1 ms, Sleep 50 ms, read the channel) | 10 pass | 10 pass | D1 variant held |
| `TestInitWorkerThenSleep` (worker goroutine started by `init`, Sleep 50 ms) | 10 pass | 10 pass | D1 variant held |
| `TestSyscallStatMtime` (`syscall.Stat` of a file just written, age < 1 min) | 10 pass | 10 fail | **D2b** |
| `TestChildStatVersusChildDate` (one shell: `date +%s` − `stat -c %Y`) | 10 pass | 10 fail | **D2b** |
| `TestMaphashSeed`, `TestSyncMapRange` | vary | one outcome | held |
| `TestPid` (`os.Getpid()` even) | vary | 7 pass / 3 fail, 2 fingerprints | **D3b** |
| `TestDevUrandom` (one byte of `/dev/urandom`) | vary | 4 pass / 6 fail, 2 fingerprints | **D3b** |

- **D2b. The D2 shift is partial.**
  - `syscall.Stat`/`Fstat`/`Lstat` and `x/sys/unix` are not shifted. In a child, the shim shifts `clock_gettime` but not `stat`, so a shell sees `date` in 2025 and a file it just touched in 2026.
  - The `--det` start message (`test.go:389`) says "file timestamps (real time; seed 0 starts each test's virtual clock at the real time so they stay comparable)". Both halves contradict REPORT-2 D2: the epoch is fixed and `os` mtimes are shifted.
  - Fix: shift the `syscall` stat family too, and have the shim interpose `stat`/`fstat`/`statx` (or say so at start); correct the message.
- **D3b. Single-goroutine entropy left:** the pid (`xid`, `ObjectID` and temp names use it) and direct reads of `/dev/urandom`.
  - Each outcome has the fingerprint of an event-free test, so the verifier cannot name the source. Neither source is said at start.
  - Fix: route `/dev/urandom` and `/dev/random` opens to the crypto stream and make `os.Getpid` seed-derived under `--det`, or list both at start.

### 2.4 Numbers (MEASURED, `harness/go/review_r025b_check.py`)

- **N4. The telegraf rows cover 33.2% of telegraf's test time.**
  - In skip-r4 (all 6 shards), shard 5 alone is 66.8% of telegraf's test time, and Go's cache reuses 48% of it against 74-85% on the other shards.
  - On shards 0-4, skip-r4 already gives fenvix 10% / 9% and Go 96% / 83%. The skip-r5/r6 rows (10% / 10% vs 96-97% / 83%) therefore show no change from the virtual clock, measured on a third of the suite.
  - The table says "5 of 6 shards". The Status bullet ("telegraf: 10% / 10% vs 97% / 83%") does not say it is partial, and does not say it is skip-r6 while the other two rows are skip-r5.
  - Fix: label it in the Status section (33.2% of test time, skip-r6), or wait for shard 5.
- **N5. Fingerprint coverage 56.0% → 70.0% is 62.7% → 70.0% like for like.**
  - On the 1,006 tests with a `--det` result in both flaky-final and flaky-r8, coverage went from 62.7% to 70.0%.
  - The 56.0% denominator (1,145) holds 139 quic-go tests that have no `--det` result in flaky-r8. quic-go's `--det` arm went from 7.0 s (flaky-final) to 600.7 / 600.9 / 601.5 s: the 10-minute timeout.
  - Its plain arm took 7.7 s. `aggregate.py`'s `slowdown_invalid` (`aggregate.py:27`) tests `plain ≥ timeout or det ≥ timeout` and prints "both arms stopped by the go test timeout". REPORT-2 repeats this ("quic-go (both arms stopped by the timeout)"), and it is false.
  - By REPORT-2's own N2 rule ("a timeout under `--det` is itself a break"), quic-go is broken by `--det` in flaky-r8: 138 tests pass 10/10 plain and have no `--det` result. The cause is very likely the new `sched` control (GOMAXPROCS=1, preemption off): ESTIMATED, as no run isolates it.
  - "Broken by `--det`: 1" should say 1 test plus quic-go's suite timeout. The +5.5% median leaves out a 7,729% (truncated) comparison under a false label.
  - Fix: correct the label in `aggregate.py`; report coverage like for like; count the quic-go timeout as a break and find its cause.

Re-derived and correct: every skip-r4/r5/r6 cell, the wrong and flaky counts, 0 wrong in every walk, flaky-r8 704/1,006 = 70.0% and its +5.5% over 20 (given its exclusions), N1-N3 (`review_r025_check.py`), and the skip-r4 clock-rule points. Pending items are labelled pending: telegraf shard 5 (r5 and r6), nats-server and teleport (flaky-r8, `harness/go/RUN`).

### 2.5 Rust boundary (claim 6)

- **R2. Two rules of the skip decision are still in the Go shell:**
  1. The virtual-day epoch: `test.go:335-343` computes today 00:00 UTC and passes it into `static_parts`. The core does not know that the day must be in the key.
  2. The real-clock classification: `summarizeSkip`, `test.go:660`, decides which tests "pass on the virtual day and fail on the real clock", and counts disagreeing reuses.
- REPORT-2 itself says the day rule "must be applied" again in Python and Node: duplication by design.
- Everything else in Go is interface: running the binary, `ownAddresses`, `binaryContentID` and the overlay; the shim is overlay C.
- Fix: `fenvix_skip_open` takes the mode (virtual day or real clock) and computes the epoch. The core reports the real-clock list.

### 2.6 The nightly real-clock run (claim 2, F6 trade-off)

- **NC. The run DECISIONS 2026-11-19 relies on does not exist yet, and it bounds less than the report says.**
  - What exists:
    - the `--skip-real-clock` flag;
    - a fixture test (`TestSkipRealClockReportsExpiry`, MEASURED pass);
    - a recipe in `docs/GO.md`.
  - What does not exist:
    - no scheduled job anywhere, including on the walk repositories (DECLARED in REPORT-2);
    - no run on a real project, so its output and exit code there are UNKNOWN.
  - What it does not bound:
    - It does not see C2/C3. On the real clock those tests pass, while the virtual-day reuse is wrong.
    - It sees C1 only when it runs after the TTL ran out, and names it as an "expired fixture".
    - Every fenvix run sees 00:00 UTC, and the nightly samples one time of day (03:17 in the recipe). Time-of-day failures that plain `go test` would hit at other hours are never observed by either.
  - Fix:
    - schedule the check on at least one walk repository and report one real run;
    - state in the docs what it cannot bound (C2/C3 and the time of day), or fix C1-C3 so that it only has to bound F6.

## 3. Claims, one by one

| claim | verdict |
|---|---|
| 1. All 17 R-025 findings fixed | **holds** (MEASURED: 36 R-025 tests pass, check exits 0). New variants: F1 → F1b, F2 → F2b, F3 → P1 (`/proc/self` dropped), F5 → F5b, F6 → C1-C3, F7 → A1 found; F4 → F4b (abstract unix socket), F8 (`GOFLAGS=-timeout`), F9 held; D1 variants held, D2 → D2b, D3 → D3b found; D4 holds (nit 1) |
| 2. Virtual-day clock in skip mode | **does not hold as sound**: C1, C2, C3 wrong reuses within the day; S1 breaks 8 real tests. Held: `init()` clock (virtual: `00:00:00.000001`), TZ and `/etc/localtime` (keyed), static Go helper (`exec:`), monotonic clock (virtual, `time.Since` = 1 µs). F6 trade-off: as stated, but the nightly run does not exist and bounds less (NC) |
| 3. `/proc/1/stat` "cannot be keyed soundly" | see section 4: true of keying the bytes, not a reason to leave it volatile |
| 4. Absent inputs | **holds**. All 14 cases are refused (`TestR025b_A2`/`A3`/`A4`): `os.Stat` of a missing file, glob gaining a match, missing directory created, `os.Root` and `os.DirFS` stats, a tool appearing on PATH (`LookPath`), a child's `test -e`, `LookupEnv`, a file in the package directory, a user config file, a go:embed pattern gaining a file, a new `_test.go`, a `//go:build` file, `GOFLAGS=-timeout=1s`, a replace directive, a new `go.work`. Many are caught by the listing of `testdata` (sound, coarse). The absent-input hole is the cgo `getenv` (A1) |
| 5. MEASURED numbers | reproduced, except N4 (label) and N5 (comparison and label); nits 3-4 |
| 6. Non-interface logic in Rust or the overlay | **mostly**; R2 |

## 4. `/proc/<pid>` and `/proc/1/stat` (claim 3)

- **"Keying it would be unsound": true, but only of keying the bytes.**
  - Keying the whole file is sound but never matches.
  - Keying a subset of fields is unsound, because nothing tells which fields the reader uses.
- **Virtualising the file is sound, for the same reason the clock is.** Under `--det` and skip mode, the overlay serves `/proc/1/stat`, `/proc/self/stat` and similar files to Go code:
  - fields that are fixed for the machine's uptime (pid, comm, ppid, pgrp, session, flags, starttime) keep their real values and are keyed by them;
  - fields that change by themselves (state, CPU times, faults, vsize, rss) are replaced by constants.
- Why that is sound:
  - What the code can observe is then a function of keyed values, whichever fields it uses. So the reader does not need to be identified, contrary to REPORT-2 section 4.
  - Reads that bypass the overlay (cgo, a child, a raw `open`) still show up in strace and stay volatile, so this stays sound.
  - Serving: an in-memory fd (`memfd_create` with the synthetic content) keeps `*os.File` semantics.
- Trade-off: a test that measures pid 1's or its own CPU or memory sees constants. The cost has the same nature as the virtual clock's: deterministic but not real.
- The same mechanism, or plain content keying, should cover `/proc/self/{limits,cgroup,mountinfo,status}`, which are dropped today (P1).
- **What it would give (ESTIMATED, upper bound, `review_r025b_check.py` Q3):**
  - telegraf skip-r6 would go from 10% / 10% to at most 86% / 73% (median / mean share of test time), against Go's 97% / 83%, on the 5 measured shards (33.2% of the suite, N4).
  - Upper bound, because the walk records only the first reason per test. r5→r6 already showed a chain: `environ`, then `stat`. Further volatile reads behind `/proc/1/stat` are UNKNOWN.
  - 312 telegraf packages hit it (4,344 s of test time as the first reason in skip-r6). The reader is UNKNOWN.
  - prometheus and terraform: no gain (their `/proc` first reasons are under 0.1 point).
- **`/proc/<pid>` metadata "start time as mtime": not what procfs gives.**
  - Its inode times are set when the inode is instantiated, at first lookup, not at process start. MEASURED here: `/proc/1` mtime is 1,795,043,326 while boot by `/proc/uptime` is 1,795,127,096; `/proc/$$` mtime is the time of the `stat`.
  - Eviction can therefore change the value. That is the safe direction (rerun), so it is nit 2, not a finding.

## 5. Nits (not counted)

1. **`TestR025_D3_Go122` skips instead of failing or passing on a cold toolchain.** The skip condition matches "downloading go1.22.12" with a non-zero exit, and that exit is the deterministic `TestReflectMapOrder` failure. On a fresh machine the gate asserts nothing. It passes once the toolchain is cached (MEASURED), and CI covers the build separately.
2. `/proc/<pid>` mtime semantics (section 4).
3. Two numbers in REPORT-2 do not reproduce exactly from the committed data:
   - "`timestamppb.New(time.Now())` 13,293 s": the data gives 13,812 s as first reason (`why`) and 14,084 s (`why_own`);
   - "`/proc/1/stat`: 4,667 s": the data gives 4,344 s (`why`) and 4,686 s (`why_own`).
   Either state the filter or use the reproducible figure.
4. The REPORT-2 gap table drops the `code-or-config` column and folds it into "other" without saying so.

## 6. Tests added by this review

| test | result on 05a7dfa | finding |
|---|---|---|
| `TestR025b_C1_FileAgeIsRealTime` | FAIL | C1 |
| `TestR025b_C2_RealClockBesideVirtual` | FAIL (3 tests) | C2, C3 (`TestInitClock` held) |
| `TestR025b_C6_StaticHelperNotReused` | PASS | held |
| `TestR025b_C7_TimeZone` (TZ, `/etc/localtime`) | PASS | held |
| `TestR025b_P_ProcessAttributes` (affinity, umask, nofile) | FAIL ×3 | P1 |
| `TestR025b_A1_CgoGetenv` | FAIL | A1 |
| `TestR025b_A2_AbsentInputs` (10 cases) | PASS | held |
| `TestR025b_A3_BuildInputs` (4 cases) | PASS | held |
| `TestR025b_A4_ModuleGraph` (2 cases) | PASS | held |
| `TestR025b_F1b_WriteByAnotherPackage` | FAIL | F1b |
| `TestR025b_F2b_FileOwner` | FAIL | F2b |
| `TestR025b_F4b_AbstractUnixService` | PASS | held |
| `TestR025b_F5b_NetlinkInterfaces` | FAIL | F5b |
| `TestR025b_R1b_FifoInputHangs` | FAIL (60 s bound) | R1b |
| `TestR025b_D1_BrokenByDet` | 2 PASS, 2 FAIL | D2b |
| `TestR025b_D3_UncontrolledEntropy` | 2 PASS, 2 FAIL | D3b |
| `harness/go/review_r025b_check.py` | exit 1 | N4, N5, S1 (+ Q3 estimate) |

The 16 findings: C1, C2, C3, P1, A1, F1b, F2b, F5b, R1b, S1, D2b, D3b, N4, N5, R2, NC.
