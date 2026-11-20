# P-021 Go track, report 2: fixes for review R-025 (FIX 17) and the coordinator's follow-ups

Session 2026-11-19, branch `claude/go-l0`. Review: `sessions/2026-11-19-review-go/REPORT.md` (merged from `claude/review-r025`). First report: fenvix-brain-cli `sessions/2026-11-18-go-l0/REPORT.md`. This session could not attach the brain repository; the review quotes the numbers it corrects, and this report corrects them from the committed data.

Labels: MEASURED (with where, or the Actions run id), ESTIMATED, DECLARED, UNKNOWN. No human-team time estimates.

## Status

- **F1-F9, D1-D4, R1: fixed.** Every `TestR025` test passes, including the review's held attacks (MEASURED, this container, from a clean Go build cache).
- **N1-N3: corrected** in section 6. `harness/go/review_r025_check.py` exits 0.
- **Coordinator follow-ups in this round:**
  - goroutine scheduling under `--det` (control `sched`);
  - the skip key's reuse gap to Go's cache: virtual clock in skip mode, the `/proc` refinements, reusable dynamically linked children;
  - the nightly real-clock check.
- **Skip walks after the fixes: 0 wrong reuses in every run** (section 4). The share of test time reused, against Go's own cache on the same commits (median / mean):
  - prometheus: 53% / 46% vs 55% / 57%;
  - terraform: 32% / 31% vs 43% / 41%;
  - telegraf: 10% / 10% vs 97% / 83%. Its gap is one file, `/proc/1/stat`, which cannot be keyed soundly (section 4).
- **Fingerprint coverage under `--det` (flaky round flaky-r8, 23 of the 24 projects): 70.0%.** The same 23 projects had 56.0% before.
- Three changes to the review's own tests, each explained in section 7.

## 1. Gates (MEASURED, this container)

Container: 4 CPUs, Linux 6.18, Go 1.24.7, go1.22.12 and go1.26.0 through GOTOOLCHAIN, strace, gcc.

| gate | result |
|---|---|
| `cd go && go test ./cmd/fenvix-go -run 'TestR025' -v` | 36 PASS lines, 0 FAIL: F1, F2 (4 cases), F3 (3), F4, F5, F6, F7, F8 (3), F9, Held (6), D1 (3), D2 (3), DetHeld, D3 (Go 1.22) |
| `python3 harness/go/review_r025_check.py` | exit 0 (N1a, N1b, N1c ×2, N2, N3, R1) |
| `cargo test -p detpy-core -p fenvix-go` | 44 + 15 passed |
| `cd go && go clean -cache && go test -count=1 ./...` | all packages ok |
| CI `go-tests` | runs on every push. Its toolchain loop now includes go1.22.12 and fails on a build error |

One pitfall, found and fixed in this session: Go's build cache does not track `libfenvix_go.a`, the static library named in `#cgo LDFLAGS`. After a Rust-only change, a `go build` can link the old core. Every gate above was re-run after `go clean -cache`. CI builds from scratch, so it is not affected.

## 2. Fixes for the review

### Rust boundary (R1)

What moved into the core:
- the key, the decider, the cache, the prefix closure, network locality and the strace parser now live in `crates/fenvix-go/src/skip.rs` and `strace.rs`;
- they sit behind five C functions: `fenvix_skip_open`, `_decide`, `_record`, `_free`, `_strace_args`;
- `go/internal/skip` and `go/internal/strace` are deleted.

What Go keeps:
- the Go shell (`cmd/fenvix-go/exec.go`) runs the test binary;
- it hands over the raw hook records and the strace log;
- it prints what the core decided.

Other changes:
- digests are the core's BLAKE3;
- the cache format is versioned, so caches written by the old key are ignored.

Not done: Python and Node do not call this decider yet. They have no skip mode in their engines on this branch (see section 3).

### Skip with proof (F1-F9)

