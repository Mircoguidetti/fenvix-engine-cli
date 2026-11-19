package main

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/core"
	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/session"
	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/skip"
	"github.com/mircoguidetti/fenvix-engine-cli/go/internal/strace"
)

// decision is one line of decisions.jsonl (skip cache).
type decision struct {
	Pkg           string  `json:"pkg"`
	Test          string  `json:"test"`
	Reuse         bool    `json:"reuse"`          // inputs unchanged: reused with proof
	ReuseOwn      bool    `json:"reuse_own"`      // measurement only: own inputs, no prefix rule
	WhyOwn        string  `json:"why_own,omitempty"`
	Why           string  `json:"why,omitempty"`  // why it had to run
	Cached        string  `json:"cached"`         // cached outcome
	CachedElapsed float64 `json:"cached_elapsed"` // seconds
	Fresh         string  `json:"fresh,omitempty"`
	Elapsed       float64 `json:"elapsed"` // seconds of the fresh run (0 when not run)
	Commit        string  `json:"commit,omitempty"`
}

// the test flags that do not change what a test does
var neutralTestFlags = map[string]bool{"test.run": true, "test.v": true, "test.timeout": true,
	"test.paniconexit0": true, "test.count": true, "test.shuffle": true, "test.testlogfile": true,
	"test.outputdir": true, "test.gocoverdir": true, "test.failfast": true, "test.skip": true, "test.fullpath": true}

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

// parseDeps turns packed hook dependencies into a Raw. Paths go through the
// same filter as strace's (roots and ignored directories: /proc, /sys, /tmp,
// caches), so both captures follow one rule.
func parseDeps(p []byte, raw *skip.Raw, keep func(string) bool) {
	for _, item := range strings.Split(string(p), "\x1e") {
		if len(item) < 2 || item[1] != 0x1f {
			continue
		}
		k, name := item[0], item[2:]
		switch k {
		case 'E':
			raw.Env[name] = true
		case 'O':
			if p := filepath.Clean(name); keep(p) {
				raw.Reads[p] = true
			}
		case 'S':
			if p := filepath.Clean(name); keep(p) {
				raw.Exists[p] = true
			}
		case 'L':
			if p := filepath.Clean(name); keep(p) {
				raw.Lists[p] = true
			}
		case 'X':
			raw.Execs = append(raw.Execs, name)
		case 'N':
			raw.Net = append(raw.Net, name)
		}
	}
}

func isLocal(ip string, port int, proxyPorts map[int]bool) bool {
	if port == 53 {
		return false
	}
	a := net.ParseIP(ip)
	if a == nil || !(a.IsLoopback() || a.IsUnspecified() || ownAddress(a)) {
		return false
	}
	return !proxyPorts[port]
}

var (
	ownOnce  sync.Once
	ownAddrs []net.IP
)

// ownAddress: an address of one of this machine's interfaces (a connection
// to it does not leave the machine); the same rule as the net hook.
func ownAddress(ip net.IP) bool {
	ownOnce.Do(func() {
		addrs, _ := net.InterfaceAddrs()
		for _, a := range addrs {
			if n, ok := a.(*net.IPNet); ok {
				ownAddrs = append(ownAddrs, n.IP)
			}
		}
	})
	for _, a := range ownAddrs {
		if a.Equal(ip) {
			return true
		}
	}
	return false
}

var reProxy = regexp.MustCompile(`^(?:([a-z0-9]+)://)?(?:[^@/]*@)?(\[[^\]]+\]|[^:/]+)(?::(\d+))?`)

// loopbackProxyPorts: ports of HTTP(S)/SOCKS proxies configured on loopback
// (a connect to them leaves the machine: R-002b).
func loopbackProxyPorts(env map[string]string) map[int]bool {
	out := map[int]bool{}
	for _, k := range []string{"HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"} {
		v := env[k]
		if v == "" {
			continue
		}
		m := reProxy.FindStringSubmatch(v)
		if m == nil {
			continue
		}
		host := strings.Trim(m[2], "[]")
		ip := net.ParseIP(host)
		if host != "localhost" && (ip == nil || !(ip.IsLoopback() || ip.IsUnspecified())) {
			if ip == nil {
				// a name other than localhost may map to loopback: count any loopback connect to its port
			} else {
				continue
			}
		}
		port, err := strconv.Atoi(m[3])
		if err != nil {
			switch m[1] {
			case "https":
				port = 443
			case "socks", "socks5", "socks5h", "socks4", "socks4a":
				port = 1080
			default:
				port = 80
			}
		}
		out[port] = true
	}
	return out
}

