// Inputs that are absent when the test is recorded: the test looks for them,
// does not find them, and behaves accordingly. Each scenario then creates the
// input; the test fails with it.
package absent

import (
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestNoOverride(t *testing.T) {
	if _, err := os.Stat("testdata/override.json"); !errors.Is(err, fs.ErrNotExist) {
		t.Fatal("override present")
	}
}

func TestGoldenGlob(t *testing.T) {
	m, _ := filepath.Glob("testdata/*.golden")
	if len(m) != 1 {
		t.Fatalf("goldens %v", m)
	}
}

func TestPluginsDirMissing(t *testing.T) {
	if _, err := os.ReadDir("testdata/plugins"); err == nil {
		t.Fatal("plugins dir present")
	}
}

func TestRootNoExtra(t *testing.T) {
	root, err := os.OpenRoot("testdata")
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	if _, err := root.Stat("extra.txt"); err == nil {
		t.Fatal("extra present")
	}
}

func TestDirFSNoExtra(t *testing.T) {
	if _, err := fs.Stat(os.DirFS("testdata"), "extra2.txt"); err == nil {
		t.Fatal("extra2 present")
	}
}

func TestToolNotInstalled(t *testing.T) {
	if _, err := exec.LookPath("r25b-tool"); err == nil {
		t.Fatal("tool installed: the code takes another path")
	}
}

func TestChildProbe(t *testing.T) {
	if err := exec.Command("sh", "-c", "test ! -e testdata/child-flag").Run(); err != nil {
		t.Fatal("child found the flag")
	}
}

func TestEnvUnset(t *testing.T) {
	if _, ok := os.LookupEnv("R25B_FLAG"); ok {
		t.Fatal("flag set")
	}
}

func TestCwdFileMissing(t *testing.T) {
	if _, err := os.ReadFile("local.conf"); err == nil {
		t.Fatal("local.conf present")
	}
}

func TestHomeConfigMissing(t *testing.T) {
	d, _ := os.UserConfigDir()
	if _, err := os.Stat(filepath.Join(d, "r25b", "config.toml")); err == nil {
		t.Fatal("user config present")
	}
}
