// A test that polls a named pipe without blocking (a status pipe of a
// supervisor, a log fifo).
package fifo

import (
	"syscall"
	"testing"
)

func TestPollFifo(t *testing.T) {
	fd, err := syscall.Open("testdata/status.fifo", syscall.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		t.Skip(err)
	}
	syscall.Close(fd)
}
