package main

// Review R-025b (last review of the Go track, target claude/go-l0 at 05a7dfa):
// new attacks on `fenvix-go test --skip-cache`, written against the fixes for
// R-025 and the virtual-day clock of skip mode.
//
// Fixture: testdata/fixtures/review-r025b. Same method as review_r025_test.go:
// every run is --skip-verify (every test runs; the decision report says
// whether the key would have reused it). A test here FAILS when it finds a
// wrong reuse (the key says reuse, the fresh run of the same state does not
// pass); it passes when the key holds.
//
// Run: cd go && go test ./cmd/fenvix-go -run 'TestR025b' -v

import (
	"encoding/json"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
	"unsafe"
)

func newR025b(t *testing.T, pkg string, env ...string) *r025 {
	t.Helper()
	if _, err := exec.LookPath("strace"); err != nil {
		t.Skip("strace not installed: the review targets the strace capture (the walk's)")
	}
	return &r025{t: t, dir: copyFixture(t, "review-r025b"), cache: filepath.Join(t.TempDir(), "cache"),
		env: append([]string{"GOFLAGS="}, env...), pkg: pkg}
}

// sameUTCDay skips a clock scenario that would cross 00:00 UTC (the day is in
// the key, so a crossing would hide the finding, not refute it).
func sameUTCDay(t *testing.T, d time.Duration) {
	now := time.Now().UTC()
	if now.Add(d).Day() != now.Day() {
		t.Skip("too close to 00:00 UTC: the scenario would cross the day in the key")
	}
}

// buildHelpers builds ../clockprint twice: with cgo (dynamically linked) and
// without (statically linked).
func buildHelpers(t *testing.T, dir string) {
	t.Helper()
	for _, b := range []struct{ out, cgo string }{{"clockprint", "1"}, {"clockprint-static", "0"}} {
		cmd := exec.Command("go", "build", "-o", filepath.Join("clockprint", b.out), "./clockprint")
		cmd.Dir = dir
		cmd.Env = append(os.Environ(), "CGO_ENABLED="+b.cgo, "GOFLAGS=")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Skipf("cannot build the helper (cgo=%s): %v\n%s", b.cgo, err, out)
		}
	}
}

// C1. File age under the virtual-day clock (REPORT-2 section 3, D2 mechanism
// (1)): the mtime a test sees is shifted by (virtual - real) at test start,
// so time.Since(mtime) is the real time since the file was written. Nothing
// in the key moves during the UTC day.
func TestR025b_C1_FileAgeIsRealTime(t *testing.T) {
	sameUTCDay(t, 30*time.Second)
	r := newR025b(t, "clockmtime")
	now := time.Now()
	os.Chtimes(r.path("clockmtime/testdata/stamp"), now, now)
	r.record([]string{"TestStampIsFresh"})
	r.mustReuse("TestStampIsFresh")
	time.Sleep(4 * time.Second) // the ttl is 3 s; no file, flag or variable changes
	r.noWrongReuse("4 s later, same UTC day, nothing changed", "TestStampIsFresh")
}

// C2-C4. Wall-clock readings the virtual clock does not reach, compared with
// time.Now: a dynamically linked Go helper (keyed as a reusable child, but the
// Go runtime reads the clock through the vDSO, not libc, so LD_PRELOAD does
// not move it), C code through cgo, a raw clock_gettime system call. The
// tolerance is set so that the record run passes; 3 s later the difference
// has grown by 3 s. C5 (held): package-level time.Now in a dependency's init.
func TestR025b_C2_RealClockBesideVirtual(t *testing.T) {
	sameUTCDay(t, 60*time.Second)
	r := newR025b(t, "clockreal")
	buildHelpers(t, r.dir)
	now := time.Now().UTC()
	midnight := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	// the record run sees a difference of (now - 00:00 UTC) plus up to a few
	// seconds of build and start-up: give it 15 s
	tol := now.Sub(midnight) + 15*time.Second
	os.WriteFile(r.path("clockreal/testdata/limit.txt"), []byte(strconv.FormatInt(int64(tol), 10)+"\n"), 0o644)
	tests := []string{"TestGoHelperClock", "TestCgoClock", "TestRawSyscallClock", "TestInitClock"}
	r.record(tests)
	// wait until the tolerance is exceeded: no input changes
	time.Sleep(time.Until(midnight.Add(tol)) + 2*time.Second)
	got := r.run()
	for _, n := range tests {
		d := got[n]
		t.Logf("%s: reuse=%v fresh=%s why=%q", n, d.Reuse, d.Fresh, d.Why)
		if d.Reuse && d.Fresh != "passed" {
			t.Errorf("WRONG REUSE (same UTC day, nothing changed): %s reused with proof, fresh run %s", n, d.Fresh)
		}
	}
	if d := got["TestInitClock"]; d.Fresh != "passed" {
		t.Errorf("held attack: init-time clock is not virtual: %+v", d)
	}
}

