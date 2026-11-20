// Command fenvix-go is the Go shell of fenvix (deterministic CI): a wrapper
// around `go test` that
//
//   - with --det, builds the tests against a build-time overlay of the Go
//     standard library (seeded and recorded test and package order, seeded
//     math/rand, math/rand/v2 and crypto/rand, deterministic map order,
//     virtual clock, sorted directory listings, network closed except
//     loopback, t.Parallel serialised) and writes a trace with one execution
//     fingerprint per test (Rust core, same format as Python and Node);
//   - with --skip-cache DIR, reuses with proof the passing tests whose
//     inputs did not change (the key and the decision are the Rust core's:
//     crates/fenvix-go/src/skip.rs);
//   - `fenvix-go verify A.jsonl B.jsonl` names the first diverging event.
//
// Usage:
//
//	fenvix-go test [--det] [--det-seed=N] [--det-disable=c1,c2] [--det-trace=PATH]
//	               [--skip-cache=DIR] [--skip-verify] [go test flags] [packages]
//	fenvix-go verify TRACE...
//	fenvix-go overlay            (print the overlay for the current toolchain)
//	fenvix-go exec BINARY ARGS   (internal: started by go test -exec)
package main

import (
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var code int
	switch os.Args[1] {
	case "test":
		code = cmdTest(os.Args[2:])
	case "exec":
		code = cmdExec(os.Args[2:])
	case "verify":
		code = cmdVerify(os.Args[2:])
	case "overlay":
		code = cmdOverlay(os.Args[2:])
	case "-h", "--help", "help":
		usage()
	default:
		fmt.Fprintf(os.Stderr, "fenvix-go: unknown command %q\n", os.Args[1])
		usage()
		code = 2
	}
	os.Exit(code)
}

func usage() {
	fmt.Fprint(os.Stderr, `usage:
  fenvix-go test [fenvix flags] [go test flags] [packages]
  fenvix-go verify TRACE...
  fenvix-go overlay

fenvix flags:
  --det                    deterministic run (Level 0) and trace
  --det-seed=N             0 (default) = source order; N = shuffled order and seeds for exploration
  --det-disable=a,b        turn controls off: time,random,crypto,maps,fs,net,serial,fastwait
  --det-trace=PATH         trace file (default .fenvix/go-trace-<seed>.jsonl)
  --det-epoch=RFC3339      virtual wall clock at every test start (default 2025-01-01T00:00:00Z)
  --det-tick=NS            clock tick per read (default 1000)
  --det-gomaxprocs=N       set GOMAXPROCS for the test binaries (recorded either way)
  --skip-cache=DIR         reuse passing tests whose inputs did not change (skip with proof)
  --skip-verify            run every test anyway and check each reuse against the fresh outcome
  --skip-real-clock        nightly check: run every test on the real clock (the cache is read, not
                           written) and list the tests that pass on the virtual day (skip mode's
                           clock: today 00:00 UTC) and fail on the real clock: expired fixtures
  --skip-capture=MODE      strace (default when available) or hooks
  --skip-report=PATH       JSON lines: one decision per test
  --skip-commit=SHA        informative, stored with the cache entries
  --fenvix-dir=DIR         keep the session (parts, logs) in DIR
`)
}
