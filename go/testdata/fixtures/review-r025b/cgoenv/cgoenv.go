// Package cgoenv reads a variable from C (a C library's own configuration
// variable: OPENSSL_CONF, KRB5_CONFIG, PGHOST through libpq...).
package cgoenv

/*
#include <stdlib.h>
static int mode_set(void) { return getenv("R25B_CMODE") != NULL; }
*/
import "C"

// ModeSet says whether R25B_CMODE is set, as the C library sees it.
func ModeSet() bool { return C.mode_set() != 0 }