// C6 (held). A statically linked helper is never reused (exec:).
func TestR025b_C6_StaticHelperNotReused(t *testing.T) {
	r := newR025b(t, "clockstatic")
	buildHelpers(t, r.dir)
	r.record([]string{"TestStaticHelper"})
	d := r.run()["TestStaticHelper"]
	if d.Reuse || !strings.HasPrefix(d.Why, "exec:") {
		t.Errorf("static helper: %+v, want a rerun with reason exec:", d)
	}
}

// C7 (held). The local zone: TZ (keyed by name) and /etc/localtime (keyed by
// content through strace).
func TestR025b_C7_TimeZone(t *testing.T) {
	t.Run("TZ", func(t *testing.T) {
		r := newR025b(t, "tz", "TZ=")
		r.record([]string{"TestLocalIsUTC"})
		r.mustReuse("TestLocalIsUTC")
		r.env = append(r.env, "TZ=Asia/Tokyo")
		r.noWrongReuse("TZ=Asia/Tokyo", "TestLocalIsUTC")
	})
	t.Run("/etc/localtime", func(t *testing.T) {
		target, err := os.Readlink("/etc/localtime")
		if err != nil || syscall.Access("/etc", 2) != nil {
			t.Skip("/etc/localtime is not a symlink this test can change")
		}
		r := newR025b(t, "tz")
		r.env = append(r.env[:1:1], "TZ") // unset in the child: os.Environ order, last wins
		os.Unsetenv("TZ")
		r.record([]string{"TestLocalIsUTC"})
		r.mustReuse("TestLocalIsUTC")
		os.Remove("/etc/localtime")
		os.Symlink("/usr/share/zoneinfo/Asia/Tokyo", "/etc/localtime")
		defer func() { os.Remove("/etc/localtime"); os.Symlink(target, "/etc/localtime") }()
		r.noWrongReuse("/etc/localtime -> Asia/Tokyo", "TestLocalIsUTC")
	})
}

// runVia is r.run with fenvix-go started through a wrapper (taskset, prlimit,
// a shell that sets the umask): the wrapper changes only what the process
// inherits.
func (r *r025) runVia(prefix []string, extra ...string) map[string]decision {
	r.t.Helper()
	r.n++
	report := filepath.Join(r.t.TempDir(), "report-via.jsonl")
	args := append(append([]string{}, prefix...), fenvixBin, "test", "--skip-cache="+r.cache, "--skip-verify", "--skip-report="+report)
	args = append(append(args, extra...), "./"+r.pkg)
	cmd := exec.Command(args[0], args[1:]...)
	cmd.Dir = r.dir
	cmd.Env = append(os.Environ(), r.env...)
	out, err := cmd.CombinedOutput()
	res := map[string]decision{}
	b, rerr := os.ReadFile(report)
	if rerr != nil {
		r.t.Fatalf("run via %v: no decision report (%v): %v\n%s", prefix, err, rerr, out)
	}
	for _, line := range strings.Split(string(b), "\n") {
		var d decision
		if jsonUnmarshal([]byte(line), &d) == nil {
			res[d.Test] = d
		}
	}
	r.t.Logf("run %d via %v: decisions %+v", r.n, prefix, res)
	return res
}

func (r *r025) noWrongReuseVia(what, test string, prefix []string) {
	r.t.Helper()
	d := r.runVia(prefix)[test]
	if d.Fresh == "" {
		r.t.Fatalf("%s: %s did not run: %+v", what, test, d)
	}
	if d.Reuse && d.Fresh != "passed" {
		r.t.Errorf("WRONG REUSE after %s: %s reused with proof, fresh run %s (cached %s)", what, test, d.Fresh, d.Cached)
	} else {
		r.t.Logf("%s: %s reuse=%v fresh=%s why=%q", what, test, d.Reuse, d.Fresh, d.Why)
	}
}

