// A panic in a goroutine the test started (not recovered by the testing
// package): the whole binary crashes.
package crashgo

import (
	"testing"
	"time"
)

func TestGoroutinePanics(t *testing.T) {
	go func() { panic("boom") }()
	time.Sleep(100 * time.Millisecond)
}
