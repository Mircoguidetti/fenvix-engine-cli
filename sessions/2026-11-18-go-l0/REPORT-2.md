# P-021 Go track, report 2: fixes for review R-025 (FIX 17)

Session 2026-11-19, branch `claude/go-l0`. Review: `sessions/2026-11-19-review-go/REPORT.md` (merged from `claude/review-r025`). First report: fenvix-brain-cli `sessions/2026-11-18-go-l0/REPORT.md` (not read in this session: the brain repository could not be attached; the review quotes the numbers it corrects, and this report corrects them from the committed data).

Labels: MEASURED (with where/run id), ESTIMATED, DECLARED, UNKNOWN.

## Status

- F1-F9, D1-D4, R1: fixed. Every `TestR025` test passes, including the review's held attacks (MEASURED, this container, Go 1.24.7, strace; log below).
- N1-N3: corrected below; `harness/go/review_r025_check.py` exits 0 (MEASURED, this container).
- Skip walk re-run on GitHub Actions after the fixes: WALK_STATUS.
- Three changes to the review's own tests, each explained in section 4: a missing fixture file (F6), one step of F4, the exit-code condition of D3. No test was skipped or weakened beyond these.

## 1. Gates (MEASURED, this container: 4 CPUs, Linux 6.18, Go 1.24.7, go1.22.12 and go1.26.0 through GOTOOLCHAIN, strace, gcc)

| gate | result |
|---|---|
| `cd go && go test ./cmd/fenvix-go -run 'TestR025' -v` | all pass: F1, F2 (4 cases), F3 (3), F4, F5, F6, F7, F8 (3), F9, Held (6), D1 (3), D2 (3), DetHeld, D3 (Go 1.22) |
| `python3 harness/go/review_r025_check.py` | exit 0 (N1a, N1b, N1c ×2, N2, N3, R1) |
| `cargo test -p detpy-core -p fenvix-go` | 44 + 15 passed (fenvix-go: 6 before, +9 for the skip key and the strace parser) |
| `cd go && go test -count=1 ./...` | all packages ok (cmd/fenvix-go 104 s) |
| CI `go-tests` (adds go1.22.12 to the toolchain loop; a build failure now fails the job) | CI_STATUS |

## 2. Fixes

### Rust boundary (R1)

The key, the decider, the cache, the prefix closure, network locality and the strace parser are in the core: `crates/fenvix-go/src/skip.rs` and `strace.rs` (1,730 lines with their tests), behind five C functions (`fenvix_skip_open`, `_decide`, `_record`, `_free`, `_strace_args`). `go/internal/skip` and `go/internal/strace` are deleted. The Go shell (`cmd/fenvix-go/exec.go`) runs the test binary, passes the raw hook records and the strace log path, and prints what the core decided. The cache digest is the core's BLAKE3, and the cache format has a version: caches written by the old Go key are ignored.

Not done: Python and Node do not call this decider yet (they keep their own); the C ABI is ready for it.

### Skip with proof (F1-F9)

| # | fix | test |
|---|---|---|
| F1 | Every input any entry of the package recorded is valued **before the test binary starts** (`Session::open`, called before `cmd.Start`, so before `init` and `TestMain`). A new entry takes the pre-run value. An input first seen in this run takes its value after the run only when strace saw no change to it (no write, rename, chmod or utimens of the path or an ancestor, no entry created or removed in it); otherwise its value is `?` and the test runs again next time, which takes a pre-run value. | `TestR025_F1`: `TestReadsState` reruns (`unkeyed:c:.../state.txt`) |
| F2 | stat/lstat/statx/access/readlink keep the call kind. Key values: file type, permission bits, size and mtime (ns); a symlink's target; directories: type, mode, mtime (mtime left out for world-writable scratch directories such as `/tmp`, which any process moves). Listings hash names with entry types. | `TestR025_F2` mode, mtime, symlink-target, entry-type |
| F3 | The root allowlist is gone: every path observed is an input except `/proc/self`, devices (`/dev` but `/dev/shm`), the run's own outputs (first access created or truncated it, or it lies under a directory the run created) and fenvix's and Go's working state (session, skip cache, GOCACHE, `~/.config/go/telemetry`, the test binary's directory). `/proc/sys` is keyed; other `/proc` files make the test not reusable (`volatile:`). | `TestR025_F3` `/var/lib`, `/srv`, `~/.cache` |
| F4 | A loopback or own-address connection counts as inside only when the port was bound by the run itself (strace `bind`/`getsockname`); unix sockets likewise (`bind`). A service the run did not start is reason `local-service`: never reused. | `TestR025_F4` (one step changed, section 4) |
| F5 | `sendto`, `sendmsg`, `sendmmsg` are traced with their address. | `TestR025_F5` |
| F6 | Wall clock, without changing what tests see (no virtual clock in skip mode). A `time.Time` from the clock carries a monotonic reading; arithmetic between two such times does not depend on the date. The overlay (`time-deps`, part of the deps control) records when the wall part of one is used: in `After`/`Before`/`Compare`/`Equal` with a fixed time it records a condition (fixed time, offset to the real clock, sign) that the key re-evaluates against the clock at decision time; any other use (`sec()`: formatting, `Unix()`, `Sub` with a fixed time; `Nanosecond()`) makes the test not reusable (`clock:<site>`). A test that started another program is not reusable either (`exec:`): that program's clock and entropy are invisible. | `TestR025_F6`: reruns with `clock:<NotAfter>` once the date passed |
| F7 | `LD_*`, `GLIBC_*`, `MALLOC_*` are keyed as families (any added, removed or changed variable); `HOME`, `TMPDIR`, `PATH` joined the fixed list. | `TestR025_F7` (`env:LD_*`) |
| F8 | Only presentational test flags are neutral (`-v`, `-paniconexit0`, `-testlogfile`, `-outputdir`, `-gocoverdir`, `-fullpath`); `-run`, `-skip`, `-timeout`, `-count`, `-shuffle` are keyed. | `TestR025_F8` skip-subtest, run-subtest, timeout |
| F9 | The module root is in the key. | `TestR025_F9` |

