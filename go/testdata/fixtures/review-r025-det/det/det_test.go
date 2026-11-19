// Package det: attempts to break --det (review R-025). Each test makes its
// outcome depend on one source; under --det seed 0 every run should give
// one outcome and one fingerprint (or the source is a documented limit).
package det

import (
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"
	"unsafe"
	_ "unsafe"
)

//go:linkname cheaprand runtime.cheaprand
func cheaprand() uint32

//go:linkname fastrand runtime.fastrand
func fastrand() uint32

// runtime.cheaprand through linkname (allowed: bytedance/gopkg, phuslu/log...).
// One goroutine, no interleaving.
func TestLinknameCheaprand(t *testing.T) {
	if v := cheaprand(); v%2 == 1 {
		t.Fatalf("cheaprand() = %d (odd)", v)
	}
}

// runtime.fastrand through linkname (expected controlled: it calls rand()).
func TestLinknameFastrand(t *testing.T) {
	if v := fastrand(); v%2 == 1 {
		t.Fatalf("fastrand() = %d (odd)", v)
	}
}

// getrandom(2) called directly (golang.org/x/sys/unix.Getrandom does this).
func TestRawGetrandom(t *testing.T) {
	var b [1]byte
	_, _, e := syscall.Syscall(318 /* SYS_GETRANDOM amd64 */, uintptr(unsafe.Pointer(&b[0])), 1, 0)
	if e != 0 {
		t.Skip(e)
	}
	if b[0]%2 == 1 {
		t.Fatalf("getrandom byte %d (odd)", b[0])
	}
}

// A kernel-chosen ephemeral port: two servers sorted by address string
// (common when a test builds a member list or a golden output from addresses).
func TestEphemeralPorts(t *testing.T) {
	a, _ := net.Listen("tcp", "127.0.0.1:0")
	b, _ := net.Listen("tcp", "127.0.0.1:0")
	defer a.Close()
	defer b.Close()
	if a.Addr().String() > b.Addr().String() {
		t.Fatalf("first listener sorts after the second: %s > %s", a.Addr(), b.Addr())
	}
}

// select among two ready channels, one goroutine (documented: cheaprand).
func TestSelectReady(t *testing.T) {
	c1, c2 := make(chan int, 1), make(chan int, 1)
	c1 <- 1
	c2 <- 2
	select {
	case <-c1:
	case <-c2:
		t.Fatal("select chose c2")
	}
}

// sync.Pool, one goroutine: Put then Get after a blocking syscall.
func TestSyncPool(t *testing.T) {
	p := sync.Pool{New: func() any { return "new" }}
	p.Put("pooled")
	os.ReadFile("/etc/hostname")
	time.Sleep(time.Millisecond)
	if v := p.Get(); v != "pooled" {
		t.Fatalf("pool returned %v", v)
	}
}

// reflect over a map (expected controlled: map seed and iteration start).
func TestReflectMapOrder(t *testing.T) {
	m := map[string]int{}
	for i := 0; i < 16; i++ {
		m[strconv.Itoa(i)] = i
	}
	if k := reflect.ValueOf(m).MapKeys()[0].String(); k[0] < '5' {
		t.Fatalf("first key %s", k)
	}
}

// A file's mtime is set by the kernel's real clock; the test compares it
// with time.Now (a cache TTL / staleness check).
func TestMtimeTTL(t *testing.T) {
	p := filepath.Join(t.TempDir(), "entry")
	os.WriteFile(p, []byte("x"), 0o644)
	time.Sleep(20 * time.Millisecond)
	st, _ := os.Stat(p)
	if age := time.Since(st.ModTime()); age < 10*time.Millisecond {
		t.Fatalf("cache entry age %v after sleeping 20ms: not stale", age)
	}
}

// A child process's clock (git commit dates, `date`, any tool) against time.Now.
func TestChildClock(t *testing.T) {
	out, err := exec.Command("date", "+%s").Output()
	if err != nil {
		t.Skip(err)
	}
	sec, _ := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
	if d := time.Since(time.Unix(sec, 0)); d < -time.Hour || d > time.Hour {
		t.Fatalf("child clock and time.Now differ by %v", d)
	}
}

// time.AfterFunc then Sleep past its delay (no goroutine started by the test).
func TestAfterFuncThenSleep(t *testing.T) {
	var mu sync.Mutex
	fired := false
	time.AfterFunc(time.Millisecond, func() { mu.Lock(); fired = true; mu.Unlock() })
	time.Sleep(50 * time.Millisecond)
	mu.Lock()
	defer mu.Unlock()
	if !fired {
		t.Fatal("AfterFunc(1ms) had not fired after Sleep(50ms)")
	}
}
