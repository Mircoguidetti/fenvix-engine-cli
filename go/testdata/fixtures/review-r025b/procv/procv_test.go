// Readers of /proc/1/stat that use the changing fields: a CPU-usage check and
// a memory ratio (process monitors, container detection heuristics). Plain go
// test reads the real file.
package procv

import (
	"os"
	"strconv"
	"strings"
	"testing"
)

func field(t *testing.T, n int) int64 {
	b, err := os.ReadFile("/proc/1/stat")
	if err != nil {
		t.Skip(err)
	}
	s := string(b)
	f := strings.Fields(s[strings.LastIndexByte(s, ')')+1:])
	v, _ := strconv.ParseInt(f[n-3], 10, 64)
	return v
}

// PID 1 has used some CPU since boot.
func TestPid1UsedCPU(t *testing.T) {
	if field(t, 14)+field(t, 15) == 0 {
		t.Fatal("pid 1 has used no CPU time")
	}
}

// Resident share of pid 1's address space, in percent (integer division).
func TestPid1MemoryRatio(t *testing.T) {
	rssPages, vsize := field(t, 24), field(t, 23)
	if pct := rssPages * 4096 * 100 / vsize; pct > 100 {
		t.Fatalf("rss %d%% of vsize", pct)
	}
}
