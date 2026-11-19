// The test's own /proc/self/stat: its nice value (field 19), inherited from
// whoever started the run.
package procself

import (
	"os"
	"strings"
	"testing"
)

func TestNotNiced(t *testing.T) {
	b, err := os.ReadFile("/proc/self/stat")
	if err != nil {
		t.Skip(err)
	}
	s := string(b)
	f := strings.Fields(s[strings.LastIndexByte(s, ')')+1:])
	if f[19-3] != "0" {
		t.Fatalf("running at nice %s", f[19-3])
	}
}
