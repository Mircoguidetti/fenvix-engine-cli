package controls

import (
	"runtime"
	"sync"
	"testing"
	"time"
)

// Level 1, not controlled by --det: goroutine interleaving. The final value
// depends on how two goroutines interleave; the fingerprint shows the
// difference (thread numbers and event order), the test does not fail.
// fenvix-go measures this (Level 1), it does not control it.
func TestInterleaving(t *testing.T) {
	var mu sync.Mutex
	var order []int
	var wg sync.WaitGroup
	for g := 0; g < 2; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			for i := 0; i < 50; i++ {
				mu.Lock()
				order = append(order, g)
				_ = time.Now() // an event: its thread number shows the interleaving
				mu.Unlock()
				runtime.Gosched()
			}
		}(g)
	}
	wg.Wait()
	t.Logf("first switches: %v", order[:10])
}
