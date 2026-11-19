# fenvix-go: the Go shell (Level 0 and skip with proof for `go test`)

Branch `claude/go-l0` (P-021). Code: `crates/fenvix-go` (C ABI over the Rust core) and `go/` (the `fenvix-go` command).

## Build and use

```bash
cargo build -p fenvix-go --release          # target/release/libfenvix_go.a
cd go && go build -o fenvix-go ./cmd/fenvix-go
fenvix-go test --det ./...                  # seed 0: source order, trace in .fenvix/go-trace-0.jsonl
fenvix-go test --det --det-seed=7 ./...     # exploration: shuffled order and other seeds
fenvix-go verify a.jsonl b.jsonl            # names the first diverging event (same verifier as Python and Node)
fenvix-go test --skip-cache=.fenvix/skip ./...                 # skip with proof
fenvix-go test --skip-cache=.fenvix/skip --skip-verify ./...   # run everything, check every reuse
```

Linux only (the product runs on our machines). Go 1.23 to 1.26: every control. Go 1.22 (end of life): the time, fastwait and random controls are unavailable, and getrandom(2) through `syscall.RawSyscall` is not controlled; all four are reported at start, the test binary builds and every other control works (review R-025 D4 found the build broken; CI now runs 1.22 and fails on a build error).

## How it works

`fenvix-go test` runs `go test -exec "fenvix-go exec" -overlay <overlay.json> -count=1 [-p 1]`.

1. **Build-time overlay of the standard library** (`go/internal/overlay`). Go's `-overlay` replaces source files at build time, including files of the standard library. fenvix-go adds one file to a few standard packages and patches a few functions at stable anchors (function headers). The test binary is the customer's code compiled against this patched standard library. Nothing in the customer's repository changes.
   - Each patch belongs to a group. If an anchor is missing in a toolchain, only that group and the controls that need it are disabled, and the reason is printed. The group `core` (testing hook) is required.
   - Go refuses overlays of files under `GOMODCACHE`, where `go` puts toolchains it downloads for a `go.mod` that needs a newer Go. fenvix-go links such a toolchain (hard links) into its cache and runs it with `GOTOOLCHAIN=local`.
   - Go before 1.24: `go vet` cannot read files an overlay adds, so fenvix-go turns vet off there and says so.
