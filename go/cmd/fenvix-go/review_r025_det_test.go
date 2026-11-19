package main

// Review R-025, part 2: attempts to break --det (fixture
// testdata/fixtures/review-r025-det). Tests named TestR025_D<n> fail on
// claude/go-l0 (findings); TestR025_DetHeld passes there.
//
// Run: cd go && go test ./cmd/fenvix-go -run 'TestR025_D' -v

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

const r025Runs = 10

var (
	r025DetOnce   sync.Once
	r025DetOut    map[string]map[string]int // test -> outcome -> runs (--det seed 0)
	r025DetFP     map[string]map[string]int // test -> fingerprint -> runs
	r025PlainOut  map[string]map[string]int
	r025DetFailed string
)

func r025DetRuns(t *testing.T) {
	t.Helper()
	r025DetOnce.Do(func() {
		dir := copyFixture(t, "review-r025-det")
		r025DetOut, r025DetFP = map[string]map[string]int{}, map[string]map[string]int{}
		for i := 0; i < r025Runs; i++ {
			trace := filepath.Join(t.TempDir(), "trace.jsonl")
			out, _ := runFenvix(t, dir, []string{"GOFLAGS="}, "test", "--det", "--det-trace="+trace, "./det")
			tests, _, _ := func() (map[string]traceTest, []string, map[string]any) {
				if _, err := os.Stat(trace); err != nil {
					r025DetFailed = out
					return nil, nil, nil
				}
				return readTrace(t, trace)
			}()
			for name, tt := range tests {
				if r025DetOut[name] == nil {
					r025DetOut[name], r025DetFP[name] = map[string]int{}, map[string]int{}
				}
				r025DetOut[name][tt.Outcome]++
				r025DetFP[name][tt.Fingerprint]++
			}
		}
		r025PlainOut = nativeOutcomes(t, filepath.Join(dir, "det"), r025Runs)
	})
	if r025DetFailed != "" {
		t.Fatalf("--det run produced no trace:\n%s", r025DetFailed)
	}
}

// D1: tests that pass in every plain run and fail in every --det run
// (P-021's "broken by --det").
func TestR025_D1_BrokenByDet(t *testing.T) {
	r025DetRuns(t)
	for _, name := range []string{
		"TestAfterFuncThenSleep", // fastwait: Sleep returns at once although an AfterFunc timer is pending
		"TestMtimeTTL",           // kernel timestamps (file mtime) are real time, time.Now is virtual
		"TestChildClock",         // a child process's clock is real time
	} {
		t.Run(name, func(t *testing.T) {
			plain, det := r025PlainOut[name], r025DetOut[name]
			t.Logf("plain %v, --det seed 0 %v", plain, det)
			if plain["pass"] == r025Runs && det["failed"] == r025Runs {
				t.Errorf("%s passes %d/%d plain and fails %d/%d under --det: broken by --det", name, r025Runs, r025Runs, r025Runs, r025Runs)
			}
		})
	}
}

// D2: entropy reachable without any goroutine interleaving that --det does
// not control: the outcome changes between runs of seed 0 while the
// fingerprint of each outcome is the same as that of any event-free test (the
// verifier cannot name the source).
func TestR025_D2_UncontrolledEntropy(t *testing.T) {
	r025DetRuns(t)
	for _, name := range []string{
		"TestLinknameCheaprand", // runtime.cheaprand via linkname (bytedance/gopkg; same source as select)
		"TestRawGetrandom",      // getrandom(2) directly (x/sys/unix.Getrandom)
		"TestEphemeralPorts",    // kernel-chosen ports
	} {
		t.Run(name, func(t *testing.T) {
			t.Logf("--det seed 0 outcomes %v fingerprints %v", r025DetOut[name], r025DetFP[name])
			if len(r025DetOut[name]) != 1 || len(r025DetFP[name]) != 1 {
				t.Errorf("%s: %d outcomes and %d fingerprints in %d runs of --det seed 0", name,
					len(r025DetOut[name]), len(r025DetFP[name]), r025Runs)
			}
		})
	}
}

// Held: sources --det does control (or documents).
func TestR025_DetHeld(t *testing.T) {
	r025DetRuns(t)
	for _, name := range []string{"TestLinknameFastrand", "TestReflectMapOrder"} {
		if len(r025DetOut[name]) != 1 || len(r025DetFP[name]) != 1 {
			t.Errorf("%s: outcomes %v fingerprints %v", name, r025DetOut[name], r025DetFP[name])
		}
	}
	// documented limit (select among ready channels) and sync.Pool after a
	// blocking syscall (P migration, rare: 1 failure in 20 runs in this
	// session): logged only
	t.Logf("TestSyncPool: outcomes %v fingerprints %v", r025DetOut["TestSyncPool"], r025DetFP["TestSyncPool"])
	t.Logf("TestSelectReady (documented, not controlled): %v", r025DetOut["TestSelectReady"])
}

// D3: Go 1.22 ("time and random unavailable, reported at start; the rest
// works", docs/GO.md and the report): the limits are printed, then the test
// binary does not build (testing hook refers to time.FenvixNow, which is in
// the disabled time group). The CI job never runs 1.22 (its loop starts at
// 1.23 and ignores failures).
func TestR025_D3_Go122(t *testing.T) {
	dir := copyFixture(t, "review-r025-det")
	gomod := filepath.Join(dir, "go.mod")
	os.WriteFile(gomod, []byte("module example.com/r025det\n\ngo 1.22.12\n"), 0o644)
	out, code := runFenvix(t, dir, []string{"GOFLAGS=", "GOTOOLCHAIN=go1.22.12"}, "test", "--det", "-v", "-run=TestReflectMapOrder", "./det")
	if strings.Contains(out, "toolchain not available") || strings.Contains(out, "downloading go1.22.12") && code != 0 && !strings.Contains(out, "zz_fenvix") {
		t.Skipf("go1.22.12 not available:\n%s", out)
	}
	if !strings.Contains(out, "control time unavailable") {
		t.Errorf("limits not said at start:\n%s", out)
	}
	// Fix (REPORT-2, D4): the finding is that the test binary did not build.
	// The review asked for exit 0, but TestReflectMapOrder's outcome depends
	// on the map implementation: under --det seed 0 on Go 1.22 (pre-swiss
	// maps) its first key is "15" in every run, so it fails, deterministically
	// (plain go1.22 runs vary). What must hold is that the binary builds and
	// the test runs with the controls said at start.
	ran := strings.Contains(out, "--- PASS: TestReflectMapOrder") || strings.Contains(out, "--- FAIL: TestReflectMapOrder") ||
		strings.Contains(out, "\nok ")
	if strings.Contains(out, "build failed") || strings.Contains(out, "setup failed") || !ran {
		t.Errorf("go1.22.12 --det: exit %d, test binary did not build or run\n%s", code, out)
	}
}
