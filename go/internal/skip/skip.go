// Package skip is the per-test cache with proof for Go tests.
//
// A top-level test is reused (not run, its passing outcome reported) only when
// everything its last passing run depended on is unchanged:
//
//   - code executed: the compiled test binary (its digest covers the package,
//     its test files, every imported package, the Go toolchain and runtime,
//     GOOS/GOARCH, build tags and flags, cgo objects linked statically, and
//     the fenvix overlay);
//   - test configuration: the test flags that change behaviour (-short, -cpu,
//     custom flags...), the --det controls and seed;
//   - runtime identity: Go version, GOOS/GOARCH, CGO_ENABLED, and (strace)
//     every shared library, tzdata or certificate file the run read;
//   - files read by the test and by the package set-up (init, TestMain):
//     content digest; paths stat'ed must still exist, paths probed missing
//     must still be missing, directories listed must list the same names;
//   - environment variables read (by name, value digest), always including
//     those the Go runtime and libc read below the hooks; a test that started
//     another program depends on the whole environment;
//   - never reused: a test that failed, was skipped, connected to an address
//     outside the machine (or a loopback proxy), or ran without a dependency
//     capture.
package skip

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// AlwaysEnv are read below the hooks (Go runtime, libc, time zone): always in the key.
var AlwaysEnv = []string{"GODEBUG", "GOGC", "GOMAXPROCS", "GOMEMLIMIT", "GOTRACEBACK", "GORACE", "TZ", "ZONEINFO",
	"LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "LC_NUMERIC", "LC_TIME", "LC_COLLATE",
	"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy",
	"SSL_CERT_FILE", "SSL_CERT_DIR", "GOCOVERDIR"}

// Entry is the record of one test's last run.
type Entry struct {
	Static  string            `json:"static"`  // binary, flags, runtime identity, det config
	Outcome string            `json:"outcome"` // passed / failed / skipped
	Elapsed float64           `json:"elapsed"` // seconds (informative)
	Files   map[string]string `json:"files"`   // path -> content digest
	Exists  []string          `json:"exists"`
	Missing []string          `json:"missing"`
	Lists   map[string]string `json:"lists"` // dir -> digest of the sorted names
	Env     map[string]string `json:"env"`   // name -> value digest ("*" = whole environment)
	Net     []string          `json:"net"`   // outside addresses contacted
	Execs   []string          `json:"execs"`
	Capture string            `json:"capture"`
	Commit  string            `json:"commit,omitempty"`
}

// Package is the cache file of one package.
type Package struct {
	Pkg   string            `json:"pkg"`
	Tests map[string]*Entry `json:"tests"`
	// Own: measurement only (never used to skip): the same entries without
	// the prefix rule (each test's own inputs plus package set-up), to
	// measure what the prefix rule costs and whether dropping it is wrong.
	Own map[string]*Entry `json:"own,omitempty"`
}

func fileFor(dir, pkg string) string {
	h := sha256.Sum256([]byte(pkg))
	return filepath.Join(dir, hex.EncodeToString(h[:])[:24]+".json")
}

// Load reads a package's cache (empty when absent).
func Load(dir, pkg string) *Package {
	p := &Package{Pkg: pkg, Tests: map[string]*Entry{}}
	b, err := os.ReadFile(fileFor(dir, pkg))
	if err != nil {
		return p
	}
	if json.Unmarshal(b, p) != nil || p.Tests == nil {
		return &Package{Pkg: pkg, Tests: map[string]*Entry{}}
	}
	return p
}

// Save writes a package's cache atomically.
func (p *Package) Save(dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	b, err := json.Marshal(p)
	if err != nil {
		return err
	}
	f := fileFor(dir, p.Pkg)
	tmp := f + ".tmp"
	if err := os.WriteFile(tmp, b, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, f)
}

// Hash is a short digest of strings.
func Hash(parts ...string) string {
	h := sha256.New()
	for _, p := range parts {
		fmt.Fprintf(h, "%d:%s\x00", len(p), p)
	}
	return hex.EncodeToString(h.Sum(nil))[:32]
}

// State answers questions about the machine now; memoised per run.
type State struct {
	DigestFile func(string) string // "" when unreadable
	Env        map[string]string   // the environment the test binary gets
	files      map[string]string
	lists      map[string]string
}

// NewState builds a State for the given environment.
func NewState(digestFile func(string) string, env []string) *State {
	m := map[string]string{}
	for _, kv := range env {
		if i := strings.IndexByte(kv, '='); i > 0 {
			m[kv[:i]] = kv[i+1:]
		}
	}
	return &State{DigestFile: digestFile, Env: m, files: map[string]string{}, lists: map[string]string{}}
}

// File is the digest of a file now ("-" missing, "d" directory).
func (s *State) File(p string) string {
	if v, ok := s.files[p]; ok {
		return v
	}
	v := "-"
	if st, err := os.Stat(p); err == nil {
		if st.IsDir() {
			v = "d"
		} else if d := s.DigestFile(p); d != "" {
			v = d
		} else {
			v = "?unreadable"
		}
	}
	s.files[p] = v
	return v
}

