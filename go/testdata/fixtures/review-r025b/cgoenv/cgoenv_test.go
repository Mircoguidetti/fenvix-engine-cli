package cgoenv

import "testing"

func TestDefaultMode(t *testing.T) {
	if ModeSet() {
		t.Fatal("the C library runs in another mode")
	}
}
