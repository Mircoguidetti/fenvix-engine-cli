package slow

import (
	"testing"
	"time"
)

func TestTakesTwoSeconds(t *testing.T) {
	time.Sleep(2 * time.Second)
}
