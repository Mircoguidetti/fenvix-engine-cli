// Variants of the R-025 --det findings D1-D3 (review R-025b). Each test
// passes in every plain run when its source is deterministic, or shows the
// uncontrolled source by varying.
package det

import (
	"hash/maphash"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
)

// D1 variants: fastwait skips a Sleep when "the test started no goroutine and
// no timer of the test is due". A timer whose channel is read after the
// sleep, and a worker goroutine started by package initialisation (not by
// the test), are both pending work the Sleep is waiting for.

func TestTimerChannelThenSleep(t *testing.T) {
	tm := time.NewTimer(time.Millisecond)
	time.Sleep(50 * time.Millisecond)
	select {
	case <-tm.C:
	default:
		t.Fatal("timer did not fire during the sleep")
	}
}

var (
	jobs = make(chan int, 1)
	done atomic.Int64
)

func init() {
	go func() {
		for j := range jobs {
			done.Add(int64(j))
		}
	}()
}

func TestInitWorkerThenSleep(t *testing.T) {
	jobs <- 1
	time.Sleep(50 * time.Millisecond)
	if done.Load() != 1 {
		t.Fatal("the worker did not run during the sleep")
	}
}

// D2 variants: real time next to the virtual clock.

func TestSyscallStatMtime(t *testing.T) {
	p := filepath.Join(t.TempDir(), "f")
	os.WriteFile(p, nil, 0o644)
	var st syscall.Stat_t
	if err := syscall.Stat(p, &st); err != nil {
		t.Fatal(err)
	}
	if d := time.Since(time.Unix(st.Mtim.Unix())); d < -time.Minute || d > time.Minute {
		t.Fatalf("file written now is %v old", d)
	}
}

func TestChildStatVersusChildDate(t *testing.T) {
	p := filepath.Join(t.TempDir(), "f")
	out, err := exec.Command("sh", "-c", `touch "$1"; echo $(( $(date +%s) - $(stat -c %Y "$1") ))`, "sh", p).Output()
	if err != nil {
		t.Skip(err)
	}
	d, _ := strconv.Atoi(strings.TrimSpace(string(out)))
	if d < -60 || d > 60 {
		t.Fatalf("in the same shell, date and the file's mtime differ by %d s", d)
	}
}

// D3 variants: entropy in one goroutine.

func TestMaphashSeed(t *testing.T) {
	if maphash.String(maphash.MakeSeed(), "x")%2 != 0 {
		t.Fatal("odd")
	}
}

func TestSyncMapRange(t *testing.T) {
	var m sync.Map
	for i := 0; i < 16; i++ {
		m.Store(i, i)
	}
	first := -1
	m.Range(func(k, v any) bool { first = k.(int); return false })
	if first%2 != 0 {
		t.Fatalf("first key %d", first)
	}
}

func TestPid(t *testing.T) {
	if os.Getpid()%2 != 0 {
		t.Fatalf("pid %d", os.Getpid())
	}
}

func TestDevUrandom(t *testing.T) {
	f, err := os.Open("/dev/urandom")
	if err != nil {
		t.Skip(err)
	}
	defer f.Close()
	b := make([]byte, 1)
	f.Read(b)
	if b[0]%2 != 0 {
		t.Fatalf("byte %d", b[0])
	}
}
