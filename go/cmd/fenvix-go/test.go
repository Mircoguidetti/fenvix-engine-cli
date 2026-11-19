package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/core"
	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/overlay"
	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/session"
)

// go test flags that take a separate value (`-run X`); `-x=y` forms are
// always self-contained.
var valueFlags = map[string]bool{
	"run": true, "skip": true, "bench": true, "benchtime": true, "count": true, "cpu": true, "parallel": true,
	"timeout": true, "shuffle": true, "tags": true, "o": true, "exec": true, "coverprofile": true,
	"covermode": true, "coverpkg": true, "blockprofile": true, "blockprofilerate": true, "cpuprofile": true,
	"memprofile": true, "memprofilerate": true, "mutexprofile": true, "mutexprofilefraction": true,
	"outputdir": true, "trace": true, "fuzz": true, "fuzztime": true, "fuzzminimizetime": true, "list": true,
	"p": true, "gcflags": true, "ldflags": true, "asmflags": true, "gccgoflags": true, "mod": true,
	"modfile": true, "overlay": true, "pgo": true, "toolexec": true, "C": true, "vet": true, "pkgdir": true,
	"buildmode": true, "compiler": true, "installsuffix": true, "covermode=": true, "args": false,
}

// flags whose value changes the compiled test binary or what go list sees
var buildFlags = map[string]bool{"tags": true, "mod": true, "modfile": true, "gcflags": true, "ldflags": true,
	"asmflags": true, "race": true, "msan": true, "asan": true, "cover": true, "covermode": true, "coverpkg": true,
	"pgo": true, "trimpath": true, "buildvcs": true}

type opts struct {
	det, keepParallel, skipVerify      bool
	seed                               uint64
	disable                            map[string]bool
	trace, epoch, gomaxprocs           string
	tick, adapt                        int64
	tickSet                            bool
	maxEvents                          int
	skipCache, skipCapture, skipReport string
	skipCommit, fenvixDir              string
}

func parseOpts(args []string) (*opts, []string, error) {
	o := &opts{disable: map[string]bool{}, tick: 1000, maxEvents: 50000}
	var rest []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "--" {
			rest = append(rest, args[i+1:]...)
			break
		}
		if !strings.HasPrefix(a, "--det") && !strings.HasPrefix(a, "--skip-") && !strings.HasPrefix(a, "--fenvix-") {
			rest = append(rest, a)
			continue
		}
		name, val, hasVal := strings.Cut(strings.TrimPrefix(a, "--"), "=")
		need := func() (string, error) {
			if hasVal {
				return val, nil
			}
			if i+1 >= len(args) {
				return "", fmt.Errorf("--%s needs a value", name)
			}
			i++
			return args[i], nil
		}
		var err error
		switch name {
		case "det":
			o.det = true
		case "det-seed":
			var v string
			if v, err = need(); err == nil {
				o.seed, err = strconv.ParseUint(v, 10, 64)
			}
		case "det-disable":
			var v string
			if v, err = need(); err == nil {
				for _, c := range strings.Split(v, ",") {
					c = strings.TrimSpace(c)
					if _, ok := overlay.Bits[c]; !ok && c != "" {
						return nil, nil, fmt.Errorf("--det-disable: unknown control %q", c)
					}
					o.disable[c] = true
				}
			}
		case "det-trace":
			o.trace, err = need()
		case "det-epoch":
			o.epoch, err = need()
		case "det-tick":
			var v string
			if v, err = need(); err == nil {
				o.tick, err = strconv.ParseInt(v, 10, 64)
				o.tickSet = true
			}
		case "det-adapt":
			var v string
			if v, err = need(); err == nil {
				o.adapt, err = strconv.ParseInt(v, 10, 64)
			}
		case "det-max-events":
			var v string
			if v, err = need(); err == nil {
				o.maxEvents, err = strconv.Atoi(v)
			}
		case "det-gomaxprocs":
			o.gomaxprocs, err = need()
		case "det-keep-parallel":
			o.keepParallel = true
		case "skip-cache":
			o.skipCache, err = need()
		case "skip-verify":
			o.skipVerify = true
		case "skip-capture":
			o.skipCapture, err = need()
		case "skip-report":
			o.skipReport, err = need()
		case "skip-commit":
			o.skipCommit, err = need()
		case "fenvix-dir":
			o.fenvixDir, err = need()
		default:
			return nil, nil, fmt.Errorf("unknown fenvix flag --%s", name)
		}
		if err != nil {
			return nil, nil, err
		}
	}
	return o, rest, nil
}