| # | fix | test |
|---|---|---|
| F1 | Every input any entry of the package recorded is valued **before the test binary starts**: `Session::open` is called before `cmd.Start`, so before `init` and `TestMain`. An input first seen in a run takes its value after the run only when strace saw no change to it, an ancestor of it, or an entry in it; otherwise its value is `?` and the test runs again next time. | `TestR025_F1` |
| F2 | stat/lstat/statx/access/readlink keep the call kind. Values: type, permission bits, size and mtime; a symlink's target; listings hold names with entry types. Directories: mtime too, except world-writable scratch directories (`/tmp`). | `TestR025_F2` (4 cases) |
| F3 | There is no root allowlist any more: every observed path is an input. Not inputs: `/proc/self`, devices, the run's own outputs, and fenvix's and Go's working state. `/proc` state that changes by itself is volatile: the test is not reusable. | `TestR025_F3` (3 cases) |
| F4 | A loopback or own-address port counts as local only when the run itself bound it (`bind`/`getsockname` in strace); unix sockets likewise. A service the run did not start gives reason `local-service`: never reused. | `TestR025_F4` |
| F5 | `sendto`, `sendmsg` and `sendmmsg` are traced with their address. | `TestR025_F5` |
| F6 | See section 3: the virtual clock in skip mode, plus the condition rule where the time control is unavailable. | `TestR025_F6`, `TestSkipRealClockReportsExpiry` |
| F7 | `LD_*`, `GLIBC_*` and `MALLOC_*` are keyed as families; `HOME`, `TMPDIR` and `PATH` are keyed too. | `TestR025_F7` |
| F8 | Only presentational test flags are neutral. `-run`, `-skip`, `-timeout`, `-count` and `-shuffle` are keyed. | `TestR025_F8` (3 cases) |
| F9 | The module root is in the key. | `TestR025_F9` |

Also:
- with hooks capture only (no strace), nothing is reused, and this is said at start;
- reasons are ordered code-or-config first, so the first reason names a code change when there is one (the attribution problem behind N1).

### `--det` (D1-D4)

| # | fix | test (10 plain runs and 10 `--det` seed-0 runs each) |
|---|---|---|
| D1 | fastwait skips a sleep only when the test started no goroutine **and no timer of the test is due before the sleep ends**. | `TestAfterFuncThenSleep`: 10/10 pass plain and under `--det` |
| D2 | The epoch stays fixed. A real-time epoch was tried and reverted: it made `TestClockParity` vary between seed-0 runs. Instead: (1) file mtimes from `Stat`/`Lstat`/`File.Stat` move by the offset between the virtual and the real clock at test start, and `Chtimes` moves the other way, so a set time reads back unchanged; (2) dynamically linked programs a test starts get the same offset through `LD_PRELOAD` of a small library, built once with the C compiler. | `TestMtimeTTL`, `TestChildClock`, `TestChtimesRoundTrip` |
| D3 | Three sources now come from the test's deterministic stream: (1) `runtime.cheaprand` on user goroutines; (2) `getrandom(2)` through `syscall.Syscall*`/`RawSyscall*`, handled in nosplit code; (3) listener ports on port 0. | `TestLinknameCheaprand`, `TestRawGetrandom`, `TestEphemeralPorts`: one outcome and one fingerprint in 10 runs each |
| D4 | The `t.Deadline()` hook is guarded by the time group, so Go 1.22 builds. Unavailable on Go 1.22, and said at start: time, fastwait, random, and getrandom through `RawSyscall`. | `TestR025_D3_Go122` |

Every `--det` run now prints at start:
- the unavailable controls;
- the optional hooks that did not apply;
- what `--det` does not control.

## 3. The clock: the decision, Python/Node, the F6 trade-off, the nightly check

**Why the first walk after the fixes (skip-r4) collapsed:**
- the walk runs skip mode without `--det`, so the clock was real;
- the strict rule then marked every test that used the wall part of a time as not reusable;
- by test time, the clock rule alone cost:

| repository | points of test time lost to the clock rule |
|---|---:|
| prometheus | 47.4 |
| telegraf | 51.0 |
| terraform | 23.3 |
| caddy | 14.0 |

- the top clock sites were `timestamppb.New(time.Now())` (protobuf, 13,293 s of test time), the ssh library, `net/http` (Date header, idle state) and loggers (MEASURED, skip-r4, run 44549297298).

