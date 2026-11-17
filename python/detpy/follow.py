"""Child processes under the cache with proof (``--det-cache-follow``).

Without following, a test that starts a process is never cached: the child's inputs are invisible to the
in-process recorder. With following, every process the tests start through ``subprocess`` (and
``multiprocessing``'s spawn and forkserver starters, which call the same ``fork_exec``) runs under
``strace -D -ff``: the child keeps its pid, signals and exit status (``-D``: the tracer is a detached
grandchild), and every process of its tree writes its file and network system calls to a log. At the end
of the session each log becomes inputs of the context (test, fixture, collection, import) that started it:

* the executable and every path the tree opened, stat-ed, accessed, executed or read a link of: content
  digest, ``missing`` or ``dir`` (the same deps as in-process reads; a Python child that finds a warm
  ``__pycache__`` stats the source, so the source is an input);
* every directory it listed (``getdents``);
* the whole environment (a child's ``getenv`` is not observable);
* paths it wrote, as in-process writes (a later reader in another test is not cached); paths the tree
  itself wrote first are internal (gcc's temporary objects) and are not inputs.

Refused (the test is not cached): a connect or sendto to an internet, netlink or foreign Unix socket;
reads of ``/proc``, ``/sys`` or ``/dev`` other than the process's own entries, the null and terminal devices
and the machine shape (CPU and memory limits); a log that is missing, incomplete (a process still running at
the end of the session) or has a system call the parser does not know; strace missing or unable to trace.

Not recorded (limits): the child's real clock (vDSO, invisible to strace) and its entropy
(``getrandom``, ``/dev/urandom``) are outside detpy's control; they are counted, not refused.
The child's arguments are not a key: they are computed by the test's code from its recorded inputs, and a key
must be known before the test runs.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading

STRACE_TRACE = ("%file,getdents,getdents64,chdir,fchdir,connect,sendto,sendmsg,bind,getrandom,"
                "clone,clone3,fork,vfork")

_tls = threading.local()


class Spawn:
    __slots__ = ("ctx", "prefix", "cwd", "exe", "argv", "detail")

    def __init__(self, ctx, prefix, cwd, exe, argv, detail):
        self.ctx, self.prefix, self.cwd, self.exe, self.argv, self.detail = ctx, prefix, cwd, exe, argv, detail


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


# ---------------------------------------------------------------------------
# strace availability
_PROBE: dict = {}


def probe(logdir: str) -> str | None:
    """None when ``strace -D -ff`` can trace a child here, else why not."""
    if "why" in _PROBE:
        return _PROBE["why"]
    exe = shutil.which("strace")
    why = None
    if exe is None:
        why = "strace not found"
    else:
        os.makedirs(logdir, exist_ok=True)
        prefix = os.path.join(logdir, "probe")
        true = shutil.which("true") or "/bin/true"
        try:
            p = subprocess.run([exe, "-DDD", "-ff", "-q", "-y", "--seccomp-bpf", "-e", "trace=" + STRACE_TRACE, "-o",
                                prefix, "--", true], capture_output=True, timeout=30)
            logs = _wait_logs(prefix, 2.0)
            if p.returncode != 0:
                why = "strace failed: " + p.stderr.decode(errors="replace").strip()[:200]
            elif not logs:
                why = "strace wrote no log"
        except (OSError, subprocess.SubprocessError) as e:
            why = f"strace failed: {e}"
        for f in _logs(prefix):
            try:
                os.unlink(f)
            except OSError:
                pass
    _PROBE["why"] = why
    _PROBE["exe"] = exe
    return why


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
    return tail.startswith(b"+++ exited with") or tail.startswith(b"+++ killed by")


def _wait_logs(prefix: str, timeout: float) -> list[str]:
    """The logs of ``prefix`` once every one ends with its process's exit (the detached tracer writes it)."""
    import time

    t_end = time.monotonic() + timeout
    while True:
        logs = _logs(prefix)
        if logs and all(_complete(f) for f in logs):
            return logs
        if time.monotonic() > t_end:
            return logs
        time.sleep(0.01)