// P1-P3. Process attributes: CPU affinity (runtime.NumCPU and the default
// GOMAXPROCS: a restored or shared cache on a runner with fewer CPUs), the
// umask, the open-files limit (read from /proc/self/limits, a path the
// classifier drops as process-private). None is in the key.
func TestR025b_P_ProcessAttributes(t *testing.T) {
	cases := []struct {
		name, test string
		via        []string
		need       string
	}{
		{"cpu-affinity", "TestTwoCPUs", []string{"taskset", "-c", "0"}, "taskset"},
		{"umask", "TestCreatedMode", []string{"sh", "-c", `umask 002; exec "$@"`, "sh"}, "sh"},
		{"nofile-limit", "TestOpenFilesLimit", []string{"prlimit", "--nofile=1024:1024", "--"}, "prlimit"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if _, err := exec.LookPath(c.need); err != nil {
				t.Skip(c.need + " not installed")
			}
			if c.name == "cpu-affinity" && len(cpusAllowed()) < 2 {
				t.Skip("fewer than 2 CPUs")
			}
			r := newR025b(t, "procattr")
			r.record([]string{c.test})
			r.run() // t.TempDir: /tmp is first seen in the record run and valued in the next
			r.mustReuse(c.test)
			r.noWrongReuseVia(c.name+" changed", c.test, c.via)
		})
	}
}

func cpusAllowed() []int {
	var set [16]uint64
	_, _, e := syscall.RawSyscall(syscall.SYS_SCHED_GETAFFINITY, 0, uintptr(len(set)*8), uintptr(unsafePointer(&set)))
	if e != 0 {
		return nil
	}
	var out []int
	for i, w := range set {
		for b := 0; b < 64; b++ {
			if w&(1<<b) != 0 {
				out = append(out, i*64+b)
			}
		}
	}
	return out
}

// A1. A variable read by C code (cgo), below the os.Getenv hook.
func TestR025b_A1_CgoGetenv(t *testing.T) {
	r := newR025b(t, "cgoenv")
	r.record([]string{"TestDefaultMode"})
	r.mustReuse("TestDefaultMode")
	r.env = append(r.env, "R25B_CMODE=1")
	r.noWrongReuse("R25B_CMODE set (read by C)", "TestDefaultMode")
}

// A2. Absent inputs, later created. Each case starts from a fresh copy and an
// empty cache, records, checks the unchanged run is reused, creates the input
// and checks the test is not reused.
func TestR025b_A2_AbsentInputs(t *testing.T) {
	cases := []struct {
		name, test string
		create     func(r *r025)
	}{
		{"os.Stat missing file", "TestNoOverride", func(r *r025) { os.WriteFile(r.path("absent/testdata/override.json"), []byte("{}"), 0o644) }},
		{"glob gains a match", "TestGoldenGlob", func(r *r025) { os.WriteFile(r.path("absent/testdata/two.golden"), []byte("b"), 0o644) }},
		{"missing directory created", "TestPluginsDirMissing", func(r *r025) { os.MkdirAll(r.path("absent/testdata/plugins"), 0o755) }},
		{"os.Root stat", "TestRootNoExtra", func(r *r025) { os.WriteFile(r.path("absent/testdata/extra.txt"), nil, 0o644) }},
		{"os.DirFS stat", "TestDirFSNoExtra", func(r *r025) { os.WriteFile(r.path("absent/testdata/extra2.txt"), nil, 0o644) }},
		{"tool installed on PATH", "TestToolNotInstalled", func(r *r025) {
			os.WriteFile(r.path("bin/r25b-tool"), []byte("#!/bin/sh\n"), 0o755)
		}},
		{"child probe", "TestChildProbe", func(r *r025) { os.WriteFile(r.path("absent/testdata/child-flag"), nil, 0o644) }},
		{"variable set", "TestEnvUnset", func(r *r025) { r.env = append(r.env, "R25B_FLAG=") }},
		{"file in the package dir", "TestCwdFileMissing", func(r *r025) { os.WriteFile(r.path("absent/local.conf"), nil, 0o644) }},
		{"user config file", "TestHomeConfigMissing", func(r *r025) {
			os.MkdirAll(r.path("xdg/r25b"), 0o755)
			os.WriteFile(r.path("xdg/r25b/config.toml"), nil, 0o644)
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := newR025b(t, "absent")
			os.MkdirAll(r.path("bin"), 0o755)
			os.MkdirAll(r.path("xdg"), 0o755)
			r.env = append(r.env, "PATH="+r.path("bin")+":"+os.Getenv("PATH"), "XDG_CONFIG_HOME="+r.path("xdg"))
			r.record([]string{c.test})
			r.mustReuse(c.test)
			c.create(r)
			r.noWrongReuse(c.name, c.test)
		})
	}
}

