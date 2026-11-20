package main

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/core"
	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/overlay"
	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/session"
)

// decision is one line of decisions.jsonl (skip cache).
type decision struct {
	Pkg           string  `json:"pkg"`
	Test          string  `json:"test"`
	Reuse         bool    `json:"reuse"`     // inputs unchanged: reused with proof
	ReuseOwn      bool    `json:"reuse_own"` // measurement only: own inputs, no prefix rule
	WhyOwn        string  `json:"why_own,omitempty"`
	Why           string  `json:"why,omitempty"`  // why it had to run
	Cached        string  `json:"cached"`         // cached outcome
	CachedElapsed float64 `json:"cached_elapsed"` // seconds
	Fresh         string  `json:"fresh,omitempty"`
	Elapsed       float64 `json:"elapsed"`                 // seconds of the fresh run (0 when not run)
	VirtualClock  string  `json:"virtual_clock,omitempty"` // outcome on the virtual day when the reported run was on the real clock
	Commit        string  `json:"commit,omitempty"`
}

func sanitize(s string) string {
	return strings.Map(func(r rune) rune {
		if r == '/' || r == '\\' || r == ':' || r == ' ' {
			return '_'
		}
		return r
	}, s)
}

type record struct {
	kind    byte
	payload []byte
}

func readRecords(path string) ([]record, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	r := bufio.NewReader(f)
	var out []record
	for {
		var h [5]byte
		if _, err := io.ReadFull(r, h[:]); err != nil {
			if err == io.EOF || err == io.ErrUnexpectedEOF {
				return out, nil
			}
			return out, err
		}
		n := binary.LittleEndian.Uint32(h[1:])
		p := make([]byte, n)
		if _, err := io.ReadFull(r, p); err != nil {
			return out, nil // truncated by a crash: keep what is complete
		}
		out = append(out, record{h[0], p})
	}
}

// netConfig: the machine's network configuration as a netlink query sees
// it (interfaces with flags, MTU, hardware and IP addresses): the value of
// the netlink input of the key (review R-025b F5b).
func netConfig() string {
	ifs, err := net.Interfaces()
	if err != nil {
		return "error:" + err.Error()
	}
	var b strings.Builder
	for _, i := range ifs {
		fmt.Fprintf(&b, "%s|%v|%d|%s|", i.Name, i.Flags, i.MTU, i.HardwareAddr)
		addrs, _ := i.Addrs()
		for _, a := range addrs {
			b.WriteString(a.String() + ",")
		}
		b.WriteByte('\n')
	}
	return b.String()
}

// ownAddresses: the addresses of this machine's interfaces (a connection
// to one of them does not leave the machine).
func ownAddresses() []string {
	var out []string
	addrs, _ := net.InterfaceAddrs()
	for _, a := range addrs {
		if n, ok := a.(*net.IPNet); ok {
			out = append(out, n.IP.String())
		}
	}
	return out
}