# ---------------------------------------------------------------------------
# the fork_exec wrapper
class Follower:
    def __init__(self, cap, logdir: str, follow: bool):
        self.cap = cap
        self.logdir = logdir
        self.spawns: list[Spawn] = []
        self.n = 0
        # without --det-cache-follow the wrapper still sees every fork_exec (multiprocessing's starters raise no
        # subprocess audit event) and refuses its context
        self.why_not = probe(logdir) if follow else "--det-cache-follow not set"
        self.exe = _PROBE.get("exe")
        self._saved: list = []

    @property
    def enabled(self) -> bool:
        return self.why_not is None

    def install(self) -> None:
        import _posixsubprocess

        real = _posixsubprocess.fork_exec
        self._saved = [(_posixsubprocess, "fork_exec", real), (subprocess, "_fork_exec", subprocess._fork_exec),
                       (subprocess, "_USE_POSIX_SPAWN", subprocess._USE_POSIX_SPAWN)]
        follower = self

        def fork_exec(*args):
            return real(*follower.rewrite(args))

        _posixsubprocess.fork_exec = fork_exec
        subprocess._fork_exec = fork_exec
        # subprocess's posix_spawn fast path would bypass fork_exec
        subprocess._USE_POSIX_SPAWN = False

    def uninstall(self) -> None:
        for obj, name, v in self._saved:
            setattr(obj, name, v)
        self._saved = []

    def rewrite(self, args: tuple) -> tuple:
        """``fork_exec`` arguments that run the program under strace (or unchanged, refusing the context)."""
        cap = self.cap
        pending = getattr(_tls, "pending", None)
        _tls.pending = None
        if not cap.active:
            return args
        if pending is None:
            # not announced by a subprocess.Popen audit event: multiprocessing's spawn / forkserver starter
            if cap._caller_kind() == "infra":
                return args
            pending = (cap._cur(), None, True)
        ctx, detail, follow_it = pending
        if not follow_it:
            return args
        argv = list(args[0])
        cwd = args[4]
        cwd = os.fsdecode(cwd) if cwd is not None else os.getcwd()
        if not os.path.isabs(cwd):
            cwd = os.path.join(os.getcwd(), cwd)
        cwd = os.path.normpath(cwd)
        exe = None
        for cand in args[1]:
            c = os.path.normpath(os.path.join(cwd, os.fsdecode(cand)))  # exec runs after the child's chdir
            if os.path.isfile(c) and os.access(c, os.X_OK):
                exe = c
                break
            cap.child_read(ctx, c)  # PATH search: the candidates before the program are inputs (missing)
        if detail is None:
            from .proofcache import _spawn_detail

            detail = _spawn_detail("subprocess.Popen", (exe, argv))
        cap.env_read_ctx(ctx, "*")
        if exe is None:
            return args  # exec fails in the child: nothing runs
        if not self.enabled:
            cap.flag(ctx, "spawn", f"{detail} [not followed: {self.why_not}]")
            return args
        self.n += 1
        prefix = os.path.join(self.logdir, f"s{os.getpid()}-{self.n}")
        self.spawns.append(Spawn(ctx, prefix, cwd, exe, [os.fsdecode(a) for a in argv], detail))
        argv0 = os.fsdecode(argv[0]) if argv else exe
        new_argv = [self.exe, "-DDD", "-ff", "-q", "-y", "-s", "1", "--seccomp-bpf", "-e", "trace=" + STRACE_TRACE,
                    "-e", "signal=none", "-o", prefix, "--argv0", argv0, "--", exe, *[os.fsdecode(a) for a in argv[1:]]]
        return (new_argv, (os.fsencode(self.exe),), *args[2:])

    def announce(self, ctx: int, detail: str | None, follow_it: bool = True) -> None:
        """A ``subprocess.Popen`` audit event: the next fork_exec of this thread is that child (``follow_it``
        False: already accounted for, run it unchanged)."""
        _tls.pending = (ctx, detail, follow_it)


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
            wr = any(f in flags for f in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"))
            if not ok or not wr:
                ops.append(("r", p))
            else:
                if "O_RDWR" in flags and "O_TRUNC" not in flags:
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


# ---------------------------------------------------------------------------
# paths a child may touch without them being inputs
_DEV_OK = ("/dev/null", "/dev/zero", "/dev/full", "/dev/tty", "/dev/stdin", "/dev/stdout", "/dev/stderr")
_MACHINE = ("/proc/sys/vm/overcommit_memory", "/proc/cpuinfo", "/proc/meminfo", "/sys/devices/system/cpu/",
            "/sys/fs/cgroup/", "/proc/sys/kernel/random/boot_id", "/proc/filesystems", "/proc/mounts")


def special(p: str, pids: set[str]) -> str | None:
    """'skip' (not an input), 'entropy', 'proc' (refused) or None (an ordinary path)."""
    if not p.startswith(("/proc", "/sys", "/dev")):
        return None
    if p in ("/proc", "/sys", "/dev"):
        return "skip"
    if p in _DEV_OK or p.startswith(("/dev/fd/", "/dev/pts/", "/dev/shm/")):
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


