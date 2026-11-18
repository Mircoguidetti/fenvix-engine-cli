package strace

import (
	"os"
	"path/filepath"
	"testing"
)

func TestKeepMostSpecificWins(t *testing.T) {
	f := &Filter{Roots: []string{"/tmp/w/repo", "/usr"}, Ignore: []string{"/tmp", "/tmp/w/repo/.fenvix"}}
	cases := map[string]bool{
		"/tmp/w/repo/a.txt":       true,
		"/tmp/w/repo/.fenvix/x":   false,
		"/tmp/TestX/001/f":        false,
		"/usr/share/zoneinfo/UTC": true,
		"/home/x":                 false,
		"/tmp/w/repo/.git/HEAD":   false,
		"/__fenvix_marker__/B/1":  false,
	}
	for p, want := range cases {
		if got := f.Keep(p); got != want {
			t.Errorf("Keep(%s) = %v, want %v", p, got, want)
		}
	}
}

func TestParseAttributesToTests(t *testing.T) {
	dir := t.TempDir()
	log := filepath.Join(dir, "log")
	lines := `100 openat(AT_FDCWD</r>, "/r/init.txt", O_RDONLY|O_CLOEXEC) = 3</r/init.txt>
100 access("/__fenvix_marker__/B/0", F_OK) = -1 ENOENT (No such file or directory)
100 openat(AT_FDCWD</r>, "a.txt", O_RDONLY|O_CLOEXEC) = 3</r/a.txt>
101 newfstatat(AT_FDCWD</r>, "/r/missing", 0xc0, 0) = -1 ENOENT (No such file or directory)
100 access("/__fenvix_marker__/X/0", F_OK) = -1 ENOENT (No such file or directory)
100 access("/__fenvix_marker__/B/1", F_OK) = -1 ENOENT (No such file or directory)
100 openat(AT_FDCWD</r>, "/r/out.txt", O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC, 0644) = 3</r/out.txt>
100 openat(AT_FDCWD</r>, "/r/rw.db", O_RDWR|O_CLOEXEC) = 3</r/rw.db>
100 getdents64(3</r/dir>, 0xc0 /* 3 entries */, 8192) = 80
100 connect(5<socket:[1]>, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("1.2.3.4")}, 16) = -1 EINPROGRESS
102 execve("/usr/bin/cat", ["cat"], 0x0 /* 3 vars */) = 0
100 access("/__fenvix_marker__/X/1", F_OK) = -1 ENOENT (No such file or directory)
`
	os.WriteFile(log, []byte(lines), 0o644)
	res, err := Parse(log, "/r", &Filter{Roots: []string{"/r", "/usr"}})
	if err != nil {
		t.Fatal(err)
	}
	pkg, t0, t1 := res.Segments[-1], res.Segments[0], res.Segments[1]
	if !pkg.Reads["/r/init.txt"] || !t0.Reads["/r/a.txt"] || !t0.Missing["/r/missing"] {
		t.Errorf("package %v test0 %v", pkg, t0)
	}
	if t1.Reads["/r/out.txt"] || !t1.Reads["/r/rw.db"] || !t1.Lists["/r/dir"] {
		t.Errorf("test1 reads %v lists %v: truncated output is not an input, read-write open is", t1.Reads, t1.Lists)
	}
	if len(t1.Net) != 1 || t1.Net[0] != [2]string{"1.2.3.4", "443"} || len(t1.Execs) != 1 {
		t.Errorf("test1 net %v execs %v", t1.Net, t1.Execs)
	}
}
