package skip

import (
	"os"
	"path/filepath"
	"testing"
)

func digest(p string) string {
	b, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	return Hash(string(b))
}

func TestWhyAndAbsorb(t *testing.T) {
	dir := t.TempDir()
	f := filepath.Join(dir, "f")
	os.WriteFile(f, []byte("1"), 0o644)
	st := NewState(digest, []string{"A=1", "B=2"})
	raw := NewRaw()
	raw.Reads[f] = true
	raw.Env["A"] = true
	raw.Missing[filepath.Join(dir, "m")] = true
	e := MakeEntry("s", "passed", 1, raw, st, "strace", "/bin/x")
	if w := e.Why("s", NewState(digest, []string{"A=1", "B=3"})); w != "" {
		t.Fatalf("unread variable changed: %q", w)
	}
	if w := e.Why("s", NewState(digest, []string{"A=2"})); w != "env:A" {
		t.Fatalf("read variable changed: %q", w)
	}
	if w := e.Why("t", st); w != "code-or-config" {
		t.Fatalf("static changed: %q", w)
	}
	os.WriteFile(filepath.Join(dir, "m"), nil, 0o644)
	if w := e.Why("s", NewState(digest, []string{"A=1"})); w == "" {
		t.Fatal("missing path appeared but the entry is reusable")
	}
	prev := &Entry{Files: map[string]string{"/p": "x"}, Env: map[string]string{"P": "y"}, Net: []string{"1.2.3.4:443"}}
	e.Absorb(prev)
	if e.Files["/p"] != "x" || e.Env["P"] != "y" || e.Why("s", st) != "network" {
		t.Fatalf("absorb: %+v", e)
	}
	failed := MakeEntry("s", "failed", 1, NewRaw(), st, "strace", "")
	if failed.Why("s", st) != "last-failed" {
		t.Fatal("a failure was reusable")
	}
	nocap := MakeEntry("s", "passed", 1, NewRaw(), st, "", "")
	if nocap.Why("s", st) != "no-capture" {
		t.Fatal("an entry without capture was reusable")
	}
}

func TestForeignExecDependsOnWholeEnvironment(t *testing.T) {
	st := NewState(digest, []string{"X=1"})
	raw := NewRaw()
	raw.Execs = []string{"/usr/bin/cat"}
	e := MakeEntry("s", "passed", 1, raw, st, "strace", "/tmp/pkg.test")
	if _, ok := e.Env["*"]; !ok {
		t.Fatal("a test that started another program must depend on the whole environment")
	}
	if e.Why("s", NewState(digest, []string{"X=1", "NEW=1"})) == "" {
		t.Fatal("a new variable must invalidate it")
	}
}
