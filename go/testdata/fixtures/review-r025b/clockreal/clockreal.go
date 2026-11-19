// Package clockreal reads the wall clock where the virtual clock does not
// reach: C code (cgo) and a raw clock_gettime system call.
package clockreal

/*
#include <time.h>
static long long cnow(void) { struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts); return (long long)ts.tv_sec*1000000000LL + ts.tv_nsec; }
*/
import "C"

import (
	"syscall"
	"unsafe"
)

// CNow is clock_gettime(CLOCK_REALTIME) called from C, in Unix ns.
func CNow() int64 { return int64(C.cnow()) }

// RawNow is the clock_gettime system call made directly (as x/sys/unix or
// assembly would), in Unix ns.
func RawNow() int64 {
	var ts syscall.Timespec
	syscall.Syscall(syscall.SYS_CLOCK_GETTIME, 0, uintptr(unsafe.Pointer(&ts)), 0)
	return ts.Nano()
}
