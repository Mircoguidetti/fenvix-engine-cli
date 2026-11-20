package clock

import (
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestFixtureNotExpired: a test certificate / token with a NotAfter date,
// committed in testdata. The content never changes; the date passes.
func TestFixtureNotExpired(t *testing.T) {
	b, err := os.ReadFile("testdata/notafter.txt")
	if err != nil {
		t.Fatal(err)
	}
	sec, _ := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
	if time.Now().After(time.Unix(sec, 0)) {
		t.Fatalf("fixture expired at %v", time.Unix(sec, 0).UTC())
	}
}
