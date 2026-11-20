package procstat

import (
	"os"
	"strings"
	"testing"
)

func fields(t *testing.T) []string {
	b, err := os.ReadFile("/proc/1/stat")
	if err != nil {
		t.Skip(err)
	}
	s := string(b)
	return strings.Fields(s[strings.LastIndexByte(s, ')')+1:]) // from field 3
}

// TestInitStat: a dependency reads /proc/1/stat at init (gopsutil-style) and
// parses it: it must still work.
func TestInitStat(t *testing.T) {
	f := fields(t)
	if len(f) < 20 {
		t.Fatalf("short stat: %v", f)
	}
	t.Logf("stat: %s", strings.Join(f, " "))
}

// TestRealCPUTime depends on a field that changes by itself (utime, field
// 14): under fenvix it sees the virtual constant 100 in every run.
func TestRealCPUTime(t *testing.T) {
	if utime := fields(t)[14-3]; utime != "100" {
		t.Fatalf("utime %s: the real, changing value", utime)
	}
}
