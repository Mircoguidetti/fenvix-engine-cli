// Package overlay builds the `go build -overlay` file that turns the Go
// standard library of one toolchain into its fenvix variant: a few files are
// added to standard packages (the shared state lives in package runtime) and
// a few functions are patched at stable anchors (function headers). Each
// control depends on its patches; a patch whose anchor is missing in this
// toolchain disables that control and the reason is reported, never hidden.
package overlay

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

//go:embed files/*.txt
var files embed.FS

// Control names, in bit order (keep in sync with files/runtime.go.txt).
const (
	CtlTime     = "time"
	CtlRandom   = "random"
	CtlCrypto   = "crypto"
	CtlMaps     = "maps"
	CtlFs       = "fs"
	CtlNet      = "net"
	CtlSerial   = "serial"
	CtlDeps     = "deps"
	CtlFastWait = "fastwait"
)

// Bits maps a control name to its bit.
var Bits = map[string]uint32{
	CtlTime: 1 << 0, CtlRandom: 1 << 1, CtlCrypto: 1 << 2, CtlMaps: 1 << 3, CtlFs: 1 << 4,
	CtlNet: 1 << 5, CtlSerial: 1 << 6, CtlDeps: 1 << 7, CtlFastWait: 1 << 8,
}

// DetControls are the controls `--det` turns on (deps is added by the skip
// cache, fastwait follows time).
var DetControls = []string{CtlTime, CtlRandom, CtlCrypto, CtlMaps, CtlFs, CtlNet, CtlSerial, CtlFastWait}

type op struct {
	kind   string // "insert": add text after the anchor line; "replace": replace the anchor line
	anchor string // the exact line (trimmed); an anchor ending in "(" matches a function header
	text   string
}

// A patch group is applied whole or not at all. Hook code that needs a group
// sits between "// fenvix:if <group>" and "// fenvix:end" in the added files
// and is dropped with the group.
type patch struct {
	group string
	file  string // relative to GOROOT/src
	ops   []op
}

type addition struct {
	file  string // relative to GOROOT/src
	tmpl  string // embedded template
	needs string // group the whole file needs ("" = core)
}

