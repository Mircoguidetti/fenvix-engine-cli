// The two clocks meet (fenvix fix for R-025b S1, terraform
// TestMetaBackend_GetStateStoreProviderFactory): a Go program the test starts
// reads the real clock, the test reads the virtual day. Compared, they differ
// by the time of day (a certificate the program makes is "not yet valid").
// Added by fenvix next to the reviewer's fixtures; not a reviewer scenario.
package clockmeet

import (
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func childNow(t *testing.T) time.Time {
	p, _ := filepath.Abs("../clockprint/clockprint-static")
	out, err := exec.Command(p).Output()
	if err != nil {
		t.Fatal(err)
	}
	ns, err := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
	if err != nil {
		t.Fatal(err)
	}
	return time.Unix(0, ns)
}

func TestClockMeetsChild(t *testing.T) {
	if d := time.Since(childNow(t)); d > time.Minute || d < -time.Minute {
		t.Fatalf("the program's clock and the test's differ by %v", d)
	}
}

// a real failure stays a failure on the real clock
func TestGenuineFailWithChild(t *testing.T) {
	childNow(t)
	t.Fatal("genuine failure")
}

func TestPlain(t *testing.T) {}