**Decision (coordinator, 2026-11-19): skip mode runs under the virtual clock.**
- The time control is on in skip mode.
- Without `--det`, the epoch is today 00:00 UTC, and the day is in the key: a cached result is reused on the day it was recorded only.
- File mtimes and dynamically linked child processes are moved onto the virtual clock (the D2 mechanisms).
- The strict rule stays only where the time control is unavailable (Go 1.22, `--det-disable=time`). There:
  - a comparison of the clock with a fixed time is recorded and re-evaluated against the current clock (`TestR025_F6`'s mechanism);
  - any other wall-clock use makes the test rerun.

**Python and Node today:**
- Under `--det`, both use a fixed epoch, 2025-01-01T00:00:00Z (`python/detpy/_state.py`, `--det-epoch` in `python/detpy/plugin.py`; `node/src/session.js`, `node/src/clock.js`). Go's `--det` uses the same epoch.
- Neither engine has a skip-with-proof mode on this branch: the skip studies are harness code, not engine code.
- So the day epoch is a rule of Go's skip mode only. If Python and Node get a skip mode, this rule must be applied there too. That is not done; it is DECLARED here as the rule to follow.

**The F6 trade-off, labelled for the founder (MEASURED, `TestSkipRealClockReportsExpiry`, this container):**
- A fixture whose NotAfter falls later today still passes under fenvix until the next UTC day.
- The test records a pass, waits until the fixture's real expiry, then runs again in skip mode. Result: `reuse=true fresh=passed`. That is not a wrong reuse (the fresh fenvix run agrees with it), but plain `go test` would fail.
- The gap is bounded to one day and made visible by the nightly real-clock check below.

**The nightly real-clock check:**
- Command: `fenvix-go test --skip-cache=DIR --skip-real-clock ./...`.
- It runs every test on the real clock, reads the skip cache without writing it, and lists the tests that pass on the virtual day and fail on the real clock. The exit code is non-zero when there are any.
- `TestSkipRealClockReportsExpiry` checks it: the expired fixture is named, and the cache is unchanged afterwards.
- `docs/GO.md` gives the CI recipe (a scheduled job restoring the same skip cache).
- No scheduled workflow was added to this repository: it has no user project for the job to run against.

**Programs a test starts:**
- A dynamically linked program gets the virtual clock, and everything it reads is keyed through strace, so the test is reusable. Example: `cat` in `TestSubprocess`.
- A statically linked program ignores `LD_PRELOAD`, so its clock is real and the test is not reusable (`exec:`). Evidence: `file $(go env GOROOT)/bin/go` reports "statically linked". This is why tests that run the `go` command stay unkeyable: 4.1 points of terraform's test time in skip-r5.

## 4. Skip walks after the fixes (GitHub Actions)

Same 5 repositories and commit windows as skip-r3. Every test runs; every reuse the key would make is checked against the fresh outcome. A wrong-looking reuse is re-run 3 times alone, to separate flaky tests from wrong reuses.

### skip-r4: the F1-F9 key, real clock (run 44549297298)

Hugo shards 1-3 lost their runners (logs 404). They are kept partial, at 30/20/30 of 50 commits.

| repository | transitions (min over shards) | fenvix share of test time reused, median / mean | Go cache, median / mean | fenvix reuses verified | wrong | flaky |
|---|---:|---:|---:|---:|---:|---:|
| caddy | 50 | 12% / 8% | 25% / 23% | 3,256 | 0 | 0 |
| hugo | 19 | 0% / 2% | 0% / 21% | 11,693 | 0 | 0 |
| prometheus | 50 | 3% / 3% | 56% / 58% | 27,837 | 0 | 0 |
| telegraf | 50 | 3% / 3% | 37% / 59% | 7,094 | 0 | 0 |
| terraform | 50 | 4% / 4% | 65% / 48% | 46,025 | 0 | 0 |

### skip-r5 and skip-r6: virtual-day clock, dynamically linked children, `/proc/<pid>` (runs 44580058184 and 44600259928)

skip-r5 walked prometheus, telegraf and terraform at commit 79975c2. skip-r6 walked telegraf at a03d24d: skip-r5 plus `/proc/1/{environ,cmdline,comm,exe}` and `/proc/filesystems` keyed by content. For both telegraf walks, shard 5 of 6 had not reported when this report was written, so they cover 5 of 6 shards.

| repository | transitions | fenvix share of test time reused, median / mean | Go cache, median / mean | fenvix reuses verified | wrong | flaky |
|---|---:|---:|---:|---:|---:|---:|
| prometheus (r5) | 50 | **53% / 46%** | 55% / 57% | 70,290 | **0** | 18 |
| terraform (r5) | 50 | **32% / 31%** | 43% / 41% | 117,508 | **0** | 0 |
| telegraf (r5, 5 of 6 shards) | 50 | 10% / 10% | 96% / 83% | 16,599 | **0** | 8 |
| telegraf (r6, 5 of 6 shards) | 50 | 10% / 10% | 97% / 83% | 17,275 | **0** | 14 |

"flaky" counts reuses whose fresh run failed and that then passed 3/3 alone, as in the first report. R-022's caveat applies: passing alone also covers an order-dependent wrong reuse.

**Test time Go's cache reused and fenvix ran, by fenvix's reason (skip-r5, points of all test time):**

| repository | gap | network | local-service | exec | meta | unkeyed / volatile | other |
|---|---:|---:|---:|---:|---:|---:|---:|
| prometheus | 13.1 | 1.3 | 7.5 | 0.0 | 1.7 | 2.3 | 0.3 |
| terraform | 10.8 | 3.0 | 0.1 | 4.1 | 0.6 | 0.7 | 2.4 |
| telegraf | 72.6 | 4.1 | 0.0 | 1.0 | 0.0 | 67.3 | 0.2 |

**What remains, with evidence:**
- **telegraf: `/proc/1/stat`** (MEASURED, skip-r6). After `/proc/1/environ` was keyed, the next read is `/proc/1/stat`: 4,667 s of test time, across many unrelated packages (`plugins/inputs/prometheus`, `outputs/heartbeat`, `outputs/opensearch`, `models`...). So it is a read in a shared dependency's initialisation. The file holds fields that change all the time (state, CPU times, memory). The shell sees one read of the whole file, not which fields the code uses. Keying a subset of fields would be unsound, and keying the whole file never matches. It stays volatile. Fixing it needs the reader identified and a rule for its exact fields: UNKNOWN which dependency it is. Not done in this round.
- **network** (an outside address) and **local-service** (a service the run did not start: prometheus's local stack): not cacheable by rule.
- **exec of a static program** (the `go` command): see section 3.

## 5. Goroutine scheduling under `--det` (coordinator request; control `sched`)

**What the control does:**
- the test binary runs with one P (`GOMAXPROCS=1`, unless `--det-gomaxprocs` is given);
- `GODEBUG=asyncpreemptoff=1,gcstoptheworld=1`;
- sysmon's time slice goes from 10 ms to 500 ms;
- with an exploration seed, the run queue's runnext choice comes from the seed.

The in-binary part is Go: runtime overlay group `sched`, nosplit code. No decision is taken outside the binary, so nothing moves to Rust.

**Flaky round flaky-r8 (run 44556337969; rclone re-run 44588263294 after the Chtimes fix), 23 of 24 projects:**
- fingerprint coverage (same fingerprint in 3 seed-0 runs): **70.0%, 704 of 1,006** tests with a `--det` result. The same 23 projects in flaky-final had 641 of 1,145, 56.0%.
- nats-server and teleport lost their runners. They were re-dispatched (run 44609015944) and had not reported when this report was written; nats-server is the project that had 2,191 tests with no `--det` result.

**The rest, with causes:**
- 280 of the 302 diverging tests diverge at a goroutine interleaving next to a timer event: `time.Now`, `time.timer`, `time.NewTimer`. 232 of them are terraform's DAG walker (5 s timers).
- Cause: timers still fire after their real delay, and runtime background goroutines (scavenger, sysmon wakeups) enter the run queue at real-time-dependent moments.
- Evidence: plain `go test` with `GOMAXPROCS=1` and no fenvix shows the same in this container, with 2 interleavings in 12 runs of `TestInterleaving`.
- The other 22 diverge at clock values (14), listing order (6) and beyond the trace (2).
- Closing this needs timers driven by the virtual clock instead of real delays. Not done.

**Broken by `--det` (passes 10/10 plain, fails 3/3 under `--det`): 1.**
- The test: docker/cli `TestRunBuildFromGitHubSpecialCase`.
- Cause: its `git clone` child reaches github.com; with the preloaded clock the child lives in 2025, and TLS verification fails.
- A child's network access was already outside `--det`. This is a cost of the D2 child-clock mechanism, stated here.
- rclone's 2 bisync tests broke in the first flaky-r8 run (mtimes read back double-shifted). Fixed by moving `Chtimes`; they pass in the re-run.

**Slowdown:** median +5.5% over 20 valid comparisons (NOISY). Left out: cortex (`--det` ran 8 of 54 tests) and quic-go (both arms stopped by the timeout).

## 6. Numbers corrected (MEASURED from the committed data, `harness/go/aggregate.py`, `review_r025_check.py`)

**N1. The gap to Go's cache on terraform.**
- The first report attributed it to the network rule ("61,389 test-transitions").
- The data has 66,908 such test-transitions at c22b02f, and 67,616 test-transitions at the branch head (hugo shard 1 was added after the report).
- By test time, Go's cache reused and fenvix ran 29.1% of terraform's test time. Of that, the network rule explains 2.2 points and the Go telemetry counters (the defect fixed in c22b02f) 19.4 points; changed files explain 7.4.
- With telemetry-only reruns counted as reused (the report's own upper bound):
  - terraform: 48% / 46% (published 28% / 27%);
  - caddy: 39% / 32% (published 38% / 24%).

| repository (skip-r3) | gap | network | telemetry | file | other |
|---|---:|---:|---:|---:|---:|
| caddy | 1.2 | 1.2 | 0.0 | 0.0 | 0.0 |
| hugo | 13.3 | 12.6 | 0.0 | 0.2 | 0.5 |
| prometheus | 12.3 | 12.2 | 0.0 | 0.0 | 0.1 |
| telegraf | 27.9 | 2.5 | 16.5 | 8.9 | 0.0 |
| terraform | 29.1 | 2.2 | 19.4 | 7.4 | 0.0 |

**N2. Tests with no `--det` result.** The flaky table now has two more columns. flaky-final:

| project | tests | broken by --det (fails 3/3) | 10/10 plain, no --det result | 10/10 plain, not 3/3 --det | fingerprint coverage |
|---|---:|---:|---:|---:|---:|
| cortex | 66 | 0 | 55 | 0 | 37.5% |
| nats-server | 2,895 | 0 | 2,191 | 15 | 16.4% |
| quic-go | 159 | 0 | 0 | 1 | 6.9% |
| temporal | 17 | 0 | 0 | 1 | 43.8% |
| all 24 projects | 4,099 | 0 | 2,246 | 17 | 38.9% of 2,013 |

- "Broken by `--det`: 0" and the 38.9% held only for the tests with a `--det` result: about half the suite.
- nats-server's serial `--det` run hits the 10-minute timeout after 879 tests. That is itself a break.
- cortex: cause UNKNOWN.
- In flaky-r8, 181 tests that pass 10/10 plain have no `--det` result (cortex, quic-go).

**N3. `--det` slowdown, flaky-final.** The median over the 21 valid comparisons is +3.9% (NOISY). Left out: nats-server (both arms hit the timeout) and cortex. The published +2.1% included both.

## 7. Changes to the review's tests

- **F6 fixture:** `clock/testdata/notafter.txt` was missing from the review commit (git drops the empty `testdata` directory), so the record run could never pass. Added.
- **F4:** the step "unchanged service: the test must be reused" became "unchanged service: the test reruns with reason `local-service`". A service the run did not start cannot be keyed. The change step (the service's answer changes, so the test must not be reused) is unchanged.
- **D3 (Go 1.22):** the review asked for exit 0. The finding is that the binary did not build. Now the binary builds and the test runs: `TestReflectMapOrder` fails deterministically on go1.22 under `--det` (first key "15" in every run), while plain go1.22 runs vary.
- **First-report tests:**
  - `skip_test.go`: `TestSubprocess` is reusable again, through the virtual clock for dynamically linked children;
  - `TestInterleavingIsMeasuredNotControlled` became `TestInterleavingSchedControl`: it checks that the control is on and logs the distribution;
  - `TestDetUnchangedOnDeterministicPackages` runs the remaining Go packages.

## 8. Limits and open points

- **telegraf `/proc/1/stat`:** needs its reader identified, so that only the fields it uses can be keyed (section 4).
- **Static programs:** a test that runs one (the `go` command, Go tools) is not reusable.
- **The virtual-day clock:** an expiry within the day is hidden until the next UTC day. The nightly real-clock check bounds and reports it.
- **Directory mtimes:** not keyed for world-writable directories.
- **Strict clock rule (where the time control is unavailable):** it does not see clock reads that bypass package `time`.
- **`--det` interleavings at timers:** the main residual of `sched`; timers need to be driven by the virtual clock.
- **Child clocks:** need a C compiler and a dynamically linked program. They also break children that do TLS against outside servers under `--det` (docker/cli).
- **Python and Node:** they keep their own (harness) skip logic; moving them onto `fenvix_skip_*` and the day-epoch rule is the next step of R1.
- **Still running when this report was written:** nats-server and teleport (flaky-r8), telegraf shard 5 (skip-r6).
