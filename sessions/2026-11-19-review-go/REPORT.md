FIX 17

# R-025 · Review of the Go track (P-021, branch `claude/go-l0`)

Reviewer session, 2026-11-19. Target: `claude/go-l0` at 623ae70 (the report names c22b02f; the two later commits only add hugo shard 1 data). Report under review: fenvix-brain-cli `sessions/2026-11-18-go-l0/REPORT.md` (PARTIAL) and `INTERMEDIATE-1.md`; prompt `prompts/P-021-go-l0.md`; design `docs/GO.md`. Branch of this review: `claude/review-r025` = target + review tests + this file.

Environment: this session's container (4 CPUs, Linux 6.18, Go 1.24.7, Go 1.22.12 and 1.23.12 downloaded through `GOTOOLCHAIN`, strace, gcc, cargo). Labels as in the brain (MEASURED / ESTIMATED / DECLARED / UNKNOWN).

## Verdict: FIX 17

- **Skip with proof: 9 ways to get a wrong reuse** (F1 to F9). In each one the key says "reuse with proof" and the fresh run of the same state fails. That is exactly what the P-021 walk counts as wrong. Most are ordinary Go test idioms: a permission or mtime check, a fixture under `/var` or `~/.cache`, a service container on `localhost`, an expiring test certificate, `-run`/`-skip` on subtests, `-timeout`.
- **`--det`: 4 findings** (D1 to D4).
  - Three idioms are broken by `--det`: plain 10/10 pass, `--det` 10/10 fail.
  - Three entropy sources are uncontrolled in a single goroutine.
  - The Go 1.22 claim is false: the test binary does not build.
- **Numbers: 3 findings** (N1 to N3).
  - The terraform gap to Go's cache is attributed to the network rule. It is mostly the telemetry defect: network explains 2.2 of 29.1 points.
  - 2,246 tests that pass 10/10 plain have no `--det` result. They are counted in "tests 4,099" but appear in no column.
  - The +2.1% median slowdown includes two invalid comparisons. Without them it is +3.9%.
- **Rust boundary: 1 finding** (R1). The whole skip decision is Go code.

The 0 wrong in 386,012 verified reuses is correct as a count (re-derived below). It shows that these 5 repositories, over these commits, on one runner, did not hit a hole. It does not show that the key is sound: none of F1 to F9 is exercised by 50 ordinary commits walked in one unchanging environment.

## How to reproduce (all on `claude/review-r025`)

```bash
cargo build -p fenvix-go --release
cd go && go test ./cmd/fenvix-go -run 'TestR025' -v        # F1-F9, D1-D3 fail; TestR025_Held, TestR025_DetHeld pass
cd .. && python3 harness/go/review_r025_check.py            # N1-N3, R1 (exit 1)
```

Fixtures: `go/testdata/fixtures/review-r025` (skip key: one package per scenario) and `go/testdata/fixtures/review-r025-det` (`--det`). Tests: `go/cmd/fenvix-go/review_r025_test.go`, `review_r025_det_test.go`.

How a skip scenario works:
- Every run is `fenvix-go test --skip-cache=C --skip-verify`: every test runs, and the decision report says whether the key would have reused it.
- A scenario first records a passing run.
- Where it matters, it then shows that an unchanged run is reused, so the key is stable and a later "not reused" would be caused by the change.
- It changes one input and fails if the key says reuse while the fresh outcome is not `passed`.

## Engine tests (MEASURED, this container)

| suite | result |
|---|---|
| `cargo test -p detpy-core -p fenvix-go` | 44 + 6 passed |
| `cd go && go test ./...` at the target head (before the review files) | all 4 packages ok (cmd/fenvix-go 49.5 s); 22 test functions, as reported |
| review held attacks (`TestR025_Held`: embed, `os.Environ` prefix scan, `init()` of a dependency reading a file, `TestMain` reading a file, `-ldflags -X`, `-tags`) | 6/6 caught: the changed test reran |
| review findings (`TestR025_F*`, `TestR025_D*`) | fail as described below |

## 1. Skip with proof: wrong reuses (MEASURED, Go 1.24.7, strace capture)