Also: without strace (hooks capture) nothing is reused; decisions are still reported and the limit is said at start (the hooks cannot see child processes, cgo, raw syscalls or which paths the run created).

Reasons are now ordered code-or-config before network, so the first reason names a code change when there is one (the attribution problem behind N1).

### `--det` (D1-D4)

| # | fix | test (10 plain runs, 10 `--det` seed-0 runs) |
|---|---|---|
| D1 | fastwait skips a sleep only when the test started no goroutine **and no timer of the test is due before the sleep ends** (timers carry an `armed` flag: set at creation and Reset, cleared at Stop and one-shot fire). | `TestAfterFuncThenSleep`: 10/10 pass plain, 10/10 under `--det` |
| D2 | The epoch stays fixed (2025-01-01 at seed 0). A real-time epoch was tried first and reverted: it made `TestClockParity` (absolute time) vary between seed-0 runs, breaking the determinism promise. Instead real time is brought onto the virtual timeline: modification times from `Stat`/`Lstat`/`File.Stat` move by the offset between the virtual and the real clock at the start of the test; programs a test starts get the same offset through a small preloaded library (`LD_PRELOAD`, built once with the C compiler from `go/internal/overlay/files/faketime.c.txt`; dynamically linked programs only). | `TestMtimeTTL`, `TestChildClock`: 10/10 pass plain and under `--det` |
| D3 | `runtime.cheaprand` on user goroutines uses the deterministic source of the maps control (so `select` among ready channels in one goroutine is deterministic too); `getrandom(2)` through `syscall.Syscall`/`Syscall6`/`RawSyscall`/`RawSyscall6` is served from the test's stream (nosplit code: no locks or allocation, the buffer may be on the caller's stack); listeners on port 0 get ports from the test's stream (10000-29999, a port in use is skipped). | `TestLinknameCheaprand`, `TestRawGetrandom`, `TestEphemeralPorts`: one outcome and one fingerprint in 10 seed-0 runs each (the outcome is a deterministic failure for all three: the fixtures assert a parity or an order, and seed 0 gives the other one). `TestSelectReady`: 10/10 one outcome (was 7/3) |
| D4 | The `t.Deadline()` hook needs the time group; it is now inside `fenvix:if time`. Go 1.22 builds and runs with time, fastwait and random unavailable and getrandom through `RawSyscall` uncontrolled, all said at start. The CI toolchain loop runs go1.22.12 and fails on a build error (no `|| true` on that check). | `TestR025_D3_Go122` |

Said at start (D2/D4): every `--det` run prints the unavailable controls, the optional hooks that did not apply, and the list of what `--det` does not control (interleaving, real timer delays, `select` across goroutines, `synctest`, poller deadlines, vdso/raw clock reads, clock and entropy of child processes and cgo, file timestamps).

Docs: `docs/GO.md` sections "Controls" and "Skip with proof" rewritten accordingly; the Go 1.22 sentence states exactly what is unavailable.

## 3. Numbers corrected (MEASURED from the committed data, `harness/go/aggregate.py`, `review_r025_check.py`)

**N1. Gap to Go's cache on terraform.** The report attributed it to the network rule ("61,389 test-transitions"). The data has 66,908 at c22b02f and 67,616 test-transitions at the branch head (hugo shard 1 was added after the report) whose first reason is network. By test time, of terraform's test time that Go's cache reused and fenvix ran (29.1% of all test time), the network rule explains 2.2 points and the Go telemetry counters (the defect fixed in c22b02f) 19.4 points; the rest is mostly files that changed (7.4 points). With telemetry-only reruns counted as reused (the report's own upper bound, applied to every repository): terraform 48% / 46% (published 28% / 27%), caddy 39% / 32% (published 38% / 24%), telegraf 28%/56% as already published. The skip-r3 table by reason (points of all test time) is now printed by `aggregate.py skip`:

