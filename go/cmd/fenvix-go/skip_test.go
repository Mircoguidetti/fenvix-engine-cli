package main

// Integration tests of the skip key (testdata/fixtures/skipkey): after a first
// run fills the cache, an unchanged second run reuses every passing test
// that did not touch the network; each change of one input makes the tests
// that depend on it run again, and only those (plus, by the prefix rule, the
// tests that ran after them in the same process).

import (
	"bufio"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

type skipRun struct {
	t     *testing.T
	dir   string
	cache string
	n     int
	env   []string
	extra []string
}

func (r *skipRun) run(env ...string) map[string]decision {
	r.t.Helper()
	r.n++
	report := filepath.Join(r.dir, "..", "report.jsonl")
	args := append([]string{"test", "--skip-cache=" + r.cache, "--skip-report=" + report}, r.extra...)
	args = append(args, "./...")
	out, code := runFenvix(r.t, r.dir, append(append([]string{}, r.env...), env...), args...)
	if code != 0 && !strings.Contains(out, "asked to fail") {
		r.t.Fatalf("run %d: exit %d\n%s", r.n, code, out)
	}
	f, err := os.Open(report)
	if err != nil {
		r.t.Fatalf("run %d: no report: %v\n%s", r.n, err, out)
	}
	defer f.Close()
	res := map[string]decision{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var d decision
		if json.Unmarshal(sc.Bytes(), &d) == nil {
			res[d.Test] = d
		}
	}
	return res
}

func expectReuse(t *testing.T, step string, got map[string]decision, reused, reran []string) {
	t.Helper()
	for _, n := range reused {
		if d, ok := got[n]; !ok || !d.Reuse {
			t.Errorf("%s: %s should be reused, got %+v", step, n, d)
		}
	}
	for _, n := range reran {
		if d, ok := got[n]; !ok || d.Reuse {
			t.Errorf("%s: %s should run again, got %+v", step, n, d)
		}
	}
}

func newSkipRun(t *testing.T, extra ...string) *skipRun {
	if _, err := exec.LookPath("strace"); err != nil {
		t.Log("strace not found: capture falls back to the hooks")
	}
	dir := copyFixture(t, "skipkey")
	// a file outside the module, in the user's home (temp directories are
	// outputs, never inputs)
	home, _ := os.UserHomeDir()
	extDir, err := os.MkdirTemp(home, ".fenvix-skipkey-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(extDir) })
	ext := filepath.Join(extDir, "external.txt")
	os.WriteFile(ext, []byte("ext v1"), 0o644)
	r := &skipRun{t: t, dir: dir, cache: filepath.Join(t.TempDir(), "cache"),
		env: []string{"SKIPKEY_EXTERNAL=" + ext, "SKIPKEY_ENV=one", "TZ=UTC"}, extra: extra}
	first := r.run()
	for n, d := range first {
		if d.Reuse {
			t.Fatalf("first run reused %s", n)
		}
	}
	return r
}

// source order of the fixture tests (the order they run in)
var fixtureOrder = []string{"TestIndependent", "TestOwnCode", "TestDependency", "TestDataFile", "TestExternalFile",
	"TestEnv", "TestTimeZone", "TestMissingPath", "TestListing", "TestShortFlag", "TestFailsOnDemand", "TestSubprocess",
	"TestNetwork"}

var allPassing = fixtureOrder[:len(fixtureOrder)-1]

// reusable: every passing test except TestSubprocess, which started another
// program (cat): its clock and entropy are invisible to the key, so it is
// never reused (review R-025 F6, REPORT-2). TestNetwork comes after it.
var reusable = fixtureOrder[:len(fixtureOrder)-2]

func TestSkipUnchangedReusesAllButNetwork(t *testing.T) {
	r := newSkipRun(t)
	got := r.run()
	expectReuse(t, "unchanged", got, reusable, []string{"TestSubprocess", "TestNetwork"})
	if w := got["TestSubprocess"].Why; w != "exec:/usr/bin/cat" && w != "exec:/bin/cat" {
		t.Errorf("TestSubprocess reason %q, want exec:<cat>", w)
	}
	if got["TestNetwork"].Why != "network" {
		t.Errorf("TestNetwork reason %q, want network", got["TestNetwork"].Why)
	}
}

func TestSkipKeyInputs(t *testing.T) {
	r := newSkipRun(t)
	r.run()
	write := func(rel, content string) {
		if err := os.WriteFile(filepath.Join(r.dir, rel), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	// tests before the changed one are reused; the changed one runs again
	// (and, by the prefix rule, those after it in the same process)
	before := func(name string) []string {
		for i, n := range fixtureOrder {
			if n == name {
				return fixtureOrder[:i]
			}
		}
		t.Fatalf("unknown test %s", name)
		return nil
	}
	step := func(what, test string, env ...string) {
		t.Helper()
		expectReuse(t, what, r.run(env...), before(test), []string{test})
		expectReuse(t, what+" (again)", r.run(env...), append(before(test), test), nil)
	}

	write("testdata/data.txt", "data v2") // file read through package os
	step("data.txt changed", "TestDataFile")
	ext := strings.TrimPrefix(r.env[0], "SKIPKEY_EXTERNAL=")
	os.WriteFile(ext, []byte("ext v2"), 0o644) // file outside the module
	step("external file changed", "TestExternalFile")
	r.env[1] = "SKIPKEY_ENV=two" // environment variable read by the test
	step("SKIPKEY_ENV changed", "TestEnv")
	expectReuse(t, "unrelated variable", r.run("UNRELATED_VARIABLE=x"), before("TestSubprocess"), []string{"TestSubprocess"})
	write("testdata/optional.txt", "now here") // a path probed missing appears
	step("optional.txt created", "TestMissingPath")
	write("testdata/dir/b.txt", "b") // a listed directory gets a new entry
	step("dir listing changed", "TestListing")
	write("testdata/sub.txt", "sub v2") // file read by a child process (cat): never reused (it started a program)
	expectReuse(t, "sub.txt changed", r.run(), before("TestSubprocess"), []string{"TestSubprocess"})

	// TZ is read by package time below package os: always in the key
	r.env[2] = "TZ=Europe/Rome"
	expectReuse(t, "TZ changed", r.run(), nil, []string{"TestTimeZone", "TestIndependent"})

	// code of the package, code of a dependency
	write("skipkey.go", "package skipkey\n\n// Answer is used by TestOwnCode.\n//go:noinline\nfunc Answer() int { return 43 }\n")
	expectReuse(t, "package code changed", r.run(), nil, []string{"TestOwnCode", "TestIndependent"})
	write("lib/lib.go", "package lib\n\n// Value is used by TestDependency.\n//go:noinline\nfunc Value() int { return 2 }\n")
	expectReuse(t, "dependency code changed", r.run(), nil, []string{"TestDependency", "TestIndependent"})
	expectReuse(t, "after code changes", r.run(), reusable, nil)
	// a change that compiles to the same machine code is reused, as go's own cache does
	write("lib/lib.go", "package lib\n\n// Value is used by TestDependency.\n//go:noinline\nfunc Value() int { return 1 + 1 }\n")
	expectReuse(t, "same machine code", r.run(), reusable, nil)
}

func TestSkipFlagsFailuresAndDet(t *testing.T) {
	r := newSkipRun(t)
	r.run()
	// a test flag that changes behaviour
	r.extra = []string{"-short"}
	expectReuse(t, "-short", r.run(), nil, []string{"TestShortFlag", "TestIndependent"})
	expectReuse(t, "-short again", r.run(), reusable, nil)
	// a failure is never reused
	got := r.run("SKIPKEY_FAIL=1")
	if got["TestFailsOnDemand"].Reuse {
		t.Fatalf("SKIPKEY_FAIL=1: the test was reused: %+v", got["TestFailsOnDemand"])
	}
	got = r.run()
	if d := got["TestFailsOnDemand"]; d.Reuse || d.Why != "last-failed" {
		t.Errorf("after a failure: %+v, want a rerun with reason last-failed", d)
	}
	// --det and its seed are part of the key
	r.extra = []string{"-short", "--det"}
	expectReuse(t, "--det on", r.run(), nil, []string{"TestIndependent"})
	expectReuse(t, "--det again", r.run(), []string{"TestIndependent", "TestEnv"}, nil)
	r.extra = []string{"-short", "--det", "--det-seed=5"}
	expectReuse(t, "--det-seed changed", r.run(), nil, []string{"TestIndependent"})
}

func TestSkipVerifyRunsEverything(t *testing.T) {
	r := newSkipRun(t, "--skip-verify")
	got := r.run()
	for _, n := range reusable {
		d := got[n]
		if !d.Reuse || d.Fresh != "passed" || d.Cached != "passed" {
			t.Errorf("verify mode: %s %+v: want a reusable test that also ran", n, d)
		}
	}
}

// Go's own test cache, for comparison: it does not see TZ (read by package
// time below package os) nor a file read by a child process.
func TestGoTestCacheMissesWhatTheKeySees(t *testing.T) {
	dir := copyFixture(t, "skipkey")
	cache := t.TempDir()
	goTest := func(env ...string) string {
		cmd := exec.Command("go", "test", "-run", "^(TestTimeZone|TestSubprocess)$", "-v", ".")
		cmd.Dir = dir
		cmd.Env = append(append(os.Environ(), "GOCACHE="+cache, "GOFLAGS="), env...)
		out, _ := cmd.CombinedOutput()
		return string(out)
	}
	goTest("TZ=UTC")
	os.WriteFile(filepath.Join(dir, "testdata", "sub.txt"), []byte("sub v9"), 0o644)
	out := goTest("TZ=Asia/Tokyo")
	if !strings.Contains(out, "(cached)") {
		t.Logf("go test reran after TZ and a child-read file changed (Go version behaviour changed?):\n%s", out)
	} else {
		t.Logf("go test reused its cached result although TZ and a file read by a child process changed (as documented)")
	}
}
