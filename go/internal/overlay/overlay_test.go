package overlay

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestGenerateForTheLocalToolchain(t *testing.T) {
	out, err := exec.Command("go", "env", "GOROOT", "GOVERSION").Output()
	if err != nil {
		t.Skip("no go command")
	}
	f := strings.Fields(string(out))
	res, err := Generate(f[0], f[1], t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if goMinor := f[1]; strings.HasPrefix(goMinor, "go1.2") && len(res.Available) < len(DetControls) {
		t.Errorf("%s: controls unavailable: %v", f[1], res.Unavailable)
	}
	b, err := os.ReadFile(res.Path)
	if err != nil || !strings.Contains(string(b), filepath.Join(f[0], "src", "runtime", "zz_fenvix.go")) {
		t.Fatalf("overlay %s: %v\n%s", res.Path, err, b)
	}
	// deterministic: same input, same digest
	again, _ := Generate(f[0], f[1], t.TempDir())
	if again.Digest != res.Digest {
		t.Fatal("overlay digest is not deterministic")
	}
}

func TestMissingAnchorDisablesOnlyItsControl(t *testing.T) {
	// a fake GOROOT copy where math/rand/v2 lacks the hook anchor
	out, err := exec.Command("go", "env", "GOROOT").Output()
	if err != nil {
		t.Skip("no go command")
	}
	src := filepath.Join(strings.TrimSpace(string(out)), "src")
	fake := t.TempDir()
	for _, p := range []string{"runtime", "time", "math/rand", "math/rand/v2", "crypto/internal/sysrand", "crypto/rand",
		"os", "syscall", "net", "testing", "internal/runtime/atomic"} {
		os.MkdirAll(filepath.Join(fake, "src", p), 0o755)
		ents, _ := os.ReadDir(filepath.Join(src, p))
		for _, e := range ents {
			if !e.IsDir() {
				b, _ := os.ReadFile(filepath.Join(src, p, e.Name()))
				os.WriteFile(filepath.Join(fake, "src", p, e.Name()), b, 0o644)
			}
		}
	}
	v2 := filepath.Join(fake, "src", "math", "rand", "v2", "rand.go")
	b, _ := os.ReadFile(v2)
	os.WriteFile(v2, []byte(strings.ReplaceAll(string(b), "func (runtimeSource) Uint64() uint64 {", "func (runtimeSource) Uint64() (x uint64) {")), 0o644)
	res, err := Generate(fake, "go-test", t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if res.Has(CtlRandom) || !res.Has(CtlTime) || !res.Has(CtlMaps) {
		t.Fatalf("available %v unavailable %v", res.Available, res.Unavailable)
	}
	if !strings.Contains(res.Unavailable[CtlRandom], "anchor") {
		t.Fatalf("reason: %q", res.Unavailable[CtlRandom])
	}
}
