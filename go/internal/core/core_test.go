package core

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRecorderTraceVerify(t *testing.T) {
	dir := t.TempDir()
	write := func(name, v string) string {
		p := filepath.Join(dir, name)
		r := NewRecorder(0, 0)
		defer r.Free()
		if err := r.Open(p, map[string]any{"runtime": "go", "runner": "go test"}, []string{"pkg::TestA"}); err != nil {
			t.Fatal(err)
		}
		if err := r.BeginTest("pkg::TestA", 0); err != nil {
			t.Fatal(err)
		}
		if n, err := r.RecordPacked([]byte("time\x1ftime.Now\x1fa_test.go:3\x1f1000\x1erandom\x1fmath/rand\x1fa_test.go:4\x1f" + v + "\x1e")); err != nil || n != 2 {
			t.Fatal(n, err)
		}
		fp, err := r.EndTest("passed")
		if err != nil || len(fp) != 32 {
			t.Fatal(fp, err)
		}
		if _, err := r.Close(); err != nil {
			t.Fatal(err)
		}
		return p
	}
	a, b, c := write("a.jsonl", "7"), write("b.jsonl", "7"), write("c.jsonl", "9")
	txt, err := VerifyText([]string{a, b}, false)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(txt, "a_test.go:4") {
		t.Fatalf("identical runs reported a divergence:\n%s", txt)
	}
	txt, err = VerifyText([]string{a, c}, false)
	if err != nil || !strings.Contains(txt, "a_test.go:4") {
		t.Fatalf("divergence not named: %v\n%s", err, txt)
	}
	m, err := MergeTraces([]string{a, b}, filepath.Join(dir, "m.jsonl"), map[string]any{"runtime": "go"}, nil)
	if err != nil || m.NTests != 2 {
		t.Fatal(m, err)
	}
	if _, err := os.Stat(filepath.Join(dir, "m.jsonl")); err != nil {
		t.Fatal(err)
	}
}

func TestSeedsShuffleDigest(t *testing.T) {
	if DeriveSeed(1, "a") == DeriveSeed(1, "b") || DeriveSeed(1, "a") != DeriveSeed(1, "a") {
		t.Fatal("derive_seed")
	}
	p := ShuffleIndices(10, 3, "k")
	seen := map[int]bool{}
	for _, i := range p {
		seen[i] = true
	}
	if len(seen) != 10 {
		t.Fatal(p)
	}
	if Digest([]byte("abc")) == Digest([]byte("abd")) || len(Digest(nil)) != 32 {
		t.Fatal("digest")
	}
	f := filepath.Join(t.TempDir(), "f")
	os.WriteFile(f, []byte("x"), 0o644)
	if len(DigestFile(f)) != 64 || DigestFile("/no/such/file") != "" {
		t.Fatal("digest file")
	}
	if err := (&Recorder{p: nil}).BeginTest("x", 0); err == nil {
		t.Fatal("nil recorder accepted")
	}
}
