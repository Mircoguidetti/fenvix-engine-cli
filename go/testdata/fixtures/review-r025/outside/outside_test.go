package outside

import (
	"os"
	"testing"
)

// TestOutsideFixture reads a fixture provisioned by CI outside the repository
// (path given by a variable, whose value does not change).
func TestOutsideFixture(t *testing.T) {
	b, err := os.ReadFile(os.Getenv("R025_OUTSIDE"))
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "expected\n" {
		t.Fatalf("fixture = %q", b)
	}
}
