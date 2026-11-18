// Package strace runs a command under `strace -f` and attributes what the
// process tree observed of the file system and the network to the tests of a
// Go test binary, using the marker syscalls the fenvix testing hook makes at
// the start and end of every top-level test
// (access("/__fenvix_marker__/B/<i>") and ".../X/<i>").
//
// The rules follow harness/skip_study2/strace_deps.py (reviewed, R-002):
//   - a file is an input when its first access in the run could observe its
//     content before the run: opened read-only, or read-write/append without
//     truncating or creating it; truncated or created first -> output;
//   - a path stat'ed that existed -> existence dependency; a path probed that
//     did not exist -> "missing" dependency (a file created there later can
//     change the outcome);
//   - a directory listed (getdents64) -> listing dependency;
//   - every inet connect() is recorded (address, port), whatever its result;
//   - programs executed are recorded.
//
// Syscalls outside any test (package init, TestMain, between tests) belong
// to the package: every test of the package depends on them.
package strace

import (
	"bufio"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

// Syscalls is the strace -e trace= set.
const Syscalls = "%file,getdents64,connect,fchdir,clone,clone3,fork,vfork"

// Args returns the strace command prefix that writes its log to logPath.
func Args(logPath string) []string {
	return []string{"strace", "-f", "-qq", "-y", "--seccomp-bpf", "-e", "trace=" + Syscalls, "-e", "signal=none",
		"-s", "4096", "-o", logPath, "--"}
}

// Deps is what one segment (a test, or the package) depended on.
type Deps struct {
	Reads   map[string]bool // files whose content before the run was observable
	Exists  map[string]bool
	Missing map[string]bool
	Lists   map[string]bool
	Execs   []string
	Net     [][2]string // [address, port]
}

func newDeps() *Deps {
	return &Deps{Reads: map[string]bool{}, Exists: map[string]bool{}, Missing: map[string]bool{}, Lists: map[string]bool{}}
}

// Result maps a test position (as in the markers) to its deps; -1 is the package.
type Result struct {
	Segments map[int]*Deps
	Written  map[string]bool // paths the run wrote (never dependencies of later tests' content)
	Lines    int
}

var (
	reLine   = regexp.MustCompile(`^(\d+)\s+(.*)$`)
	reCall   = regexp.MustCompile(`^([a-z0-9_]+)\((.*)\)\s+=\s+(-?\d+|\?)(.*)$`)
	reStr    = regexp.MustCompile(`"((?:[^"\\]|\\.)*)"`)
	reFdPath = regexp.MustCompile(`^(?:AT_FDCWD|\d+)<([^>]*)>`)
	reRet    = regexp.MustCompile(`^<([^>]*)>`)
	reFlag   = regexp.MustCompile(`\bO_[A-Z]+\b`)
	reInet   = regexp.MustCompile(`inet_addr\("([^"]+)"\)|inet_pton\(AF_INET6, "([^"]+)"`)
	rePort   = regexp.MustCompile(`sin6?_port=htons\((\d+)\)`)
	reMarker = regexp.MustCompile(`^/__fenvix_marker__/([BX])/(\d+)$`)
)

var statCalls = map[string]bool{"stat": true, "lstat": true, "newfstatat": true, "statx": true, "access": true,
	"faccessat": true, "faccessat2": true, "readlink": true, "readlinkat": true, "stat64": true, "lstat64": true, "fstatat64": true}
var openCalls = map[string]bool{"open": true, "openat": true, "openat2": true, "creat": true}
var writeCalls = map[string]bool{"unlink": true, "unlinkat": true, "rename": true, "renameat": true, "renameat2": true,
	"mkdir": true, "mkdirat": true, "rmdir": true, "symlink": true, "symlinkat": true, "link": true, "linkat": true,
	"truncate": true, "utimensat": true, "chmod": true, "fchmodat": true}

func unescape(s string) string {
	if !strings.Contains(s, `\`) {
		return s
	}
	if u, err := strconv.Unquote(`"` + s + `"`); err == nil {
		return u
	}
	return s
}

// Filter decides which paths can be dependencies.
type Filter struct {
	Roots  []string
	Ignore []string
}

func under(p, dir string) bool {
	return p == dir || strings.HasPrefix(p, dir+"/")
}

// Keep reports whether path can be a dependency: it must be under a root,
// and the most specific match decides between roots and ignored directories
// (a repository checked out under /tmp is kept, a temp dir under it is not).
func (f *Filter) Keep(p string) bool {
	if strings.HasPrefix(p, "/__fenvix_marker__/") {
		return false
	}
	if strings.Contains(p, "/.git/") {
		// .git internals are read by tools (VCS stamping): the commit is in
		// the binary already when it matters
		return false
	}
	bestRoot, bestIgnore := -1, -1
	for _, r := range f.Roots {
		if r != "" && under(p, r) && len(r) > bestRoot {
			bestRoot = len(r)
		}
	}
	for _, d := range f.Ignore {
		if d != "" && under(p, d) && len(d) > bestIgnore {
			bestIgnore = len(d)
		}
	}
	return bestRoot >= 0 && bestRoot > bestIgnore
}

// Parse reads a strace log written with Args.
func Parse(logPath, cwd string, filter *Filter) (*Result, error) {
	fh, err := os.Open(logPath)
	if err != nil {
		return nil, err
	}
	defer fh.Close()
	res := &Result{Segments: map[int]*Deps{-1: newDeps()}, Written: map[string]bool{}}
	cur := -1
	seg := func() *Deps {
		d := res.Segments[cur]
		if d == nil {
			d = newDeps()
			res.Segments[cur] = d
		}
		return d
	}
	cwds := map[string]string{}
	pending := map[string]string{}
	first := map[string]byte{} // path -> 'r' (first access read the old content) / 'w'
	missingSeen := map[string]bool{}
	rootPid := ""
	absify := func(pid, dirpart, p string) string {
		if strings.HasPrefix(p, "/") {
			return filepath.Clean(p)
		}
		base := dirpart
		if base == "" {
			base = cwds[pid]
		}
		if base == "" {
			base = cwd
		}
		return filepath.Clean(filepath.Join(base, p))
	}
	sc := bufio.NewScanner(fh)
	sc.Buffer(make([]byte, 1<<20), 1<<24)
	for sc.Scan() {
		m := reLine.FindStringSubmatch(sc.Text())
		if m == nil {
			continue
		}
		pid, rest := m[1], m[2]
		if rootPid == "" {
			rootPid = pid
			cwds[pid] = cwd
		}
		if strings.HasSuffix(rest, "<unfinished ...>") {
			pending[pid] = strings.TrimSpace(strings.TrimSuffix(rest, "<unfinished ...>"))
			continue
		}
		if strings.HasPrefix(rest, "<...") {
			head, ok := pending[pid]
			if !ok {
				continue
			}
			delete(pending, pid)
			if k := strings.Index(rest, "resumed>"); k >= 0 {
				rest = head + rest[k+len("resumed>"):]
			} else {
				rest = head
			}
		}
		if strings.HasPrefix(rest, "+++") || strings.HasPrefix(rest, "---") {
			continue
		}
		cm := reCall.FindStringSubmatch(rest)
		if cm == nil {
			continue
		}
		res.Lines++
		name, args, ret, tail := cm[1], cm[2], cm[3], cm[4]
		ok := ret != "?" && !strings.HasPrefix(ret, "-")
		switch {
		case name == "clone" || name == "clone3" || name == "fork" || name == "vfork":
			if ok && ret != "0" {
				if _, seen := cwds[ret]; !seen {
					cwds[ret] = cwds[pid]
				}
			}
			continue
		case name == "chdir":
			if s := reStr.FindStringSubmatch(args); ok && s != nil {
				cwds[pid] = absify(pid, "", unescape(s[1]))
			}
			continue
		case name == "fchdir":
			if fm := reFdPath.FindStringSubmatch(args); ok && fm != nil {
				cwds[pid] = fm[1]
			}
			continue
		case name == "getdents64":
			if fm := reFdPath.FindStringSubmatch(args); ok && fm != nil && filter.Keep(fm[1]) {
				seg().Lists[fm[1]] = true
			}
			continue
		case name == "connect":
			if strings.Contains(args, "AF_INET") {
				ip, port := "?", "0"
				if im := reInet.FindStringSubmatch(args); im != nil {
					ip = im[1]
					if ip == "" {
						ip = im[2]
					}
				}
				if pm := rePort.FindStringSubmatch(args); pm != nil {
					port = pm[1]
				}
				seg().Net = append(seg().Net, [2]string{ip, port})
			}
			continue
		}
		dirpart := ""
		if fm := reFdPath.FindStringSubmatch(args); fm != nil {
			dirpart = fm[1]
		}
		sloc := reStr.FindStringSubmatchIndex(args)
		if sloc == nil {
			continue
		}
		raw := unescape(args[sloc[2]:sloc[3]])
		if mm := reMarker.FindStringSubmatch(raw); mm != nil {
			i, _ := strconv.Atoi(mm[2])
			if mm[1] == "B" {
				cur = i
			} else {
				cur = -1
			}
			continue
		}
		path := absify(pid, dirpart, raw)
		switch {
		case openCalls[name]:
			flags := args[sloc[1]:]
			if ok {
				real := path
				if rp := reRet.FindStringSubmatch(strings.TrimSpace(tail)); rp != nil {
					real = rp[1]
				}
				fl := map[string]bool{}
				for _, f := range reFlag.FindAllString(flags, -1) {
					fl[f] = true
				}
				if fl["O_WRONLY"] || fl["O_RDWR"] || fl["O_CREAT"] || fl["O_TRUNC"] || fl["O_APPEND"] || name == "creat" {
					res.Written[path] = true
					res.Written[real] = true
					clobber := name == "creat" || fl["O_TRUNC"] || fl["O_EXCL"] || missingSeen[path] || !(fl["O_RDWR"] || fl["O_APPEND"])
					if clobber {
						if _, seen := first[path]; !seen {
							first[path] = 'w'
						}
					} else if filter.Keep(path) {
						if _, seen := first[path]; !seen {
							first[path] = 'r'
						}
						if first[path] == 'r' {
							seg().Reads[path] = true
						}
					}
					continue
				}
				if fl["O_DIRECTORY"] {
					if filter.Keep(path) {
						seg().Exists[path] = true
					}
					continue
				}
				if filter.Keep(path) {
					if _, seen := first[path]; !seen {
						first[path] = 'r'
					}
					seg().Reads[path] = true
				}
			} else if (strings.Contains(tail, "ENOENT") || strings.Contains(tail, "ENOTDIR")) && filter.Keep(path) {
				seg().Missing[path] = true
				missingSeen[path] = true
			}
		case statCalls[name]:
			if !filter.Keep(path) {
				continue
			}
			if ok {
				seg().Exists[path] = true
			} else if strings.Contains(tail, "ENOENT") || strings.Contains(tail, "ENOTDIR") {
				seg().Missing[path] = true
				missingSeen[path] = true
			}
		case name == "execve":
			if ok {
				seg().Execs = append(seg().Execs, path)
			}
		case writeCalls[name]:
			if ok {
				res.Written[path] = true
				if _, seen := first[path]; !seen {
					first[path] = 'w'
				}
				if all := reStr.FindAllStringSubmatch(args, -1); len(all) > 1 {
					res.Written[absify(pid, "", unescape(all[len(all)-1][1]))] = true
				}
			}
		}
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	// A path written by the run is a dependency only if its first access read
	// the old content; a listing of a directory the run modified is dropped
	// (it reflects the run's own outputs).
	for _, d := range res.Segments {
		for p := range d.Reads {
			if res.Written[p] && first[p] != 'r' {
				delete(d.Reads, p)
			}
		}
		for p := range d.Lists {
			if res.Written[p] {
				delete(d.Lists, p)
			}
		}
		for p := range d.Exists {
			if res.Written[p] || d.Reads[p] {
				delete(d.Exists, p)
			}
		}
		for p := range d.Missing {
			if res.Written[p] || d.Exists[p] || d.Reads[p] {
				delete(d.Missing, p)
			}
		}
	}
	return res, nil
}
