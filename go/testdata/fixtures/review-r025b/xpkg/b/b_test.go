package b

import (
	"os"
	"testing"
	"time"
)

func TestReadsShared(t *testing.T) {
	b, err := os.ReadFile("../shared/state.txt")
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "v1\n" {
		t.Fatalf("state %q", b)
	}
	time.Sleep(3 * time.Second)
}