var patches = []patch{
	{group: "time", file: "runtime/time.go", ops: []op{
		{kind: "replace", anchor: "//go:linkname timeSleep time.Sleep", text: "//go:linkname timeSleep time.fenvixRealSleep"},
	}},
	{group: "time", file: "time/time.go", ops: []op{
		{kind: "insert", anchor: "func Now() Time {", text: "\tif fenvixTimeOn() {\n\t\tif t, ok := fenvixNow(\"time.Now\"); ok {\n\t\t\treturn t\n\t\t}\n\t}"},
		{kind: "insert", anchor: "func Since(t Time) Duration {", text: "\tif fenvixTimeOn() {\n\t\tif n, ok := fenvixNow(\"time.Since\"); ok {\n\t\t\treturn n.Sub(t)\n\t\t}\n\t}"},
		{kind: "insert", anchor: "func Until(t Time) Duration {", text: "\tif fenvixTimeOn() {\n\t\tif n, ok := fenvixNow(\"time.Until\"); ok {\n\t\t\treturn t.Sub(n)\n\t\t}\n\t}"},
	}},
	{group: "time", file: "time/sleep.go", ops: []op{
		{kind: "replace", anchor: "func Sleep(d Duration)", text: "// Sleep: see zz_fenvix.go"},
		{kind: "replace", anchor: "func NewTimer(d Duration) *Timer {", text: "func fenvixOrigNewTimer(d Duration) *Timer {"},
		{kind: "replace", anchor: "func AfterFunc(d Duration, f func()) *Timer {", text: "func fenvixOrigAfterFunc(d Duration, f func()) *Timer {"},
		{kind: "replace", anchor: "func (t *Timer) Reset(d Duration) bool {", text: "func (t *Timer) fenvixOrigReset(d Duration) bool {"},
		{kind: "replace", anchor: "func (t *Timer) Stop() bool {", text: "func (t *Timer) fenvixOrigStop() bool {"},
	}},
	{group: "time", file: "time/sleep.go", ops: []op{
		// the timer API of Go 1.23 and later (Go 1.22 has another one)
		{kind: "replace", anchor: "func newTimer(when, period int64, f func(any, uintptr, int64), arg any, cp unsafe.Pointer) *Timer", text: "func newTimer(when, period int64, f func(any, uintptr, int64), arg any, cp unsafe.Pointer) *Timer"},
	}},
	{group: "time", file: "time/tick.go", ops: []op{
		{kind: "replace", anchor: "func NewTicker(d Duration) *Ticker {", text: "func fenvixOrigNewTicker(d Duration) *Ticker {"},
		{kind: "replace", anchor: "func (t *Ticker) Reset(d Duration) {", text: "func (t *Ticker) fenvixOrigReset(d Duration) {"},
	}},
	{group: "time-deps", file: "time/time.go", ops: []op{
		// skip key: an observation of the wall clock (review R-025 F6)
		{kind: "insert", anchor: "func (t *Time) sec() int64 {", text: "\tif t.wall&hasMonotonic != 0 {\n\t\tfenvixWallSeen()\n\t}"},
		{kind: "insert", anchor: "func (t Time) Nanosecond() int {", text: "\tif t.wall&hasMonotonic != 0 {\n\t\tfenvixWallSeen()\n\t}"},
		{kind: "insert", anchor: "func (t Time) After(u Time) bool {", text: "\tif (t.wall^u.wall)&hasMonotonic != 0 && fenvixClockDeps() {\n\t\treturn fenvixCompare(t, u) > 0\n\t}"},
		{kind: "insert", anchor: "func (t Time) Before(u Time) bool {", text: "\tif (t.wall^u.wall)&hasMonotonic != 0 && fenvixClockDeps() {\n\t\treturn fenvixCompare(t, u) < 0\n\t}"},
		{kind: "insert", anchor: "func (t Time) Compare(u Time) int {", text: "\tif (t.wall^u.wall)&hasMonotonic != 0 && fenvixClockDeps() {\n\t\treturn fenvixCompare(t, u)\n\t}"},
		{kind: "insert", anchor: "func (t Time) Equal(u Time) bool {", text: "\tif (t.wall^u.wall)&hasMonotonic != 0 && fenvixClockDeps() {\n\t\treturn fenvixCompare(t, u) == 0\n\t}"},
	}},
	{group: "cheaprand", file: "runtime/rand.go", ops: []op{
		// select, semaphores and linkname users (review R-025 D3): the same
		// deterministic source as map seeds on user goroutines
		{kind: "insert", anchor: "func cheaprand() uint32 {", text: "\tif fenvixRandHook() {\n\t\treturn uint32(fenvixMapsRand() >> 32)\n\t}"},
	}},
	{group: "getrandom", file: "syscall/syscall_linux.go", ops: []op{
		// getrandom(2) called directly (x/sys/unix.Getrandom...): the test's crypto stream (R-025 D3)
		{kind: "insert", anchor: "func Syscall(trap, a1, a2, a3 uintptr) (r1, r2 uintptr, err Errno) {", text: "\tif fenvixRawRandOn && fenvixIsGetrandom(trap) {\n\t\treturn fenvixRawGetrandom(a1, a2), 0, 0\n\t}"},
		{kind: "insert", anchor: "func Syscall6(trap, a1, a2, a3, a4, a5, a6 uintptr) (r1, r2 uintptr, err Errno) {", text: "\tif fenvixRawRandOn && fenvixIsGetrandom(trap) {\n\t\treturn fenvixRawGetrandom(a1, a2), 0, 0\n\t}"},
	}},
	{group: "getrandom-raw", file: "syscall/syscall_linux.go", ops: []op{
		// Go 1.23 and later (RawSyscall6 is written in Go)
		{kind: "insert", anchor: "func RawSyscall(trap, a1, a2, a3 uintptr) (r1, r2 uintptr, err Errno) {", text: "\tif fenvixRawRandOn && fenvixIsGetrandom(trap) {\n\t\treturn fenvixRawGetrandom(a1, a2), 0, 0\n\t}"},
		{kind: "insert", anchor: "func RawSyscall6(trap, a1, a2, a3, a4, a5, a6 uintptr) (r1, r2 uintptr, err Errno) {", text: "\tif fenvixRawRandOn && fenvixIsGetrandom(trap) {\n\t\treturn fenvixRawGetrandom(a1, a2), 0, 0\n\t}"},
	}},
	{group: "net-ports", file: "net/tcpsock_posix.go", ops: []op{
		{kind: "replace", anchor: "func (sl *sysListener) listenTCP(ctx context.Context, laddr *TCPAddr) (*TCPListener, error) {", text: "func (sl *sysListener) fenvixOrigListenTCP(ctx context.Context, laddr *TCPAddr) (*TCPListener, error) {"},
	}},
	{group: "net-ports", file: "net/udpsock_posix.go", ops: []op{
		{kind: "replace", anchor: "func (sl *sysListener) listenUDP(ctx context.Context, laddr *UDPAddr) (*UDPConn, error) {", text: "func (sl *sysListener) fenvixOrigListenUDP(ctx context.Context, laddr *UDPAddr) (*UDPConn, error) {"},
	}},
	{group: "maps-alg", file: "runtime/alg.go", ops: []op{
		{kind: "replace", anchor: "func alginit() {", text: "func fenvixOrigAlginit() {"},
	}},
	{group: "maps-rand", file: "runtime/rand.go", ops: []op{
		{kind: "insert", anchor: "func rand() uint64 {", text: "\tif fenvixRandHook() {\n\t\treturn fenvixMapsRand()\n\t}"},
	}},
	{group: "rand-v1", file: "math/rand/rand.go", ops: []op{
		{kind: "insert", anchor: "func globalRand() *Rand {", text: "\tif r := fenvixGlobalRand(); r != nil {\n\t\treturn r\n\t}"},
	}},
	{group: "rand-v2", file: "math/rand/v2/rand.go", ops: []op{
		{kind: "insert", anchor: "func (runtimeSource) Uint64() uint64 {", text: "\tif v, ok := fenvixUint64(); ok {\n\t\treturn v\n\t}"},
	}},
	{group: "os-temp", file: "os/tempfile.go", ops: []op{
		{kind: "insert", anchor: "func nextRandom() string {", text: "\tif s, ok := fenvixNextRandom(); ok {\n\t\treturn s\n\t}"},
	}},
	{group: "crypto", file: "crypto/internal/sysrand/rand.go", ops: []op{
		{kind: "insert", anchor: "func Read(b []byte) {", text: "\tif fenvixRead(b) {\n\t\treturn\n\t}"},
	}},
	{group: "crypto-123", file: "crypto/rand/rand_unix.go", ops: []op{
		{kind: "insert", anchor: "func (r *reader) Read(b []byte) (n int, err error) {", text: "\tif fenvixRead(b) {\n\t\treturn len(b), nil\n\t}"},
	}},
	{group: "os-dir", file: "os/dir.go", ops: []op{
		{kind: "replace", anchor: "func (f *File) Readdir(n int) ([]FileInfo, error) {", text: "func (f *File) fenvixOrigReaddir(n int) ([]FileInfo, error) {"},
		{kind: "replace", anchor: "func (f *File) Readdirnames(n int) (names []string, err error) {", text: "func (f *File) fenvixOrigReaddirnames(n int) (names []string, err error) {"},
		{kind: "replace", anchor: "func (f *File) ReadDir(n int) ([]DirEntry, error) {", text: "func (f *File) fenvixOrigReadDir(n int) ([]DirEntry, error) {"},
	}},
	{group: "os-open", file: "os/file.go", ops: []op{
		{kind: "insert", anchor: "func OpenFile(name string, flag int, perm FileMode) (*File, error) {", text: "\tfenvixDepOpen(name, flag)"},
	}},
	{group: "os-stat", file: "os/stat.go", ops: []op{
		{kind: "insert", anchor: "func Stat(name string) (FileInfo, error) {", text: "\tfenvixDep('S', name)"},
		{kind: "insert", anchor: "func Lstat(name string) (FileInfo, error) {", text: "\tfenvixDep('S', name)"},
	}},
	{group: "os-exec", file: "os/exec.go", ops: []op{
		{kind: "insert", anchor: "func StartProcess(name string, argv []string, attr *ProcAttr) (*Process, error) {", text: "\tfenvixDep('X', name)"},
	}},
	{group: "env", file: "syscall/env_unix.go", ops: []op{
		{kind: "insert", anchor: "func Getenv(key string) (value string, found bool) {", text: "\tfenvixDepEnv(key)"},
		{kind: "insert", anchor: "func Environ() []string {", text: "\tfenvixDepEnv(\"*\")"},
	}},
	{group: "net", file: "net/hook_unix.go", ops: []op{
		{kind: "replace", anchor: "connectFunc       func(int, syscall.Sockaddr) error = syscall.Connect", text: "\tconnectFunc       func(int, syscall.Sockaddr) error = syscall.Connect // fenvix: replaced in zz_fenvix.go init"},
	}},
	{group: "core", file: "testing/testing.go", ops: []op{
		{kind: "insert", anchor: "func runTests(", text: "\ttests = fenvixTests(tests)"},
	}},
	{group: "time", file: "testing/testing.go", ops: []op{
		{kind: "replace", anchor: "func (t *T) Deadline() (deadline time.Time, ok bool) {", text: "func (t *T) Deadline() (deadline time.Time, ok bool) {\n\tif d, ok := t.fenvixOrigDeadline(); ok {\n\t\treturn fenvixDeadline(d), true\n\t}\n\treturn time.Time{}, false\n}\n\nfunc (t *T) fenvixOrigDeadline() (deadline time.Time, ok bool) {"},
	}},
	{group: "serial", file: "testing/testing.go", ops: []op{
		{kind: "insert", anchor: "func (t *T) Parallel() {", text: "\tif fenvixSerial() {\n\t\treturn\n\t}"},
	}},
}

