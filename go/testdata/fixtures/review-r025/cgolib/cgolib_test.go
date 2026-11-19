package cgolib

import "testing"

// TestNative: the result of the native library the loader picked.
func TestNative(t *testing.T) {
	if got := Fx(); got != 1 {
		t.Fatalf("fx() = %d, want 1", got)
	}
}