// List is the digest of a directory's sorted entry names now.
func (s *State) List(dir string) string {
	if v, ok := s.lists[dir]; ok {
		return v
	}
	ents, err := os.ReadDir(dir)
	v := "-"
	if err == nil {
		names := make([]string, len(ents))
		for i, e := range ents {
			names[i] = e.Name()
		}
		sort.Strings(names)
		v = Hash(names...)
	}
	s.lists[dir] = v
	return v
}

// EnvValue is the digest of a variable's value now ("" when unset).
func (s *State) EnvValue(name string) string {
	if name == "*" {
		keys := make([]string, 0, len(s.Env))
		for k := range s.Env {
			if strings.HasPrefix(k, "FENVIX_GO_") {
				continue
			}
			keys = append(keys, k)
		}
		sort.Strings(keys)
		parts := make([]string, 0, 2*len(keys))
		for _, k := range keys {
			parts = append(parts, k, s.Env[k])
		}
		return Hash(parts...)
	}
	v, ok := s.Env[name]
	if !ok {
		return ""
	}
	return Hash(v)
}

// Why returns "" when the entry can be reused now, else the first reason not to.
func (e *Entry) Why(static string, s *State) string {
	switch {
	case e == nil:
		return "new"
	case e.Capture == "":
		return "no-capture"
	case e.Outcome != "passed":
		return "last-" + e.Outcome
	case len(e.Net) > 0:
		return "network"
	case e.Static != static:
		return "code-or-config"
	}
	for name, h := range e.Env {
		if s.EnvValue(name) != h {
			return "env:" + name
		}
	}
	for p, h := range e.Files {
		if s.File(p) != h {
			return "file:" + p
		}
	}
	for _, p := range e.Exists {
		if s.File(p) == "-" {
			return "vanished:" + p
		}
	}
	for _, p := range e.Missing {
		if s.File(p) != "-" {
			return "appeared:" + p
		}
	}
	for d, h := range e.Lists {
		if s.List(d) != h {
			return "listing:" + d
		}
	}
	return ""
}

// Raw is what a run observed for one test (test and package deps merged).
type Raw struct {
	Reads, Exists, Missing, Lists, Env map[string]bool
	Net, Execs                         []string
}

// NewRaw returns an empty Raw.
func NewRaw() *Raw {
	return &Raw{Reads: map[string]bool{}, Exists: map[string]bool{}, Missing: map[string]bool{}, Lists: map[string]bool{},
		Env: map[string]bool{}}
}

// Merge adds o into r.
func (r *Raw) Merge(o *Raw) {
	if o == nil {
		return
	}
	for k := range o.Reads {
		r.Reads[k] = true
	}
	for k := range o.Exists {
		r.Exists[k] = true
	}
	for k := range o.Missing {
		r.Missing[k] = true
	}
	for k := range o.Lists {
		r.Lists[k] = true
	}
	for k := range o.Env {
		r.Env[k] = true
	}
	r.Net = append(r.Net, o.Net...)
	r.Execs = append(r.Execs, o.Execs...)
}

// MakeEntry turns observations into an entry, hashing the current state.
func MakeEntry(static, outcome string, elapsed float64, raw *Raw, s *State, capture, selfBinary string) *Entry {
	e := &Entry{Static: static, Outcome: outcome, Elapsed: elapsed, Files: map[string]string{}, Lists: map[string]string{},
		Env: map[string]string{}, Capture: capture}
	for p := range raw.Reads {
		e.Files[p] = s.File(p)
	}
	for p := range raw.Exists {
		if _, ok := e.Files[p]; !ok {
			e.Exists = append(e.Exists, p)
		}
	}
	for p := range raw.Missing {
		e.Missing = append(e.Missing, p)
	}
	for d := range raw.Lists {
		e.Lists[d] = s.List(d)
	}
	for _, n := range AlwaysEnv {
		e.Env[n] = s.EnvValue(n)
	}
	for n := range raw.Env {
		e.Env[n] = s.EnvValue(n)
	}
	foreign := false
	for _, x := range raw.Execs {
		if x != selfBinary {
			foreign = true
			e.Execs = append(e.Execs, x)
			if _, ok := e.Files[x]; !ok && strings.HasPrefix(x, "/") {
				e.Files[x] = s.File(x)
			}
		}
	}
	if foreign {
		// another program inherits the environment and reads what it wants
		e.Env["*"] = s.EnvValue("*")
	}
	e.Net = append(e.Net, raw.Net...)
	sort.Strings(e.Exists)
	sort.Strings(e.Missing)
	sort.Strings(e.Execs)
	return e
}

// Absorb adds the recorded inputs of a test that ran before this one in the
// same process (and was reused): this test may depend on state it left.
func (e *Entry) Absorb(prev *Entry) {
	for k, v := range prev.Files {
		if _, ok := e.Files[k]; !ok {
			e.Files[k] = v
		}
	}
	for k, v := range prev.Lists {
		if _, ok := e.Lists[k]; !ok {
			e.Lists[k] = v
		}
	}
	for k, v := range prev.Env {
		if _, ok := e.Env[k]; !ok {
			e.Env[k] = v
		}
	}
	e.Exists = mergeSorted(e.Exists, prev.Exists)
	e.Missing = mergeSorted(e.Missing, prev.Missing)
	e.Net = append(e.Net, prev.Net...)
}

func mergeSorted(a, b []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, x := range append(append([]string{}, a...), b...) {
		if !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	sort.Strings(out)
	return out
}