var additions = []addition{
	{file: "runtime/zz_fenvix.go", tmpl: "runtime.go.txt"},
	{file: "syscall/zz_fenvix.go", tmpl: "syscall.go.txt"},
	{file: "testing/zz_fenvix.go", tmpl: "testing.go.txt"},
	{file: "time/zz_fenvix.go", tmpl: "time.go.txt", needs: "time"},
	{file: "time/zz_fenvix_deps.go", tmpl: "timedeps.go.txt", needs: "time-deps"},
	{file: "math/rand/zz_fenvix.go", tmpl: "mathrand.go.txt", needs: "rand-v1"},
	{file: "math/rand/v2/zz_fenvix.go", tmpl: "mathrandv2.go.txt", needs: "rand-v2"},
	{file: "crypto/internal/sysrand/zz_fenvix.go", tmpl: "sysrand.go.txt", needs: "crypto"},
	{file: "crypto/rand/zz_fenvix.go", tmpl: "cryptorand123.go.txt", needs: "crypto-123"},
	{file: "os/zz_fenvix.go", tmpl: "os.go.txt"},
	{file: "net/zz_fenvix.go", tmpl: "net.go.txt", needs: "net"},
	{file: "net/zz_fenvix_ports.go", tmpl: "netports.go.txt", needs: "net-ports"},
}