// splitGoArgs separates go test flags from package patterns. Arguments after
// -args go to the test binaries.
func splitGoArgs(args []string) (flags, pkgs, binArgs []string) {
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "-args" || a == "--args" {
			binArgs = args[i+1:]
			break
		}
		if strings.HasPrefix(a, "-") {
			flags = append(flags, a)
			name := strings.TrimLeft(a, "-")
			if !strings.Contains(name, "=") && valueFlags[name] && i+1 < len(args) {
				i++
				flags = append(flags, args[i])
			}
			continue
		}
		pkgs = append(pkgs, a)
	}
	return
}

func flagName(a string) string {
	n := strings.TrimLeft(a, "-")
	n, _, _ = strings.Cut(n, "=")
	return n
}

// goBin is the go command used for everything after the toolchain is
// resolved; goExtraEnv is added to its environment.
var (
	goBin      = "go"
	goExtraEnv []string
)

func goCommand(args ...string) *exec.Cmd {
	cmd := exec.Command(goBin, args...)
	cmd.Env = append(os.Environ(), goExtraEnv...)
	return cmd
}

// materializeToolchain: Go refuses -overlay replacements of files under
// GOMODCACHE, which is where `go` puts the toolchains it downloads for a
// go.mod that needs a newer Go. Such a toolchain is linked (hard links, no
// extra space; copied when links are not possible) into the fenvix cache and
// run from there with GOTOOLCHAIN=local.
func materializeToolchain(goroot, gomodcache, version string) (string, error) {
	if gomodcache == "" || !strings.HasPrefix(goroot, gomodcache+string(filepath.Separator)) {
		return goroot, nil
	}
	dst := filepath.Join(cacheDir(), "toolchains", version)
	if _, err := os.Stat(filepath.Join(dst, "bin", "go")); err == nil {
		return dst, nil
	}
	tmp := dst + ".tmp"
	os.RemoveAll(tmp)
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return "", err
	}
	if out, err := exec.Command("cp", "-al", goroot, tmp).CombinedOutput(); err != nil {
		os.RemoveAll(tmp)
		if out2, err2 := exec.Command("cp", "-a", goroot, tmp).CombinedOutput(); err2 != nil {
			return "", fmt.Errorf("copy toolchain: %v %s / %v %s", err, out, err2, out2)
		}
	}
	exec.Command("chmod", "-R", "u+w", tmp).Run()
	if err := os.Rename(tmp, dst); err != nil {
		return "", err
	}
	return dst, nil
}

func goEnv(dir string, keys ...string) (map[string]string, error) {
	cmd := goCommand(append([]string{"env", "-json"}, keys...)...)
	cmd.Dir = dir
	cmd.Stderr = os.Stderr
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("go env: %w", err)
	}
	m := map[string]string{}
	return m, json.Unmarshal(out, &m)
}

func cacheDir() string {
	if d := os.Getenv("FENVIX_GO_CACHE"); d != "" {
		return d
	}
	if d, err := os.UserCacheDir(); err == nil {
		return filepath.Join(d, "fenvix-go")
	}
	return filepath.Join(os.TempDir(), "fenvix-go-cache")
}

func repoRoot(dir, gomod string) string {
	cmd := exec.Command("git", "rev-parse", "--show-toplevel")
	cmd.Dir = dir
	if out, err := cmd.Output(); err == nil {
		if r := strings.TrimSpace(string(out)); r != "" {
			return r
		}
	}
	if gomod != "" && gomod != os.DevNull {
		return filepath.Dir(gomod)
	}
	return dir
}

