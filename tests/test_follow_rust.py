"""The strace log parser of ``detpy.follow`` in Rust (``crates/detpy-py/src/follow.rs``), checked against the Python
original kept verbatim in ``tests/rust_hotpaths_ref/_ref_follow.py``:

* line by line (``_split_line``, ``_split_args``, ``_unquote``) on synthetic edge cases, generated lines and every
  line of real strace logs;
* whole ``parse`` (every ``Result`` attribute) on real strace logs of several programs, written by strace with the
  flags ``Follower.rewrite`` uses, and on synthetic logs (still running, unreadable, killed, non-UTF-8 paths, chdir and
  fchdir, clocks, the clock shim's marker, sockets, malformed lines);
* ``special`` and ``shebang`` on lists of paths and files; ``_logs`` and ``_complete`` on a directory of logs.
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from detpy import _core, follow

REF = Path(__file__).parent / "rust_hotpaths_ref"
sys.path.insert(0, str(REF))
import _ref_follow as ref  # noqa: E402

ATTRS = ("ops", "net", "proc", "bad", "entropy", "pids", "bound", "clock", "unshimmed", "t0", "t1")


def _enc(s: str) -> bytes:
    return s.encode("utf-8", "surrogateescape")


def _call(f, *args):
    try:
        return "ok", f(*args)
    except Exception as e:  # noqa: BLE001 (the original's exceptions must be raised the same)
        return "exc", type(e), str(e)


def _new_split_line(line):
    return _core.follow_split_line(_enc(line))


def _new_split_args(s):
    return _core.follow_split_args(_enc(s))


def _new_unquote(tok):
    return _core.follow_unquote(_enc(tok))


def _attrs(res) -> dict:
    out = {a: getattr(res, a) for a in ATTRS}
    for a in ("t0", "t1"):  # floats: identical bits, not only equal
        out[a] = None if out[a] is None else (type(out[a]), out[a].hex())
    out["ops_types"] = [tuple(type(x) for x in op) for op in res.ops]
    return out


def same_parse(paths, cwd):
    a = _call(ref.parse, paths, cwd)
    b = _call(follow.parse, paths, cwd)
    if a[0] == "ok" and b[0] == "ok":
        assert type(b[1]) is follow.Result
        assert _attrs(a[1]) == _attrs(b[1])
        return b[1]
    assert a == b
    return None


def same_lines(lines):
    for line in lines:
        assert _call(ref._split_line, line) == _call(_new_split_line, line), line
        sp = ref._split_line(line)
        texts = [line] + ([sp[1]] if sp else [])
        for t in texts:
            assert _call(ref._split_args, t) == _call(_new_split_args, t), t
            for a in ref._split_args(t):
                assert _call(ref._unquote, a) == _call(_new_unquote, a), a
        assert _call(ref._unquote, line) == _call(_new_unquote, line), line


# ---------------------------------------------------------------------------------------------------------------
# synthetic lines

SYNTH = [
    'openat(AT_FDCWD</home/u>, "a.txt", O_RDONLY|O_CLOEXEC) = 3</home/u/a.txt>',
    'openat(AT_FDCWD</home/u>, "missing", O_RDONLY) = -1 ENOENT (No such file or directory)',
    'openat(3</usr/lib>, "x\\x41\\x4g\\x4", O_RDONLY) = 4</usr/lib/xA>',
    'open("/tmp/\\303\\251t\\303\\251", O_WRONLY|O_CREAT|O_TRUNC, 0666) = 3</tmp/\xe9t\xe9>',
    'open("a\\nb\\tc\\rd\\ve\\ff\\\\g\\"h\\\'i\\aj\\bk\\el\\qm\\0n\\1o\\12p\\123q\\777r\\1234", O_RDONLY) = 3',
    'open("tr"..., O_RDONLY) = 3',
    'open("unterminated, O_RDONLY) = 3',
    'open("bad \\8 octal", O_RDONLY) = 3',
    'open("bad \\9", O_RDONLY) = 3',
    'open("", O_RDONLY) = -1 ENOENT (No such file or directory)',
    'stat("/a/b", 0x7ffd) = ?',
    'stat("/a/b", 0x7ffd) = ? <unavailable>',
    'execve("/usr/bin/x", ["x"...], 0x7ff /* 3 vars */) = ?',
    'exit_group(0) = ?',
    'newfstatat(AT_FDCWD</>, "/etc/ld.so.cache", {st_mode=S_IFREG|0644, st_size=1234, ...}, 0) = 0',
    'newfstatat(3</usr/lib/x86_64-linux-gnu/libc.so.6>, "", {st_mode=S_IFREG|0755, ...}, AT_EMPTY_PATH) = 0',
    'statx(AT_FDCWD</w>, "f", AT_STATX_SYNC_AS_STAT, STATX_ALL, {stx_mask=STATX_ALL|0x1000, ...}) = 0',
    'faccessat2(AT_FDCWD</w>, "/__detpy_clock_shim__", F_OK, 0) = -1 ENOENT (No such file or directory)',
    'connect(3<socket:[1234]>, {sa_family=AF_UNIX, sun_path="/run/nscd/socket"}, 110) = -1 ENOENT (No such file)',
    'connect(3<UNIX:[1]>, {sa_family=AF_UNIX, sun_path=@"abstract\\0name"}, 20) = 0',
    'connect(3, {sa_family=AF_UNIX, sun_path=@"\\x"}, 20) = 0',
    ('connect(3, {sa_family=AF_INET6, sin6_port=htons(80), sin6_flowinfo=htonl(0), inet_pton(AF_INET6, "::1", '
     '&sin6_addr), sin6_scope_id=0}, 28) = -1 ECONNREFUSED (Connection refused)'),
    'connect(3, {sa_family=AF_INET, sin_port=htons(53), sin_addr=inet_addr("10.0.0.1")}, 16) = 0',
    'bind(3<NETLINK:[5]>, {sa_family=AF_NETLINK, nl_pid=0, nl_groups=00000000}, 12) = 0',
    'sendto(3, "\\24\\0\\0\\0"..., 20, 0, {sa_family=AF_NETLINK, nl_pid=0, nl_groups=00000000}, 12) = 20',
    'sendto(3<TCP:[1]>, "GET /"..., 100, MSG_NOSIGNAL, NULL, 0) = 100',
    'sendmsg(3, {msg_name=NULL, msg_namelen=0, msg_iov=[{iov_base="x", iov_len=1}], msg_iovlen=1}, 0) = 1',
    'getdents64(3</home/u/dir>, 0x55 /* 4 entries */, 32768) = 112',
    'getdents64(3<pipe:[1]>, 0x55 /* 0 entries */, 32768) = 0',
    'getdents64(3, 0x55, 32768) = -1 EBADF (Bad file descriptor)',
    'renameat2(AT_FDCWD</w>, "a", 4</w/d>, "b", RENAME_NOREPLACE) = 0',
    'rename("a", "b") = -1 EXDEV (Invalid cross-device link)',
    'linkat(AT_FDCWD</w>, "a", AT_FDCWD</w>, "c", 0) = 0',
    'symlinkat("target", AT_FDCWD</w>, "link") = 0',
    'symlink("/abs/target", "rel/link") = -1 EEXIST (File exists)',
    'chdir("sub/../other") = 0',
    'fchdir(4</new/cwd>) = 0',
    'clock_gettime(CLOCK_REALTIME, {tv_sec=1, tv_nsec=2}) = 0',
    'clock_gettime(CLOCK_MONOTONIC, {tv_sec=1, tv_nsec=2}) = 0',
    'clock_gettime( CLOCK_TAI , {tv_sec=1, tv_nsec=2}) = 0',
    'gettimeofday({tv_sec=1, tv_usec=2}, NULL) = 0',
    'time(NULL) = 1700000000',
    'getrandom("\\x12\\x34", 16, GRND_NONBLOCK) = 16',
    'clone(child_stack=NULL, flags=CLONE_CHILD_CLEARTID|SIGCHLD, child_tidptr=0x7f) = 1234',
    'clone3({flags=CLONE_VM|CLONE_VFORK, exit_signal=SIGCHLD, stack=0x7f, stack_size=0x9000}, 88) = 99',
    'readlink("/proc/self/exe", "/u"..., 4096) = 13',
    'mmap(NULL, 8192, PROT_READ, MAP_PRIVATE, 3, 0) = 0x7f0000000000',
    'unknown_call(1, 2) = 0x1f',
    'weird(a) = 0x',
    'f(x) =  0',
    'f(x)  = 0',
    'f(x) = 0 = 1',
    'f(") = 0", x) = 5',
    'f(x) = 3<a>b> ENOENT (x) <unavailable>',
    'f(x) = 3<a> EX () <unavailable>',
    'f(x) = 3<a> E (x)',
    'f(x) = 3<a> E1_ (x))',
    'f(x) = -5 ERESTARTSYS (To be restarted if SA_RESTART is set)',
    'f(x) = ? ERESTART_RESTARTBLOCK (Interrupted by signal)',
    'f(x) = -',
    'f(x) = --1',
    '(x) = 0',
    'noparen = 0',
    '',
    '   ',
    '+++ exited with 0 +++',
    '--- SIGCHLD {si_signo=SIGCHLD} ---',
    'open("caf\udce9/\udcff\udc80", O_RDONLY) = 3</x/caf\udce9>',
    'open("   spaced  ", O_RDONLY) = 3',
    'open(　"ws-quoted" , O_RDONLY) = 3',
    'f({a, b}, [c, d], (e, f), <g, h>, "i, j", k) = 0',
    'f({a, {b, c}}, [x, [y]], z) = 0',
    'f(a,, b, ) = 0',
    'f(a, "x\\", y) = 0',
    'f("\\',
    'f(x) = 0\x1f',
    'f(x) = 0 \x85',
    'f(x) = 0<é>',
    'f(x) = ٣',  # an Arabic-Indic digit: \d in Python (see test_known_differences)
    'unlinkat(5</d>, "f", 0) = 0',
    'utimensat(AT_FDCWD</w>, NULL, [UTIME_NOW, UTIME_NOW], 0) = 0',
    'mkdir("//double/./slash/..", 0777) = 0',
    'mkdir("///triple", 0777) = 0',
    'inotify_add_watch(3, "/etc", IN_MODIFY) = 1',
    'execveat(3</bin>, "sh", ["sh"], 0x7ff /* 0 vars */, 0) = 0',
]


def test_known_differences_are_only_unicode_digits():
    # Python's \d and str.isdigit accept every Unicode digit; the port reads ASCII digits (strace writes nothing
    # else). The one generated line that shows it:
    line = "f(x) = ٣"
    assert ref._split_line(line) == ("f", "x", "٣", None, None)
    assert _new_split_line(line) is None


def _gen_lines(n: int, seed: int) -> list[str]:
    rnd = random.Random(seed)
    names = ["open", "openat", "stat", "newfstatat", "execve", "connect", "bind", "rename", "f", "x(y", ""]
    atoms = ['"', "\\", "(", ")", "{", "}", "[", "]", "<", ">", ",", " ", "=", "-", "?", "...", "AT_FDCWD<",
             "sun_path=", "@", "sa_family=AF_", "UNIX", "x", "0x1f", "12", "ENOENT", " (", " <unavailable>",
             "\\x4", "\\777", "\\n", " ", " ", "\udcff", "é", "\t", "\r", "\x0b", "a/b", "/", "..",
             ") = ", ")  = ", " = -1 ", "O_CREAT", "O_RDWR"]
    out = []
    for _ in range(n):
        body = "".join(rnd.choice(atoms) for _ in range(rnd.randint(0, 14)))
        tail = rnd.choice([") = 0", ") = -1 ENOENT (No such file or directory)", ") = ?", ") = 3<x>", "", ") = 0x10",
                           ") = 3<a>b> EX (y) <unavailable>", ") = -2 E (z))"])
        out.append(rnd.choice(names) + "(" + body + tail)
    return out


def test_split_line_args_unquote_synthetic():
    same_lines([x for x in SYNTH if "٣" not in x])


def test_split_line_args_unquote_generated():
    same_lines([x for x in _gen_lines(4000, 1) if "٣" not in x])


def test_unquote_tokens():
    toks = ['"a"', '""', '"', "", " ", '"abc"...', '"abc..."', '"..."', "'a'", '"\\x41\\x4"', '"\\', '"\\"',
            '"\\x"', '"\\xZZ"', '"\\0\\00\\000\\0000"', '"\\8"', '"\\9x"', '"\\\n"', '"a\\\nb"', '"\\\udcff"',
            '"\\é"', ' \t"x"  ', ' "x"', '"\udce9\udc80"', '"\\303\\251"', '"\\377\\376"',
            '"\\xff\\xFE"', '"\\e\\a\\b\\f\\v"', '"\\q\\z\\N"']
    for t in toks:
        assert _call(ref._unquote, t) == _call(_new_unquote, t), t


def test_split_args_edge():
    cases = ["", ",", "a,", "a, ", ",a", '"a,b",c', '"a\\"b",c', '"a\\', '"\\', "{a,b},c", "{a,b,c", "}a,b",
             "a)b,c", "<x,y>,z", "　a　, b", "a,\x1f,b", "\udcff,\udc80"]
    for c in cases:
        assert _call(ref._split_args, c) == _call(_new_split_args, c), c


# ---------------------------------------------------------------------------------------------------------------
# synthetic logs

def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return str(path)


def _log(*lines: str | bytes, ts: bool = True, end: str | bytes | None = "+++ exited with 0 +++") -> bytes:
    out = []
    t = 1700000000.000001
    for x in list(lines) + ([end] if end is not None else []):
        b = x if isinstance(x, bytes) else _enc(x)
        if ts:
            b = f"{t:.6f} ".encode() + b
            t += 0.000137
        out.append(b)
    return b"\n".join(out) + b"\n"


def test_parse_synthetic(tmp_path):
    d = tmp_path
    cwds = ["/w", "", "rel/dir", "/", "//x", "///y/./z/..", "/caf\udce9"]
    cases = {
        "all": _log(*SYNTH),
        "running": _log('openat(AT_FDCWD</w>, "a", O_RDONLY) = 3', end=None),
        "running-ts-only": _log('stat("/a", 0x1) = 0', end="--- SIGTERM ---"),
        "killed": _log('openat(AT_FDCWD</w>, "a", O_RDONLY) = 3', end="+++ killed by SIGKILL +++"),
        "killed-core": _log('stat("a", 0x1) = 0', end="+++ killed by SIGSEGV (core dumped) +++"),
        "nonutf8": _log(b'openat(AT_FDCWD</caf\xe9>, "x\xff\\377\xc3", O_RDONLY) = 3',
                        b'chdir("/d\xe9j\xe0") = 0', b'stat("rel\x80", 0x1) = 0',
                        b'execve("/bin/\xff", ["x"], 0x1 /* 0 vars */) = 0', b'garbage \xff\xfe ' + b"\xe9" * 200),
        "chdirs": _log('stat("a", 0x1) = 0', 'chdir("sub") = 0', 'stat("b", 0x1) = 0',
                       'chdir("nope") = -1 ENOENT (No such file or directory)', 'stat("c", 0x1) = 0',
                       'fchdir(5</fd/dir>) = 0', 'stat("d", 0x1) = 0', 'fchdir(5<>) = 0', 'stat("e", 0x1) = 0',
                       'fchdir(9) = -1 EBADF (Bad file descriptor)', 'fchdir(AT_FDCWD) = 0',
                       'openat(AT_FDCWD</new/cwd>, "f", O_RDONLY) = 3', 'stat("g", 0x1) = 0',
                       'getdents64(AT_FDCWD, 0x1, 10) = 0', 'getdents64(3<>, 0x1, 10) = 0'),
        "clocks": _log('clock_gettime(CLOCK_MONOTONIC, {tv_sec=1}) = 0', 'clock_gettime(CLOCK_BOOTTIME, {}) = 0',
                       'clock_gettime(CLOCK_REALTIME_COARSE, {tv_sec=1}) = 0', 'time(NULL) = 5'),
        "clock-gtod": _log('gettimeofday({tv_sec=1}, NULL) = 0', 'clock_gettime(CLOCK_TAI, {}) = 0'),
        "shim-marked": _log('execve("/usr/bin/python3", ["python3"], 0x1 /* 9 vars */) = 0',
                            'faccessat(AT_FDCWD</w>, "/__detpy_clock_shim__", F_OK) = -1 ENOENT (No such file)'),
        "shim-unmarked": _log('execve("/usr/bin/static", ["static"], 0x1 /* 9 vars */) = 0', 'stat("/x", 0x1) = 0'),
        "shim-remarked": _log('execve("/a", ["a"], 0x1) = 0', 'access("/__detpy_clock_shim__", F_OK) = -1 ENOENT (x)',
                              'execve("/b", ["b"], 0x1) = 0'),
        "exec-failed": _log('execve("/no", ["no"], 0x1) = -1 ENOENT (No such file or directory)'),
        "exec-noargs": _log("execve() = 0"),
        "exec-empty-path": _log('execve("", [], 0x1) = 0'),
        "execveat-short": _log('execveat(3) = 0'),
        "fchdir-noargs": _log("fchdir() = 0"),
        "openat-noargs": _log("openat() = 3"),
        "octal": _log('stat("\\8", 0x1) = 0'),
        "octal-sock": _log('connect(3, {sa_family=AF_UNIX, sun_path="\\9"}, 5) = 0'),
        "sockets": _log('bind(3, {sa_family=AF_UNIX, sun_path="srv.sock"}, 10) = 0',
                        'connect(4, {sa_family=AF_UNIX, sun_path="srv.sock"}, 10) = 0',
                        'connect(4, {sa_family=AF_UNIX, sun_path="/run/nscd/socket"}, 10) = -1 ENOENT (x)',
                        'connect(4, {sa_family=AF_UNIX, sun_path="/run/x"}, 10) = -1 ENOTDIR (x)',
                        'bind(5, {sa_family=AF_UNIX, sun_path=@"abs"}, 10) = 0',
                        'connect(6, {sa_family=AF_UNIX, sun_path=@"abs"}, 10) = 0',
                        'bind(7, {sa_family=AF_UNIX}, 2) = 0', 'connect(8, {sa_family=AF_UNIX}, 2) = 0',
                        'bind(9, {sa_family=AF_INET, sin_port=htons(0)}, 16) = 0',
                        'connect(9, {sa_family=AF_UNIX, sun_path="/var/run/dbus"}, 10) = -1 EACCES (x)'),
        "net-unix": _log('connect(4, {sa_family=AF_UNIX, sun_path="/var/run/docker.sock"}, 10) = 0'),
        "net-unix-none": _log('sendto(4, "x", 1, 0, {sa_family=AF_UNIX}, 2) = 1'),
        "net-inet6": _log('connect(3, {sa_family=AF_INET6, sin6_port=htons(443)}, 28) = 0'),
        "net-netlink": _log('bind(3, {sa_family=AF_NETLINK, nl_pid=0}, 12) = 0'),
        "unknown": _log("ptrace(PTRACE_TRACEME) = 0", 'stat("/after", 0x1) = 0'),
        "unparsed": _log("this is not strace " + "é" * 50 + "\udcff" * 100, 'open("tr"..., O_RDONLY) = 3'),
        "tmpfile": _log('openat(AT_FDCWD</w>, "/tmp", O_RDWR|O_EXCL|O_TMPFILE, 0600) = 3'),
        "rdwr": _log('openat(AT_FDCWD</w>, "a", O_RDWR) = 3', 'openat(AT_FDCWD</w>, "b", O_RDWR|O_TRUNC) = 3',
                     'openat(AT_FDCWD</w>, "c", O_RDWR|O_CREAT|O_EXCL, 0600) = 3',
                     'openat(AT_FDCWD</w>, "d", O_RDWR|O_CREAT, 0600) = 3',
                     'openat(AT_FDCWD</w>, "e", O_WRONLY|O_APPEND) = -1 EACCES (x)', 'open("f", O_APPEND) = 4'),
        "renames": _log('renameat2(3</a>, "x", 4</b>, "y", 0) = 0', 'renameat(3</a>, "x", 4</b>) = 0',
                        'link("a", "b") = -1 EEXIST (x)', 'rename("a") = 0',
                        'symlinkat("t", 5</d>, "l") = 0', 'symlinkat("t", 5</d>) = 0'),
        "empty-at": _log('newfstatat(3</x>, "", {}, AT_EMPTY_PATH) = 0', 'stat("", 0x1) = -1 ENOENT (x)',
                         'unlinkat(AT_FDCWD</w>, "q", 0) = -1 ENOENT (x)', 'mkdir("m", 0777) = 0'),
        "no-ts": _log('stat("/a", 0x1) = 0', ts=False),
        "line-breaks": _log(b'stat("/a\rb", 0x1) = 0', b'stat("/c\x0bd", 0x1) = 0', b'stat("/e\xc2\x85f", 0x1) = 0',
                            b'stat("/g\xe2\x80\xa8h", 0x1) = 0', b'stat("/i\x1cj", 0x1) = 0',
                            b'stat("/k\x0cl", 0x1) = 0', b'stat("/m\r\nn", 0x1) = 0', b'stat("/\xe2\x80", 0x1) = 0'),
        "crlf-end": _log('stat("/a", 0x1) = 0').replace(b"\n", b"\r\n"),
        "trailing-blank": _log('stat("/a", 0x1) = 0') + b"\n",
        "empty": b"",
        "only-newlines": b"\n\n\n",
        "huge-ts": b"9" * 400 + b".5 stat(\"/a\", 0x1) = 0\n" + b"0001.0010000000000000000001 +++ exited with 0 +++\n",
        "ts-odd": b"1.2.3 stat(\"/a\", 0x1) = 0\n12. stat(\"/b\", 0x1) = 0\n.5 x\n1700000000.5 +++ exited with 1 +++\n",
    }
    paths = {k: _write(d / f"log.{i}", v) for i, (k, v) in enumerate(cases.items())}
    os.mkdir(d / "adir.7")
    for k, p in paths.items():
        for cwd in cwds:
            same_parse([p], cwd)
    allp = list(paths.values())
    missing = str(d / "missing.99")
    adir = str(d / "adir.7")
    same_parse(allp, "/w")
    same_parse(list(reversed(allp)), "/w")
    for combo in ([missing], [adir], [missing, paths["all"]], [paths["running"], missing], [paths["all"], missing],
                  [paths["nonutf8"], paths["killed"], adir], [], [paths["sockets"], paths["sockets"]],
                  [paths["octal"], missing], [missing, paths["octal"]],
                  [paths["shim-unmarked"], paths["exec-empty-path"]],
                  [paths["exec-empty-path"], paths["shim-unmarked"]], [paths["no-ts"], paths["clocks"]],
                  [paths["clocks"], paths["no-ts"], paths["huge-ts"]], [paths["unparsed"], paths["unknown"]]):
        same_parse(combo, "/w")
    r = same_parse([paths["nonutf8"]], "/w")
    assert ("r", "/caf\udce9/x\udcff\udcff\udcc3") in r.ops
    r = same_parse([missing], "/w")
    assert r.bad.startswith("log unreadable: [Errno 2]")
    r = same_parse([paths["shim-unmarked"]], "/w")
    assert r.unshimmed == "/usr/bin/static"
    r = same_parse([paths["clocks"]], "/w")
    assert r.clock == "reads the real clock (CLOCK_REALTIME_COARSE)"
    for k in ("octal", "execveat-short", "fchdir-noargs", "openat-noargs", "octal-sock"):
        assert same_parse([paths[k]], "/w") is None  # the original raises; so does the port


def test_parse_generated_logs(tmp_path):
    rnd = random.Random(7)
    lines = [x for x in _gen_lines(3000, 2) if "٣" not in x] + SYNTH[:-1]
    rnd.shuffle(lines)
    paths = []
    for i in range(0, len(lines), 60):
        chunk = lines[i:i + 60]
        if rnd.random() < 0.8:
            chunk = [x for x in chunk if x.strip() and not x.startswith(("+++", "---"))]
        paths.append(_write(tmp_path / f"g.{i}", _log(*chunk, end=rnd.choice(["+++ exited with 0 +++", None]))))
    for p in paths:
        same_parse([p], "/g")
    same_parse(paths, "/g")


# ---------------------------------------------------------------------------------------------------------------
# real strace logs

def _strace_ok(tmp: Path) -> bool:
    return shutil.which("strace") is not None and follow.probe(str(tmp / "probe")) is None


PY_SCRIPT = r"""
import json, os, socket, subprocess, sys, time
d = sys.argv[1]
os.chdir(d)
os.mkdir("sub")
with open("sub/a.txt", "w") as fh:
    fh.write("x")