// controlGroups: a control is available when all its groups applied.
var controlGroups = map[string][]string{
	CtlTime: {"time"}, CtlFastWait: {"time"}, CtlRandom: {"rand-v1", "rand-v2", "os-temp"},
	CtlCrypto: {"crypto"}, CtlMaps: {"maps-alg", "maps-rand", "cheaprand"}, CtlFs: {"os-dir"},
	CtlNet: {"net", "net-ports"}, CtlSerial: {"serial"}, CtlDeps: {"os-dir", "os-open", "os-stat", "os-exec", "env", "net", "time-deps"},
}

// Result describes a generated overlay.
type Result struct {
	Path        string            `json:"path"`        // the overlay JSON to pass to -overlay
	Dir         string            `json:"dir"`         // where the patched files live
	GoVersion   string            `json:"go_version"`  // toolchain the overlay was built for
	Available   []string          `json:"available"`   // controls whose patches all applied
	Unavailable map[string]string `json:"unavailable"` // control -> why not
	Digest      string            `json:"digest"`      // digest of the overlay content
	Partial     map[string]string `json:"partial"`     // optional hook -> why it is missing (its control works without it)
}

// optionalGroups: hooks a control uses when they apply, without depending on
// them; a missing one is reported at start.
var optionalGroups = map[string]string{
	"getrandom":     "getrandom(2) through syscall.Syscall (x/sys/unix.Getrandom...) not controlled",
	"getrandom-raw": "getrandom(2) through syscall.RawSyscall not controlled",
}