// A3. Build inputs that are absent, then added: a file matched by a go:embed
// pattern, a new _test.go file in the package, a file selected by a build
// constraint; a test flag given through GOFLAGS.
func TestR025b_A3_BuildInputs(t *testing.T) {
	cases := []struct {
		name, pkg, test string
		change          func(r *r025)
	}{
		{"go:embed pattern gains a file", "embedpat", "TestOneEmbedded", func(r *r025) {
			os.WriteFile(r.path("embedpat/testdata/b.txt"), []byte("b"), 0o644)
		}},
		{"new _test.go file", "embedpat", "TestNoExtraFile", func(r *r025) {
			os.WriteFile(r.path("embedpat/extra_test.go"), []byte("package embedpat\n\nfunc init() { extra = true }\n"), 0o644)
		}},
		{"file matched by //go:build", "embedpat", "TestNoExtraFile", func(r *r025) {
			os.WriteFile(r.path("embedpat/zz_linux_test.go"), []byte("//go:build linux\n\npackage embedpat\n\nfunc init() { extra = true }\n"), 0o644)
		}},
		{"GOFLAGS=-timeout=1s", "slow", "TestTakesTwoSeconds", func(r *r025) { r.env = append(r.env, "GOFLAGS=-timeout=1s") }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := newR025b(t, c.pkg)
			r.record([]string{c.test})
			r.mustReuse(c.test)
			c.change(r)
			r.noWrongReuse(c.name, c.test)
		})
	}
}

// F1b. F1 across packages: go test runs packages in parallel (skip mode keeps
// -p). Package a rewrites a file package b read; b's strace log shows no
// change, so b's entry takes the value after the run (v2), a content b never
// saw. The next commit has v2: b is reused, and fails.
func TestR025b_F1b_WriteByAnotherPackage(t *testing.T) {
	r := newR025b(t, "xpkg/...")
	r.record([]string{"TestReadsShared", "TestRegenerateShared"})
	os.WriteFile(r.path("xpkg/shared/state.txt"), []byte("v2\n"), 0o644) // the next commit
	r.noWrongReuse("state.txt v1 -> v2 (written by package a during the record run)", "TestReadsShared")
}

func jsonUnmarshal(b []byte, v any) error { return json.Unmarshal(b, v) }

func unsafePointer[T any](p *T) unsafe.Pointer { return unsafe.Pointer(p) }

// F2b. File ownership: the metadata value is type, mode, size and mtime; the
// owner is not in it.
func TestR025b_F2b_FileOwner(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("needs root to chown")
	}
	r := newR025b(t, "owner")
	r.record([]string{"TestConfigOwnedByMe"})
	r.mustReuse("TestConfigOwnedByMe")
	if err := os.Chown(r.path("owner/testdata/conf"), 65534, 65534); err != nil {
		t.Skip(err)
	}
	r.noWrongReuse("testdata/conf chowned to nobody", "TestConfigOwnedByMe")
}

// F5b. The network configuration read through netlink: strace sees a
// sendto/sendmsg to an AF_NETLINK address, which is neither a file nor an
// inet or unix address. The check run is in a new network namespace (only a
// loopback interface): a runner without network, or with another one.
func TestR025b_F5b_NetlinkInterfaces(t *testing.T) {
	if _, err := exec.LookPath("unshare"); err != nil || os.Getuid() != 0 {
		t.Skip("needs unshare and root")
	}
	if exec.Command("unshare", "-n", "true").Run() != nil {
		t.Skip("cannot create a network namespace here")
	}
	r := newR025b(t, "netcfg")
	r.record([]string{"TestHasNonLoopbackInterface"})
	r.mustReuse("TestHasNonLoopbackInterface")
	r.noWrongReuseVia("a machine without that interface (new network namespace)", "TestHasNonLoopbackInterface", []string{"unshare", "-n"})
}

