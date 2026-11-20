// Package a regenerates a file shared with package b (a golden file, a
// generated schema). go test runs packages in parallel.
package a

import (
	"os"
	"testing"
	"time"
)

func TestRegenerateShared(t *testing.T) {
	time.Sleep(1 * time.Second)
	if err := os.WriteFile("../shared/state.txt", []byte("v2\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}
