package main

// Review R-025 (independent review of P-021, branch claude/go-l0): attempts to
// get a wrong reuse out of `fenvix-go test --skip-cache`.
//
// Every scenario uses the fixture module testdata/fixtures/review-r025 and
// runs fenvix-go in verify mode (--skip-verify): every test runs, and the
// decision report says whether the key would have reused it. A wrong reuse is
// what the P-021 skip walk counts as wrong: the key says reuse, the fresh run
// of the same state does not pass.
//
//   - TestR025_F<n>_*: attacks that get through on claude/go-l0 (they fail
//     there; each is a finding of sessions/2026-11-19-review-go/REPORT.md);
//   - TestR025_Held_*: attacks the key catches (they pass there).
//
// Run: cd go && go test ./cmd/fenvix-go -run 'TestR025' -v

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"testing"
	"time"
)

type r025 struct {
	t     *testing.T
	dir   string
	cache string
	env   []string
	pkg   string
	n     int
}

func newR025(t *testing.T, pkg string, env ...string) *r025 {
	t.Helper()
	if _, err := exec.LookPath("strace"); err != nil {
		t.Skip("strace not installed: the review targets the strace capture (the walk's)")
	}
	return &r025{t: t, dir: copyFixture(t, "review-r025"), cache: filepath.Join(t.TempDir(), "cache"),
		env: append([]string{"GOFLAGS="}, env...), pkg: pkg}
}

// run runs fenvix-go test --skip-cache --skip-verify on the scenario package
// and returns the decisions by test name.
func (r *r025) run(extra ...string) map[string]decision {
	r.t.Helper()
	r.n++
	report := filepath.Join(r.t.TempDir(), fmt.Sprintf("report-%d.jsonl", r.n))
	args := []string{"test", "--skip-cache=" + r.cache, "--skip-verify", "--skip-report=" + report}
	args = append(args, extra...)
	args = append(args, "./"+r.pkg)
	out, code := runFenvix(r.t, r.dir, r.env, args...)
	res := map[string]decision{}
	f, err := os.Open(report)
	if err != nil {
		r.t.Fatalf("run %d: no decision report (exit %d): %v\n%s", r.n, code, err, out)
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var d decision
		if json.Unmarshal(sc.Bytes(), &d) == nil {
			res[d.Test] = d
		}
	}
	r.t.Logf("run %d %v: exit %d, decisions %+v", r.n, extra, code, res)
	return res
}

// record is the first run: every named test must pass (nothing to reuse yet).
func (r *r025) record(tests []string, extra ...string) {
	r.t.Helper()
	got := r.run(extra...)
	for _, n := range tests {
		if got[n].Fresh != "passed" {
			r.t.Fatalf("record run: %s did not pass: %+v", n, got[n])
		}
	}
}

// mustReuse: sanity step with nothing changed; the key reuses the test (so a
// later "not reused" is caused by the change, not by an unstable key).
func (r *r025) mustReuse(test string, extra ...string) {
	r.t.Helper()
	if d := r.run(extra...)[test]; !d.Reuse || d.Fresh != "passed" {
		r.t.Fatalf("unchanged: %s not reused (%+v): the scenario proves nothing", test, d)
	}
}

// noWrongReuse: after the change, the key must not reuse a test whose fresh
// run does not pass.
func (r *r025) noWrongReuse(what, test string, extra ...string) {
	r.t.Helper()
	d := r.run(extra...)[test]
	if d.Fresh == "" {
		r.t.Fatalf("%s: %s did not run: %+v", what, test, d)
	}
	if d.Reuse && d.Fresh != "passed" {
		r.t.Errorf("WRONG REUSE after %s: %s reused with proof, fresh run %s (cached %s)", what, test, d.Fresh, d.Cached)
	} else {
		r.t.Logf("%s: %s reuse=%v fresh=%s why=%q", what, test, d.Reuse, d.Fresh, d.Why)
	}
}