| # | test | change between record and check | test wrongly reused (fresh outcome) | why the key misses it |
|---|---|---|---|---|
| F1 | `TestR025_F1_DigestAfterRunNotAtRead` | `TestReadsState` reads `testdata/state.txt` = v1. A later test in the package regenerates it to v2. The next commit commits v2. | `TestReadsState` (failed) | `MakeEntry` hashes files after the package run, not the content the test read. The key holds v2, a content this test never saw. |
| F2 | `TestR025_F2_FileMetadata` (4 cases) | `chmod -x` of a script; mtime of a source moved past its generated file; a symlink retargeted between two existing files; a listed regular file replaced by a directory of the same name | `TestScriptIsExecutable`, `TestGeneratedIsFresh`, `TestCurrentLink`, `TestEntryTypes` (all failed) | strace turns `stat`/`lstat`/`statx`/`readlink*` into "exists" only. A listing is the digest of the names only. Mode, mtime, link target and entry type are outside the key. Same hole as R-021 F1/F2 for Node. |
| F3 | `TestR025_F3_InputsOutsideRoots` (3 cases) | a fixture at `/var/lib/...`, `/srv/...`, `~/.cache/...` changes content; the path, given by an unchanged variable, stays the same | `TestOutsideFixture` (failed, 3/3) | `Filter.Keep` is an allowlist: repository, GOMODCACHE, GOROOT, `/etc`, `/usr`, `/lib*`, `/opt`, `$HOME`. `~/.cache` (UserCacheDir) is ignored. Reads anywhere else are dropped silently, and the test stays reusable. `/tmp` is excluded by design (docs), but nothing marks a test that read there. |
| F4 | `TestR025_F4_LoopbackService` | a service on `127.0.0.1` answers differently: a CI service container (postgres, redis), a local mock, docker's socket | `TestLocalService` (failed) | Loopback and the machine's own addresses are "inside", so the test is reusable. The service's state is in no key. AF_UNIX connects are not even recorded. |
| F5 | `TestR025_F5_UDPSendtoOutside` | none: the test sends a datagram to 192.0.2.1:9 with `WriteTo` (`sendto`, verified with strace: 4 bytes sent) | `TestSendsOutside` is reused (rule violation) | "Never reused: a test that connected to an address outside the machine". The strace set has no `sendto`/`sendmsg`, so unconnected UDP is invisible: statsd, syslog, SSDP/mDNS, probes. |
| F6 | `TestR025_F6_WallClock` | none. A test certificate or token in `testdata` has a NotAfter date, and that date passes. | `TestFixtureNotExpired` (failed) | Without `--det` the wall clock is an input of every test and is not in the key. The walk and the documented `--skip-cache` usage run without `--det`. |
| F7 | `TestR025_F7_LoaderEnvironment` | `LD_LIBRARY_PATH` points to another `libfx.so` (cgo) | `TestNative` (failed) | The dynamic loader reads `LD_LIBRARY_PATH`/`LD_PRELOAD` below every hook. They are not in `AlwaysEnv`. The key checks only the old library path, which is unchanged. |
| F8 | `TestR025_F8_NeutralFlags` (3 cases) | the record run had `-skip=TestParent/broken`, then `-run=TestParent/^ok$`; the check run drops it. `-timeout=1s` on a 2 s test. | `TestParent` (failed, twice), `TestTakesTwoSeconds` (interrupted) | `neutralTestFlags` treats `-run`, `-skip` and `-timeout` as neutral. A subtest pattern or a timeout changes what a top-level test does. Go's own cache gets all three right here: it keys `-run` and `-timeout` and does not cache `-skip` (MEASURED, Go 1.24.7). A regression against the baseline the report compares with. |
| F9 | `TestR025_F9_CheckoutLocation` | a second checkout of the same commit with a different `testdata/value.txt` shares the cache (`-trimpath`) | `TestValue` in checkout B (failed) | The key holds absolute paths and the cache file is keyed by import path only. With `-trimpath` both checkouts build the same binary, and B is checked against A's files. This covers worktrees, several CI workspaces on one host, and the planned shared or restored cache. |

Fix directions (for the coordinator):
- F1: hash at first read, or keep strace's read order and store the pre-run digest. Simplest: digest every candidate input before the binary starts, from the previous entry's file list, and compare that.
- F2: key `lstat`/`readlink` by link target, and `stat` by type, size and mode. mtime only where a test reads it (`statx` mask), or document it.
- F3: invert the filter: a denylist of outputs (temp dirs the run created, `/proc`, `/sys`, `/dev`, caches). A read outside the roots makes the test not reusable instead of being dropped.
- F4: treat a connection to a listener the test did not open (another process) as outside. Or require a declared service digest (image plus data), as cassettes would.
- F5: trace `sendto`/`sendmsg` with an address.
- F6: either run skip mode under the virtual clock or put the date in the key when a test read the clock. The core already sees clock reads.
- F7: add `LD_*` to `AlwaysEnv`, plus the loader's resolved path list.
- F8: put `-run`/`-skip` patterns that reach subtests, and `-timeout`, in the key, or never reuse under them.
- F9: key paths relative to the module root and include the root in `static`.

## 2. `--det` (MEASURED, 10 plain runs and 10 `--det` seed-0 runs each)

Fixture `review-r025-det`:

| test | plain (10) | `--det` seed 0 (10) | fingerprints under `--det` |
|---|---|---|---|
| `TestAfterFuncThenSleep` (`AfterFunc(1ms)`, `Sleep(50ms)`, flag set?) | 10 pass | 10 fail | 1 |
| `TestMtimeTTL` (write a file, `Sleep(20ms)`, `time.Since(mtime) ≥ 10ms`?) | 10 pass | 10 fail | 1 |
| `TestChildClock` (`date +%s` vs `time.Now`, within an hour?) | 10 pass | 10 fail | 1 |
| `TestLinknameCheaprand` (`runtime.cheaprand` via linkname, even?) | 4 pass / 6 fail | 6 pass / 4 fail | 2 |
| `TestRawGetrandom` (`getrandom(2)` direct) | 3 / 7 | 6 / 4 | 2 |
| `TestEphemeralPorts` (two listeners sorted by address) | 3 / 7 | 5 / 5 | 2 |
| `TestSelectReady` (documented limit) | 3 / 7 | 7 / 3 | 2 |
| `TestLinknameFastrand`, `TestReflectMapOrder` | random | one outcome, one fingerprint | held |
| `TestSyncPool` (Put, blocking syscall, Get; one goroutine) | 9 / 1 | 9 / 1 in one series, 10 / 0 in another | logged only (rare) |

- **D1. fastwait ignores pending timers** (`TestR025_D1_BrokenByDet/TestAfterFuncThenSleep`). `Sleep` returns at once "when the test started no goroutine", but a pending `AfterFunc` runs `f` in its own goroutine when it fires. The ubiquitous `AfterFunc` (or debounce) then `Sleep` then assert pattern is broken by `--det`. Fix: a test with a pending timer or ticker is not fast-waited, or the virtual clock fires due timers synchronously before `Sleep` returns.
- **D2. Real time leaks next to the virtual clock** (`.../TestMtimeTTL`, `.../TestChildClock`). File timestamps set by the kernel, and the clock of any child process (`date`, git commit dates, a server under test), are real (2026). `time.Now` is virtual (2025-01-01). The docs list `vdso` and `synctest` as not controlled, not these. Cache-TTL and git-based tests mix the two. Fix: at least document this and say it at start. Better: offset the virtual epoch to the real start time for seed 0, so the two clocks stay comparable, or shift `Stat` times.
- **D3. Uncontrolled entropy in a single goroutine** (`TestR025_D2_UncontrolledEntropy`). `runtime.cheaprand` is linkname-exported for `bytedance/gopkg` (Go's own "hall of shame" comment). Raw `getrandom(2)` is what `x/sys/unix.Getrandom` calls. Kernel-chosen ports also vary. Each gives two outcomes over 10 runs of seed 0. Each outcome has the same fingerprint as any event-free test, so the verifier cannot name the source. The docs mention `cheaprand` only for `select`; the other two are not mentioned. Fix: seed `cheaprand` on user goroutines (the report's own Level 1 proposal), record `getrandom` through the existing crypto stream (seccomp or overlay of `x/sys` is not possible, so document it), and list ports as observed, not controlled.
- **D4. Go 1.22: "time and random unavailable, said at start; the rest works" is false** (`TestR025_D3_Go122`).
  - The limits are printed: "control time unavailable…", "control random unavailable…", "control fastwait unavailable…", "go vet turned off".
  - Then the build fails: `testing/zz_fenvix.go:206:14: undefined: time.FenvixNow`. The `t.Deadline()` hook, added after the toolchain check, needs the disabled time group.
  - The CI job never runs 1.22: its loop starts at go1.23.12, and `|| true` hides failures.
  - Go 1.23.12 works here, with vet turned off and said.

"Said at start": only unavailable controls and vet are printed. The Level 1 limits (interleaving, `select`, timer delays) and the uncontrolled sources (D2, D3, UDP, raw syscalls, cgo) appear only in `docs/GO.md`. They are not in the run output.

## 3. Numbers re-derived (`harness/go/review_r025_check.py`, MEASURED from committed data)

Correct as published (data at c22b02f):
- skip table: prometheus 62%/53% vs Go 56%/57%, terraform 28%/27% vs 70%/55%, caddy 38%/24% vs 25%/23%, telegraf 27%/24% vs 31%/54%, hugo 1%/10% vs 1%/42%;
- fenvix verified reuses 386,012 (0 wrong, 8 flaky); Go's verified reuses 382,996 (0 wrong, 12 flaky);
- the no-prefix variant;
- rerun reasons;
- the telegraf telemetry upper bound 28%/56%.

The 8 fenvix "flaky" are graylog ×2 and tail `TestLogRotateCreate` ×6, each 3/3 passing alone. Plausibly flaky, but the classifier has R-022's blind spot: "passes alone" also covers order-dependent wrong reuses.

