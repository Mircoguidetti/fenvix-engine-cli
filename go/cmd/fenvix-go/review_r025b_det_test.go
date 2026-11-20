package main

// Review R-025b, --det part: variants of R-025 D1-D3 (fixture
// testdata/fixtures/review-r025b-det). 10 plain runs and 10 --det seed-0 runs.
// A test here fails when it finds a test broken by --det (10/10 plain pass,
// 10/10 --det fail) or a source --det leaves uncontrolled (two outcomes in 10
// --det seed-0 runs).
//
// Run: cd go && go test ./cmd/fenvix-go -run 'TestR025b_D' -v

import (
	"os"
	"path/filepath"
	"sync"
	"testing"
)

var (
	r025bDetOnce            sync.Once
	r025bDetOut, r025bDetFP map[string]map[string]int
	r025bPlainOut           map[string]map[string]int
	r025bDetFailed          string
)

func r025bDetRuns(t *testing.T) {
	t.Helper()
	r025bDetOnce.Do(func() {
		dir := copyFixture(t, "review-r025b-det")
		r025bDetOut, r025bDetFP = map[string]map[string]int{}, map[string]map[string]int{}
		for i := 0; i < r025Runs; i++ {
			trace := filepath.Join(t.TempDir(), "trace.jsonl")
			out, _ := runFenvix(t, dir, []string{"GOFLAGS="}, "test", "--det", "--det-trace="+trace, "./det")
			if _, err := os.Stat(trace); err != nil {
				r025bDetFailed = out
				return
			}
			tests, _, _ := readTrace(t, trace)
			for name, tt := range tests {
				if r025bDetOut[name] == nil {
					r025bDetOut[name], r025bDetFP[name] = map[string]int{}, map[string]int{}
				}
				r025bDetOut[name][tt.Outcome]++
				r025bDetFP[name][tt.Fingerprint]++
			}
		}
		r025bPlainOut = nativeOutcomes(t, filepath.Join(dir, "det"), r025Runs)
	})
	if r025bDetFailed != "" {
		t.Fatalf("--det run produced no trace:\n%s", r025bDetFailed)
	}
}

// D1b/D2b: broken by --det.
func TestR025b_D1_BrokenByDet(t *testing.T) {
	r025bDetRuns(t)
	for _, name := range []string{
		"TestTimerChannelThenSleep",    // D1 variant: a timer read through its channel after the sleep
		"TestInitWorkerThenSleep",      // D1 variant: a worker goroutine started by package init
		"TestSyscallStatMtime",         // D2 variant: syscall.Stat is not shifted
		"TestChildStatVersusChildDate", // D2 variant: in a child, date is shifted and stat is not
	} {
		t.Run(name, func(t *testing.T) {
			plain, det := r025bPlainOut[name], r025bDetOut[name]
			t.Logf("plain %v, --det seed 0 %v", plain, det)
			if plain["pass"] == r025Runs && det["failed"] == r025Runs {
				t.Errorf("%s passes %d/%d plain and fails %d/%d under --det: broken by --det", name, r025Runs, r025Runs, r025Runs, r025Runs)
			}
		})
	}
}

// D3b: entropy in one goroutine.
func TestR025b_D3_UncontrolledEntropy(t *testing.T) {
	r025bDetRuns(t)
	for _, name := range []string{"TestMaphashSeed", "TestSyncMapRange", "TestPid", "TestDevUrandom"} {
		t.Run(name, func(t *testing.T) {
			t.Logf("plain %v; --det seed 0 outcomes %v fingerprints %v", r025bPlainOut[name], r025bDetOut[name], r025bDetFP[name])
			if len(r025bDetOut[name]) != 1 {
				t.Errorf("%s: %d outcomes in %d runs of --det seed 0", name, len(r025bDetOut[name]), r025Runs)
			}
		})
	}
}
