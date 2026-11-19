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