func appendJSONL(path string, v any) {
	b, err := json.Marshal(v)
	if err != nil {
		return
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	f.Write(append(b, '\n'))
	f.Close()
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
	var sig []string
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
		if !neutralTestFlags[name] {
			sig = append(sig, a)
		}
		runArgs = append(runArgs, a)
	}

	stamp := fmt.Sprintf("%020d-%s", time.Now().UnixNano(), sanitize(pkg))
	partBase := filepath.Join(sess.Dir, "parts", stamp)
	evPath := partBase + ".events"
	evf, err := os.Create(evPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
		return 2
	}
	outR, outW, _ := os.Pipe()
	inR, inW, _ := os.Pipe()

	// skip cache: what can be reused
	var cache *skip.Package
	var static string
	var state *skip.State
	childEnv := os.Environ()
	initSeed := core.DeriveSeed(sess.Seed, pkg+"::<init>")
	explore := 0
	if sess.Det && sess.Seed != 0 {
		explore = 1
	}
	cfg := fmt.Sprintf("ctl=%d;epoch=%d;tick=%d;adapt=%d;seed=%d;root=%s;goroot=%s;maxev=%d;explore=%d",
		sess.Ctl, sess.Epoch, sess.Tick, sess.Adapt, initSeed, sess.Root, sess.Goroot, sess.MaxEvents, explore)
	childEnv = append(childEnv, "FENVIX_GO_DET="+cfg, "FENVIX_GO_FDS=3,4,5")
	if sess.GoMaxProcs != "" {
		childEnv = append(childEnv, "GOMAXPROCS="+sess.GoMaxProcs)
	}
	if sess.Skip != nil {
		cache = skip.Load(sess.Skip.Dir, pkg)
		binDigest := binaryContentID(sess.Goroot, bin)
		static = skip.Hash(append([]string{"bin", binDigest, "go", sess.GoVersion, sess.GOOS, sess.GOARCH,
			"cgo", sess.CgoEnabled, "overlay", sess.OverlayHash, "ctl", strconv.Itoa(int(sess.Ctl)),
			"seed", strconv.FormatUint(sess.Seed, 10), "epoch", strconv.FormatInt(sess.Epoch, 10),
			"tick", strconv.FormatInt(sess.Tick, 10), "gomaxprocs", sess.GoMaxProcs, "flags"},
			append(append([]string{}, sess.BuildFlags...), sig...)...)...)
		state = skip.NewState(core.DigestFile, os.Environ())
	}

	// control pipe: names -> order, seeds, tests to leave out
	var names, order, fullOrder []string
	stdout := &reusePrinter{w: os.Stdout}
	wouldReuse := map[string]bool{}
	whyOwn := map[string]string{}
	why := map[string]string{}
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
			names = strings.Split(line[2:], "\x1f")
			if len(names) == 1 && names[0] == "" {
				names = nil
			}
			idx := make([]int, len(names))
			for i := range idx {
				idx[i] = i
			}
			if sess.Det && sess.Seed != 0 {
				idx = core.ShuffleIndices(len(names), sess.Seed, pkg)
			}
			var ord, seeds []string
			reused := map[string]*skip.Entry{}
			for _, i := range idx {
				name := names[i]
				fullOrder = append(fullOrder, name)
				if cache != nil {
					w := cache.Tests[name].Why(static, state)
					why[name] = w
					whyOwn[name] = cache.Own[name].Why(static, state)
					if w == "" {
						wouldReuse[name] = true
						if !sess.Skip.Verify {
							reused[name] = cache.Tests[name]
							continue
						}
					}
				}
				ord = append(ord, strconv.Itoa(i))
				seeds = append(seeds, strconv.FormatUint(core.DeriveSeed(sess.Seed, pkg+"::"+name), 10))
				order = append(order, name)
			}
			stdout.setReused(reused)
			fmt.Fprintf(inW, "O\x1f%s\x1f%s\n", strings.Join(ord, ","), strings.Join(seeds, ","))
		}
	}()

	// reused tests are reported before the binary runs the others
	var cmdArgs []string
	logPath := partBase + ".strace"
	useStrace := sess.Skip != nil && sess.Skip.Capture == "strace"
	if useStrace {
		cmdArgs = append(strace.Args(logPath), bin)
	} else {
		cmdArgs = []string{bin}
	}
	cmdArgs = append(cmdArgs, runArgs...)
	cmd := exec.Command(cmdArgs[0], cmdArgs[1:]...)
	cmd.Stdin, cmd.Stderr = os.Stdin, os.Stderr
	stdout.json, stdout.verbose = testJSON, verbose
	cmd.Stdout = stdout
	cmd.Env = childEnv
	cmd.ExtraFiles = []*os.File{evf, outW, inR}
	if err := cmd.Start(); err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
		return 2
	}
	evf.Close()
	outW.Close()
	inR.Close()
	runErr := cmd.Wait()
	outR.Close()
	inW.Close()
	ctlWG.Wait()
	stdout.flushReused()
	code := exitCode(runErr)

	// events -> fingerprints (Rust core) -> partial trace
	recs, _ := readRecords(evPath)
	rec := core.NewRecorder(0, 0)
	defer rec.Free()
	if err := rec.Open(partBase+".jsonl", traceMeta(sess, pkg), prefixed(pkg, order)); err != nil {
		fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
	}
	type result struct {
		outcome string
		elapsed float64
		deps    *skip.Raw
		pos     int
	}
	results := map[string]*result{}
	keepPath := func(string) bool { return true }
	if sess.Skip != nil {
		f := &strace.Filter{Roots: sess.Skip.Roots, Ignore: sess.Skip.Ignore}
		keepPath = f.Keep
	}
	pkgRaw := skip.NewRaw()
	var cur string
	idx := 0
	for _, r := range recs {
		switch r.kind {
		case 'I':
			parseDeps(r.payload, pkgRaw, keepPath)
		case 'B':
			cur = string(r.payload)
			rec.BeginTest(pkg+"::"+cur, uint64(idx))
			results[cur] = &result{outcome: "interrupted", deps: skip.NewRaw(), pos: idx}
			idx++
		case 'E':
			if _, err := rec.RecordPacked(r.payload); err != nil {
				fmt.Fprintln(os.Stderr, "fenvix-go exec:", err)
			}
		case 'D':
			if res := results[cur]; res != nil {
				parseDeps(r.payload, res.deps, keepPath)
			}
		case 'X':
			parts := strings.Split(string(r.payload), "\x1f")
			if res := results[cur]; res != nil {
				res.outcome = parts[0]
				if len(parts) > 2 {
					ns, _ := strconv.ParseInt(parts[2], 10, 64)
					res.elapsed = float64(ns) / 1e9
				}
			}
			rec.EndTest(parts[0])
			cur = ""
		}
	}
	rec.Close()
	os.Remove(evPath)

	if sess.Skip != nil {
		var st *strace.Result
		if useStrace {
			st, err = strace.Parse(logPath, cwd, &strace.Filter{Roots: sess.Skip.Roots, Ignore: sess.Skip.Ignore})
			if err != nil {
				fmt.Fprintln(os.Stderr, "fenvix-go exec: strace:", err)
				st = nil
			}
			os.Remove(logPath)
		}
		capture := sess.Skip.Capture
		if useStrace && st == nil {
			capture = ""
		}
		proxies := loopbackProxyPorts(state.Env)
		toRaw := func(d *strace.Deps, raw *skip.Raw, dropFirstExec bool) {
			if d == nil {
				return
			}
			for p := range d.Reads {
				raw.Reads[p] = true
			}
			for p := range d.Exists {
				raw.Exists[p] = true
			}
			for p := range d.Missing {
				raw.Missing[p] = true
			}
			for p := range d.Lists {
				raw.Lists[p] = true
			}
			ex := d.Execs
			if dropFirstExec && len(ex) > 0 {
				ex = ex[1:] // the test binary itself
			}
			raw.Execs = append(raw.Execs, ex...)
			for _, c := range d.Net {
				port, _ := strconv.Atoi(c[1])
				if !isLocal(c[0], port, proxies) {
					raw.Net = append(raw.Net, net.JoinHostPort(c[0], c[1]))
				}
			}
		}
		if st != nil {
			toRaw(st.Segments[-1], pkgRaw, true)
		}
		// Prefix closure: a test also depends on everything the tests before
		// it in the same process read (shared process state: a file loaded
		// once by an earlier test, a cached configuration...).
		closure := map[string]*skip.Raw{}
		ownRaw := map[string]*skip.Raw{}
		before := map[string][]*skip.Entry{} // reused tests that came before (their recorded inputs)
		acc := skip.NewRaw()
		acc.Merge(pkgRaw)
		var accEntries []*skip.Entry
		for _, name := range fullOrder {
			res := results[name]
			if res == nil {
				if e := cache.Tests[name]; e != nil && wouldReuse[name] {
					accEntries = append(accEntries, e)
				}
				continue
			}
			own := skip.NewRaw()
			own.Merge(res.deps)
			if st != nil {
				toRaw(st.Segments[res.pos], own, false)
			}
			o := skip.NewRaw()
			o.Merge(pkgRaw)
			o.Merge(own)
			ownRaw[name] = o
			acc.Merge(own)
			c := skip.NewRaw()
			c.Merge(acc)
			closure[name] = c
			before[name] = append([]*skip.Entry(nil), accEntries...)
		}
		decPath := filepath.Join(sess.Dir, "decisions.jsonl")
		for _, name := range names {
			d := decision{Pkg: pkg, Test: name, Commit: sess.Skip.Commit}
			if e := cache.Tests[name]; e != nil {
				d.Cached, d.CachedElapsed = e.Outcome, e.Elapsed
			}
			d.Reuse = wouldReuse[name]
			d.Why = why[name]
			d.WhyOwn = whyOwn[name]
			d.ReuseOwn = cache != nil && whyOwn[name] == ""
			res := results[name]
			if res == nil {
				appendJSONL(decPath, d)
				continue // reused (not run) or filtered out by -run
			}
			d.Fresh, d.Elapsed = res.outcome, res.elapsed
			appendJSONL(decPath, d)
			raw := closure[name]
			for p := range raw.Exists {
				if state.File(p) == "-" {
					delete(raw.Exists, p) // the run's own output, gone now
				}
			}
			e := skip.MakeEntry(static, res.outcome, res.elapsed, raw, state, capture, bin)
			for _, prev := range before[name] {
				e.Absorb(prev)
			}
			e.Commit = sess.Skip.Commit
			cache.Tests[name] = e
			if o := ownRaw[name]; o != nil {
				for p := range o.Exists {
					if state.File(p) == "-" {
						delete(o.Exists, p)
					}
				}
				if cache.Own == nil {
					cache.Own = map[string]*skip.Entry{}
				}
				cache.Own[name] = skip.MakeEntry(static, res.outcome, res.elapsed, o, state, capture, bin)
			}
		}
		if err := cache.Save(sess.Skip.Dir); err != nil {
			fmt.Fprintln(os.Stderr, "fenvix-go exec: skip cache:", err)
		}
	}
	return code
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

// reusePrinter passes the binary's output through and, before its first
// byte, reports the tests reused with proof in the format go test expects.
type reusePrinter struct {
	w             io.Writer
	json, verbose bool
	reused        map[string]*skip.Entry
	mu            sync.Mutex
	done          bool
}

func (p *reusePrinter) setReused(m map[string]*skip.Entry) {
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
	names := make([]string, 0, len(p.reused))
	for n := range p.reused {
		names = append(names, n)
	}
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
