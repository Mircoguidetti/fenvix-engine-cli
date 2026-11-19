package meta

import (
	"os"
	"testing"
)

// TestScriptIsExecutable: a permission check (only the mode changes).
func TestScriptIsExecutable(t *testing.T) {
	st, err := os.Stat("testdata/run.sh")
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode()&0o111 == 0 {
		t.Fatalf("run.sh is not executable: %v", st.Mode())
	}
}

// TestGeneratedIsFresh: a make-style staleness check (only mtimes change).
func TestGeneratedIsFresh(t *testing.T) {
	src, err := os.Stat("testdata/src.txt")
	if err != nil {
		t.Fatal(err)
	}
	gen, err := os.Stat("testdata/gen.txt")
	if err != nil {
		t.Fatal(err)
	}
	if gen.ModTime().Before(src.ModTime()) {
		t.Fatalf("gen.txt is older than src.txt: regenerate")
	}
}

// TestCurrentLink: which version a symlink selects (both targets exist).
func TestCurrentLink(t *testing.T) {
	target, err := os.Readlink("testdata/current")
	if err != nil {
		t.Fatal(err)
	}
	if target != "v1.txt" {
		t.Fatalf("current -> %s, want v1.txt", target)
	}
}

// TestEntryTypes: entry types in a listing (names unchanged).
func TestEntryTypes(t *testing.T) {
	ents, err := os.ReadDir("testdata/tree")
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range ents {
		if e.IsDir() {
			t.Fatalf("%s is a directory, want only files", e.Name())
		}
	}
}