// Has reports whether a control is available.
func (r *Result) Has(c string) bool {
	for _, a := range r.Available {
		if a == c {
			return true
		}
	}
	return false
}

func applyOps(src string, ops []op) (string, error) {
	lines := strings.Split(src, "\n")
	for _, o := range ops {
		found := -1
		for i, l := range lines {
			t := strings.TrimSpace(l)
			if t == strings.TrimSpace(o.anchor) || (strings.HasSuffix(o.anchor, "(") && strings.HasPrefix(t, o.anchor) && strings.HasSuffix(t, "{")) {
				if found >= 0 {
					return "", fmt.Errorf("anchor %q found twice", o.anchor)
				}
				found = i
			}
		}
		if found < 0 {
			return "", fmt.Errorf("anchor %q not found", o.anchor)
		}
		if o.kind == "replace" {
			lines[found] = o.text
		} else {
			lines = append(lines[:found+1], append([]string{o.text}, lines[found+1:]...)...)
		}
	}
	return strings.Join(lines, "\n"), nil
}

// dropSections removes "// fenvix:if <group>" ... "// fenvix:end" blocks of failed groups.
func dropSections(src string, failed map[string]string) string {
	var out []string
	skipping := false
	for _, l := range strings.Split(src, "\n") {
		t := strings.TrimSpace(l)
		if g, ok := strings.CutPrefix(t, "// fenvix:if "); ok {
			if _, bad := failed[strings.TrimSpace(g)]; bad {
				skipping = true
			}
			continue
		}
		if t == "// fenvix:end" {
			skipping = false
			continue
		}
		if !skipping {
			out = append(out, l)
		}
	}
	return strings.Join(out, "\n")
}

