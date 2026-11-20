# GO notes (agent GO, audit P-036)

Audited: `/home/user/audit/engine` (claude/release-1), binary `/home/user/audit/build/opt/bin/fenvix-go`, local
Go 1.24.7, strace 6.8, root, 4 shared cores. Scratch: `/home/user/audit/work/GO/` (modules m1..m5, tc, ver/, logs).
The audit was **stopped by the budget limit** after tasks 1 (versions), most of 2 and 3, the skip probes of 4 and part
of 5. 80 gaps written (GO-001..GO-080). Everything below "Not covered" still has to be done by another session.

## Not covered (exact list, so another session can finish)

**Task 1, versions**
- Run on a real module per toolchain (only the 8-test module m1 was run on 1.21.13, 1.22.12, 1.23.12, 1.24.7,
  1.25.14, 1.26.11, 1.27.4; the wider controls module m3 only on 1.24.7).
- Port determinism (GO-001) on Go 1.25/1.26/1.27 and on a GitHub-hosted runner kernel (only 1.24.7, kernel 6.18,
  `net.mptcp.enabled=1` was run). The engine's own review test `TestR025_D2_UncontrolledEntropy/TestEphemeralPorts`
  was not run here.
- gccgo and TinyGo: read only (GO-040), not run.
- Where the std rebuild lands on a CI without a persisted GOCACHE; size of the overlay build in GOCACHE.

**Task 2, go test flags not probed at all**
`-parallel N` alone (only with `--det-keep-parallel`), `-skip`, `-run` interplay with the plan, `-coverpkg`,
`-o` alone, `-mod=vendor` and vendoring, `-asmflags`, `-pgo`, `-msan`/`-asan`, `-cpu`, `-benchtime`,
`-fuzzminimizetime`, user `-overlay` merge, `-C`, `-modfile`, `-race` together with `--skip-cache`,
`testing/synctest` (Go 1.24 experiment / 1.25), `go.work` workspaces, nested modules, `replace` directives,
generated code (`go generate`, protobuf, mocks: are generator inputs keyed), `CGO_ENABLED=0` versus 1 (only the
default cgo build was run), assembly packages, `unsafe`/linkname users beyond `runtime.nanotime`, plugins,
`TestMain` calling `m.Run` twice (READ only: second run unhooked, `testing.go.txt:138`), `-timeout` against the
virtual clock beyond one run, `-list`, `t.Setenv`/`t.Cleanup` beyond one passing run each.
Probed (results in the gaps): `-race`, `-count`, `-shuffle`, `-p`, `--det-keep-parallel`, `-bench`, `-fuzz`,
`-failfast`, `-short`, `-tags`, `-timeout`, `-cover`, `-coverprofile`, `-c`, `-exec`, `-trimpath`, `-vet=off`,
`-ldflags`, `-gcflags`, `-mod=mod`, `-json`, `-v`, GOFLAGS (`-trimpath`, `-exec`, `-p`, `-shuffle`),
`toolchain` line with GOTOOLCHAIN=auto (works), GOTOOLCHAIN=local with a too-new go.mod (plain go error).

**Task 3, controls not probed**
`--det-epoch`, `--det-tick`, `--det-adapt`, `--det-gomaxprocs`, `--det-disable=<each>`; exploration effect on fs
order and clock (seed != 0) beyond one run; `sync.Pool` after a blocking syscall; `select` among channels made ready
by other goroutines; map order with several goroutines; `net/http` client deadlines (poller); AF_UNIX; DNS through
cgo resolver; proxy on loopback; testcontainers-go / dockertest (Docker daemon not running here); a statically
linked or Go child's clock; `os/user` beyond one read; `time.Local` with `ZONEINFO`.

**Task 4, features not probed**
- The verifier naming a first divergent event for Go: no divergence was ever produced (every pair verified
  identical); the text of a divergence report and whether the site is the user's file:line in that report are unchecked.
- `--skip-verify` beyond the uname case; `--skip-commit`; `--fenvix-dir`; `--skip-capture=hooks` explicitly.
- Wrong-reuse probes not done: go.mod dependency version bump (m4 has uuid v1.5.0 ready, bump to v1.6.0 not run),
  file read only by a Go child, symlink retarget, file mode/owner change, a loopback service outside the run,
  statfs free space, stdin, terminal ioctl, cross-package file written by another package's test.
- Comparison with Go's own cache on a real module by measurement (only the reports' numbers: GO-058).
- Overhead on one real module (plain vs `--det` vs skip cold/warm): **not measured**. github.com/google/uuid and a
  `t.Parallel` module were never cloned. The m2 packages slow1..slow4 (for the `-p 1` slowdown) were created and never run.
- testify, ginkgo/gomega (through `fenvix-go test` and through `ginkgo`), gotestsum, go-junit-report, Bazel rules_go:
  not run (matrix rows `not checked`).

