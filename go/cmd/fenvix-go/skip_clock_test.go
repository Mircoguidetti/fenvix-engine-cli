package main

import (
	"strings"
	"testing"
	"time"
)

// R-025b S1 (terraform e2etest TestMetaBackend_GetStateStoreProviderFactory,
// skip-r8): a test that starts a Go program compares the program's real clock
// with its own virtual day. fenvix runs the package again on the real clock
// and reports that run; the virtual-clock outcome is in the decision; the test
// is never reused; a genuine failure stays a failure.
func TestSkipClockMeetsChild(t *testing.T) {
	if time.Now().UTC().Hour() == 0 && time.Now().UTC().Minute() < 2 {
		t.Skip("too close to 00:00 UTC: the virtual day and the real clock nearly agree")
	}
	r := newR025b(t, "clockmeet")
	buildHelpers(t, r.dir)
	for i := 0; i < 2; i++ {
		got := r.run()
		m, g, p := got["TestClockMeetsChild"], got["TestGenuineFailWithChild"], got["TestPlain"]
		if m.Fresh != "passed" || m.Reuse {
			t.Errorf("run %d: TestClockMeetsChild %+v, want fresh passed (real-clock run), not reused", i+1, m)
		}
		if i == 0 && m.VirtualClock != "failed" {
			t.Errorf("run 1: TestClockMeetsChild virtual_clock %q, want failed (the clocks met)", m.VirtualClock)
		}
		if g.Fresh != "failed" || g.Reuse || g.VirtualClock != "" {
			t.Errorf("run %d: TestGenuineFailWithChild %+v, want failed on both clocks", i+1, g)
		}
		if p.Fresh == "" && !p.Reuse {
			t.Errorf("run %d: TestPlain %+v", i+1, p)
		}
	}
	out, code := runFenvix(t, r.dir, r.env, "test", "--skip-cache="+r.cache, "-v", "./clockmeet")
	if code == 0 || strings.Count(out, "--- FAIL: TestGenuineFailWithChild") != 1 || strings.Contains(out, "--- FAIL: TestClockMeetsChild") {
		t.Errorf("output: exit %d; want one FAIL for the genuine failure and none for the clock meeting:\n%s", code, out)
	}
}
