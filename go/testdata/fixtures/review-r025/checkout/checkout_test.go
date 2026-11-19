package checkout

import (
	"os"
	"testing"
)

func TestValue(t *testing.T) {
	b, err := os.ReadFile("testdata/value.txt")
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "one\n" {
		t.Fatalf("value = %q", b)
	}
}
