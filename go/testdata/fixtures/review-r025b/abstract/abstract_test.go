// A local service reached through an abstract unix socket (no file: the name
// starts with a NUL byte), as dbus, containerd shims and some test
// supervisors use.
package abstract

import (
	"io"
	"net"
	"testing"
)

func TestServiceSaysOK(t *testing.T) {
	c, err := net.Dial("unix", "@r25b-service")
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	b, _ := io.ReadAll(c)
	if string(b) != "ok" {
		t.Fatalf("service says %q", b)
	}
}