**Task 5, strace**
- Cost of tracing (with vs without strace): not measured.
- `docker run` with the default seccomp profile, Kubernetes, gVisor, Fargate: not run (Docker daemon not running:
  `failed to connect to the docker API at unix:///var/run/docker.sock`). `/proc/sys/kernel/yama/ptrace_scope` does
  not exist on this kernel. Only the "already traced" refusal was run (GO-080).
- `fenvix_backends()` (`crates/fenvix-go/src/lib.rs:563-570` lists `PythonHooks` and `Syscall`): whether
  `Syscall.implemented()` is true was not read.

**Task 6, platforms**: all from code/docs only (GO-041, GO-074, GO-075, GO-076); no arm64 build attempted; build
constraints of the Go sources (`//go:build`) not grepped; the cgo static link of `libfenvix_go.a` for arm64 not tried.

**Task 7, branch `origin/claude/go-l0`**: the 6 commits ahead of release-1 were **not diffed**. Only the reports were
read: REPORT-3 is PARTIAL (S1 waits for walk skip-r9, run 44673909307; GO-059).

Files not read in full: `crates/fenvix-go/src/skip.rs` (only lines 1-60, 228-436 and the function list),
`strace.rs` (lines 20-66 and the function list), `lib.rs` (function list), overlay files `os.go.txt`, `ostime.go.txt`,
`mathrand*.go.txt`, `sysrand.go.txt`, `cryptorand123.go.txt`, `faketime.c.txt`, `timedeps.go.txt`,
`go/internal/core`, `go/internal/session`, the `*_test.go` suites, `harness/go/*.py`, the `go-*.yml` workflows except
the first 40 lines of `go-tests.yml`, brain REPORT.md, INTERMEDIATE-1.md, review REPORT.md, prompt P-021.

## Could not check

- GO-001 on GitHub-hosted runners: the release gate is said green on Go 1.26 there; whether their kernel has MPTCP on
  (which decides if the port control works) is unknown from here.
- GO-041 on a real Alpine container (no container runtime); evidence is `ldd` only.
- GO-047 (sysinfo) to an actual wrong reuse: RAM cannot be changed here.
- GO-058 numbers: taken from the session reports, not re-measured; skip-r9 has not reported.
- Whether a kernel upgrade (uname release) is a realistic cache-sharing path: the cache has no machine identity in
  its key except path, process attributes and files read, so GO-046 applies whenever the directory is restored on
  another host.

## Contradictions and false claims found

1. docs/GO.md:47 "a listener on port 0 gets a port from the test's deterministic stream": false for TCP on
   Go 1.24.7 with MPTCP (GO-001).
2. docs/GO.md:17 "Go 1.23 to 1.26: every control", RELEASE-1.md "Go 1.22+": Go 1.27, the current line, loses the
   maps control (GO-034); CI tests stop at 1.26.0.
3. release/install-image.sh:5 "fenvix-go ... self-contained": dynamically linked to glibc and libgcc (GO-041); it also
   needs the `go` toolchain, `strace`, a C compiler (clock library), `unshare` and root (pid).
4. "reused with proof": proof covers keyed inputs only; uname is unkeyed (GO-046), a lucky pass of a random test is
   reused (GO-048), a ptrace refusal fails the suite (GO-080).
5. `verify` prints "covered by Level 0: N" for tests whose uncontrolled inputs differed, also on toolchains where
   controls are reported unavailable (GO-002, ver/go1.21.13, go1.22.12, go1.27.4 logs).
6. docs/GO.md:53 still says "`--det` does not change GOMAXPROCS" two lines after the sched row says it sets 1.
7. `fenvix-go --help` lists `--det-disable` controls without `sched` and omits three flags (GO-042).
8. docs/GO.md:3 says "Branch claude/go-l0": the doc was copied to release-1 unchanged.

## Evidence appendix (commands and trimmed real output, by gap id)

All commands were run with `. /home/user/audit/work/GO/env.sh` (FENVIX_HOME=/home/user/audit/build/opt, own
GOCACHE and FENVIX_GO_CACHE under the scratch folder). Full outputs are the files named.