func cmdTest(args []string) int {
	o, rest, err := parseOpts(args)
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go:", err)
		return 2
	}
	if !o.det && o.skipCache == "" {
		// without --det and without a skip cache fenvix-go is plain go test
		cmd := exec.Command("go", append([]string{"test"}, rest...)...)
		cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
		return exitCode(cmd.Run())
	}
	cwd, _ := os.Getwd()
	env, err := goEnv(cwd, "GOROOT", "GOVERSION", "GOOS", "GOARCH", "CGO_ENABLED", "GOMODCACHE", "GOCACHE", "GOMOD")
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go:", err)
		return 2
	}
	if root, err := materializeToolchain(env["GOROOT"], env["GOMODCACHE"], env["GOVERSION"]); err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go:", err)
		return 2
	} else if root != env["GOROOT"] {
		goBin = filepath.Join(root, "bin", "go")
		goExtraEnv = []string{"GOTOOLCHAIN=local"}
		env["GOROOT"] = root
	}
	if env["GOOS"] != "linux" {
		fmt.Fprintf(os.Stderr, "fenvix-go: only linux is supported (GOOS=%s)\n", env["GOOS"])
		return 2
	}
	ov, err := overlay.Generate(env["GOROOT"], env["GOVERSION"], cacheDir())
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go:", err)
		return 2
	}
	self, _ := os.Executable()
	self, _ = filepath.EvalSymlinks(self)

	flags, pkgs, binArgs := splitGoArgs(rest)
	if len(pkgs) == 0 {
		pkgs = []string{"."}
	}
	// controls
	var controls []string
	want := map[string]bool{}
	if o.det {
		for _, c := range overlay.DetControls {
			want[c] = true
		}
	}
	if o.skipCache != "" {
		want[overlay.CtlDeps] = true
		if !o.keepParallel {
			want[overlay.CtlSerial] = true
		}
	}
	if o.keepParallel {
		delete(want, overlay.CtlSerial)
	}
	if o.disable[overlay.CtlTime] {
		delete(want, overlay.CtlFastWait)
	}
	var ctl uint32
	for _, c := range append(append([]string{}, overlay.DetControls...), overlay.CtlDeps) {
		if !want[c] || o.disable[c] {
			continue
		}
		if !ov.Has(c) {
			fmt.Fprintf(os.Stderr, "fenvix-go: control %s unavailable on %s: %s\n", c, ov.GoVersion, ov.Unavailable[c])
			continue
		}
		controls = append(controls, c)
		ctl |= overlay.Bits[c]
	}
	epoch := int64(1735689600) * 1e9
	if o.det && o.seed != 0 {
		// exploration also moves the clock: the epoch anywhere in the year
		// after 2025-01-01 and a tick between 0.5 and 10 µs, both derived from
		// the seed (seed 0 keeps the fixed epoch and tick)
		if o.epoch == "" {
			epoch += int64(core.DeriveSeed(o.seed, "<epoch>")%(365*24*3600)) * 1e9
		}
		if !o.tickSet {
			o.tick = 500 + int64(core.DeriveSeed(o.seed, "<tick>")%9500)
		}
	}
	if o.epoch != "" {
		t, err := time.Parse(time.RFC3339, o.epoch)
		if err != nil {
			fmt.Fprintln(os.Stderr, "fenvix-go: --det-epoch:", err)
			return 2
		}
		epoch = t.UnixNano()
	}

	// sched: goroutines of a test binary share one P (Level 1 for goroutines),
	// unless --det-gomaxprocs says otherwise
	gomaxprocs := o.gomaxprocs
	schedOn := false
	for _, c := range controls {
		if c == overlay.CtlSched {
			schedOn = true
		}
	}
	if schedOn && gomaxprocs == "" {
		gomaxprocs = "1"
	}
	shim := ""
	if want[overlay.CtlTime] && ov.Has(overlay.CtlTime) && !o.disable[overlay.CtlTime] && ov.Partial["os-time"] == "" {
		var err error
		if shim, err = buildShim(); err != nil {
			fmt.Fprintf(os.Stderr, "fenvix-go: programs started by tests keep the real clock: %v\n", err)
		}
	}
	if o.det {
		for _, g := range sortedKeys(ov.Partial) {
			fmt.Fprintf(os.Stderr, "fenvix-go: on %s: %s\n", ov.GoVersion, ov.Partial[g])
		}
		// what --det does not control, said at start (review R-025 D2, D4)
		fmt.Fprintln(os.Stderr, "fenvix-go: --det does not control (Level 1 and outside the process): goroutine interleaving, "+
			"real timer delays, select among channels made ready by other goroutines, testing/synctest bubbles, "+
			"deadlines inside the network poller, clock reads through the vdso or raw syscalls, the clock and "+
			"entropy of child processes and cgo code, file timestamps (real time; seed 0 starts each test's virtual "+
			"clock at the real time so they stay comparable)")
	}

	// build flags that matter for go list and for the key
	var listFlags, keyFlags []string
	userOverlay := ""
	var goFlags []string
	for i := 0; i < len(flags); i++ {
		f := flags[i]
		n := flagName(f)
		val := ""
		if strings.Contains(f, "=") {
			_, val, _ = strings.Cut(f, "=")
		} else if valueFlags[n] && i+1 < len(flags) {
			val = flags[i+1]
		}
		consumed := !strings.Contains(f, "=") && valueFlags[n] && i+1 < len(flags)
		switch {
		case n == "overlay":
			userOverlay = val
		case n == "exec":
			fmt.Fprintln(os.Stderr, "fenvix-go: -exec is used by fenvix-go itself")
			return 2
		case o.det && n == "shuffle":
			// the order is fenvix's (--det-seed)
		case o.det && n == "p":
		default:
			goFlags = append(goFlags, f)
			if consumed {
				goFlags = append(goFlags, flags[i+1])
			}
			if buildFlags[n] {
				listFlags = append(listFlags, "-"+n+"="+val)
				if val == "" {
					listFlags[len(listFlags)-1] = "-" + n
				}
			}
		}
		if consumed {
			i++
		}
	}
	keyFlags = append(keyFlags, listFlags...)
	sort.Strings(keyFlags)

	// packages: import path <-> directory, and the order
	listArgs := append(append([]string{"list", "-e", "-f", "{{.ImportPath}}\t{{.Dir}}\t{{len .TestGoFiles}}\t{{len .XTestGoFiles}}"}, listFlags...), pkgs...)
	lc := goCommand(listArgs...)
	lc.Stderr = os.Stderr
	out, err := lc.Output()
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go: go list:", err)
		return 2
	}
	pkgMap := map[string]string{}
	var importPaths []string
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.Split(line, "\t")
		if len(parts) != 4 {
			continue
		}
		pkgMap[parts[1]] = parts[0]
		if real, err := filepath.EvalSymlinks(parts[1]); err == nil {
			pkgMap[real] = parts[0]
		}
		importPaths = append(importPaths, parts[0])
	}
	runPkgs := pkgs
	if o.det {
		sort.Strings(importPaths)
		if o.seed != 0 {
			perm := core.ShuffleIndices(len(importPaths), o.seed, "<packages>")
			shuffled := make([]string, len(importPaths))
			for i, j := range perm {
				shuffled[i] = importPaths[j]
			}
			importPaths = shuffled
		}
		runPkgs = importPaths
	}

	dir := o.fenvixDir
	if dir == "" {
		dir, err = os.MkdirTemp("", "fenvix-go-")
		if err != nil {
			fmt.Fprintln(os.Stderr, "fenvix-go:", err)
			return 2
		}
		defer os.RemoveAll(dir)
	}
	dir, _ = filepath.Abs(dir)
	os.MkdirAll(filepath.Join(dir, "parts"), 0o755)

	sess := &session.Session{
		Dir: dir, Self: self, Det: o.det, Seed: o.seed, Controls: controls, Ctl: ctl, Unavailable: ov.Unavailable,
		Epoch: epoch, Shim: shim, Sched: schedOn, Tick: o.tick, Adapt: o.adapt, MaxEvents: o.maxEvents, Root: repoRoot(cwd, env["GOMOD"]),
		Goroot: env["GOROOT"], GoVersion: env["GOVERSION"], GOOS: env["GOOS"], GOARCH: env["GOARCH"],
		CgoEnabled: env["CGO_ENABLED"], GoMaxProcs: gomaxprocs, Pkgs: pkgMap, OverlayHash: ov.Digest,
		BuildFlags: keyFlags,
	}
	if o.skipCache != "" {
		capture := o.skipCapture
		if capture == "" {
			capture = "hooks"
			if _, err := exec.LookPath("strace"); err == nil {
				capture = "strace"
			}
		}
		abs, _ := filepath.Abs(o.skipCache)
		// every path the run reads is an input (review R-025 F3) except
		// fenvix's and go's own working state
		drop := []string{dir, abs, env["GOCACHE"], filepath.Join(sess.Root, ".fenvix"), cacheDir()}
		if cfg, err := os.UserConfigDir(); err == nil {
			drop = append(drop, filepath.Join(cfg, "go", "telemetry")) // counters the go command rewrites on every run
		}
		if capture != "strace" {
			fmt.Fprintln(os.Stderr, "fenvix-go: skip: strace not found: the hooks alone cannot see every input (child processes, cgo, raw syscalls); decisions are reported, nothing is reused")
		}
		sess.Skip = &session.Skip{Dir: abs, Verify: o.skipVerify, Capture: capture, Drop: drop,
			Commit: o.skipCommit}
	}
	if err := sess.Save(); err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go:", err)
		return 2
	}

	ovPath := ov.Path
	if userOverlay != "" {
		ovPath = filepath.Join(dir, "overlay.json")
		if err := overlay.Merge(ov.Path, userOverlay, ovPath); err != nil {
			fmt.Fprintln(os.Stderr, "fenvix-go:", err)
			return 2
		}
	}
	goArgs := []string{"test", "-exec", self + " exec", "-overlay", ovPath}
	hasCount := false
	for _, f := range goFlags {
		if flagName(f) == "count" {
			hasCount = true
		}
	}
	if !hasCount {
		goArgs = append(goArgs, "-count=1")
	}
	if goMinor(env["GOVERSION"]) < 24 && !hasFlag(goFlags, "vet") {
		// go vet before Go 1.24 does not see files an overlay adds to a package
		fmt.Fprintf(os.Stderr, "fenvix-go: %s: go vet turned off (it cannot read the overlay)\n", env["GOVERSION"])
		goArgs = append(goArgs, "-vet=off")
	}
	if o.det {
		goArgs = append(goArgs, "-p", "1")
	}
	goArgs = append(goArgs, goFlags...)
	goArgs = append(goArgs, runPkgs...)
	if len(binArgs) > 0 {
		goArgs = append(append(goArgs, "-args"), binArgs...)
	}
	cmd := goCommand(goArgs...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	cmd.Env = append(cmd.Env, "FENVIX_GO_SESSION="+dir)
	runErr := cmd.Run()
	code := exitCode(runErr)

	// one trace from the per-package parts, in execution order
	parts, _ := filepath.Glob(filepath.Join(dir, "parts", "*.jsonl"))
	sort.Strings(parts)
	if o.det || len(parts) > 0 {
		tracePath := o.trace
		if tracePath == "" {
			tracePath = filepath.Join(".fenvix", fmt.Sprintf("go-trace-%d.jsonl", o.seed))
		}
		meta := traceMeta(sess, "")
		res, err := core.MergeTraces(parts, tracePath, meta, nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, "fenvix-go: trace:", err)
		} else if o.det {
			fmt.Fprintf(os.Stderr, "fenvix-go: trace %s (%d tests, seed %d, controls %s)\n", tracePath, res.NTests, o.seed,
				strings.Join(controls, ","))
		}
	}
	if sess.Skip != nil {
		summarizeSkip(dir, o.skipReport)
	}
	return code
}

