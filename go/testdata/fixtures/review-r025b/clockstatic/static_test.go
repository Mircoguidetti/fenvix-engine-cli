// A statically linked helper (a Go program built without cgo): the report says
// it ignores the preloaded clock and the test is never reused (exec:).
package clockstatic

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestStaticHelper(t *testing.T) {
	p, _ := filepath.Abs("../clockprint/clockprint-static")
	if err := exec.Command(p).Run(); err != nil {
		t.Fatal(err)
	}
}
