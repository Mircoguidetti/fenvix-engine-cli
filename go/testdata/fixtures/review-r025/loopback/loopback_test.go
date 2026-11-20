package loopback

import (
	"io"
	"net/http"
	"os"
	"testing"
)

// TestLocalService asks a service listening on loopback (address from a
// variable whose value does not change).
func TestLocalService(t *testing.T) {
	resp, err := http.Get("http://" + os.Getenv("R025_ADDR") + "/")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	if string(b) != "schema-v1" {
		t.Fatalf("service says %q", b)
	}
}