func hasFlag(flags []string, name string) bool {
	for _, f := range flags {
		if flagName(f) == name {
			return true
		}
	}
	return false
}

// goMinor returns 24 for "go1.24.7" (0 when unknown).
func goMinor(v string) int {
	v = strings.TrimPrefix(v, "go1.")
	n := 0
	for _, c := range v {
		if c < '0' || c > '9' {
			break
		}
		n = n*10 + int(c-'0')
	}
	return n
}

func traceMeta(s *session.Session, pkg string) map[string]any {
	m := map[string]any{
		"runtime": "go", "runtime_version": s.GoVersion, "runner": "go test", "seed": s.Seed,
		"controls": s.Controls, "goos": s.GOOS, "goarch": s.GOARCH, "overlay": s.OverlayHash,
		"epoch_ns": s.Epoch, "tick_ns": s.Tick, "gomaxprocs": s.GoMaxProcs,
	}
	if s.GoMaxProcs == "" {
		m["gomaxprocs"] = "default"
	}
	if pkg != "" {
		m["package"] = pkg
	}
	return m
}

func exitCode(err error) int {
	if err == nil {
		return 0
	}
	if ee, ok := err.(*exec.ExitError); ok {
		return ee.ExitCode()
	}
	fmt.Fprintln(os.Stderr, "fenvix-go:", err)
	return 1
}