| repository | gap | network | telemetry | file | other reasons |
|---|---:|---:|---:|---:|---:|
| caddy | 1.2 | 1.2 | 0.0 | 0.0 | 0.0 |
| hugo | 13.3 | 12.6 | 0.0 | 0.2 | 0.5 |
| prometheus | 12.3 | 12.2 | 0.0 | 0.0 | 0.1 |
| telegraf | 27.9 | 2.5 | 16.5 | 8.9 | 0.0 |
| terraform | 29.1 | 2.2 | 19.4 | 7.4 | 0.0 |

**N2. Tests with no `--det` result.** The flaky table (`aggregate.py flaky`) now has two more columns; the rows where they are not zero:

| project | tests | broken by --det (fails 3/3) | 10/10 plain, no --det result | 10/10 plain, not 3/3 --det | fingerprint coverage | slowdown |
|---|---:|---:|---:|---:|---:|---|
| cortex | 66 | 0 | 55 | 0 | 37.5% | +1.8% (invalid: --det ran 8 of 66 tests) |
| nats-server | 2,895 | 0 | 2,191 | 15 | 16.4% | +0.2% (invalid: both arms stopped by the go test timeout) |
| quic-go | 159 | 0 | 0 | 1 | 6.9% | +16.5% |
| temporal | 17 | 0 | 0 | 1 | 43.8% | -0.5% |
| all 24 projects | 4,099 | 0 | 2,246 | 17 | 38.9% of 2,013 | median +3.9% over 21 valid |

 Of the 4,099 tests of the plain baseline, 2,246 pass 10/10 plain and have no `--det` seed-0 result (nats-server 2,191: the serial `--det` run hits the 10-minute `go test` timeout after 879 tests; cortex 55: cause not established, UNKNOWN), and 17 pass 10/10 plain but not 3/3 under `--det` (nats-server 15, quic-go 1, temporal 1). "Broken by `--det`: 0" (fails 3/3) and the fingerprint coverage 38.9% (783 of 2,013) hold only for the 2,013 tests that have a `--det` result: about half the suite. The nats-server timeout under serial `--det` is itself a break.

**N3. `--det` slowdown.** Median +3.9% over the 21 valid comparisons (NOISY, as labelled in the first report). Left out: nats-server (both arms stopped by the 10-minute timeout) and cortex (`--det` ran 8 of 66 tests). The published +2.1% included both.

Not re-run: the flaky round itself (24 projects). Its numbers above are re-derived from the committed `flaky-final` data, not re-measured with the fixed `--det`.

## 4. Changes to the review's tests

- **F6 fixture**: `go/testdata/fixtures/review-r025/clock/testdata/notafter.txt` was missing from the review commit (git does not keep the empty `testdata` directory the test writes into), so the record run could never pass and F6 failed for that reason alone. Added with a date in 2100; the test overwrites it.
- **F4**: the review's step "unchanged service: the test must be reused" (`mustReuse`) is replaced by "unchanged service: the test reruns with reason `local-service`". A service the run did not start (image, data, state) is in no key; only a declared service digest could justify a reuse, and the rule of this fix is that an input that cannot be keyed soundly makes the test rerun. The change step (service answer changes, the test must not be reused) is unchanged.
- **D3 (Go 1.22)**: the review required exit 0. The finding is that the binary did not build. `TestReflectMapOrder`'s outcome depends on the map implementation: under `--det` seed 0 on Go 1.22 its first key is "15" in every run (3/3 here), so it fails deterministically, while plain go1.22 runs vary. The test now requires that the binary builds and the test runs, and that the limits are said at start.
- `skip_test.go` (the first report's tests): `TestSubprocess` (runs `cat`) is no longer expected to be reused (rule `exec:`).
- `TestDetUnchangedOnDeterministicPackages`: runs the Go packages that remain (`internal/overlay`, `internal/core`).

## 5. Skip walk after the fixes (GitHub Actions run 44549297298, set `skip-r4`)

WALK_SECTION

## 6. Limits and open points

- The wall-clock rule is strict: any `net/http` server (Date header, idle-connection timestamps) and any logger with timestamps makes the test, and by the prefix rule every later test in the same process, not reusable. A per-site analysis of standard-library uses that are provably relative (for example `net/http`'s idle tracking) could recover some of it; not done.
- Directory mtimes are not keyed for world-writable directories (`/tmp`): a test whose outcome depends on `/tmp`'s mtime alone could be wrongly reused. Known, accepted, documented.
- Clock reads that bypass package `time` (vdso or `clock_gettime` called directly, `syscall.Gettimeofday`) are not seen by the F6 rule; kernel file timestamps compared with a constant are not either. Documented.
- Programs started by a test are never reused, which also removes tests that only run `go` or `git` from reuse.
- `--det` child clock: needs a C compiler and a dynamically linked program; Go programs started by a test keep the real clock (said at start).
- The flaky round (24 projects) was not re-run with the fixed `--det`; nats-server still needs a longer timeout or a non-serial mode to get a `--det` result.
- Python and Node keep their own skip deciders; moving them onto `fenvix_skip_*` is the next step of R1.
