// Each test compares a wall-clock reading that does not go through package
// time with time.Now: a timestamp written by a C library, by a helper program
// written in Go, or read with a raw system call, checked against the test's
// own clock with a tolerance (testdata/limit.txt, in ns). Plain go test
// passes all three whenever the tolerance is a few seconds. Under skip mode the
// difference is the real time since 00:00 UTC, which grows during the day,
// while the key holds the day only.
package clockreal

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"example.com/r025b/initdep"
)

func limit(t *testing.T) time.Duration {
	b, err := os.ReadFile("testdata/limit.txt")
	if err != nil {
		t.Fatal(err)
	}
	n, err := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
	if err != nil {
		t.Fatal(err)
	}
	return time.Duration(n)
}

func check(t *testing.T, what string, other int64) {
	d := time.Unix(0, other).Sub(time.Now())
	if d < 0 {
		d = -d
	}
	if l := limit(t); d > l {
		t.Fatalf("%s clock differs from time.Now by %v (tolerance %v)", what, d, l)
	}
}

// A helper program written in Go, built with cgo (so it is dynamically
// linked and fenvix keys it as a reusable child), prints its clock.
func TestGoHelperClock(t *testing.T) {
	p, _ := filepath.Abs("../clockprint/clockprint")
	out, err := exec.Command(p).Output()
	if err != nil {
		t.Fatal(err)
	}
	n, err := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
	if err != nil {
		t.Fatal(err)
	}
	check(t, "helper", n)
}

func TestCgoClock(t *testing.T) { check(t, "cgo", CNow()) }

func TestRawSyscallClock(t *testing.T) { check(t, "raw syscall", RawNow()) }

// Held: a dependency's package-level time.Now runs under the virtual clock.
func TestInitClock(t *testing.T) { check(t, "init", initdep.Start.UnixNano()) }
