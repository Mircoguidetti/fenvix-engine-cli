package skipkey

import (
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"example.com/skipkey/lib"
)

func TestIndependent(t *testing.T) {}

func TestOwnCode(t *testing.T) {
	if Answer() != 42 {
		t.Fatal("answer")
	}
}

func TestDependency(t *testing.T) {
	if lib.Value() != 1 {
		t.Fatal("value")
	}
}

func TestDataFile(t *testing.T) {
	if _, err := os.ReadFile(filepath.Join("testdata", "data.txt")); err != nil {
		t.Fatal(err)
	}
}

func TestExternalFile(t *testing.T) {
	p := os.Getenv("SKIPKEY_EXTERNAL")
	if p == "" {
		t.Skip("SKIPKEY_EXTERNAL not set")
	}
	if _, err := os.ReadFile(p); err != nil {
		t.Fatal(err)
	}
}

func TestEnv(t *testing.T) {
	_ = os.Getenv("SKIPKEY_ENV")
}

func TestTimeZone(t *testing.T) {
	// package time reads TZ below package os (go's own test cache misses it)
	_ = time.Unix(0, 0).In(time.Local).String()
}

func TestMissingPath(t *testing.T) {
	if _, err := os.Stat(filepath.Join("testdata", "optional.txt")); err == nil {
		t.Log("optional file present")
	}
}

func TestListing(t *testing.T) {
	ents, err := os.ReadDir(filepath.Join("testdata", "dir"))
	if err != nil {
		t.Fatal(err)
	}
	_ = len(ents)
}

func TestShortFlag(t *testing.T) {
	if testing.Short() {
		t.Log("short")
	}
}

func TestFailsOnDemand(t *testing.T) {
	if os.Getenv("SKIPKEY_FAIL") == "1" {
		t.Fatal("asked to fail")
	}
}

func TestSubprocess(t *testing.T) {
	out, err := exec.Command("cat", filepath.Join("testdata", "sub.txt")).Output()
	if err != nil || len(out) == 0 {
		t.Fatal(err)
	}
}

func TestNetwork(t *testing.T) {
	c, err := net.DialTimeout("tcp", "192.0.2.1:9", 200*time.Millisecond)
	if err == nil {
		c.Close()
	}
}