open("sub/a.txt").read()
with open("sub/a.txt", "r+") as fh:
    fh.write("y")
os.rename("sub/a.txt", "sub/b.txt")
os.symlink("b.txt", "sub/l.txt")
os.link("sub/b.txt", "sub/h.txt")
os.listdir("sub")
os.chdir("sub")
os.stat("../sub/b.txt")
os.path.exists("nope/../x")
os.utime("b.txt")
os.chmod("b.txt", 0o600)
os.unlink("h.txt")
weird = os.fsencode(os.getcwd()) + b"/caf\xe9 \xff\x01\"q\\"
with open(weird, "wb") as fh:
    fh.write(b"x")
os.listdir(os.fsencode(os.getcwd()))
fd = os.open("..", os.O_RDONLY)
os.fchdir(fd)
os.stat("sub")
os.urandom(8)
time.time()
time.monotonic()
s = socket.socket(socket.AF_UNIX)
s.bind(os.path.join(d, "srv.sock"))
s.listen()
c = socket.socket(socket.AF_UNIX)
c.connect(os.path.join(d, "srv.sock"))
for path in (os.path.join(d, "nosock"), "/nonexistent/dir/sock"):
    try:
        socket.socket(socket.AF_UNIX).connect(path)
    except OSError:
        pass
