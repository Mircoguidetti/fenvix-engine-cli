// Fixtures for fenvix-go: each test depends on one source of
// non-determinism, so it fails in some runs without --det and has one
// outcome (and one fingerprint) in every run with --det.
package controls

import (
	crand "crypto/rand"
	"math/rand"
	randv2 "math/rand/v2"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"sync"
	"testing"
	"time"
)

// --- order: TestOrderUser passes only if TestOrderSetup ran first.
var configured bool

func TestOrderSetup(t *testing.T) { configured = true }

func TestOrderUser(t *testing.T) {
	if !configured {
		t.Fatal("depends on TestOrderSetup having run before")
	}
}

// --- random: math/rand global source.
func TestRandom(t *testing.T) {
	if rand.Intn(2) == 1 {
		t.Fatal("unlucky math/rand draw")
	}
}

// --- random: math/rand/v2 global source.
func TestRandomV2(t *testing.T) {
	if randv2.IntN(2) == 1 {
		t.Fatal("unlucky math/rand/v2 draw")
	}
}

// --- crypto: crypto/rand.
func TestCrypto(t *testing.T) {
	b := make([]byte, 1)
	crand.Read(b)
	if b[0]&1 == 1 {
		t.Fatal("unlucky crypto/rand byte")
	}
}

// --- maps: iteration order.
func TestMapOrder(t *testing.T) {
	m := map[int]bool{}
	for i := 0; i < 16; i++ {
		m[i] = true
	}
	for k := range m {
		if k%2 == 1 {
			t.Fatalf("first key %d is odd", k)
		}
		break
	}
}

// --- time: wall clock reading.
func TestClockParity(t *testing.T) {
	if time.Now().Nanosecond()/1000%2 == 0 {
		t.Fatal("even microsecond")
	}
}

// --- time: elapsed time across a sleep and a timer.
func TestElapsed(t *testing.T) {
	start := time.Now()
	time.Sleep(2 * time.Millisecond)
	<-time.After(3 * time.Millisecond)
	if el := time.Since(start); el.Microseconds()%2 == 0 {
		t.Fatalf("even elapsed %v", el)
	}
}

// --- time: AfterFunc and a ticker move the clock to their due time.
func TestTimers(t *testing.T) {
	start := time.Now()
	done := make(chan time.Duration, 1)
	time.AfterFunc(4*time.Millisecond, func() { done <- time.Since(start) })
	el := <-done
	tk := time.NewTicker(time.Millisecond)
	<-tk.C
	<-tk.C
	tk.Stop()
	if el.Microseconds()%2 == 0 {
		t.Fatalf("even elapsed %v", el)
	}
}

// --- fs: directory listing order.
func TestListing(t *testing.T) {
	dir := t.TempDir()
	for i := 0; i < 12; i++ {
		f, err := os.CreateTemp(dir, "f")
		if err != nil {
			t.Fatal(err)
		}
		f.Close()
	}
	d, err := os.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	names, _ := d.Readdirnames(-1)
	sorted := append([]string(nil), names...)
	sort.Strings(sorted)
	if names[0] != sorted[0] {
		t.Fatalf("listing not in name order: %v", names[:3])
	}
}

// --- net: an address outside the machine.
func TestNetworkOff(t *testing.T) {
	c, err := net.DialTimeout("tcp", "192.0.2.1:9", 300*time.Millisecond)
	if err == nil {
		c.Close()
	}
	t.Log("dial:", err)
}

// --- net: loopback stays allowed.
func TestLoopback(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	go func() {
		c, err := l.Accept()
		if err == nil {
			c.Write([]byte("hi"))
			c.Close()
		}
	}()
	c, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	b := make([]byte, 2)
	if _, err := c.Read(b); err != nil || string(b) != "hi" {
		t.Fatal("loopback broken", err)
	}
}

// --- serial: two parallel tests race on a shared log.
var (
	logMu sync.Mutex
	log   []string
)

func TestParallelA(t *testing.T) {
	t.Parallel()
	logMu.Lock()
	log = append(log, "A")
	logMu.Unlock()
}

func TestParallelB(t *testing.T) {
	t.Parallel()
	time.Sleep(time.Duration(rand.Intn(200)) * time.Microsecond)
	logMu.Lock()
	defer logMu.Unlock()
	log = append(log, "B")
	if len(log) != 2 || log[0] != "A" {
		t.Fatalf("parallel order %v", log)
	}
}

// --- a file in the package directory (skip key fixture).
func TestReadsData(t *testing.T) {
	b, err := os.ReadFile(filepath.Join("testdata", "input.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if want := os.Getenv("CONTROLS_WANT"); want != "" && string(b) != want {
		t.Fatalf("input %q, want %q", b, want)
	}
	_ = strconv.Itoa(len(b))
}
