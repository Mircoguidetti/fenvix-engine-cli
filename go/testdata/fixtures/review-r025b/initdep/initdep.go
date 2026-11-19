// Package initdep reads the clock in its initialisation, before any test.
package initdep

import "time"

var Start = time.Now()
