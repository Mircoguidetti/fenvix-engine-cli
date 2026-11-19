// A test that panics: go test reports FAIL and the binary exits 2.
package panicky

import "testing"

func TestPanics(t *testing.T) {
	var m map[string]int
	m["x"] = 1 // assignment to a nil map: panic
}
