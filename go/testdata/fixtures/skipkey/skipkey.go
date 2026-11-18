// Package skipkey is the fixture of the skip-with-proof key: each test
// depends on one kind of input, and a change of that input must make that
// test (and only the tests that depend on it) run again.
package skipkey

// Answer is used by TestOwnCode.
func Answer() int { return 42 }
