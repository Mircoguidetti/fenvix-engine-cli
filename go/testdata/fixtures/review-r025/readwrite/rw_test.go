package readwrite

import (
	"os"
	"testing"
)

// TestReadsState checks the committed state file.
func TestReadsState(t *testing.T) {
	b, err := os.ReadFile("testdata/state.txt")
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "v1\n" {
		t.Fatalf("state.txt = %q, want v1", b)
	}
}

// TestRegenerates rewrites the file (a generator test, "go generate"-style).
func TestRegenerates(t *testing.T) {
	if err := os.WriteFile("testdata/state.txt", []byte("v2\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}
