"""Reference: the strace log parsing of ``detpy.follow`` before it moved to Rust (``crates/detpy-py/src/follow.rs``),
kept verbatim (the pre-port original) for the equivalence tests (``tests/test_follow_rust.py``).

Only the parsing half is here: ``Result``, the timestamp and log-file helpers (``_strip_ts``, ``_logs``,
``_complete``), the line parser (``_unquote``, ``_split_args``, ``_split_line``, ``parse``, ``_base``, ``_join``,
``_sockaddr``, ``_parse_one``) and ``special`` / ``shebang`` with their tables. ``Follower``, ``probe``,
``build_shim`` and ``_wait_logs`` stay in ``detpy.follow``.
"""

from __future__ import annotations

import os
import re

SHIM_MARK = "/__detpy_clock_shim__"
_REALTIME_CLOCKS = ("CLOCK_REALTIME", "CLOCK_REALTIME_COARSE", "CLOCK_REALTIME_ALARM", "CLOCK_TAI")
_TS = re.compile(r"^(\d+\.\d+) ")


class Result:
    """What one spawn's process tree did: ordered (op, path) with op r = probe/read, d = listing, w = write."""

    def __init__(self):
        self.ops: list[tuple[str, str]] = []
        self.net: str | None = None
        self.proc: str | None = None
        self.bad: str | None = None
        self.entropy = 0
        self.pids: set[str] = set()
        self.bound: set = set()  # Unix socket paths the tree itself bound
        self.clock: str | None = None  # a real-clock read (the clock shim made it a system call)
        self.unshimmed: str | None = None  # a program that ran without the clock shim
        self.t0: float | None = None  # first and last system call of the tree (strace -ttt, real clock)
        self.t1: float | None = None


def _strip_ts(line: str) -> tuple[float | None, str]:
    m = _TS.match(line)
    if m:
        return float(m.group(1)), line[m.end():]
    return None, line


def _logs(prefix: str) -> list[str]:
    d, base = os.path.split(prefix)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted(os.path.join(d, n) for n in names if n.startswith(base + ".") and n[len(base) + 1:].isdigit())


