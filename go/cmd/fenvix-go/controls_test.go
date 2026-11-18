package main

// Integration tests: every --det control on the fixture module
// testdata/fixtures/controls. Contract (as the Python and Node shells):
//   - without --det, each control test fails in some runs (it is flaky);
//   - with --det, every run of a seed gives the same outcome and the same
//     fingerprint, and some seed makes it pass (it is reproducible, not broken);
//   - goroutine interleaving is Level 1: measured (the verifier names it), not
//     controlled.

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

var fenvixBin string

func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "fenvix-go-test-")
	if err != nil {
		panic(err)
	}
	fenvixBin = filepath.Join(dir, "fenvix-go")
	out, err := exec.Command("go", "build", "-o", fenvixBin, ".").CombinedOutput()
	if err != nil {
		fmt.Fprintf(os.Stderr, "build fenvix-go: %v\n%s", err, out)
		os.Exit(1)
	}
	os.Setenv("FENVIX_GO_CACHE", filepath.Join(dir, "cache"))
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

// copyFixture copies testdata/fixtures/<name> to a temp dir (a module on its own).
func copyFixture(t *testing.T, name string) string {
	t.Helper()
	src := filepath.Join("..", "..", "testdata", "fixtures", name)
	dst := filepath.Join(t.TempDir(), name)
	err := filepath.Walk(src, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, p)
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			if info.Name() == ".fenvix" {
				return filepath.SkipDir
			}
			return os.MkdirAll(target, 0o755)
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, info.Mode())
	})
	if err != nil {
		t.Fatal(err)
	}
	return dst
}

type traceTest struct {
	Nodeid      string `json:"nodeid"`
	Outcome     string `json:"outcome"`
	Fingerprint string `json:"fingerprint"`
}

func readTrace(t *testing.T, path string) (map[string]traceTest, []string, map[string]any) {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	res := map[string]traceTest{}
	var order []string
	var meta map[string]any
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<26)
	for sc.Scan() {
		var line struct {
			Type string         `json:"type"`
			Meta map[string]any `json:"meta"`
			traceTest
		}
		if err := json.Unmarshal(sc.Bytes(), &line); err != nil {
			t.Fatal(err)
		}
		switch line.Type {
		case "header":
			meta = line.Meta
		case "test":
			name := line.Nodeid[strings.LastIndex(line.Nodeid, "::")+2:]
			res[name] = line.traceTest
			order = append(order, name)
		}
	}
	return res, order, meta
}

func runFenvix(t *testing.T, dir string, env []string, args ...string) (string, int) {
	t.Helper()
	cmd := exec.Command(fenvixBin, args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), env...)
	out, err := cmd.CombinedOutput()
	return string(out), exitCode(err)
}

// nativeOutcomes runs plain go test (random order, default parallelism) n
// times and returns per test the set of outcomes.
func nativeOutcomes(t *testing.T, dir string, n int) map[string]map[string]int {
	t.Helper()
	res := map[string]map[string]int{}
	for i := 0; i < n; i++ {
		cmd := exec.Command("go", "test", "-count=1", "-shuffle=on", "-json", ".")
		cmd.Dir = dir
		out, _ := cmd.Output()
		for _, line := range strings.Split(string(out), "\n") {
			var ev struct{ Action, Test string }
			if json.Unmarshal([]byte(line), &ev) != nil || ev.Test == "" || strings.Contains(ev.Test, "/") {
				continue
			}
			if ev.Action == "pass" || ev.Action == "fail" {
				if res[ev.Test] == nil {
					res[ev.Test] = map[string]int{}
				}
				res[ev.Test][ev.Action]++
			}
		}
	}
	return res
}

// The control each fixture test depends on.
var controlTests = map[string]string{
	"TestOrderUser":   "order",
	"TestRandom":      "random",
	"TestRandomV2":    "random",
	"TestCrypto":      "crypto",
	"TestMapOrder":    "maps",
	"TestClockParity": "time",
	"TestElapsed":     "time",
	"TestTimers":      "time",
	"TestListing":     "fs",
	"TestParallelB":   "serial",
}

func TestControlsFlakyWithoutDet(t *testing.T) {
	dir := copyFixture(t, "controls")
	nat := nativeOutcomes(t, dir, 30)
	for name, ctl := range controlTests {
		if nat[name]["fail"] == 0 {
			t.Errorf("%s (%s): never failed in 30 runs without --det (outcomes %v): the fixture does not show the problem", name, ctl, nat[name])
		}
	}
	t.Logf("native outcomes over 30 runs: %v", nat)
}