At the branch head the hugo rows moved (fenvix 11,842 and Go 11,525 verified), because hugo shard 1 data was added after the report.

- **N1. "The gap is the network rule: 61,389 test-transitions …" is not supported.**
  - The data has 66,908 (c22b02f; 67,616 at head).
  - The reason is reported first by `Why` (network is checked before code). Of those transitions, 32,976 also had a code-or-config change of their own.
  - By test time, for terraform: Go reused and fenvix reran 29.1% of all test time. The network rule explains 2.2 points of that. The Go telemetry counters (the defect fixed in c22b02f) explain 19.4 points.
  - With the report's own upper-bound method, terraform becomes at most 48%/46% instead of 28%/27%, and caddy's mean goes from 24% to 32%.
  - The report applies the correction to telegraf only. It explains terraform's gap with the R-002 network example.
- **N2. 2,246 tests that pass 10/10 plain have no `--det` result, and they are in no column.**
  - "Tests 4,099" counts the plain baseline; only 2,024 tests have a `--det` seed-0 result.
  - nats-server: 2,191 missing. The serial `--det` run hits the 10-minute `go test -timeout` after 879 tests, while the parallel plain run finishes.
  - cortex: 55 of 62 missing, cause not established; `--det` reports 8 tests.
  - Another 17 tests pass 10/10 plain but not 3/3 under `--det` (nats-server 15, including 11 failures such as `TestReadloopWarning` "No warning printed"; quic-go 1; temporal 1). The "broken" rule needs failure in 3 of 3, so they are not counted.
  - "Broken by `--det`: 0" and the 38.9% coverage (783 of 2,013) are therefore measured on half the suite. A timeout under serial `--det` is itself a break, as the report's own limit about serialised `t.Parallel` says.
- **N3. The median slowdown of +2.1% includes two invalid comparisons.**
  - nats-server: both arms stopped by the 10-minute timeout (plain 600.0 s, `--det` 601.1 s), so +0.2% is two truncated sums.
  - cortex: `--det` ran 8 tests, plain 66.
  - Over the 21 valid comparisons the median is **+3.9%** (MEASURED from the committed timings, NOISY as labelled).

**Is the comparison with Go's cache fair?**
- The environment is the same: one runner, sequential arms at every commit, the same GOCACHE, and the same per-test weights. The weights come from fenvix's serial, straced fresh run for both arms.
- Two biases remain:
  1. The telemetry defect penalised fenvix on terraform, telegraf and caddy (N1).
  2. Go's reuses are verified against fenvix's fresh outcome (serial `t.Parallel`, strace), not a plain fresh run. A failure that shows only in parallel would not be seen against Go's cache.
- One environment that never changes cannot show the inputs Go's cache ignores, as the report says. Go's cache would be wrong on F1, F3, F4, F6 and F7 too. It is right on F8, where fenvix is not.

## 4. Rust boundary

- **R1. The skip decision is Go, not Rust** (DECISIONS 2026-11-18: "move all engine logic to Rust … shells keep only thin shims").
- Rust (`crates/fenvix-go`) provides:
  - the recorder and fingerprints;
  - the verifier;
  - `derive_seed` and `shuffle_indices`;
  - file digests;
  - trace merge.
- Go implements the rest:
  - the key and decider: `go/internal/skip` (`Entry.Why`, `MakeEntry`, `Absorb`, SHA-256 `Hash` instead of the core's BLAKE3);
  - the strace dependency rules and path filter: `go/internal/strace` (a third implementation, after `strace_deps.py` and Node);
  - the prefix closure and network locality: `cmd/fenvix-go/exec.go`.
- That is about 1,000 lines of decision logic outside the core.
- F1, F3, F5 and F8 sit in exactly this code. A Rust decider shared with Python and Node would be fixed once.
- The "option later: skip decisions on our servers" decision needs this logic in the core too.

## Verdict per claim

| claim | verdict |
|---|---|
| `--det` with a build-time overlay (order, random, map seed, virtual clock, listings) | holds for what it hooks. D1 and D2 break real idioms, D3 leaves single-goroutine entropy, D4 breaks Go 1.22 |
| 0 of 24 documented flaky tests reproduced | correct as stated; the table says 23 ran |
| fingerprint coverage 38.9% pooled | arithmetic correct (783/2,013). It covers 2,013 of 4,099 tests (N2) |
| skip with proof, 0 wrong in 386,012 verified reuses | count correct; key unsound (F1 to F9) |
| `--det` median slowdown +2.1% | +3.9% over valid comparisons (N3) |
| gap to Go's cache on terraform = network rule | not supported (N1) |