func summarizeSkip(dir, report string) {
	f, err := os.Open(filepath.Join(dir, "decisions.jsonl"))
	if err != nil {
		return
	}
	defer f.Close()
	var out *os.File
	if report != "" {
		os.MkdirAll(filepath.Dir(report), 0o755)
		out, _ = os.Create(report)
		if out != nil {
			defer out.Close()
		}
	}
	var n, reused, wrong int
	var tAll, tReused float64
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<24)
	for sc.Scan() {
		var d decision
		if json.Unmarshal(sc.Bytes(), &d) != nil {
			continue
		}
		if out != nil {
			out.Write(append(sc.Bytes(), '\n'))
		}
		n++
		el := d.Elapsed
		if el == 0 {
			el = d.CachedElapsed
		}
		tAll += el
		if d.Reuse {
			reused++
			tReused += el
			if d.Fresh != "" && d.Fresh != d.Cached {
				wrong++
			}
		}
	}
	msg := fmt.Sprintf("fenvix-go: skip with proof: %d of %d tests reusable (%.1f of %.1f s of test time)", reused, n, tReused, tAll)
	if wrong > 0 {
		msg += fmt.Sprintf("; %d reuse(s) disagreed with the fresh run", wrong)
	}
	fmt.Fprintln(os.Stderr, msg)
}