func TestControlsDeterministicWithDet(t *testing.T) {
	dir := copyFixture(t, "controls")
	seeds := []int{0, 1, 2, 3, 4, 5, 6, 7}
	passedIn := map[string]bool{}
	failedIn := map[string]bool{}
	for _, seed := range seeds {
		var first map[string]traceTest
		var firstOrder []string
		for run := 0; run < 3; run++ {
			trace := filepath.Join(dir, fmt.Sprintf("s%d-r%d.jsonl", seed, run))
			out, _ := runFenvix(t, dir, nil, "test", "--det", fmt.Sprintf("--det-seed=%d", seed), "--det-trace="+trace, ".")
			tr, order, meta := readTrace(t, trace)
			if len(tr) != 16 {
				t.Fatalf("seed %d run %d: %d tests in the trace, want 16\n%s", seed, run, len(tr), out)
			}
			if meta["runtime"] != "go" || meta["runner"] != "go test" {
				t.Fatalf("header meta %v", meta)
			}
			if run == 0 {
				first, firstOrder = tr, order
				continue
			}
			if strings.Join(order, ",") != strings.Join(firstOrder, ",") {
				t.Errorf("seed %d: order changed between runs", seed)
			}
			for name := range controlTests {
				a, b := first[name], tr[name]
				if a.Outcome != b.Outcome || a.Fingerprint != b.Fingerprint {
					t.Errorf("seed %d %s: run 0 %s/%s, run %d %s/%s", seed, name, a.Outcome, a.Fingerprint, run, b.Outcome, b.Fingerprint)
				}
			}
		}
		for name := range controlTests {
			if first[name].Outcome == "passed" {
				passedIn[name] = true
			} else {
				failedIn[name] = true
			}
		}
	}
	for name, ctl := range controlTests {
		if !passedIn[name] {
			t.Errorf("%s (%s): failed under --det with every seed 0..7: broken by --det", name, ctl)
		}
	}
	t.Logf("failing in some seed (exploration finds them): %v", failedIn)
}

func TestControlsDisableBringsBackFlakiness(t *testing.T) {
	// --det-disable=random,maps: math/rand is no longer controlled (with only
	// random off, the unseeded global source falls back to runtime.rand, which
	// the maps control also makes deterministic on user goroutines), so its
	// outcome changes between runs: the controls are the cause.
	dir := copyFixture(t, "controls")
	fps := map[string]bool{}
	for run := 0; run < 6; run++ {
		trace := filepath.Join(dir, fmt.Sprintf("r%d.jsonl", run))
		runFenvix(t, dir, nil, "test", "--det", "--det-disable=random,maps", "--det-trace="+trace, "-run", "^TestRandom$", ".")
		tr, _, _ := readTrace(t, trace)
		fps[tr["TestRandom"].Outcome] = true
	}
	if len(fps) < 2 {
		t.Errorf("with the random control off TestRandom had one outcome in 6 runs: %v", fps)
	}
}

func TestNetworkBlockedAndLoopbackAllowed(t *testing.T) {
	dir := copyFixture(t, "controls")
	out, code := runFenvix(t, dir, nil, "test", "--det", "-v", "-run", "^(TestNetworkOff|TestLoopback)$", ".")
	if code != 0 {
		t.Fatalf("exit %d\n%s", code, out)
	}
	if !strings.Contains(out, "fenvix --det: network access to 192.0.2.1:9 blocked") {
		t.Errorf("outside connect not blocked:\n%s", out)
	}
	if !strings.Contains(out, "--- PASS: TestLoopback") {
		t.Errorf("loopback broken:\n%s", out)
	}
}

func TestInterleavingIsMeasuredNotControlled(t *testing.T) {
	if runtime.NumCPU() < 2 {
		t.Skip("needs 2 CPUs for goroutines to interleave")
	}
	dir := copyFixture(t, "controls")
	var traces []string
	for run := 0; run < 6; run++ {
		trace := filepath.Join(dir, fmt.Sprintf("i%d.jsonl", run))
		runFenvix(t, dir, nil, "test", "--det", "--det-trace="+trace, "-run", "^TestInterleaving$", ".")
		traces = append(traces, trace)
	}
	out, code := runFenvix(t, dir, nil, append([]string{"verify"}, traces...)...)
	if code != 0 {
		t.Fatalf("verify: %s", out)
	}
	t.Logf("verifier:\n%s", out)
	if !strings.Contains(out, "TestInterleaving") || !strings.Contains(out, "thread") {
		t.Logf("interleaving identical in 6 runs (possible on a quiet machine); verifier output above")
	}
}

func TestPlainWithoutFlagsIsGoTest(t *testing.T) {
	dir := copyFixture(t, "controls")
	out, _ := runFenvix(t, dir, nil, "test", "-run", "^TestLoopback$", "-v", ".")
	if !strings.Contains(out, "--- PASS: TestLoopback") || strings.Contains(out, "fenvix-go: trace") {
		t.Fatalf("plain mode should be go test:\n%s", out)
	}
}

// --det must not change the outcome of deterministic suites: fenvix-go's own
// packages (overlay generator, strace parser, skip key) pass under --det.
func TestDetUnchangedOnDeterministicPackages(t *testing.T) {
	out, code := runFenvix(t, filepath.Join("..", ".."), nil, "test", "--det", "--det-trace="+filepath.Join(t.TempDir(), "own.jsonl"),
		"./internal/overlay/", "./internal/strace/", "./internal/skip/")
	if code != 0 {
		t.Fatalf("own packages fail under --det (exit %d):\n%s", code, out)
	}
}
