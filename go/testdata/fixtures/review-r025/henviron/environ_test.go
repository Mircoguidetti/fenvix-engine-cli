package henviron

import (
	"os"
	"strings"
	"testing"
)

// koanf/viper-style: every APP_* variable, through os.Environ.
func TestPrefixedEnv(t *testing.T) {
	for _, kv := range os.Environ() {
		if strings.HasPrefix(kv, "R025_APP_") && kv != "R025_APP_MODE=safe" {
			t.Fatalf("unexpected %s", kv)
		}
	}
}