// Generate writes the overlay for the toolchain at goroot (version
// goversion) under cacheDir and returns its description. Generation is
// deterministic: the same toolchain and fenvix-go give the same files and the
// same digest, so the Go build cache is reused across runs.
func Generate(goroot, goversion, cacheDir string) (*Result, error) {
	src := filepath.Join(goroot, "src")
	if _, err := os.Stat(filepath.Join(src, "runtime")); err != nil {
		return nil, fmt.Errorf("GOROOT %s has no runtime sources: %w", goroot, err)
	}
	subst := map[string]string{"{{ATOMIC}}": "internal/runtime/atomic", "{{BUBBLED}}": "false"}
	if _, err := os.Stat(filepath.Join(src, "internal/runtime/atomic")); err != nil {
		subst["{{ATOMIC}}"] = "runtime/internal/atomic"
	}
	if b, err := os.ReadFile(filepath.Join(src, "time/time.go")); err == nil && strings.Contains(string(b), "func runtimeIsBubbled() bool") {
		subst["{{BUBBLED}}"] = "runtimeIsBubbled()"
	}

	// 1. try every group on the original files
	failed := map[string]string{}
	orig := map[string]string{}
	for _, p := range patches {
		b, ok := orig[p.file]
		if !ok {
			raw, err := os.ReadFile(filepath.Join(src, p.file))
			if err != nil {
				failed[p.group] = fmt.Sprintf("%s: %v", p.file, err)
				continue
			}
			b = string(raw)
			orig[p.file] = b
		}
		if _, err := applyOps(b, p.ops); err != nil {
			failed[p.group] = fmt.Sprintf("%s: %v", p.file, err)
		}
	}
	if why, bad := failed["core"]; bad {
		return nil, fmt.Errorf("this Go toolchain (%s) cannot be instrumented: %s", goversion, why)
	}
	// 2. apply the groups that work
	out := map[string]string{}
	for _, p := range patches {
		if _, bad := failed[p.group]; bad {
			continue
		}
		cur, ok := out[p.file]
		if !ok {
			cur = orig[p.file]
		}
		next, err := applyOps(cur, p.ops)
		if err != nil {
			return nil, fmt.Errorf("%s: %v", p.file, err)
		}
		out[p.file] = next
	}
	for _, a := range additions {
		if _, bad := failed[a.needs]; bad && a.needs != "" {
			continue
		}
		t, err := files.ReadFile("files/" + a.tmpl)
		if err != nil {
			return nil, err
		}
		s := dropSections(string(t), failed)
		for k, v := range subst {
			s = strings.ReplaceAll(s, k, v)
		}
		out[a.file] = s
	}
	// crypto: Go 1.24+ hooks crypto/internal/sysrand, Go 1.23 crypto/rand
	if _, bad := failed["crypto"]; bad {
		if _, bad123 := failed["crypto-123"]; !bad123 {
			delete(failed, "crypto")
		}
	} else {
		failed["crypto-123"] = "not needed"
		delete(out, "crypto/rand/rand_unix.go")
		delete(out, "crypto/rand/zz_fenvix.go")
	}
	unavailable := map[string]string{}
	for c, groups := range controlGroups {
		for _, g := range groups {
			if why, bad := failed[g]; bad {
				unavailable[c] = why
				break
			}
		}
	}

	keys := make([]string, 0, len(out))
	for k := range out {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	h := sha256.New()
	fmt.Fprintf(h, "%s\x00%s\x00", goroot, goversion)
	for _, k := range keys {
		fmt.Fprintf(h, "%s\x00%d\x00%s", k, len(out[k]), out[k])
	}
	digest := hex.EncodeToString(h.Sum(nil))[:16]
	dir := filepath.Join(cacheDir, "overlay", goversion+"-"+digest)
	replace := map[string]string{}
	for _, k := range keys {
		p := filepath.Join(dir, "src", filepath.FromSlash(k))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			return nil, err
		}
		if old, err := os.ReadFile(p); err != nil || string(old) != out[k] {
			if err := os.WriteFile(p, []byte(out[k]), 0o644); err != nil {
				return nil, err
			}
		}
		replace[filepath.Join(src, filepath.FromSlash(k))] = p
	}
	j, _ := json.MarshalIndent(map[string]any{"Replace": replace}, "", " ")
	path := filepath.Join(dir, "overlay.json")
	if err := os.WriteFile(path, j, 0o644); err != nil {
		return nil, err
	}
	res := &Result{Path: path, Dir: dir, GoVersion: goversion, Unavailable: unavailable, Digest: digest,
		Partial: map[string]string{}}
	for g, what := range optionalGroups {
		if why, bad := failed[g]; bad {
			res.Partial[g] = what + " (" + why + ")"
		}
	}
	for _, c := range append(append([]string{}, DetControls...), CtlDeps) {
		if _, bad := unavailable[c]; !bad {
			res.Available = append(res.Available, c)
		}
	}
	return res, nil
}

// Merge combines the fenvix overlay with a user overlay file (user entries
// win for files fenvix does not touch; a conflict is an error).
func Merge(fenvixPath, userPath, outPath string) error {
	read := func(p string) (map[string]string, error) {
		b, err := os.ReadFile(p)
		if err != nil {
			return nil, err
		}
		var v struct{ Replace map[string]string }
		if err := json.Unmarshal(b, &v); err != nil {
			return nil, fmt.Errorf("%s: %w", p, err)
		}
		return v.Replace, nil
	}
	a, err := read(fenvixPath)
	if err != nil {
		return err
	}
	b, err := read(userPath)
	if err != nil {
		return err
	}
	for k, v := range b {
		if _, ok := a[k]; ok {
			return fmt.Errorf("-overlay: %s is also patched by fenvix-go", k)
		}
		a[k] = v
	}
	j, _ := json.MarshalIndent(map[string]any{"Replace": a}, "", " ")
	return os.WriteFile(outPath, j, 0o644)
}
