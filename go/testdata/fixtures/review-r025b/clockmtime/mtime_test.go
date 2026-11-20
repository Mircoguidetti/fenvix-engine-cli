// A freshness check on a file's age: a cache entry, a downloaded fixture, a
// lock or pid file. Its outcome depends on the real time since the file was
// written. Under skip mode the file's mtime is shifted by the offset between
// the virtual and the real clock at test start, so the age the test sees is
// real elapsed time, while the key holds only the mtime and the UTC day.
package clockmtime

import (
	"os"
	"strings"
	"testing"
	"time"
)

func TestStampIsFresh(t *testing.T) {
	fi, err := os.Stat("testdata/stamp")
	if err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile("testdata/ttl.txt")
	ttl, err := time.ParseDuration(strings.TrimSpace(string(b)))
	if err != nil {
		t.Fatal(err)
	}
	if age := time.Since(fi.ModTime()); age > ttl {
		t.Fatalf("stamp is %v old, ttl %v", age, ttl)
	}
}
