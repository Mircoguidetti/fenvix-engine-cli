STATUS-LINE

# P-021 Go track, report 3: fixes for review R-025b (FIX 19)

Session 2026-11-19/20, branch `claude/go-l0`. Review: `sessions/2026-11-19-review-go/REPORT-2.md` (branch `claude/review-r025b`, merged; its tests `review_r025b_test.go`, `review_r025b_det_test.go` and `harness/go/review_r025b_check.py` taken unchanged, except the check script, section 9). Previous reports: `sessions/2026-11-18-go-l0/REPORT-2.md` (this branch, at 05a7dfa) and fenvix-brain-cli `sessions/2026-11-18-go-l0/REPORT.md`.

Labels: MEASURED (with where, or the Actions run id), ESTIMATED, DECLARED, UNKNOWN. No human-team time estimates.

## Status

PENDING-STATUS

## 1. Gates (MEASURED, this container, from a clean Go build cache)

Container: 4 CPUs, Linux 6.18, Go 1.24.7 (go1.26.10 through GOTOOLCHAIN for the walk repositories), strace, gcc. Every gate after `go clean -cache` (Go's cache does not track `libfenvix_go.a`, REPORT-2 section 1).

| gate | result |
|---|---|
| `cd go && go test ./cmd/fenvix-go -run 'TestR025b' -v` | PENDING-GATE-R025B |
| `cd go && go test ./cmd/fenvix-go -run 'TestR025' -v` (R-025 and R-025b) | PENDING-GATE-R025 |
| `python3 harness/go/review_r025b_check.py` | PENDING-GATE-CHECKB |
| `python3 harness/go/review_r025_check.py` | exit 0 |
| `cargo test -p fenvix-go` | PENDING-GATE-CARGO |
| `cd go && go test -count=1 ./...` | all packages ok |

## 2. Fixes, finding by finding

Commits: 65be8b5 (the bulk), 733127b (nightly workflow, walk and aggregate changes), 1604ed6 (clocks meeting, S1c below), 7430e76 (strace parser, F4c below). Each review test is the reviewer's, unchanged; "passes" means MEASURED in the gate run of section 1.

| finding | what was wrong | fix | where (Rust core unless said) | test |
|---|---|---|---|---|
| X1 | a test that panics was recorded passed and reused | the end-of-test hook records `passed` only when the test function returned; a panic unwinding through `tRunner` is `failed`; `log.Fatal` and a panic in another goroutine stay `interrupted` | overlay `testing.go.txt` (hook in the test binary; the outcome rule is the binary's own report) | `TestR025b_X1_PanicRecordedAsPassed` (3 cases) |
| C1 | file age was real elapsed time inside the day | timestamps are moved onto the virtual clock only for files the run changed (ctime at or after the test binary's real start, 20 ms margin); a file older than the run keeps its real mtime, which is keyed (`m:`) | overlay `syscall.go.txt` (syscall stat family), preloaded library `faketime.c.txt` (libc stat family) | `TestR025b_C1_FileAgeIsRealTime` (section 4 says why it passes) |
| C2 | a Go helper built with cgo was keyed as a reusable child; its clock is real (vDSO) | a Go program (`.go.buildinfo` present) is never a reusable child, whatever its linking: `exec:` (unkeyed) | `skip.rs` `is_go_binary` | `TestR025b_C2_RealClockBesideVirtual` / `TestGoHelperClock` |
| C3 | cgo and raw clock reads reached the outcome | the preloaded library is loaded into the test binary itself when it is dynamically linked, and marks every libc clock read (`/__fenvix_marker__/C/0`); `clock_gettime`, `gettimeofday` and `time` are in the strace set; either makes the test unkeyed (`clock:`) | `strace.rs`, `skip.rs`; shell sets `LD_PRELOAD` | same test, `TestCgoClock`, `TestRawSyscallClock` |
| P1 / V2 | affinity, umask, rlimits, nice, ids, capabilities in no key | read by the core before the binary starts and put into the static key | `skip.rs` `process_attributes` | `TestR025b_P_ProcessAttributes` (3), `TestR025b_V2_SelfStatNice` |
| A1 | C `getenv` reads below the `os.Getenv` hook | the preloaded library marks each C `getenv`/`secure_getenv` (`/__fenvix_marker__/E/<name>`): the variable is keyed by name; glibc's internal reads (resolver, locale, iconv) keyed from a fixed list for dynamically linked binaries | `faketime.c.txt`, `skip.rs` | `TestR025b_A1_CgoGetenv` |
| F1b | a first-seen input took its post-run value although another process could change it during the run | a first-seen input takes its value now only when its ctime (and its ancestors') is older than the run's start and strace saw no change; otherwise `?` (runs again next time) | `skip.rs` `untouched_since_start` | `TestR025b_F1b_WriteByAnotherPackage` |
| F2b | uid and gid not in the metadata value | added | `skip.rs` `meta_value` | `TestR025b_F2b_FileOwner` |
| F5b | netlink queries dropped | an `AF_NETLINK` request is an input `n:netlink`, valued by the interface and address table the core reads before the start | `strace.rs`, `skip.rs` | `TestR025b_F5b_NetlinkInterfaces` |
| V3 | `/proc/self/{cwd,root}` aliases read real content with no key | aliases resolved to their target (strace `-y` path of the returned fd, not under `/proc`) | `strace.rs` `unalias` | `TestR025b_V3_ProcSelfAliases` |
| R1b | a FIFO input hung fenvix | non-regular files are valued by type and metadata, never read | `skip.rs` | `TestR025b_R1b_FifoInputHangs` |
| V1 | constants in the virtual `/proc/1/stat` broke readers of the changing fields | plausible constants (state S, minflt 1000, majflt 10, utime 100, stime 50 ticks, 1 thread, vsize 16 MiB, rss 1024 pages); the fixed fields stay real and keyed; the start message says the copy is served | `skip.rs` `virtual_proc_stat` | `TestR025b_V1_VirtualStatBreaksReaders` |
| S1 | 8 tests failed in every fenvix run of skip-r5 (tick clock: ULIDs and ids within one millisecond, ordering by `time.Now`) | skip mode's clock is the real clock moved to the keyed day (section 3), continuous; no tick | overlay `time.go.txt`, `syscall.go.txt` | section 5 (walk) |
| D2b | the syscall stat family and the children's `stat` were not shifted | same rule as C1 in the syscall stat family and the preloaded library; `Chtimes` inverse shift unconditional | overlay, `faketime.c.txt` | `review_r025b_det_test.go` `TestSyscallStatMtime`, `TestChildStatVersusChildDate` |
| D3b | pid and `/dev/urandom` uncontrolled under `--det` | the test binary runs in its own PID namespace (`unshare --pid --fork --mount-proc`, root only; said at start otherwise); `/dev/urandom` and `/dev/random` opens are served from the test's deterministic stream (1 MiB per open) | shell, overlay `os.go.txt` | `TestPid`, `TestDevUrandom` |
| start message | `--det` message contradicted D2 | rewritten from what the overlay does; skip mode now prints what the virtual day does not reach | `test.go` | read in every gate run |
| R2 | day epoch and the real-clock summary in Go | `fenvix_skip_day_epoch` and `fenvix_skip_summary` in the core; Go passes them through | `skip.rs`, `lib.rs` | `TestSkipRealClockReportsExpiry` |
| NC | no nightly run existed | `.github/workflows/go-nightly-real-clock.yml`, scheduled 03:17 UTC; two real runs (section 7) | workflow | runs 44639691571, 44661508881 |
| N4, N5 | numbers | section 8 | `aggregate.py` (N5 label) | `review_r025b_check.py` |

### Two defects found in this round (not in the review)

- **F4c. strace lines with a padded return value were dropped (wrong reuse).** strace aligns the return value of resumed and short calls to a column: `12185 <... connect resumed>)            = 0`. The parser looked for `) = ` and skipped those lines, so their inputs were missing from the key. MEASURED here: `TestR025b_F4b_AbstractUnixService` (a reviewer test that passed the review's own runs) gave a wrong reuse in 1 of 40 runs; the cache entry of the bad run had no `unix:@r25b-service`. Fixed in 7430e76 (`strace.rs` `return_at`, unit test with the real lines): 0 of 60 runs, and 0 missing dependencies in 150 runs of the scenario. **Every walk before skip-r9 used the old parser**, REPORT-2's included: their "0 wrong" stands as measured, but they could have missed inputs, and their reuse shares may be slightly high. This is why skip-r9 re-walks everything.
- **S1c. The two clocks met (a test broken by skip mode, found in skip-r8).** terraform `internal/command/e2etest` `TestMetaBackend_GetStateStoreProviderFactory` failed in 26 of 26 fenvix runs and passed under plain `go test` (skip-r8, run 44639691509, MEASURED; reproduced here). The test builds and starts a Go provider; the provider signs a TLS certificate with the real clock (01:57 UTC), the test checks it on the virtual day (00:00 UTC): "certificate has expired or is not yet valid". Any test that exchanges a time with a Go or static program it starts can meet this. Fix (1604ed6): when a test fails on the virtual day and it, or the package set-up, started a program the clock does not reach (the core's rule, `real_clock_rerun`), the shell holds the binary's output, runs the package again on the real clock (the tests reused with proof stay reused) and reports that run. The decision records both outcomes (`fresh` real-clock, `virtual_clock` virtual-day); the cache entry keeps the virtual-day outcome its keys describe; the test is never reused (`exec:` is unkeyed). A genuine failure stays a failure. `TestSkipClockMeetsChild` (fixture `review-r025b/clockmeet`, added next to the reviewer's) checks all three. Cost: the package runs twice when such a test fails.

## 3. The clock in skip mode: exactly what reaches a test (coordinator question 1)

Skip mode's clock is the real clock plus a constant per test binary: `virtual = day + (real − start)`, where `day` is today 00:00 UTC (computed by the core, in the key) and `start` the binary's real start. It is continuous and strictly increasing; sleeps, timers and timeouts are real. So yes: **real elapsed time since the binary started reaches a test**, through every read of the wall clock and through every duration. Read by read:

| clock read | what the test sees | input? | effect on reuse |
|---|---|---|---|
| `time.Now()` in Go code (test binary, its `init`, dependencies) | day + elapsed since the binary started | the day is keyed; the elapsed part is not | reusable |
| monotonic: `time.Since`, `time.Until`, `Sub`, timers, `Sleep`, contexts' deadlines | real durations | no | reusable; a test whose outcome depends on durations is as flaky as under plain `go test`, and the walk counts it as flaky |
| C code through libc (`clock_gettime`, `gettimeofday`, `time`) in a dynamically linked test binary (cgo) | the same virtual value (the preloaded library adds the offset) | the read is marked (`/__fenvix_marker__/C/0`) | **refused**: `clock:` |
| raw system call `clock_gettime`/`gettimeofday`/`time` (assembly, `syscall.Syscall`) | real time | traced by strace | **refused**: `clock:` |
| vDSO called directly by C code (not through libc's symbol) | real time | not seen | **not covered** (UNKNOWN how common; no case found in the five repositories) |
| a dynamically linked non-Go program the test starts (`date`, `git`, shell) | virtual (preloaded library) | its clock reads are marked like the test binary's | **refused** when it reads the clock (`clock:`); keyed by content (`c:`) when it does not |
| a Go or statically linked program the test starts | real time | no | **refused**: `exec:`; and if the test fails, the package runs again on the real clock (S1c) |
| file age (`ModTime`) of a file the run changed | virtual mtime (moved by the offset) | the file is an output | consistent with `time.Now`: age = real elapsed since the write |
| file age of a file the run did not change | real mtime (keyed, `m:`) against the virtual now | mtime keyed | reusable: age = day + elapsed − mtime |

Three consequences, stated plainly:

- **A file written today before the run is "in the future" on the virtual day.** Its age is negative. A TTL check (C1: "age < 3 s") passes all day under fenvix, fresh and reused alike, while plain `go test` fails it once the TTL has run out. The reuse is consistent with fenvix's own fresh run (that is what C1 tests), but the expiry is seen only by the nightly real-clock run.
- **A reused test can depend on elapsed time inside its binary.** Example: a test that passes only in the first N seconds of the binary's life. Its fresh runs under fenvix also depend on that time, so a reuse is as right as a fresh run of the same state; it is the plain-`go test` flakiness of that test, not a wrong reuse caused by the key. The walks would count it as flaky.
- **No real time of day reaches a reused test**, except through the reads in the "refused" rows above, which are never reused.

### C1-C3 pass for these reasons (MEASURED, this container, gate run)

| test | run 1 (record) | run 2 (after the tolerance, nothing changed) | why |
|---|---|---|---|
| C1 `TestStampIsFresh` | passed, `new` | reused, fresh `passed` | the stamp was set before the run, so its mtime is real; the test's now is 00:00 UTC + seconds: age negative < 3 s, in the fresh run and the reused one |
| C2 `TestGoHelperClock` | passed | not reused, `exec:…/clockprint` | a Go program, never a reusable child |
| C3 `TestCgoClock` | passed | not reused, `clock:read outside package time (C, a program, a raw system call)` | the preloaded library marked the libc read |
| C3 `TestRawSyscallClock` | passed | not reused, `clock:…` | strace saw the raw `clock_gettime` |
| C5 `TestInitClock` (held) | passed | not reused, `clock:…` | not its own read: it runs after the tests above in the same binary, and the prefix rule takes their inputs (its own entry has no unkeyed input: `reuse_own: true`). Run alone it is reused, fresh passed. MEASURED |

## 4. Reuse after the fixes, against 05a7dfa (coordinator question 1, MEASURED)

PENDING-REUSE

## 5. Skip mode breaking tests (S1), in the walks

PENDING-S1

## 6. `--det`

- D2b and D3b: section 2 (the reviewer's `review_r025b_det_test.go` passes, section 1).
- **quic-go (N5): the `--det` timeout is a break caused by the `sched` control, not fixed.** MEASURED here: `TestReadDeadlineAsync` hangs under `--det` (killed at 600 s) and passes in 0.93 s with `--det-disable=sched`. Cause, ESTIMATED: with GOMAXPROCS=1 and no asynchronous preemption, a goroutine spinning on a deadline that only the 500 ms system-monitor slice can interrupt starves the reader. Not fixed in this round; `--det-disable=sched` is the workaround, and "broken by `--det`" counts it (section 8).
- PID: controlled only as root with util-linux `unshare`; the start message says when it is not.
- `/dev/urandom`: 1 MiB per open from the test's stream; a reader that needs more gets EOF (DECLARED; no case found).

## 7. Nightly real-clock run (NC)

- Workflow: `.github/workflows/go-nightly-real-clock.yml`, schedule `17 3 * * *` (scheduled runs fire from the default branch only; on this branch it runs on dispatch and on a push to `harness/go/NIGHTLY`). It records a skip cache on prometheus (`./model/... ./tsdb/... ./promql/... ./config/...`, 1053 tests), then runs `fenvix-go test --skip-real-clock` on the same tree: every test on the real clock, the cache read and never written, and the list of tests that pass on the virtual day and fail on the real clock (exit non-zero when there are any).
- Two real runs (MEASURED, output committed under `harness/go/results/nightly/`):
  - run 44639691571 (before the strace fix): record exit 0, check exit 0, "1053 tests ran; 0 passed on the virtual day and fail on the real clock";
  - run 44661508881 (with it): the same, 373.9 s of test time.
- What it bounds: fixtures that expire during the day (C1-class, F6), at one time of day. What it does not: time-of-day failures at other hours (it samples 03:17), and tests that are refused anyway (C2/C3: they never reuse, so there is nothing to bound).

## 8. Numbers (N4, N5), corrected

- **N4.** In skip-r4 (all 6 shards), telegraf shard 5 alone is 66.8% of telegraf's test time; REPORT-2's telegraf rows (skip-r5/r6, 5 of 6 shards) cover **33.2%** of it. Labelled so here; skip-r9 has all six shards (section 4).
- **N5.** Fingerprint coverage under `--det`, like for like (the 1006 tests with a `--det` result in both flaky-final and flaky-r8): **62.7% → 70.0%**. REPORT-2's 56.0% → 70.0% mixed denominators: the 56.0% included 139 quic-go tests that have no `--det` result in flaky-r8, because quic-go's `--det` arm hit the 10-minute timeout (600.7 / 600.9 / 601.5 s) while its plain arm took 7.7 s. `aggregate.py` now labels this "the --det arm stopped by the go test timeout" (it said "both arms"). By REPORT-2's own rule, quic-go's suite timeout is a break: **broken by `--det`: 1 test, plus quic-go's suite (sched, section 6)**.

## 9. The check script: reviewer's original kept, and the exact diff (coordinator question 2)

The reviewer's file is kept unchanged as `harness/go/review_r025b_check_original.py` (only a 3-line comment added at the top saying why it is there). It **could never exit 0**: after computing N4, N5 and S1 it appends each finding unconditionally (`findings.append("N4")` with no condition, the same for N5 and S1), so it exits 1 on any tree, fixed or not. The review computes the numbers; the decision "is the finding fixed" was left to the reader.

`harness/go/review_r025b_check.py` keeps every computation of the review and replaces each unconditional append with a test of the corrected statement:

- **N4:** the finding holds unless REPORT-3 states the share the data gives (`33.2%`, the r5/r6 coverage of telegraf's test time computed by the review's own code).
- **N5:** the finding holds unless REPORT-3 states both like-for-like numbers computed by the review's code (`62.7%` and `70.0%`) and `aggregate.py` carries the corrected label ("the --det arm stopped").
- **S1:** the review's computation (8 tests failing in ≥ 10 commits of skip-r5 and ≤ 2 of skip-r4) is kept and printed; added: in the newest walk (skip-r9), every test failing under fenvix in ≥ 10 commits while plain `go test` passes in ≥ 10 is "broken by skip mode". The finding holds if any such test exists, if prometheus, telegraf or terraform is missing from that walk, or if REPORT-3 does not state the count (`broken by skip mode: 0`).
- **Q3:** unchanged (informative, never a finding).

What the reviewer meant and is still checked: the numbers are recomputed from the committed raw files every time (nothing is hard-coded but the label strings); a wrong number or a missing label still fails; S1 is now checked on data, not on a sentence. What is not checked by the script: that the 8 tests of skip-r5 individually pass (they are covered by the "broken by skip mode" rule when they appear in ≥ 10 commits; how many of them appear is printed).

Exact diff (`diff review_r025b_check_original.py review_r025b_check.py`):

```diff
PENDING-DIFF
```

## 10. Trade-offs and what is not done

- **Reuse versus soundness, as decided:** every input that cannot be keyed soundly makes the test rerun (`exec:`, `clock:`, `volatile:`, `unix:`, `local-service:`…). Section 4 gives the cost per reason.
- **Real elapsed time inside a binary reaches tests** (section 3). Proposal if it must not: a per-test virtual clock, continuous and strictly increasing, that starts every test at `day + slot(position in the run)` instead of `day + elapsed`, with the slot large enough that no test outruns it (or the next test is marked unkeyed when one does). PENDING-PROPOSAL-VERDICT
- **The virtual day hides expiries during the day;** the nightly real-clock run bounds them at one time of day (section 7).
- **The vDSO called directly from C** is not seen (section 3).
- **PID namespace needs root;** `/dev/urandom` serves 1 MiB per open (section 6).
- **quic-go under `--det`:** not fixed (section 6).
- **hugo and caddy** were not re-walked with the fixed parser (runners: section 4); their last numbers are from skip-r4 (old parser).
- Python and Node must apply the same day rule (REPORT-2); the rule now lives in the Rust core (`fenvix_skip_day_epoch`), so they can call it instead of re-implementing it.
