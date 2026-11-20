// A configuration file must belong to the user (ssh, gpg, kubeconfig-style
// permission checks).
package owner

import (
	"os"
	"syscall"
	"testing"
)

func TestConfigOwnedByMe(t *testing.T) {
	fi, err := os.Stat("testdata/conf")
	if err != nil {
		t.Fatal(err)
	}
	if uid := fi.Sys().(*syscall.Stat_t).Uid; int(uid) != os.Getuid() {
		t.Fatalf("owned by %d, I am %d", uid, os.Getuid())
	}
}