func (r *r025) path(rel string) string { return filepath.Join(r.dir, rel) }

// F1: the digest of a file a test read is taken after the package run, not
// when the test read it. A later test in the package rewrites the file; a
// commit that changes the file to that new content is then a key match.
func TestR025_F1_DigestAfterRunNotAtRead(t *testing.T) {
	r := newR025(t, "readwrite")
	r.record([]string{"TestReadsState", "TestRegenerates"})
	// the record run left testdata/state.txt = "v2" (TestRegenerates). The next
	// commit (fresh checkout in CI) has state.txt = "v2" too:
	os.WriteFile(r.path("readwrite/testdata/state.txt"), []byte("v2\n"), 0o644)
	r.noWrongReuse("state.txt v1 -> v2", "TestReadsState")
}

// F2: metadata a test observes through stat/readlink/readdir beyond
// existence, content and entry names.
func TestR025_F2_FileMetadata(t *testing.T) {
	setup := func(r *r025) {
		now := time.Now()
		os.Chtimes(r.path("meta/testdata/src.txt"), now, now)
		os.Chtimes(r.path("meta/testdata/gen.txt"), now.Add(time.Hour), now.Add(time.Hour))
		os.Remove(r.path("meta/testdata/current"))
		if err := os.Symlink("v1.txt", r.path("meta/testdata/current")); err != nil {
			t.Fatal(err)
		}
	}
	all := []string{"TestScriptIsExecutable", "TestGeneratedIsFresh", "TestCurrentLink", "TestEntryTypes"}
	cases := []struct {
		name, test string
		change     func(r *r025)
	}{
		{"mode", "TestScriptIsExecutable", func(r *r025) { os.Chmod(r.path("meta/testdata/run.sh"), 0o644) }},
		{"mtime", "TestGeneratedIsFresh", func(r *r025) {
			later := time.Now().Add(2 * time.Hour)
			os.Chtimes(r.path("meta/testdata/src.txt"), later, later)
		}},
		{"symlink-target", "TestCurrentLink", func(r *r025) {
			os.Remove(r.path("meta/testdata/current"))
			os.Symlink("v2.txt", r.path("meta/testdata/current"))
		}},
		{"entry-type", "TestEntryTypes", func(r *r025) {
			os.Remove(r.path("meta/testdata/tree/b"))
			os.Mkdir(r.path("meta/testdata/tree/b"), 0o755)
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := newR025(t, "meta")
			setup(r)
			r.record(all)
			r.mustReuse(c.test)
			c.change(r)
			r.noWrongReuse(c.name+" changed", c.test)
		})
	}
}

// F3: files outside the root allowlist (repository, module cache, GOROOT,
// /etc, /usr, /lib*, /opt, $HOME) or under an ignored directory of $HOME
// (~/.cache) are dropped from the key without a word.
func TestR025_F3_InputsOutsideRoots(t *testing.T) {
	home, _ := os.UserHomeDir()
	cacheDir, _ := os.UserCacheDir()
	for _, base := range []string{"/var/lib", "/srv", cacheDir} {
		t.Run(filepath.Base(base), func(t *testing.T) {
			if err := os.MkdirAll(base, 0o755); err != nil {
				t.Skip(err)
			}
			d, err := os.MkdirTemp(base, "fenvix-r025-")
			if err != nil {
				t.Skip(err)
			}
			t.Cleanup(func() { os.RemoveAll(d) })
			p := filepath.Join(d, "fixture.txt")
			os.WriteFile(p, []byte("expected\n"), 0o644)
			r := newR025(t, "outside", "R025_OUTSIDE="+p)
			r.record([]string{"TestOutsideFixture"})
			r.mustReuse("TestOutsideFixture")
			os.WriteFile(p, []byte("changed\n"), 0o644)
			r.noWrongReuse(p+" changed", "TestOutsideFixture")
		})
	}
	_ = home
}