2. **Shared state.** The clock, seeds, event buffer and dependency buffer live in package `syscall` (reachable from every hooked package without import cycles). The control bits and the deterministic map source live in package `runtime` (the runtime forbids heap allocation, so only allocation-free code is there).
3. **Test runner hook** (`testing`). Before the top-level tests run, the test binary sends their names to `fenvix-go exec` over a pipe. The answer is the order (seed 0: source order; otherwise the core's `shuffle_indices`), each test's seed (the core's `derive_seed(seed, "<pkg>::<Test>")`) and the tests to leave out (reused by the skip cache). Each test is framed by begin/end records in an events file. Its events go to the Rust recorder through cgo: the same BLAKE3 hash chain and JSONL trace as Python and Node. Two marker syscalls let strace attribute file reads to the test.
4. **Packages** run one at a time under `--det` (`-p 1`), in sorted import-path order (seed 0) or the core's shuffle. Partial traces (one per package) are merged by the core in execution order.

Trace header meta: `runtime=go`, `runtime_version`, `runner=go test`, `seed`, `controls`, `goos`, `goarch`, `gomaxprocs`, `epoch_ns`, `tick_ns`, `overlay` (digest), `package` (per part). Node ids: `<import path>::<TestName>` (top-level tests; subtests belong to their parent).

## Controls (`--det`)

| control | what is controlled | not controlled |
|---|---|---|
| order | top-level tests in source order (seed 0) or the core's shuffle; packages one at a time, sorted or shuffled; Go's own `-shuffle` is replaced | subtests keep their order inside the parent (deterministic already); benchmarks, examples and fuzz seeds run as Go runs them |
| serial | `t.Parallel()` is a no-op: tests run one at a time, in the order above | a test that needs two parallel subtests to talk to each other would hang (`--det-keep-parallel` restores parallelism) |
| random | `math/rand` and `math/rand/v2` global sources: seeded per test; names from `os.CreateTemp`, `os.MkdirTemp`, `t.TempDir()` | sources the code creates itself (`rand.New(rand.NewSource(time.Now()...))` gets the virtual clock, so it is deterministic too) |
| crypto | `crypto/rand` and every standard crypto package that draws from the system source (keys, nonces, TLS): a deterministic stream per test; getrandom(2) called through `syscall.Syscall*`/`RawSyscall*` (`golang.org/x/sys/unix.Getrandom`): the same per-test stream (R-025 D3). Test builds only | cgo crypto (BoringCrypto), `/dev/urandom` opened directly, getrandom from assembly or cgo |
| maps | map iteration order and hash seeds: the per-process hash key (`alginit`, read from the raw environment before the runtime parses it) and `runtime.rand` on user goroutines (map seeds, iteration start points, including maps the compiler places on the stack) are derived from the seed; restarted per test. Side effect: anything else that calls `runtime.rand` from a user goroutine (`hash/maphash` seeds, the unseeded `math/rand` source when random is off) is deterministic too | maps used by several goroutines at once: deterministic only if the goroutines interleave the same way (Level 1). `runtime.cheaprand` on user goroutines (the `select` choice among ready channels, semaphores, linkname users such as bytedance/gopkg) uses the same source since R-025 D3; `select` among channels made ready by other goroutines still depends on the interleaving |
| time | `time.Now`, `time.Since`, `time.Until`: virtual clock, one tick per read (default 1 µs, `--det-tick`), adaptive like Python and Node (`--det-adapt`); the wall clock restarts at the epoch (2025-01-01T00:00:00Z, `--det-epoch`) for every test; the monotonic clock never goes backwards. `time.Sleep` advances the clock by its duration. Timers and tickers (`NewTimer`, `After`, `AfterFunc`, `NewTicker`, `Tick`, `Reset`, `Stop`) still fire after their real delay and then move the clock to their virtual due time, so elapsed times are exact and the same on every run. Calls from package `testing` (timeouts, durations) keep the real clock | the real delays themselves (when a timer fires relative to other goroutines: Level 1); deadlines inside the network poller (`SetDeadline` keeps real time, its duration is computed from the virtual clock); `testing/synctest` bubbles keep their own fake clock; code calling the `vdso` or `clock_gettime` directly; file access and change times through `Sys()`; the clock of statically linked programs a test starts (Go programs) |
| real time next to the virtual clock | file modification times from `Stat`, `Lstat` and `File.Stat` are moved by the offset between the virtual and the real clock at the start of the test, so a file written during the test is as old on the virtual clock as in real time since the test started; programs the test starts get the same offset through a preloaded library (built once with the C compiler; dynamically linked programs: `date`, git...). R-025 D2 | without a C compiler, child processes keep the real clock (said at start) |
| fastwait | `time.Sleep` returns at once when the test started no goroutine and no timer of the test (`AfterFunc`, `NewTimer`, a ticker) is due before the sleep ends (R-025 D1: an `AfterFunc` callback runs in its own goroutine when it fires); otherwise it waits for real | a stopped ticker still counts as due (the sleep waits: slower, not wrong) |
| fs | `(*os.File).Readdir`, `Readdirnames`, `ReadDir`: entries sorted by name with seed 0 (`os.ReadDir`, `filepath.WalkDir`, `fs.ReadDir` already sort); with an exploration seed, a permutation derived from the test's seed | raw `syscall.Getdents` |
| net | `connect()` to anything but loopback or the machine's own interface addresses is refused with an error that says so; loopback port 53 (a local DNS stub) and an HTTP(S)/SOCKS proxy configured on loopback count as outside; AF_UNIX is allowed | UDP `sendto` without connect; raw `syscall.Connect`; cgo resolvers; record/replay (cassettes) is not built for Go yet |
| ports | a listener on port 0 (TCP or UDP) gets a port from the test's deterministic stream (10000-29999); a port in use is skipped (R-025 D3) | after 32 ports in use the kernel chooses; client-side ephemeral ports |

**Said at start.** Every `--det` run prints the controls unavailable on the toolchain, the optional hooks that did not apply, and this list of what `--det` does not control: goroutine interleaving, real timer delays, `select` among channels made ready by other goroutines, `testing/synctest` bubbles, poller deadlines, clock reads through the vdso or raw syscalls, the clock and entropy of child processes and cgo code, file timestamps (moved, see above).

| sched | goroutine scheduling (Level 1 for goroutines): the test binary runs with one P (`GOMAXPROCS=1` unless `--det-gomaxprocs` is given), no signal-based preemption (`GODEBUG=asyncpreemptoff=1`), GC entirely inside its stop-the-world pause (`gcstoptheworld=1`), and sysmon's time slice stretched from 10 ms to 500 ms: goroutines switch at their own scheduling points (channel operations, locks, syscalls, `Gosched`). With an exploration seed the runqueue's runnext choice comes from the seed. | runtime background goroutines (scavenger, sysmon wakeups, timers) can still enter the run queue at a real-time-dependent moment; the netpoller and real timer delays decide when a goroutine blocked on I/O or a timer becomes runnable; a spin loop is preempted after 500 ms. Measured residual in REPORT-2 |

**GOMAXPROCS and the scheduler (before the sched control: measured, not solved).** `--det` does not change GOMAXPROCS (`--det-gomaxprocs=N` sets it; the trace records it). Goroutine interleaving, `select` among ready channels, and the moment a timer fires relative to other goroutines are not controlled. Events carry a thread number (goroutines numbered by first event in the test), so the verifier names an interleaving difference as a `thread` divergence (fixture `TestInterleaving`).

**Exploration (seed ≠ 0).** Besides the order and every seeded source, an exploration seed also moves the clock: the epoch anywhere in the year after 2025-01-01 and the tick between 0.5 and 10 µs, both derived from the seed (`--det-epoch`/`--det-tick` override). Directory listings are shuffled with the test's seed. Seed 0 keeps the fixed epoch, a 1 µs tick and sorted listings. So clock- and listing-dependent tests can be found by exploration and replayed by their seed, like order-dependent ones.

**Test deadline.** `t.Deadline()` comes from the runner's real clock; under `--det` it is moved to the virtual clock (virtual now plus the real time remaining), so arithmetic between it and `time.Now()` stays meaningful (found on rclone).

## Skip with proof (`--skip-cache=DIR`)

The key, the decision and the cache are in the Rust core (`crates/fenvix-go/src/skip.rs`, strace parsing in `strace.rs`); the Go shell runs the test binary and hands over what it observed (review R-025 R1). Unit: a top-level test. A test is reused (not run; reported as `--- PASS` with `fenvix: reused with proof`) only when all of this is unchanged since its last passing run:

- **code executed**: the compiled test binary, identified by its Go content ID (the machine code, with the build ID removed: what Go's own test cache keys on). It covers the package, its test files, every imported package, the Go toolchain and runtime, GOOS/GOARCH, build tags and flags, statically linked cgo objects and the fenvix overlay;
- **test configuration**: every test flag except the presentational ones (`-v`, `-paniconexit0`, `-testlogfile`, `-outputdir`, `-gocoverdir`, `-fullpath`): `-run`, `-skip`, `-timeout`, `-count` and `-shuffle` are keyed (R-025 F8); `--det` controls, seed, epoch and tick; **the module root** (two checkouts never share results: F9);
- **runtime identity**: Go version, GOOS/GOARCH, CGO_ENABLED; every shared library, tzdata or certificate file the run read (strace);
- **files**: everything the test and its child processes observed, anywhere on the machine (F3): the content of files read; the type, mode, size and mtime of paths stat'ed or probed, or their absence; a symlink's target (`lstat`, `readlink`); the names and entry types of directories listed (F2). Directory mtimes are keyed except for world-writable scratch directories (`/tmp`). Values are taken **before the test binary starts** (F1); an input whose value the run itself changed (written, renamed, chmod'ed, an entry created in it) and that had no pre-run value makes the test run again next time. Not inputs: the run's own outputs (a path whose first access created or truncated it, everything under a directory the run created), `/proc/self`, devices, fenvix's and Go's working state (session, skip cache, GOCACHE, the toolchain's telemetry counters, the test binary's work directory). Other `/proc` files change by themselves: a test that read one is not reusable;
- **environment variables**: those the test read, plus a fixed list read by the Go runtime and libc (`GODEBUG`, `GOGC`, `GOMAXPROCS`, `GOMEMLIMIT`, `GOTRACEBACK`, `TZ`, `ZONEINFO`, `LANG`, `LC_*`, proxies, `SSL_CERT_*`, `HOME`, `TMPDIR`, `PATH`), and the families the dynamic loader and libc read: `LD_*`, `GLIBC_*`, `MALLOC_*` (F7);
- **the wall clock** (F6): a time read from the clock carries a monotonic reading; arithmetic between such times (durations, deadlines) does not depend on the date. When the code uses the wall part of one, a comparison with a fixed time (`After`, `Before`, `Compare`, `Equal`: a certificate's NotAfter, a token's expiry) is recorded and re-evaluated against the current clock; any other use (formatting, `Unix()`, `Sub` with a fixed time; `net/http` servers and loggers with timestamps do this) makes the test not reusable;
- **prefix rule** (shared process state): a test also depends on everything that package initialisation, `TestMain` and the tests before it in the same process observed, reused tests included through their recorded inputs;
- **never reused**: a test that failed or was skipped; a test that connected or sent a datagram (`sendto`, `sendmsg`: F5) to an address outside the machine, to a loopback port or unix socket the run did not open itself (a service container, a local database, docker's socket: their state is in no key, F4), or to a loopback proxy; a test that started another program (its clock and entropy are invisible); a test recorded without the strace capture.

Capture: `strace` (complete: child processes, cgo, files read below package `os`). Without strace the hooks alone cannot see every input: decisions are reported, nothing is reused (said at start). In skip mode `t.Parallel` is serialised by default, so per-test attribution is exact (`--det-keep-parallel` restores parallelism).

The cost of these rules is a lower reuse rate than the earlier key; it is measured by rule in the session report (`harness/go/aggregate.py skip` prints the rerun reasons and the time Go's cache reused and fenvix ran, by reason).

### Compared with Go's own test cache

Go caches per package: a package's result is reused when the test binary and the cacheable flags are the same. "Tests that open files within the package's module or that consult environment variables only match future runs in which the files and environment variables are unchanged" (DECLARED, `go help test`, Go 1.24.7). What it does not see, and the fenvix key does (each case has a test in `cmd/fenvix-go/skip_test.go`):

- files outside the module (`/etc/...`, a path from an environment variable), files read by child processes, files read below package `os`;
- environment variables read below package `os` (package `time` reads `TZ` through `syscall.Getenv`). `TestGoTestCacheMissesWhatTheKeySees` shows `go test` reusing its result after `TZ` and a child-read file changed (MEASURED, Go 1.24.7);
- the network: a package that reached an outside service or a local service container is reused;
- the wall clock (an expired test certificate), the loader environment (`LD_LIBRARY_PATH`), file metadata. Go's cache keys `-run` and `-timeout` and does not cache `-skip`; fenvix keys all three since R-025 F8;
- granularity: one changed input reruns the whole package. fenvix reruns from the first test that depends on it, and tests before it in the package are reused.

Blacksmith's Go test cache is off by default because it is "only safe for hermetic tests" (DECLARED, quoted in prompt P-021; to be read in full before any publication).

## Limits

- Linux only.
- Examples (`ExampleXxx`), benchmarks and fuzz seed corpora are not fingerprinted and are never skipped (they always run).
- A panicking test ends the test binary; the trace records it as `interrupted`.
- Under `--det` the packages run one at a time; a suite that relies on packages running in parallel (shared external resource with locking) is slower, not broken.
- The overlay rebuilds the standard library and every dependency once per toolchain and fenvix version (Go's build cache keeps it); measured cost in the report.
