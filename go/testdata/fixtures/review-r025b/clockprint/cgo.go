//go:build cgo

package main

// linking libc makes the program dynamically linked

/*
#include <stdlib.h>
*/
import "C"