// F4: a service on loopback (a CI service container, a local mock, a
// database) is "inside the machine": its answers are not in the key.
func TestR025_F4_LoopbackService(t *testing.T) {
	var body atomic.Value
	body.Store("schema-v1")
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte(body.Load().(string)))
	})}
	go srv.Serve(ln)
	t.Cleanup(func() { srv.Close() })
	r := newR025(t, "loopback", "R025_ADDR="+ln.Addr().String())
	r.record([]string{"TestLocalService"})
	// Fix (REPORT-2, F4): a service the run did not start cannot be keyed
	// (its image, data and state are outside every key), so the test is
	// never reused, not even when nothing changed. The review's original
	// step here (r.mustReuse) required a reuse that only a declared service
	// digest could justify; the coordinator's rule for this fix is "where an
	// input cannot be keyed soundly, the test must rerun".
	if d := r.run()["TestLocalService"]; d.Reuse || d.Why != "local-service" {
		t.Fatalf("unchanged service: %+v, want a rerun with reason local-service", d)
	}
	body.Store("schema-v2") // the service container's image or data changed
	r.noWrongReuse("service answer changed", "TestLocalService")
}

// F5: "never reused: a test that connected to an address outside the
// machine" does not hold for datagrams sent without connect() (sendto is not
// traced).
func TestR025_F5_UDPSendtoOutside(t *testing.T) {
	r := newR025(t, "udp")
	r.record([]string{"TestSendsOutside"})
	d := r.run()["TestSendsOutside"]
	if d.Reuse {
		t.Errorf("TestSendsOutside sent a datagram to 192.0.2.1:9 and is reused with proof (why=%q); the rule says never", d.Why)
	}
}

// F6: without --det the wall clock is an input of every test and is not in
// the key (expiring test certificates, tokens, licences, "within N days").
func TestR025_F6_WallClock(t *testing.T) {
	r := newR025(t, "clock")
	expiry := filepath.Join(r.dir, "clock", "testdata", "notafter.txt")
	os.WriteFile(expiry, []byte("4102444800\n"), 0o644)
	r.run() // warm the build cache (the record run must be quick)
	r.cache = filepath.Join(t.TempDir(), "cache2")
	at := time.Now().Add(8 * time.Second)
	os.WriteFile(expiry, []byte(strconv.FormatInt(at.Unix(), 10)+"\n"), 0o644)
	r.record([]string{"TestFixtureNotExpired"})
	time.Sleep(time.Until(at) + 1500*time.Millisecond)
	r.noWrongReuse("the fixture's NotAfter date passed", "TestFixtureNotExpired")
}

// F7: the dynamic loader's environment (LD_LIBRARY_PATH, LD_PRELOAD) chooses
// which shared libraries a cgo test binary runs, and is not in the key.
func TestR025_F7_LoaderEnvironment(t *testing.T) {
	if _, err := exec.LookPath("gcc"); err != nil {
		t.Skip("gcc not installed")
	}
	r := newR025(t, "cgolib")
	build := func(dir string, v int) {
		os.MkdirAll(dir, 0o755)
		src := filepath.Join(dir, "fx.c")
		os.WriteFile(src, []byte(fmt.Sprintf("int fx(void) { return %d; }\n", v)), 0o644)
		if out, err := exec.Command("gcc", "-shared", "-fPIC", "-o", filepath.Join(dir, "libfx.so"), src).CombinedOutput(); err != nil {
			t.Fatalf("gcc: %v\n%s", err, out)
		}
	}
	libA, libB := r.path("cgolib/lib"), r.path("native-v2")
	build(libA, 1)
	build(libB, 2)
	r.env = append(r.env, "CGO_ENABLED=1")
	base := append([]string{}, r.env...)
	r.env = append(base, "LD_LIBRARY_PATH="+libA)
	r.record([]string{"TestNative"})
	r.mustReuse("TestNative")
	r.env = append(base, "LD_LIBRARY_PATH="+libB)
	r.noWrongReuse("LD_LIBRARY_PATH points to another libfx.so", "TestNative")
}

