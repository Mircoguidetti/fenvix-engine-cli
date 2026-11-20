package hinit

import (
	"testing"

	"example.com/r025/hinit/dep"
)

func TestConfigFromInit(t *testing.T) {
	if dep.Config != "cfg1\n" {
		t.Fatalf("config %q", dep.Config)
	}
}
