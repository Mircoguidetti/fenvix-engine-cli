// clockprint prints the wall clock (Unix ns). Built with cgo (cgo.go) it is a
// dynamically linked program: fenvix keys it as a reusable child, but the Go
// runtime reads the clock through the vDSO, not through libc. Built without
// cgo it is statically linked.
package main

import (
	"fmt"
	"time"
)

func main() { fmt.Println(time.Now().UnixNano()) }