// R1b (robustness). An input that is a named pipe: the core values inputs by
// reading them (content_value: std::fs::read), after the run for an input
// first seen, before the binary for a recorded one. A FIFO with no writer
// blocks that read: fenvix-go never finishes (the test opened it with
// O_NONBLOCK and passed at once).
func TestR025b_R1b_FifoInputHangs(t *testing.T) {
	r := newR025b(t, "fifo")
	os.MkdirAll(r.path("fifo/testdata"), 0o755)
	if err := syscall.Mkfifo(r.path("fifo/testdata/status.fifo"), 0o644); err != nil {
		t.Skip(err)
	}
	cmd := exec.Command(fenvixBin, "test", "--skip-cache="+r.cache, "--skip-verify", "./fifo")
	cmd.Dir = r.dir
	cmd.Env = append(os.Environ(), r.env...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		t.Logf("record run finished: %v", err)
	case <-time.After(60 * time.Second):
		syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		<-done
		t.Errorf("fenvix-go test --skip-cache did not finish in 60 s on a package whose test polls a FIFO: the core blocks reading the pipe as an input")
	}
}

// F4b (held if the test reruns). A service on an abstract unix socket that
// the run did not open; its answer changes between record and check.
func TestR025b_F4b_AbstractUnixService(t *testing.T) {
	var answer atomic.Value
	answer.Store("ok")
	ln, err := net.Listen("unix", "@r25b-service")
	if err != nil {
		t.Skip(err)
	}
	defer ln.Close()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			c.Write([]byte(answer.Load().(string)))
			c.Close()
		}
	}()
	r := newR025b(t, "abstract")
	r.record([]string{"TestServiceSaysOK"})
	answer.Store("degraded")
	r.noWrongReuse("the service's answer changed", "TestServiceSaysOK")
}

// A4 (held if the test reruns). Module graph changes: a replace directive, and
// a go.work file that did not exist (absent input of the go command).
func TestR025b_A4_ModuleGraph(t *testing.T) {
	if _, err := exec.LookPath("strace"); err != nil {
		t.Skip("strace not installed")
	}
	for _, c := range []struct {
		name   string
		change func(dir string)
	}{
		{"replace directive", func(dir string) {
			b, _ := os.ReadFile(filepath.Join(dir, "app", "go.mod"))
			os.WriteFile(filepath.Join(dir, "app", "go.mod"), []byte(strings.Replace(string(b), "../depA", "../depB", 1)), 0o644)
		}},
		{"go.work appears", func(dir string) {
			os.WriteFile(filepath.Join(dir, "app", "go.work"), []byte("go 1.24\n\nuse (\n\t.\n\t../depB\n)\n"), 0o644)
			os.WriteFile(filepath.Join(dir, "depB", "go.mod"), []byte("module example.com/dep\n\ngo 1.24\n"), 0o644)
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			dir := copyFixture(t, "review-r025b-mod")
			r := &r025{t: t, dir: filepath.Join(dir, "app"), cache: filepath.Join(t.TempDir(), "cache"),
				env: []string{"GOFLAGS=", "GOWORK="}, pkg: ""}
			if c.name == "go.work appears" {
				r.env = []string{"GOFLAGS="}
			}
			r.record([]string{"TestDepValue"})
			r.mustReuse("TestDepValue")
			c.change(dir)
			r.noWrongReuse(c.name, "TestDepValue")
		})
	}
}

// ---------------------------------------------------------------------------
// Commit 480498f (coordinator scope addition): virtual /proc/1/stat.

// V1. Readers of the changing fields: plain go test passes; under fenvix the
// constants (utime = stime = 0, vsize = 0) make them fail (an integer
// division by zero for the ratio). Deterministic, so no wrong reuse: broken
// by fenvix (skip mode and --det).
func TestR025b_V1_VirtualStatBreaksReaders(t *testing.T) {
	if _, err := os.ReadFile("/proc/1/stat"); err != nil {
		t.Skip(err)
	}
	dir := copyFixture(t, "review-r025b")
	plain := exec.Command("go", "test", "-count=1", "-v", "./procv")
	plain.Dir = dir
	plain.Env = append(os.Environ(), "GOFLAGS=")
	pout, perr := plain.CombinedOutput()
	if perr != nil {
		t.Skipf("plain go test does not pass here:\n%s", pout)
	}
	r := &r025{t: t, dir: dir, cache: filepath.Join(t.TempDir(), "cache"), env: []string{"GOFLAGS="}, pkg: "procv"}
	got := r.run()
	for _, n := range []string{"TestPid1UsedCPU", "TestPid1MemoryRatio"} {
		if d := got[n]; d.Fresh != "passed" {
			t.Errorf("%s passes plain and is %q under fenvix skip mode: broken by the virtual /proc/1/stat", n, d.Fresh)
		}
	}
	out, code := runFenvix(t, dir, []string{"GOFLAGS="}, "test", "--det", "-run", "TestPid1UsedCPU", "./procv")
	if code != 0 {
		t.Errorf("TestPid1UsedCPU passes plain and fails under --det (exit %d):\n%s", code, lastLines(out, 6))
	}
}

