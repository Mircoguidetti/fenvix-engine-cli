// Regressions found on real projects (flaky round r3).
package regressions

import (
	"net"
	"testing"
	"time"
)

// rclone: t.Deadline() (real clock) minus the virtual now gave -6m40s.
func TestDeadlineArithmetic(t *testing.T) {
	d, ok := t.Deadline()
	if ok && time.Until(d) <= 0 {
		t.Fatalf("deadline already passed: %v", time.Until(d))
	}
}

// temporal (suspected): a server on the machine's own non-loopback address was blocked.
func TestOwnAddress(t *testing.T) {
	addrs, _ := net.InterfaceAddrs()
	for _, a := range addrs {
		ipn, ok := a.(*net.IPNet)
		if !ok || ipn.IP.IsLoopback() || ipn.IP.To4() == nil {
			continue
		}
		l, err := net.Listen("tcp", ipn.IP.String()+":0")
		if err != nil {
			continue
		}
		defer l.Close()
		go func() {
			c, err := l.Accept()
			if err == nil {
				c.Close()
			}
		}()
		c, err := net.Dial("tcp", l.Addr().String())
		if err != nil {
			t.Fatalf("own address %s: %v", l.Addr(), err)
		}
		c.Close()
		return
	}
}

// quic-go, terraform: goroutines sleeping at the same time added up their
// durations on the virtual clock (two 20 ms sleeps in parallel = 40 ms).
func TestConcurrentSleepsDoNotAddUp(t *testing.T) {
	start := time.Now()
	done := make(chan struct{})
	for i := 0; i < 4; i++ {
		go func() { time.Sleep(20 * time.Millisecond); done <- struct{}{} }()
	}
	for i := 0; i < 4; i++ {
		<-done
	}
	if el := time.Since(start); el > 30*time.Millisecond {
		t.Fatalf("4 parallel 20 ms sleeps took %v on the virtual clock", el)
	}
}

// quic-go (smoke test; the race window is hard to force): a timer that fired
// and was then Reset to a long duration moved
// the virtual clock to the new deadline (idle timeout "exceeded" at once).
func TestResetAfterFireDoesNotJump(t *testing.T) {
	start := time.Now()
	tm := time.NewTimer(time.Millisecond)
	for i := 0; i < 200; i++ {
		<-tm.C
		tm.Reset(time.Millisecond) // fire, then immediately reset (fresh due time)
	}
	tm.Reset(time.Hour)
	time.Sleep(5 * time.Millisecond)
	tm.Stop()
	if el := time.Since(start); el > 10*time.Second {
		t.Fatalf("virtual clock jumped: %v", el)
	}
}
