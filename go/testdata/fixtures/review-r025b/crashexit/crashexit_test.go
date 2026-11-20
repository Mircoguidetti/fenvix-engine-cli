// log.Fatal inside a test: os.Exit(1) from the test.
package crashexit

import (
	"log"
	"testing"
)

func TestLogFatal(t *testing.T) { log.Fatal("cannot continue") }
