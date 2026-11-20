package hmain

import (
	"os"
	"testing"
)

var loaded string

func TestMain(m *testing.M) {
	b, _ := os.ReadFile("testdata/m.txt")
	loaded = string(b)
	os.Exit(m.Run())
}

func TestLoadedInMain(t *testing.T) {
	if loaded != "m1\n" {
		t.Fatalf("loaded %q", loaded)
	}
}