**GO-001** `cd m3; fenvix-go test --det -v -run TestNetLoopback ./...` twice, then with `GODEBUG=multipathtcp=0`:
```
OBS httptest url=http://127.0.0.1:42345   | OBS httptest url=http://127.0.0.1:34033
OBS listen0=0.0.0.0:46311                 | OBS listen0=0.0.0.0:45041
--- multipathtcp=0 (both runs)
OBS httptest url=http://127.0.0.1:24763   OBS listen0=0.0.0.0:15040   OBS listen127=127.0.0.1:16303
```
**GO-002..GO-016** `m3/det1.out`, `det2.out` (TZ=Asia/Tokyo LANG=it_IT.UTF-8 FOO=bar), `det3.out`; `fenvix-go verify
t1.jsonl t3.jsonl` and `t1.jsonl t2.jsonl` both: `covered by Level 0: 18  not covered: 0  missing: 0`. Diff det1/det3:
gettimeofday_sec 1795163805 vs 1795163810; new file mtime 2024-12-31T23:59:59Z vs 2025-01-01T00:00:00Z; ports; child
sh "7 d1 93 7b 5d vm" vs "7 ab 56 e6 75 vm"; child python 0.433.. vs 0.512... Under --det: `host=vm pid=1 ppid=0`,
`gomaxprocs=1 numcpu=4`, `udp sendto outside err=<nil>`, `raw connect outside err=operation now in progress`,
`rawgetdents=[beta 9 alpha zeta Mid 10]`, `gettimeofday_year=2026 clock_gettime_year=2026`.

**GO-017, GO-018, GO-019** `m2/det1.out`: `--- FAIL: ExampleRev_clock ... got: false true want: true true`;
`--- FAIL: TestBarrier (6.04s) a: partner never arrived`; `OBS counter=800000 --- PASS: TestCounterRace` (plain:
`lost updates: 639401`).

**GO-019, GO-071** race counts (m2): plain binary x50: 48 pass / 2 fail TestCounterRace, `first=b` 50/50;
`-test.count=300` 1 lost update; TestCheckThenAct 1 oversold in 20000. `--det` seed 0 x30: identical
(`counter=800000 first=b sold=1`), verify of 4 traces identical. Seeds 1..40: `first=a` 21, `first=b` 19,
counter=800000 40/40; seeds 41..70: 0 failures of TestCounterRace/TestCheckThenAct.

**GO-020..GO-033** `m2` runs in the session log: `-shuffle=5` and `-p 4` no message; `-count=3` trace 6 records, 2 node
ids; `-exec` exit 2; `-c` binary runs plain; `-trimpath` events at `time/zz_fenvix.go:79`, `TestP1 (0.30s)`;
cv3.jsonl `"why":"env:GOCOVERDIR"`; cw3.jsonl `"why":"code-or-config"`; `-bench`: `BenchmarkClock 1000000 1527 ns/op`;
`-json` third skip run: `{'Action':'pass','Test':'TestTable','Elapsed':0}` with no subtest events.

**GO-034..GO-039** `work/GO/ver/<version>/log.txt` (det1/det2/skip1/skip2 walls, control lines, OBS diffs, verify).
Walls (s): 1.21.13 44.1/1.0/0.8/0.7; 1.22.12 46.5/1.3/0.9/0.8; 1.23.12 41.9/1.4/0.8/0.7; 1.24.7 (warm) 1.0/1.0/0.9/1.2,
cold det 37.7 after a 38.3 s cold plain run; 1.25.14 35.9/0.7/23.6/0.7; 1.26.11 21.5/1.3/45.3/1.5; 1.27.4
52.0/2.0/49.2/1.1. All MEASURED, NOISY (other agents on the same 4 cores). Reuse on run 2: 2 of 8 on 1.21 and 1.22,
6 of 8 on 1.23-1.27.

**GO-046** `m5/h` (see gap): plain under `unshare --uts`: `unexpected host "otherbox"`, `domain "changed"` FAIL; fenvix
skip twice: both `reused with proof`, exit 0; `--skip-verify`: `2 of 2 tests reusable ...; 2 reuse(s) disagreed with
the fresh run`.

**GO-048** `m5/c`; **GO-049** `m5/d` (outputs quoted in the gaps).

**GO-051..GO-056** `work/GO/probe.py`, output `work/GO/probe1.log`. Probes that behaved correctly (changed input =>
dependent test rerun): testdata file, file read by a `cat` child, env var read with os.Getenv, env var read by a
shell child, os.Stat target deleted, os.Open of a missing file later created, Glob/listing, go:embed file, source of an
imported package, build tags, a file under $HOME. Correct reuse: an unused function changed and a comment-only change
(test binary identical). Wrong reuse: host name (GO-046).

**GO-060** PATH without strace, 3 runs: `skip: strace not found ... nothing is reused`, `0 of 8`, why `no-capture`.
**GO-080** output quoted in the gap (task output of the ptrace-refused run).

**Things that worked (for the lead)**: `-race`, `-tags`, `-short`, `-failfast`, `-ldflags`, `-gcflags`, `-vet=off`,
`-mod=mod`, `-list`, TestMain, t.Setenv, t.TempDir, t.Cleanup, table tests, cgo (default build), `toolchain` line in
go.mod with GOTOOLCHAIN=auto, materialised toolchains under `$FENVIX_GO_CACHE/toolchains`, the clear message when
strace is absent, `--skip-real-clock` reporting the expired fixture, `--det-seed` repeatability.
