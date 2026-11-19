package bysys

import (
	"syscall"
	"testing"
)

// /proc/1/stat opened with syscall.Open, below the os.OpenFile hook.
func TestSyscallOpen(t *testing.T) {
	fd, err := syscall.Open("/proc/1/stat", syscall.O_RDONLY, 0)
	if err != nil {
		t.Skip(err)
	}
	b := make([]byte, 512)
	n, _ := syscall.Read(fd, b)
	syscall.Close(fd)
	t.Logf("stat: %s", b[:n])
}
