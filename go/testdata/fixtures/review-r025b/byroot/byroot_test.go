package byroot

import (
	"io"
	"os"
	"testing"
)

// /proc/1/stat opened through os.Root (openat relative to /proc).
func TestRootOpen(t *testing.T) {
	r, err := os.OpenRoot("/proc")
	if err != nil {
		t.Skip(err)
	}
	defer r.Close()
	f, err := r.Open("1/stat")
	if err != nil {
		t.Skip(err)
	}
	defer f.Close()
	b, _ := io.ReadAll(f)
	t.Logf("stat: %s", b)
}
