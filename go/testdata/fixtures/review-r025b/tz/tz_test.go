// The local time zone comes from TZ or /etc/localtime.
package tz

import (
	"testing"
	"time"
)

func TestLocalIsUTC(t *testing.T) {
	if name, off := time.Now().Local().Zone(); off != 0 {
		t.Fatalf("local zone %s, offset %d", name, off)
	}
}