func lastLines(s string, n int) string {
	l := strings.Split(strings.TrimSpace(s), "\n")
	if len(l) > n {
		l = l[len(l)-n:]
	}
	return strings.Join(l, "\n")
}

// V2. /proc/self/stat is not virtualised and is dropped as process-private:
// the nice value the run inherits (field 19) is in no key.
func TestR025b_V2_SelfStatNice(t *testing.T) {
	if _, err := exec.LookPath("nice"); err != nil {
		t.Skip("nice not installed")
	}
	r := newR025b(t, "procself")
	r.record([]string{"TestNotNiced"})
	r.mustReuse("TestNotNiced")
	r.noWrongReuseVia("started at nice 5", "TestNotNiced", []string{"nice", "-n", "5"})
}

// V3. Aliases under /proc/self: a path through /proc/self/cwd or
// /proc/self/root names an ordinary file, but the classifier drops everything
// under /proc/self (and the os hook matches /proc/1/stat by its exact name).
func TestR025b_V3_ProcSelfAliases(t *testing.T) {
	t.Run("cwd alias", func(t *testing.T) {
		r := newR025b(t, "cwdalias")
		r.record([]string{"TestValueThroughCwdAlias"})
		r.mustReuse("TestValueThroughCwdAlias")
		os.WriteFile(r.path("cwdalias/testdata/value.txt"), []byte("v2\n"), 0o644)
		r.noWrongReuse("testdata/value.txt v1 -> v2", "TestValueThroughCwdAlias")
	})
	t.Run("root alias of /proc/1/stat", func(t *testing.T) {
		r := newR025b(t, "byalias")
		r.record([]string{"TestRootAlias"})
		d := r.run()["TestRootAlias"]
		t.Logf("reuse=%v why=%q", d.Reuse, d.Why)
		if d.Reuse {
			t.Errorf("TestRootAlias read the real /proc/1/stat (changing fields included) through /proc/self/root and is reused: the read is in no key")
		}
	})
}

// V4 (held if not reused). Reads of /proc/1/stat that bypass os.OpenFile:
// syscall.Open, os.Root. strace sees them; the path is volatile.
func TestR025b_V4_BypassesAreVolatile(t *testing.T) {
	for _, c := range []struct{ pkg, test string }{{"bysys", "TestSyscallOpen"}, {"byroot", "TestRootOpen"}} {
		t.Run(c.pkg, func(t *testing.T) {
			r := newR025b(t, c.pkg)
			r.record([]string{c.test})
			d := r.run()[c.test]
			t.Logf("reuse=%v why=%q", d.Reuse, d.Why)
			if d.Reuse {
				t.Errorf("%s read the real /proc/1/stat below the hook and is reused", c.test)
			}
		})
	}
}

// X1. A test that panics is recorded as passed: the decision report says
// fresh "passed" while go test prints --- FAIL and exits 1, the cache stores
// "passed", and the next ordinary run (no --skip-verify) reuses it and exits
// 0. The walk's verification reads the same decision file, so it cannot see
// this either. Held: log.Fatal in a test, a panic in a goroutine (both
// recorded "interrupted").
func TestR025b_X1_PanicRecordedAsPassed(t *testing.T) {
	for _, pkg := range []string{"panicky", "crashexit", "crashgo"} {
		t.Run(pkg, func(t *testing.T) {
			r := newR025b(t, pkg)
			report := filepath.Join(t.TempDir(), "d1.jsonl")
			out, code := runFenvix(t, r.dir, r.env, "test", "--skip-cache="+r.cache, "--skip-report="+report, "./"+pkg)
			b, _ := os.ReadFile(report)
			t.Logf("record run: exit %d, decisions %s", code, b)
			if code == 0 {
				t.Fatalf("the record run passed:\n%s", out)
			}
			out, code = runFenvix(t, r.dir, r.env, "test", "--skip-cache="+r.cache, "./"+pkg)
			if code == 0 {
				t.Errorf("a failing test (%s), unchanged, is reused and the run exits 0:\n%s", pkg, lastLines(out, 4))
			}
		})
	}
}
