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

Linux only (the product runs on our machines). Go 1.23 to 1.26: every control. Go 1.22 (end of life): time and random unavailable, reported at start.

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
| crypto | `crypto/rand` and every standard crypto package that draws from the system source (keys, nonces, TLS): a deterministic stream per test. Test builds only | cgo crypto (BoringCrypto), `/dev/urandom` opened directly |
| maps | map iteration order and hash seeds: the per-process hash key (`alginit`, read from the raw environment before the runtime parses it) and `runtime.rand` on user goroutines (map seeds, iteration start points, including maps the compiler places on the stack) are derived from the seed; restarted per test. Side effect: anything else that calls `runtime.rand` from a user goroutine (`hash/maphash` seeds, the unseeded `math/rand` source when random is off) is deterministic too | maps used by several goroutines at once: deterministic only if the goroutines interleave the same way (Level 1). `select` choice among ready channels (`cheaprand`): not controlled |
| time | `time.Now`, `time.Since`, `time.Until`: virtual clock, one tick per read (default 1 µs, `--det-tick`), adaptive like Python and Node (`--det-adapt`); the wall clock restarts at the epoch (2025-01-01T00:00:00Z, `--det-epoch`) for every test; the monotonic clock never goes backwards. `time.Sleep` advances the clock by its duration. Timers and tickers (`NewTimer`, `After`, `AfterFunc`, `NewTicker`, `Tick`, `Reset`, `Stop`) still fire after their real delay and then move the clock to their virtual due time, so elapsed times are exact and the same on every run. Calls from package `testing` (timeouts, durations) keep the real clock | the real delays themselves (when a timer fires relative to other goroutines: Level 1); deadlines inside the network poller (`SetDeadline` keeps real time, its duration is computed from the virtual clock); `testing/synctest` bubbles keep their own fake clock; code calling the `vdso` directly |
| fastwait | `time.Sleep` returns at once when the test started no goroutine (the Python and Node rule); otherwise it waits for real so the goroutines it waits for can run | |
| fs | `(*os.File).Readdir`, `Readdirnames`, `ReadDir`: entries sorted by name (`os.ReadDir`, `filepath.WalkDir`, `fs.ReadDir` already sort) | raw `syscall.Getdents` |
| net | `connect()` to anything but loopback is refused with an error that says so; loopback port 53 (a local DNS stub) and an HTTP(S)/SOCKS proxy configured on loopback count as outside; AF_UNIX is allowed | UDP `sendto` without connect; raw `syscall.Connect`; cgo resolvers; record/replay (cassettes) is not built for Go yet |

**GOMAXPROCS and the scheduler (Level 1: measured, not solved).** `--det` does not change GOMAXPROCS (`--det-gomaxprocs=N` sets it; the trace records it). Goroutine interleaving, `select` among ready channels, and the moment a timer fires relative to other goroutines are not controlled. Events carry a thread number (goroutines numbered by first event in the test), so the verifier names an interleaving difference as a `thread` divergence (fixture `TestInterleaving`).

## Skip with proof (`--skip-cache=DIR`)

Unit: a top-level test. A test is reused (not run; reported as `--- PASS` with `fenvix: reused with proof`) only when all of this is unchanged since its last passing run:

- **code executed**: the compiled test binary. Its digest covers the package, its test files, every imported package, the Go toolchain and runtime, GOOS/GOARCH, build tags and flags, statically linked cgo objects and the fenvix overlay;
- **test configuration**: test flags that change behaviour (`-short`, `-cpu`, custom flags), `--det` controls, seed, epoch and tick;
- **runtime identity**: Go version, GOOS/GOARCH, CGO_ENABLED; every shared library, tzdata or certificate file the run read (strace);
- **files read**: content digest of each file the test read, through package `os` (hooks) and through anything else, child processes included (strace -f with per-test markers). Paths stat'ed must still exist, paths probed missing must still be missing, directories listed must list the same names;
- **environment variables**: those the test read (hook on `syscall.Getenv`, which also sees the reads of package `time` and `net` below package `os`), plus a fixed list read by the Go runtime and libc (`GODEBUG`, `GOGC`, `GOMAXPROCS`, `GOMEMLIMIT`, `GOTRACEBACK`, `TZ`, `ZONEINFO`, `LANG`, `LC_*`, proxies, `SSL_CERT_*`). A test that started another program depends on the whole environment;
- **prefix rule** (shared process state): a test also depends on everything that package initialisation, `TestMain` and the tests before it in the same process read. This includes tests reused in that run, through their recorded inputs. This covers a configuration loaded once by an earlier test, and anything else in memory;
- **never reused**: a test that failed or was skipped, a test that connected to an address outside the machine (or to a loopback proxy), or a test recorded without a dependency capture.

Capture: `strace` when installed (complete: child processes, cgo, files read below package `os`), otherwise `hooks` (package-level hooks only; gaps listed above). `--skip-capture` chooses. In skip mode `t.Parallel` is serialised by default, so per-test attribution is exact (`--det-keep-parallel` restores parallelism).

### Compared with Go's own test cache

Go caches per package: a package's result is reused when the test binary and the cacheable flags are the same. "Tests that open files within the package's module or that consult environment variables only match future runs in which the files and environment variables are unchanged" (DECLARED, `go help test`, Go 1.24.7). What it does not see, and the fenvix key does (each case has a test in `cmd/fenvix-go/skip_test.go`):

- files outside the module (`/etc/...`, a path from an environment variable), files read by child processes, files read below package `os`;
- environment variables read below package `os` (package `time` reads `TZ` through `syscall.Getenv`). `TestGoTestCacheMissesWhatTheKeySees` shows `go test` reusing its result after `TZ` and a child-read file changed (MEASURED, Go 1.24.7);
- the network: a package that reached an outside service is reused;
- granularity: one changed input reruns the whole package. fenvix reruns from the first test that depends on it, and tests before it in the package are reused.

Blacksmith's Go test cache is off by default because it is "only safe for hermetic tests" (DECLARED, quoted in prompt P-021; to be read in full before any publication).

## Limits

- Linux only.
- Examples (`ExampleXxx`), benchmarks and fuzz seed corpora are not fingerprinted and are never skipped (they always run).
- A panicking test ends the test binary; the trace records it as `interrupted`.
- Under `--det` the packages run one at a time; a suite that relies on packages running in parallel (shared external resource with locking) is slower, not broken.
- The overlay rebuilds the standard library and every dependency once per toolchain and fenvix version (Go's build cache keeps it); measured cost in the report.