func cmdExec(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "fenvix-go exec: missing test binary")
		return 2
	}
	sess, err := session.Load(os.Getenv("FENVIX_GO_SESSION"))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	bin, targs := args[0], args[1:]
	cwd, _ := os.Getwd()
	pkg := sess.Pkgs[cwd]
	if pkg == "" {
		if real, err := filepath.EvalSymlinks(cwd); err == nil {
			pkg = sess.Pkgs[real]
		}
	}
	if pkg == "" {
		pkg, _ = filepath.Rel(sess.Root, cwd)
	}

	// arguments: the order is fenvix's under --det
	var runArgs []string
	testJSON, verbose := false, false
	for _, a := range targs {
		n := strings.TrimLeft(a, "-")
		name, val, _ := strings.Cut(n, "=")
		if sess.Det && name == "test.shuffle" {
			continue
		}
		if name == "test.v" {
			verbose = val != "false"
			testJSON = val == "test2json"
		}
		runArgs = append(runArgs, a)
	}

	stamp := fmt.Sprintf("%020d-%s", time.Now().UnixNano(), sanitize(pkg))
	partBase := filepath.Join(sess.Dir, "parts", stamp)
	evPath := partBase + ".events"

	childEnv := os.Environ()
	initSeed := core.DeriveSeed(sess.Seed, pkg+"::<init>")
	explore := 0
	if sess.Det && sess.Seed != 0 {
		explore = 1
	}
	cfg := fmt.Sprintf("ctl=%d;epoch=%d;tick=%d;adapt=%d;seed=%d;root=%s;goroot=%s;maxev=%d;explore=%d;shim=%s;vproc1stat=%s;clockmode=%s",
		sess.Ctl, sess.Epoch, sess.Tick, sess.Adapt, initSeed, sess.Root, sess.Goroot, sess.MaxEvents, explore, sess.Shim,
		sess.VProc1Stat, sess.ClockMode)
	childEnv = append(childEnv, "FENVIX_GO_DET="+cfg, "FENVIX_GO_FDS=3,4,5")
	if sess.VirtualPid > 0 {
		childEnv = append(childEnv, "FENVIX_GO_VPID="+strconv.Itoa(sess.VirtualPid))
	}
	if sess.GoMaxProcs != "" {
		childEnv = append(childEnv, "GOMAXPROCS="+sess.GoMaxProcs)
	}
	if sess.Shim != "" {
		// the test binary itself (C code when it is dynamically linked: cgo)
		// gets the clock library; in skip mode every libc clock read is
		// marked for strace (review R-025b C3)
		epochNow := sess.Epoch - time.Now().UnixNano()
		childEnv = append(childEnv, "FENVIX_GO_CLOCK_OFFSET="+strconv.FormatInt(epochNow, 10),
			"FENVIX_GO_CLOCK_BEGIN="+strconv.FormatInt(time.Now().UnixNano(), 10))
		lp := sess.Shim
		if pre := os.Getenv("LD_PRELOAD"); pre != "" {
			lp += ":" + pre
		}
		childEnv = append(childEnv, "LD_PRELOAD="+lp)
		if sess.Skip != nil {
			childEnv = append(childEnv, "FENVIX_GO_CLOCK_MARK=1")
		}
	}
	if sess.Sched {
		// no signal-based preemption: a goroutine gives way at its own
		// scheduling points (channel operations, locks, syscalls, Gosched)
		gd := os.Getenv("GODEBUG")
		if gd != "" {
			gd += ","
		}
		childEnv = append(childEnv, "GODEBUG="+gd+"asyncpreemptoff=1,gcstoptheworld=1")
	}

	// skip cache: the core loads it and takes the pre-run values of every
	// recorded input now, before the binary (its init, TestMain) can change them
	var sk *core.Skip
	logPath := partBase + ".strace"
	useStrace := sess.Skip != nil && sess.Skip.Capture == "strace"
	if sess.Skip != nil {
		var keyEnv []string
		for _, kv := range os.Environ() {
			if !strings.HasPrefix(kv, "FENVIX_GO_") {
				keyEnv = append(keyEnv, kv)
			}
		}
		if sess.GoMaxProcs != "" {
			keyEnv = append(keyEnv, "GOMAXPROCS="+sess.GoMaxProcs)
		}
		static := append([]string{"bin", binaryContentID(sess.Goroot, bin), "go", sess.GoVersion, sess.GOOS, sess.GOARCH,
			"cgo", sess.CgoEnabled, "overlay", sess.OverlayHash, "ctl", strconv.Itoa(int(sess.Ctl)),
			"seed", strconv.FormatUint(sess.Seed, 10), "epoch", strconv.FormatInt(sess.Epoch, 10),
			"tick", strconv.FormatInt(sess.Tick, 10), "gomaxprocs", sess.GoMaxProcs, "buildflags"}, sess.BuildFlags...)
		drop := append(append([]string{}, sess.Skip.Drop...), filepath.Dir(bin))
		sk, err = core.OpenSkip(map[string]any{
			"cache_dir": sess.Skip.Dir, "pkg": pkg, "root": sess.Root, "static_parts": static,
			"test_args": nonNil(runArgs), "env": nonNil(keyEnv), "capture": sess.Skip.Capture, "self_binary": bin,
			"drop": drop, "own_addrs": nonNil(ownAddresses()), "verify": sess.Skip.Verify,
			"commit": sess.Skip.Commit, "decisions": filepath.Join(sess.Dir, "decisions.jsonl"),
			"child_clock": sess.Shim != "", "read_only": sess.Skip.RealClock, "net_config": netConfig(),
		})
		if err != nil {
			fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
			return 2
		}
		defer sk.Free()
	}

	// one run of the binary: the control pipe hands it the order (names ->
	// order, seeds, tests to leave out); with fixed != nil the reused set
	// is the one decided before (a second run of the same package)
	type runOut struct {
		recs                    []record
		code                    int
		names, fullOrder, order []string
		reused                  map[string]bool
	}
	runBinary := func(env []string, withStrace bool, out, errOut io.Writer, ev string, fixed map[string]bool) (*runOut, error) {
		ro := &runOut{reused: map[string]bool{}}
		evf, err := os.Create(ev)
		if err != nil {
			return nil, err
		}
		outR, outW, _ := os.Pipe()
		inR, inW, _ := os.Pipe()
		printer := &reusePrinter{w: out}
		var ctlWG sync.WaitGroup
		ctlWG.Add(1)
		go func() {
			defer ctlWG.Done()
			sc := bufio.NewScanner(outR)
			sc.Buffer(make([]byte, 1<<20), 1<<26)
			for sc.Scan() {
				line := sc.Text()
				if !strings.HasPrefix(line, "L\x1f") {
					continue
				}
				ro.names = strings.Split(line[2:], "\x1f")
				if len(ro.names) == 1 && ro.names[0] == "" {
					ro.names = nil
				}
				idx := make([]int, len(ro.names))
				for i := range idx {
					idx[i] = i
				}
				if sess.Det && sess.Seed != 0 {
					idx = core.ShuffleIndices(len(ro.names), sess.Seed, pkg)
				}
				for _, i := range idx {
					ro.fullOrder = append(ro.fullOrder, ro.names[i])
				}
				switch {
				case fixed != nil:
					for n := range fixed {
						ro.reused[n] = true
					}
				case sk != nil:
					r, err := sk.Decide(ro.fullOrder)
					if err != nil {
						fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
					}
					if !sess.Skip.Verify {
						for _, n := range r {
							ro.reused[n] = true
						}
					}
				}
				var ord, seeds, reused []string
				for _, i := range idx {
					name := ro.names[i]
					if ro.reused[name] {
						reused = append(reused, name)
						continue
					}
					ord = append(ord, strconv.Itoa(i))
					seeds = append(seeds, strconv.FormatUint(core.DeriveSeed(sess.Seed, pkg+"::"+name), 10))
					ro.order = append(ro.order, name)
				}
				printer.setReused(reused)
				fmt.Fprintf(inW, "O\x1f%s\x1f%s\n", strings.Join(ord, ","), strings.Join(seeds, ","))
			}
		}()

		// reused tests are reported before the binary runs the others
		var cmdArgs []string
		if withStrace {
			cmdArgs = append(core.StraceArgs(logPath), bin)
		} else {
			cmdArgs = []string{bin}
		}
		cmdArgs = append(cmdArgs, runArgs...)
		if len(sess.PidNS) > 0 {
			// --det: the test binary's pid is the same in every run (its own PID
			// namespace and /proc; review R-025b D3b)
			cmdArgs = append(append([]string{}, sess.PidNS...), cmdArgs...)
		}
		cmd := exec.Command(cmdArgs[0], cmdArgs[1:]...)
		cmd.Stdin, cmd.Stderr = os.Stdin, errOut
		printer.json, printer.verbose = testJSON, verbose
		cmd.Stdout = printer
		cmd.Env = env
		cmd.ExtraFiles = []*os.File{evf, outW, inR}
		if err := cmd.Start(); err != nil {
			evf.Close()
			return nil, err
		}
		evf.Close()
		outW.Close()
		inR.Close()
		runErr := cmd.Wait()
		outR.Close()
		inW.Close()
		ctlWG.Wait()
		printer.flushReused()
		ro.code = exitCode(runErr)
		ro.recs, _ = readRecords(ev)
		os.Remove(ev)
		return ro, nil
	}

	// skip mode on the virtual day: the output is held until the run is
	// known not to need the real clock (review R-025b S1)
	virtualDay := sk != nil && sess.ClockMode == "offset"
	var held bytesBuffer
	var out, errOut io.Writer = os.Stdout, os.Stderr
	if virtualDay {
		// go test merges a test binary's stdout and stderr: so does the
		// held output
		out, errOut = &held, &held
	}
	ro, err := runBinary(childEnv, useStrace, out, errOut, evPath, nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
		return 2
	}
	names, fullOrder := ro.names, ro.fullOrder
	results, pkgDeps := parseResults(ro.recs)
	reported := ro
	if virtualDay {
		rerun, err := sk.RealClockRerun(map[string]any{"results": results, "pkg_deps": pkgDeps})
		if err != nil {
			fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
		}
		if len(rerun) == 0 {
			os.Stdout.Write(held.Bytes())
		} else {
			// a test failed after starting a program that reads the real
			// clock (a Go or static program): the two clocks met. The package
			// runs again on the real clock, as go test runs it, and that run
			// is the one reported. Its keys stay those of the virtual-clock
			// run; such a test is never reused (exec: is unkeyed)
			fmt.Fprintf(os.Stderr, "fenvix-go: %s: %s failed on the virtual day after starting a program that reads the real clock; the package runs again on the real clock (reported run)\n",
				pkg, strings.Join(rerun, ", "))
			realEnv := realClockEnv(childEnv, sess)
			r2, err := runBinary(realEnv, false, os.Stdout, os.Stderr, evPath+".real", ro.reused)
			if err != nil {
				fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
				os.Stdout.Write(held.Bytes())
			} else {
				reported = r2
				res2, _ := parseResults(r2.recs)
				byName2 := map[string]*result{}
				for _, r := range res2 {
					byName2[r.Name] = r
				}
				for _, r := range results {
					if r2r := byName2[r.Name]; r2r != nil && r2r.Outcome != r.Outcome {
						r.VirtualClock = r.Outcome
						r.Outcome = r2r.Outcome
						r.Elapsed = r2r.Elapsed
					}
				}
			}
		}
	}
	code := reported.code
	order := reported.order

	// events -> fingerprints (Rust core) -> partial trace
	rec := core.NewRecorder(0, 0)
	defer rec.Free()
	if err := rec.Open(partBase+".jsonl", traceMeta(sess, pkg), prefixed(pkg, order)); err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
	}
	pos := 0
	for _, r := range reported.recs {
		switch r.kind {
		case 'B':
			rec.BeginTest(pkg+"::"+string(r.payload), uint64(pos))
			pos++
		case 'E':
			if _, err := rec.RecordPacked(r.payload); err != nil {
				fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
			}
		case 'X':
			parts := strings.Split(string(r.payload), "\x1f")
			rec.EndTest(parts[0])
		}
	}
	rec.Close()

	if sk != nil {
		straceLog := ""
		if useStrace {
			straceLog = logPath
		}
		if results == nil {
			results = []*result{}
		}
		if _, err := sk.Record(map[string]any{"names": nonNil(names), "order": nonNil(fullOrder), "results": results,
			"pkg_deps": pkgDeps, "strace_log": straceLog, "cwd": cwd}); err != nil {
			fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
		}
		if useStrace {
			os.Remove(logPath)
		}
	}
	return code
}

