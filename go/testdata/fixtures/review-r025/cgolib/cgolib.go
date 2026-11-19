package cgolib

/*
#cgo LDFLAGS: -L${SRCDIR}/lib -lfx
#include "fx.h"
*/
import "C"

// Fx calls the native library.
func Fx() int { return int(C.fx()) }
