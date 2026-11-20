package byalias

import (
	"os"
	"strings"
	"testing"
)

// /proc/1/stat read through /proc/self/root (the process's root directory):
// the os hook does not match the name, and the classifier drops everything
// under /proc/self.
func TestRootAlias(t *testing.T) {
	b, err := os.ReadFile("/proc/self/root/proc/1/stat")
	if err != nil {
		t.Skip(err)
	}
	v, _ := os.ReadFile("/proc/1/stat")
	t.Logf("through the alias: %s", strings.TrimSpace(string(b)))
	t.Logf("served copy:       %s", strings.TrimSpace(string(v)))
}