func nonNil(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

// binaryContentID is the content part of the test binary's Go build ID: a
// hash of the binary with its build ID removed (what go's own test cache
// keys on). Two builds with identical machine code get the same value even
// when their inputs' hashes (the action ID) differ. Falls back to a digest
// of the whole file.
func binaryContentID(goroot, bin string) string {
	out, err := exec.Command(filepath.Join(goroot, "bin", "go"), "tool", "buildid", bin).Output()
	if id := strings.TrimSpace(string(out)); err == nil && strings.Contains(id, "/") {
		return "content:" + id[strings.LastIndex(id, "/")+1:]
	}
	return "file:" + core.DigestFile(bin)
}

func prefixed(pkg string, names []string) []string {
	out := make([]string, len(names))
	for i, n := range names {
		out[i] = pkg + "::" + n
	}
	return out
}

// result is one test's outcome as the events of a run report it.
type result struct {
	Name         string  `json:"name"`
	Outcome      string  `json:"outcome"`
	Elapsed      float64 `json:"elapsed"`
	Pos          int     `json:"pos"`
	Deps         string  `json:"deps"`
	VirtualClock string  `json:"virtual_clock,omitempty"`
}

// parseResults reads the test outcomes and packed hook dependencies of a run.
func parseResults(recs []record) ([]*result, string) {
	results := []*result{}
	byName := map[string]*result{}
	var pkgDeps strings.Builder
	var cur string
	idx := 0
	for _, r := range recs {
		switch r.kind {
		case 'I':
			pkgDeps.Write(r.payload)
			pkgDeps.WriteByte(0x1e)
		case 'B':
			cur = string(r.payload)
			res := &result{Name: cur, Outcome: "interrupted", Pos: idx}
			results = append(results, res)
			byName[cur] = res
			idx++
		case 'D':
			if res := byName[cur]; res != nil {
				res.Deps += string(r.payload) + "\x1e"
			}
		case 'X':
			parts := strings.Split(string(r.payload), "\x1f")
			if res := byName[cur]; res != nil {
				res.Outcome = parts[0]
				if len(parts) > 2 {
					ns, _ := strconv.ParseInt(parts[2], 10, 64)
					res.Elapsed = float64(ns) / 1e9
				}
			}
			cur = ""
		}
	}
	return results, pkgDeps.String()
}

// realClockEnv is the test binary's environment for a run on the real clock:
// the time controls are off and the preloaded library adds nothing.
func realClockEnv(env []string, sess *session.Session) []string {
	ctl := sess.Ctl &^ (overlay.Bits[overlay.CtlTime] | overlay.Bits[overlay.CtlFastWait])
	var out []string
	for _, kv := range env {
		switch {
		case strings.HasPrefix(kv, "FENVIX_GO_DET="):
			_, rest, _ := strings.Cut(kv, ";")
			rest = strings.Replace(rest, "clockmode="+sess.ClockMode, "clockmode=", 1)
			kv = fmt.Sprintf("FENVIX_GO_DET=ctl=%d;%s", ctl, rest)
		case strings.HasPrefix(kv, "FENVIX_GO_CLOCK_OFFSET="):
			kv = "FENVIX_GO_CLOCK_OFFSET=0"
		case strings.HasPrefix(kv, "FENVIX_GO_CLOCK_BEGIN="):
			kv = "FENVIX_GO_CLOCK_BEGIN=0"
		case strings.HasPrefix(kv, "FENVIX_GO_CLOCK_MARK="):
			continue
		}
		out = append(out, kv)
	}
	return out
}

// bytesBuffer is a goroutine-safe byte buffer.
type bytesBuffer struct {
	mu sync.Mutex
	b  []byte
}

func (b *bytesBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	b.b = append(b.b, p...)
	b.mu.Unlock()
	return len(p), nil
}

func (b *bytesBuffer) Bytes() []byte {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.b
}

// reusePrinter passes the binary's output through and, before its first
// byte, reports the tests reused with proof in the format go test expects.
type reusePrinter struct {
	w             io.Writer
	json, verbose bool
	reused        []string
	mu            sync.Mutex
	done          bool
}

func (p *reusePrinter) setReused(m []string) {
	p.mu.Lock()
	p.reused = m
	p.mu.Unlock()
}

func (p *reusePrinter) flushReused() {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.done {
		return
	}
	p.done = true
	if len(p.reused) == 0 {
		return
	}
	mark := ""
	if p.json {
		mark = "\x16"
	}
	names := append([]string{}, p.reused...)
	sortStrings(names)
	for _, n := range names {
		if !p.verbose {
			continue
		}
		fmt.Fprintf(p.w, "%s=== RUN   %s\n", mark, n)
		fmt.Fprintf(p.w, "    fenvix: reused with proof (inputs unchanged since its last pass)\n")
		fmt.Fprintf(p.w, "%s--- PASS: %s (0.00s)\n", mark, n)
	}
}

func (p *reusePrinter) Write(b []byte) (int, error) {
	// the reused set is known once the binary asked for its order, which
	// happens before any test output
	p.flushIfReady()
	return p.w.Write(b)
}

func (p *reusePrinter) flushIfReady() {
	p.mu.Lock()
	ready := !p.done && len(p.reused) > 0
	p.mu.Unlock()
	if ready {
		p.flushReused()
	}
}

func sortStrings(s []string) {
	for i := 1; i < len(s); i++ {
		for j := i; j > 0 && s[j] < s[j-1]; j-- {
			s[j], s[j-1] = s[j-1], s[j]
		}
	}
}
