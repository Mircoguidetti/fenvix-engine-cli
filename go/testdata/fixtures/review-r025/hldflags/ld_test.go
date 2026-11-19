package hldflags

import "testing"

var Version = "dev"

func TestVersion(t *testing.T) {
	if Version != "dev" && Version != "1.0" {
		t.Fatalf("version %q", Version)
	}
}