def _complete(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            n = fh.tell()
            fh.seek(max(0, n - 4096))
            tail = fh.read().rstrip(b"\n").rsplit(b"\n", 1)[-1]
    except OSError:
        return False
    tail = _strip_ts(tail.decode("utf-8", "surrogateescape"))[1]
    return tail.startswith("+++ exited with") or tail.startswith("+++ killed by")



# ---------------------------------------------------------------------------
# log parsing
_RES = re.compile(r"(-?\d+|\?|0x[0-9a-f]+)(<.*>)?( [A-Z][A-Z0-9_]+ \(.*\))?( <unavailable>)?$")
_SEP = re.compile(r"\) += ")
_FDPATH = re.compile(r"^(?:-?\d+|AT_FDCWD)<(.*)>$")
_ESC = re.compile(rb"\\(x[0-9a-fA-F]{2}|[0-7]{1,3}|.)")
_SIMPLE = {"n": b"\n", "t": b"\t", "r": b"\r", "v": b"\v", "f": b"\f", "\\": b"\\", '"': b'"', "'": b"'",
           "a": b"\a", "b": b"\b", "e": b"\x1b"}

# syscall -> (index of the dirfd or None, index of the path, kind); kind r = probe/read, w = write, x = exec,
# c = chdir
_PATH_CALLS = {
    "stat": (None, 0, "r"), "lstat": (None, 0, "r"), "stat64": (None, 0, "r"), "lstat64": (None, 0, "r"),
    "access": (None, 0, "r"), "readlink": (None, 0, "r"), "statfs": (None, 0, "r"), "statfs64": (None, 0, "r"),
    "getxattr": (None, 0, "r"), "lgetxattr": (None, 0, "r"), "listxattr": (None, 0, "r"),
    "llistxattr": (None, 0, "r"), "newfstatat": (0, 1, "r"), "fstatat64": (0, 1, "r"), "statx": (0, 1, "r"),
    "faccessat": (0, 1, "r"), "faccessat2": (0, 1, "r"), "readlinkat": (0, 1, "r"),
    "execve": (None, 0, "x"), "execveat": (0, 1, "x"), "chdir": (None, 0, "c"),
    "unlink": (None, 0, "w"), "rmdir": (None, 0, "w"), "mkdir": (None, 0, "w"), "chmod": (None, 0, "w"),
    "chown": (None, 0, "w"), "lchown": (None, 0, "w"), "utime": (None, 0, "w"), "utimes": (None, 0, "w"),
    "mknod": (None, 0, "w"), "truncate": (None, 0, "w"), "creat": (None, 0, "w"), "setxattr": (None, 0, "w"),
    "lsetxattr": (None, 0, "w"), "removexattr": (None, 0, "w"), "lremovexattr": (None, 0, "w"),
    "unlinkat": (0, 1, "w"), "mkdirat": (0, 1, "w"), "mknodat": (0, 1, "w"), "fchmodat": (0, 1, "w"),
    "fchmodat2": (0, 1, "w"), "fchownat": (0, 1, "w"), "utimensat": (0, 1, "w"), "futimesat": (0, 1, "w"),
    "inotify_add_watch": (None, 1, "r"), "name_to_handle_at": (0, 1, "r"), "getcwd": None,
}
_IGNORED_CALLS = {"clone", "clone3", "fork", "vfork", "fchdir", "getcwd", "umask"}


def _unquote(tok: str) -> str | None:
    tok = tok.strip()
    if tok.endswith("..."):
        return None  # truncated
    if len(tok) < 2 or tok[0] != '"' or tok[-1] != '"':
        return None
    raw = tok[1:-1].encode("utf-8", "surrogateescape")

    def sub(m):
        e = m.group(1)
        if e[:1] == b"x" and len(e) == 3:
            return bytes([int(e[1:], 16)])
        if e[:1].isdigit():
            return bytes([int(e, 8) & 0xFF])
        return _SIMPLE.get(e.decode("latin-1"), e)

    return os.fsdecode(_ESC.sub(sub, raw))


def _split_args(s: str) -> list[str]:
    out, depth, cur, i, n = [], 0, [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            cur.append(s[i:j + 1])
            i = j + 1
            continue
        if ch in "{[(<":
            depth += 1
        elif ch in "}])>":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    if cur:
        out.append("".join(cur).strip())
    return out


def _split_line(line: str):
    """(syscall, args text, result, decoration, errno) or None."""
    k = line.find("(")
    if k <= 0:
        return None
    name = line[:k]
    for sep in reversed(list(_SEP.finditer(line, k))):
        m = _RES.fullmatch(line[sep.end():])
        if m:
            err = m.group(3).strip().split(" ", 1)[0] if m.group(3) else None
            return name, line[k + 1:sep.start()], m.group(1), m.group(2), err
    return None


def parse(paths: list[str], cwd: str) -> Result:
    res = Result()
    for path in paths:
        pid = path.rsplit(".", 1)[-1]
        res.pids.add(pid)
        try:
            with open(path, "r", encoding="utf-8", errors="surrogateescape") as fh:
                lines = fh.read().splitlines()
        except OSError as e:
            res.bad = res.bad or f"log unreadable: {e}"
            continue
        stamped = [_strip_ts(x) for x in lines]
        times = [t for t, _ in stamped if t is not None]
        if times:
            res.t0 = min(times[0], res.t0) if res.t0 is not None else times[0]
            res.t1 = max(times[-1], res.t1) if res.t1 is not None else times[-1]
        lines = [x for _, x in stamped]
        if not lines or not (lines[-1].startswith("+++ exited with") or lines[-1].startswith("+++ killed by")):
            res.bad = res.bad or "a process was still running at the end of the session"
            continue
        _parse_one(lines, cwd, res)
    return res


def _base(tok: str, cwd: str) -> str | None:
    m = _FDPATH.match(tok.strip())
    if m:
        return m.group(1)
    if tok.strip() == "AT_FDCWD":
        return cwd
    return None


def _join(base: str | None, p: str, cwd: str) -> str:
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(base or cwd, p))


def _sockaddr(tok: str) -> tuple[str | None, str | None]:
    m = re.search(r"sa_family=(AF_[A-Z0-9]+)", tok)
    fam = m.group(1) if m else None
    p = None
    m = re.search(r'sun_path=(@?)("(?:[^"\\]|\\.)*")', tok)
    if m:
        p = ("@" if m.group(1) else "") + (_unquote(m.group(2)) or "")
    return fam, p


def _parse_one(lines: list[str], cwd: str, res: Result) -> None:
    ops = res.ops
    unmarked = None  # a program this process exec'd that has not (yet) made the clock shim's marker call
    for line in lines:
        if not line or line.startswith("+++") or line.startswith("---"):
            continue
        sp = _split_line(line)
        if sp is None:
            res.bad = res.bad or f"unparsed line: {line[:120]}"
            continue
        name, argtext, ret, deco, err = sp
        ok = ret not in ("?",) and not ret.startswith("-")
        if "AT_FDCWD<" in argtext:
            m = re.search(r"AT_FDCWD<([^>]*)>", argtext)
            if m:
                cwd = m.group(1)
        if SHIM_MARK in argtext and name in ("faccessat", "faccessat2", "access"):
            unmarked = None
            continue
        if name == "clock_gettime":
            if argtext.split(",", 1)[0].strip() in _REALTIME_CLOCKS:
                res.clock = res.clock or f"reads the real clock ({argtext.split(',', 1)[0].strip()})"
            continue
        if name in ("gettimeofday", "time"):
            res.clock = res.clock or f"reads the real clock ({name})"
            continue
        if name in ("execve", "execveat") and ok:
            args0 = _split_args(argtext)
            unmarked = _unquote(args0[0 if name == "execve" else 1]) if args0 else "?"
        if name in _IGNORED_CALLS:
            if name == "fchdir" and ok:
                b = _base(_split_args(argtext)[0], cwd)
                if b:
                    cwd = b
            continue
        args = _split_args(argtext)
        if name in ("open", "openat", "openat2"):
            i = 0 if name == "open" else 1
            base = None if name == "open" else _base(args[0], cwd)
            p = _unquote(args[i]) if len(args) > i else None
            if p is None:
                res.bad = res.bad or f"unparsed path: {line[:120]}"
                continue
            p = _join(base, p, cwd)
            flags = args[i + 1] if len(args) > i + 1 else ""
            if "O_TMPFILE" in flags:
                continue  # an unnamed temporary file in that directory: nothing visible changes
            wr = any(f in flags for f in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"))
            if not ok or not wr:
                ops.append(("r", p))
            else:
                if "O_RDWR" in flags and "O_TRUNC" not in flags and not ("O_CREAT" in flags and "O_EXCL" in flags):
                    ops.append(("r", p))
                ops.append(("w", p))
            continue
        if name in ("getdents", "getdents64"):
            if ok:
                b = _base(args[0], cwd) if args else None
                if b is None:
                    res.bad = res.bad or f"unparsed fd: {line[:120]}"
                else:
                    ops.append(("d", b))
            continue
        if name in ("rename", "renameat", "renameat2", "link", "linkat"):
            if name in ("rename", "link"):
                pairs = [(None, 0), (None, 1)]
            else:
                pairs = [(0, 1), (2, 3)]
            for bi, pi in pairs:
                p = _unquote(args[pi]) if len(args) > pi else None
                if p is None:
                    res.bad = res.bad or f"unparsed path: {line[:120]}"
                    break
                p = _join(_base(args[bi], cwd) if bi is not None else None, p, cwd)
                ops.append(("w" if ok else "r", p))
            continue
        if name in ("symlink", "symlinkat"):
            pi, bi = (1, None) if name == "symlink" else (2, 1)
            p = _unquote(args[pi]) if len(args) > pi else None
            if p is None:
                res.bad = res.bad or f"unparsed path: {line[:120]}"
                continue
            ops.append(("w" if ok else "r", _join(_base(args[bi], cwd) if bi is not None else None, p, cwd)))
            continue
        if name in ("connect", "sendto", "sendmsg", "bind"):
            fam, sun = _sockaddr(argtext)
            if fam is None:
                continue  # sendto / sendmsg on a connected socket: its connect was seen
            if fam == "AF_UNIX":
                if name == "bind":
                    if ok and sun and not sun.startswith("@"):
                        ops.append(("w", _join(None, sun, cwd)))
                    res.bound.add(sun)
                    continue
                if sun in res.bound:
                    continue
                if sun and not sun.startswith("@") and not ok and err in ("ENOENT", "ENOTDIR"):
                    ops.append(("r", _join(None, sun, cwd)))  # a probe (nscd): its absence is the input
                    continue
                res.net = res.net or f"{name} unix {sun}"
                continue
            if fam == "AF_NETLINK":
                # the kernel's network state (interfaces, MAC addresses, routes): a bind is enough, the requests
                # that follow go out with send() and no address
                res.net = res.net or f"{name} netlink"
                continue
            if name == "bind":
                continue
            res.net = res.net or f"{name} {fam}"
            continue
        if name == "getrandom":
            res.entropy += 1
            continue
        spec = _PATH_CALLS.get(name)
        if spec is None:
            res.bad = res.bad or f"system call not followed: {name}"
            continue
        bi, pi, kind = spec
        p = _unquote(args[pi]) if len(args) > pi else None
        if p is None:
            res.bad = res.bad or f"unparsed path: {line[:120]}"
            continue
        if p == "" and bi is not None:
            continue  # AT_EMPTY_PATH: the fd's own file, recorded at its open
        p = _join(_base(args[bi], cwd) if bi is not None else None, p, cwd)
        if kind == "c":
            if ok:
                cwd = p
            ops.append(("r", p))
        elif kind == "x":
            ops.append(("x", p))
        elif kind == "w" and ok:
            ops.append(("w", p))
        else:
            ops.append(("r", p))
    if unmarked is not None:
        res.unshimmed = res.unshimmed or unmarked


# ---------------------------------------------------------------------------
# paths a child may touch without them being inputs
_DEV_OK = ("/dev/null", "/dev/zero", "/dev/full", "/dev/tty", "/dev/stdin", "/dev/stdout", "/dev/stderr")
_MACHINE = ("/proc/sys/vm/overcommit_memory", "/proc/cpuinfo", "/proc/meminfo", "/sys/devices/system/cpu/",
            "/sys/fs/cgroup/", "/proc/filesystems", "/proc/mounts", "/sys/fs/selinux", "/sys/fs/selinux/")


def special(p: str, pids: set[str]) -> str | None:
    """'skip' (not an input), 'entropy', 'proc' (refused) or None (an ordinary path)."""
    if not p.startswith(("/proc", "/sys", "/dev")):
        return None
    if p in ("/proc", "/sys", "/dev"):
        return "skip"
    if p.startswith("/dev/shm/"):
        return None  # a tmpfs of ordinary files (shared memory, test data): read and written like any file
    if p in _DEV_OK or p.startswith(("/dev/fd/", "/dev/pts/")):
        return "skip"
    if p in ("/dev/urandom", "/dev/random"):
        return "entropy"
    if p.startswith(("/proc/self", "/proc/thread-self")):
        return "skip"
    if p.startswith("/proc/"):
        first = p[6:].split("/", 1)[0]
        if first in pids:
            return "skip"
    if any(p == m or (m.endswith("/") and p.startswith(m)) for m in _MACHINE):
        return "skip"
    return "proc"


def shebang(path: str) -> str | None:
    try:
        with open(path, "rb") as fh:
            head = fh.read(256)
    except OSError:
        return None
    if not head.startswith(b"#!"):
        return None
    parts = head[2:].split(b"\n", 1)[0].strip().split()
    return os.fsdecode(parts[0]) if parts else None