func cmdVerify(args []string) int {
	showStable := false
	var paths []string
	asJSON := false
	for _, a := range args {
		switch a {
		case "--show-stable":
			showStable = true
		case "--json":
			asJSON = true
		default:
			paths = append(paths, a)
		}
	}
	if len(paths) < 2 {
		fmt.Fprintln(os.Stderr, "usage: fenvix-go verify [--json] [--show-stable] TRACE TRACE...")
		return 2
	}
	var s string
	var err error
	if asJSON {
		s, err = core.VerifyJSON(paths)
	} else {
		s, err = core.VerifyText(paths, showStable)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go:", err)
		return 2
	}
	fmt.Println(s)
	return 0
}

func cmdOverlay(args []string) int {
	cwd, _ := os.Getwd()
	env, err := goEnv(cwd, "GOROOT", "GOVERSION")
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go:", err)
		return 2
	}
	ov, err := overlay.Generate(env["GOROOT"], env["GOVERSION"], cacheDir())
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go:", err)
		return 2
	}
	b, _ := json.MarshalIndent(ov, "", "  ")
	fmt.Println(string(b))
	return 0
}

func sortedKeys(m map[string]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// buildShim compiles (once per source) the library preloaded into programs
// a --det test starts, so that their wall clock follows the virtual clock
// (review R-025 D2). It needs a C compiler (CC, cc or gcc).
func buildShim() (string, error) {
	src := overlay.FaketimeC()
	out := filepath.Join(cacheDir(), "faketime-"+core.Digest([]byte(src))[:16]+".so")
	if _, err := os.Stat(out); err == nil {
		return out, nil
	}
	if err := os.MkdirAll(cacheDir(), 0o755); err != nil {
		return "", err
	}
	cc := os.Getenv("CC")
	if cc == "" {
		for _, c := range []string{"cc", "gcc", "clang"} {
			if _, err := exec.LookPath(c); err == nil {
				cc = c
				break
			}
		}
	}
	if cc == "" {
		return "", fmt.Errorf("no C compiler to build the clock library")
	}
	srcPath := out + ".c"
	if err := os.WriteFile(srcPath, []byte(src), 0o644); err != nil {
		return "", err
	}
	tmp := fmt.Sprintf("%s.%d.tmp", out, os.Getpid())
	if b, err := exec.Command(cc, "-shared", "-fPIC", "-O2", "-o", tmp, srcPath).CombinedOutput(); err != nil {
		return "", fmt.Errorf("%s: %v: %s", cc, err, strings.TrimSpace(string(b)))
	}
	return out, os.Rename(tmp, out)
}
