// The machine's network configuration, read through netlink (net.Interfaces):
// a test that needs a non-loopback interface (multicast, a bind to the
// machine's address, "is the network up").
package netcfg

import (
	"net"
	"testing"
)

func TestHasNonLoopbackInterface(t *testing.T) {
	ifs, err := net.Interfaces()
	if err != nil {
		t.Fatal(err)
	}
	for _, i := range ifs {
		if i.Flags&net.FlagLoopback == 0 && i.Flags&net.FlagUp != 0 {
			return
		}
	}
	t.Fatalf("no non-loopback interface up: %v", ifs)
}
