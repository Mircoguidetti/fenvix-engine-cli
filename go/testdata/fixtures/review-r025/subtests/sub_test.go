package subtests

import "testing"

func TestParent(t *testing.T) {
	t.Run("ok", func(t *testing.T) {})
	t.Run("broken", func(t *testing.T) { t.Fatal("this subtest fails") })
}
