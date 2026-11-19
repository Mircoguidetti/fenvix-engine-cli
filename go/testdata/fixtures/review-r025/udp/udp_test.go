package udp

import (
	"net"
	"testing"
)

// TestSendsOutside sends one datagram to an outside address (TEST-NET-1,
// RFC 5737) with WriteTo: sendto(2), no connect(2). statsd/syslog/mDNS-style
// clients and ICMP/UDP probes do this.
func TestSendsOutside(t *testing.T) {
	c, err := net.ListenPacket("udp4", ":0")
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	_, err = c.WriteTo([]byte("ping"), &net.UDPAddr{IP: net.IPv4(192, 0, 2, 1), Port: 9})
	t.Logf("sendto 192.0.2.1:9: %v", err)
}