// F8: test flags declared neutral (-run, -skip, -timeout) change what a
// top-level test does: a subtest pattern or a timeout. Go's own cache keys
// -run and -timeout (and does not cache -skip).
func TestR025_F8_NeutralFlags(t *testing.T) {
	t.Run("skip-subtest", func(t *testing.T) {
		r := newR025(t, "subtests")
		r.record([]string{"TestParent"}, "-skip=TestParent/broken")
		r.noWrongReuse("-skip dropped", "TestParent")
	})
	t.Run("run-subtest", func(t *testing.T) {
		r := newR025(t, "subtests")
		r.record([]string{"TestParent"}, "-run=TestParent/^ok$")
		r.noWrongReuse("-run dropped", "TestParent")
	})
	t.Run("timeout", func(t *testing.T) {
		r := newR025(t, "slow")
		r.record([]string{"TestTakesTwoSeconds"})
		r.noWrongReuse("-timeout=1s", "TestTakesTwoSeconds", "-timeout=1s")
	})
}

// F9: the key holds absolute paths; the checkout location is not in it. Two
// checkouts sharing a cache (git worktrees, CI workspaces on one machine, a
// shared or restored cache) build the same binary with -trimpath, and one
// reuses the other's results for its own, different, files.
func TestR025_F9_CheckoutLocation(t *testing.T) {
	a := newR025(t, "checkout")
	b := newR025(t, "checkout")
	b.cache = a.cache
	os.WriteFile(b.path("checkout/testdata/value.txt"), []byte("two\n"), 0o644)
	a.record([]string{"TestValue"}, "-trimpath")
	b.noWrongReuse("another checkout with value.txt = two", "TestValue", "-trimpath")
}

// Held: attacks the key catches (no wrong reuse on claude/go-l0).
func TestR025_Held(t *testing.T) {
	cases := []struct {
		name, pkg, test string
		env             func(r *r025) []string
		change          func(r *r025)
		extra           []string
	}{
		{"embed", "hembed", "TestEmbedded", nil,
			func(r *r025) { os.WriteFile(r.path("hembed/testdata/e.txt"), []byte("e2\n"), 0o644) }, nil},
		{"os.Environ prefix", "henviron", "TestPrefixedEnv", func(*r025) []string { return []string{"R025_APP_MODE=safe"} },
			func(r *r025) { r.env = append(r.env, "R025_APP_DEBUG=1") }, nil},
		{"init() of a dependency reads a file", "hinit", "TestConfigFromInit",
			func(r *r025) []string { return []string{"R025_CFG=" + r.path("hinit/testdata/cfg.txt")} },
			func(r *r025) { os.WriteFile(r.path("hinit/testdata/cfg.txt"), []byte("cfg2\n"), 0o644) }, nil},
		{"TestMain reads a file", "hmain", "TestLoadedInMain", nil,
			func(r *r025) { os.WriteFile(r.path("hmain/testdata/m.txt"), []byte("m2\n"), 0o644) }, nil},
		{"-ldflags -X", "hldflags", "TestVersion", nil, func(*r025) {},
			[]string{"-ldflags=-X=example.com/r025/hldflags.Version=2.0"}},
		{"-tags", "htags", "TestTagged", nil, func(*r025) {}, []string{"-tags=r025bad"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := newR025(t, c.pkg)
			if c.env != nil {
				r.env = append(r.env, c.env(r)...)
			}
			r.record([]string{c.test})
			r.mustReuse(c.test)
			c.change(r)
			d := r.run(c.extra...)[c.test]
			if d.Fresh == "passed" {
				t.Fatalf("the change did not make %s fail: the scenario proves nothing (%+v)", c.test, d)
			}
			if d.Reuse {
				t.Errorf("WRONG REUSE: %s %+v", c.test, d)
			}
		})
	}
}