a = socket.socket(socket.AF_UNIX)
a.bind("\0detpy-follow-test-%d" % os.getpid())
for fam, addr in ((socket.AF_INET, ("127.0.0.1", 9)), (socket.AF_INET6, ("::1", 9))):
    try:
        socket.socket(fam).connect(addr)
    except OSError:
        pass
try:
    socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0).bind((0, 0))
except OSError:
    pass
subprocess.run(["true"])
subprocess.run([sys.executable, "-c", "import os; os.listdir('.')"])
"""

BIG = ("import asyncio, email.parser, json, http.client, xml.etree.ElementTree, unittest, decimal, argparse, logging, "
       "zipfile, tarfile, csv, difflib, pydoc, inspect, dataclasses, typing, concurrent.futures, multiprocessing, "
       "sqlite3, ssl, urllib.request, tomllib, statistics, fractions, pathlib, shutil, tempfile, textwrap")


def _commands(work: Path) -> dict:
    cmds = {
        "py-files": [sys.executable, "-c", PY_SCRIPT, str(work / "py")],
        "py-big": [sys.executable, "-c", BIG],
        "sh-pipeline": ["sh", "-c", (f"cd {work} && mkdir -p sh/d/e && cd sh/d && ls -la .. | cat > out.txt && "
                                     "cp out.txt e/ && cat e/out.txt | wc -l && "
                                     "ls -R /etc /usr/share/zoneinfo > /dev/null 2>&1; "
                                     "cat /proc/self/status > /dev/null; true")],
        "ls": ["ls", "-la", "/etc", "/usr/bin"],
    }
    (work / "py").mkdir()
    if shutil.which("git"):
        cmds["git"] = ["git", "--version"]
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc:
        (work / "hello.c").write_text('#include <stdio.h>\nint main(void){puts("hi");return 0;}\n')
        cmds["cc"] = [cc, "-o", str(work / "hello"), str(work / "hello.c")]
    return cmds


def _run_traced(prefix: str, cmd: list, env=None) -> list:
    argv = [shutil.which("strace"), "-DDD", "-ff", "-q", "-y", "-ttt", "-s", "1", "--seccomp-bpf", "-e",
            "trace=" + follow.STRACE_TRACE, "-e", "signal=none", "-o", prefix, "--", *cmd]
    subprocess.run(argv, check=False, capture_output=True, timeout=300, env=env)
    return follow._wait_logs(prefix, 15.0)


@pytest.fixture(scope="module")
def real_logs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("follow-real")
    if not _strace_ok(tmp):
        pytest.skip(f"strace cannot trace here: {follow.probe(str(tmp / 'probe'))}")
    shim, _why = follow.build_shim(str(tmp / "shim"))
    (tmp / "logs").mkdir()
    out = {}
    for shimmed in (False, True):
        work = tmp / ("work-shim" if shimmed else "work")
        work.mkdir()
        env = dict(os.environ)
        if shimmed and shim:
            env["LD_PRELOAD"] = shim
        for name, cmd in _commands(work).items():
            key = f"{name}-{int(shimmed)}"
            out[key] = (_run_traced(str(tmp / "logs" / key), cmd, env=env), str(work))
    return out


def test_parse_real_logs(real_logs):
    n_ops = 0
    for name, (logs, work) in real_logs.items():
        assert logs, name
        for cwd in (work, "/", "rel"):
            r = same_parse(logs, cwd)
            assert r is not None
        n_ops += len(r.ops)
    assert n_ops > 1000
    r = same_parse(real_logs["py-files-0"][0], real_logs["py-files-0"][1])
    ops = set(r.ops)
    work = real_logs["py-files-0"][1]
    assert ("w", f"{work}/py/sub/b.txt") in ops and ("d", f"{work}/py/sub") in ops
    assert any(p.endswith("caf\udce9 \udcff\x01\"q\\") for _, p in r.ops)
    assert r.net and r.entropy and len(r.pids) >= 3 and f"{work}/py/srv.sock" in r.bound
    rs = same_parse(real_logs["py-files-1"][0], real_logs["py-files-1"][1])
    if follow._PROBE.get("shim"):
        assert rs.clock and r.clock is None


def test_real_log_lines(real_logs):
    lines = set()
    for logs, _ in real_logs.values():
        for f in logs:
            with open(f, encoding="utf-8", errors="surrogateescape") as fh:
                lines.update(ref._strip_ts(x)[1] for x in fh.read().splitlines())
    assert len(lines) > 500
    same_lines(sorted(lines))


def test_parse_partial_real_logs(real_logs, tmp_path):
    # a log cut anywhere (a process still running, a truncated last line)
    logs, work = real_logs["py-files-0"]
    data = Path(logs[0]).read_bytes()
    rnd = random.Random(3)
    for i, cut in enumerate(sorted(rnd.sample(range(len(data)), 40))):
        p = _write(tmp_path / f"cut.{i}", data[:cut])
        same_parse([p], work)
        same_parse([p] + logs[1:], work)


# ---------------------------------------------------------------------------------------------------------------
# special, shebang

def test_special():
    pids = {"12", "345", "\udcff"}
    paths = ["/proc", "/sys", "/dev", "/proc/", "/procx", "/system", "/device", "/dev/shm/x", "/dev/shm", "/dev/null",
             "/dev/null/x", "/dev/tty", "/dev/tty1", "/dev/stdin", "/dev/fd/3", "/dev/fd", "/dev/pts/0", "/dev/urandom",
             "/dev/random", "/dev/random2", "/proc/self", "/proc/selfish", "/proc/self/maps", "/proc/thread-self/x",
             "/proc/12", "/proc/12/status", "/proc/123/status", "/proc/345/", "/proc//12", "/proc/\udcff/x",
             "/proc/\udcfe/x", "/proc/\ud800/x", "/proc/é", "/proc/cpuinfo", "/proc/cpuinfo/x", "/proc/meminfo",
             "/proc/sys/vm/overcommit_memory", "/sys/devices/system/cpu/", "/sys/devices/system/cpu/online",
             "/sys/devices/system/cpu", "/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup", "/sys/fs/selinux",
             "/sys/fs/selinux/x", "/proc/filesystems", "/proc/mounts", "/proc/net/dev", "/sys/class/net", "/etc/x",
             "", "relative", "/", "/dev/sda", "/proc/12\udcff"]
    for p in paths:
        for ps in (pids, set(), ["12"], ("345",), frozenset({"\ud800"})):
            assert _call(ref.special, p, ps) == _call(follow.special, p, ps), (p, ps)


def test_shebang(tmp_path):
    files = {
        "sh": b"#!/bin/sh\necho\n",
        "env": b"#!  /usr/bin/env python3 -u\n",
        "empty-bang": b"#!\n",
        "ws": b"#!\t\x0b\x0c /x/y\r\n",
        "nonl": b"#!/no/newline",
        "long": b"#!/" + b"a" * 300,
        "nonutf8": b"#!/tmp/\xff\xe9/py\n",
        "none": b"echo hi\n",
        "empty": b"",
        "bang-only": b"#!",
        "space-sep": b"#! \x1c/fs/sep\n",
        "nbsp": b"#!\xc2\xa0/x\n",
        "binary": b"\x7fELF\x02\x01",
    }
    paths = [_write(tmp_path / k, v) for k, v in files.items()]
    paths += [str(tmp_path), str(tmp_path / "missing"), "/dev/null", "", "caf\udce9", str(tmp_path / "sh") + "/x"]
    for p in paths:
        assert _call(ref.shebang, p) == _call(follow.shebang, p), p
    assert _call(ref.shebang, "a\0b") == _call(follow.shebang, "a\0b")


# ---------------------------------------------------------------------------------------------------------------
# _logs, _complete

def test_logs_and_complete(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    big = _log(*(['stat("/x", 0x1) = 0'] * 500))
    contents = {
        "s1-1.100": _log('stat("/a", 0x1) = 0'),
        "s1-1.99": _log('stat("/a", 0x1) = 0', end="+++ killed by SIGKILL +++"),
        "s1-1.7": _log('stat("/a", 0x1) = 0', end=None),
        "s1-1.8": _log('stat("/a", 0x1) = 0') + b"\n\n\n",
        "s1-1.9": b"+++ exited with 0 +++",
        "s1-1.10": b"",
        "s1-1.11": b"\n\n",
        "s1-1.12": big,
        "s1-1.13": big[:-30],
        "s1-1.14": b"x" * 5000 + b"\n1.5 +++ exited with 3 +++\n",
        "s1-1.15": b"+++ exited with 0 +++\r\n",
        "s1-1.16": b"1.2.3 +++ exited with 0 +++\n",
        "s1-1.abc": b"",
        "s1-1.": b"",
        "s1-1.12.x": b"",
        "s1-10.1": b"",
        "s1-1x.1": b"",
        "other.1": b"",
    }
    for k, v in contents.items():
        (d / k).write_bytes(v)
    (d / "s1-1.55").mkdir()
    (d / os.fsdecode(b"s1-\xff.1")).write_bytes(b"")
    prefixes = [str(d / "s1-1"), str(d / "s1-10"), str(d / "other"), str(d / "none"), str(d) + "/", str(d) + "//s1-1",
                "s1-1", "", "/", str(tmp_path / "missing" / "s1-1"), str(d / os.fsdecode(b"s1-\xff")),
                str(d / "s1-1") + "/"]
    for p in prefixes:
        assert _call(ref._logs, p) == _call(follow._logs, p), p
    assert follow._logs(str(d / "s1-1"))[:3] == [str(d / "s1-1.10"), str(d / "s1-1.100"), str(d / "s1-1.11")]
    for f in sorted(os.listdir(d)) + ["missing"]:
        p = str(d / f)
        assert _call(ref._complete, p) == _call(follow._complete, p), p
    assert follow._complete(str(d / "s1-1.12")) and not follow._complete(str(d / "s1-1.13"))
    assert _call(ref._complete, "a\0b") == _call(follow._complete, "a\0b")
