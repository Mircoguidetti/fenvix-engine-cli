// A file of the package read through /proc/self/cwd (the same file as
// testdata/value.txt).
package cwdalias

import (
	"os"
	"testing"
)

func TestValueThroughCwdAlias(t *testing.T) {
	b, err := os.ReadFile("/proc/self/cwd/testdata/value.txt")
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "v1\n" {
		t.Fatalf("value %q", b)
	}
}
