package hembed

import (
	_ "embed"
	"testing"
)

//go:embed testdata/e.txt
var e string

func TestEmbedded(t *testing.T) {
	if e != "e1\n" {
		t.Fatalf("embedded %q", e)
	}
}
