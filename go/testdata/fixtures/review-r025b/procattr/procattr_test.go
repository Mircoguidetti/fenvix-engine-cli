// Process attributes the test binary inherits from whoever starts it. None is
// a file read, a variable or a flag: CPU affinity (runtime.NumCPU, the
// default GOMAXPROCS), the umask, resource limits.
package procattr

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// A worker pool or a race-detecting test that needs two CPUs.
func TestTwoCPUs(t *testing.T) {
	if n := runtime.NumCPU(); n < 2 {
		t.Fatalf("NumCPU = %d", n)
	}
}

// A file the code creates with 0666 must end up 0644 (umask 022).
func TestCreatedMode(t *testing.T) {
	p := filepath.Join(t.TempDir(), "f")
	f, err := os.OpenFile(p, os.O_CREATE|os.O_WRONLY, 0o666)
	if err != nil {
		t.Fatal(err)
	}
	f.Close()
	fi, _ := os.Stat(p)
	if m := fi.Mode().Perm(); m != 0o644 {
		t.Fatalf("mode %o", m)
	}
}

// A server test that needs many descriptors reads its limit.
func TestOpenFilesLimit(t *testing.T) {
	b, err := os.ReadFile("/proc/self/limits")
	if err != nil {
		t.Skip(err)
	}
	for _, l := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(l, "Max open files") {
			f := strings.Fields(l)
			if f[3] == "1024" {
				t.Fatalf("soft limit %s", f[3])
			}
			return
		}
	}
	t.Fatal("no Max open files line")
}
