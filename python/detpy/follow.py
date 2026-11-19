"""Child processes under the cache with proof (on by default with ``--det-cache``; ``--det-cache-no-follow``).

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
* the whole environment when the child inherits it (a child's ``getenv`` is not observable); an explicit
  ``env=`` is built by the test's recorded code from recorded reads, so it adds nothing;
* paths it wrote, as in-process writes (a later reader in another test is not cached); paths the tree
  itself wrote first are internal (gcc's temporary objects) and are not inputs.

Refused (the test is not cached): a connect or sendto to an internet, netlink or foreign Unix socket;
reads of ``/proc``, ``/sys`` or ``/dev`` other than the process's own entries, the null and terminal devices
and the machine shape (CPU and memory limits); a log that is missing, incomplete (a process still running at
the end of the session) or has a system call the parser does not know; strace missing or unable to trace.

Not recorded (limits, the same as the strace skip study): the child's real clock (vDSO, invisible to strace) and
its entropy (``getrandom``, ``/dev/urandom``: glibc and every interpreter draw some at start-up) are outside
detpy's control; entropy draws are counted, not refused. A child that is still running when the session ends
(a daemon, a forkserver) refuses the context that started it.
The child's arguments are not a key: they are computed by the test's code from its recorded inputs, and a key
must be known before the test runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time as _time_mod

from . import _core

# real clocks, bound before Level 0 virtualises the time module (waiting for a tracer is real waiting)
_mono = _time_mod.monotonic
_sleep = _time_mod.sleep

STRACE_TRACE = ("%file,getdents,getdents64,chdir,fchdir,connect,sendto,sendmsg,bind,getrandom,"
                "clone,clone3,fork,vfork,clock_gettime,gettimeofday,time")

# Real-clock reads go through the vDSO, which strace cannot see. Every followed child gets this library in
# LD_PRELOAD: its real-time reads (CLOCK_REALTIME, _COARSE, _ALARM, TAI; gettimeofday; time; timespec_get) become
# system calls, which the trace records; monotonic clocks keep the vDSO. Its constructor makes a marker call
# (``faccessat`` of ``/__detpy_clock_shim__``), so a program that ran without it (static binaries, Go, setuid, an
# environment without LD_PRELOAD) is seen too.
# A Python interpreter reads the real clock once while it initialises (the time module's timezone offsets):
# reads before Py_IsInitialized() is first true are not marked; interpreter shutdown (Py_IsFinalizing()) is not
# start-up.
SHIM_SOURCE = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

__attribute__((constructor)) static void detpy_clock_shim_mark(void) {
    syscall(SYS_faccessat, AT_FDCWD, "/__detpy_clock_shim__", F_OK, 0);
}

/* Python start-up only: Py_FinalizeEx clears Py_IsInitialized() too, before it tears the modules down (review
   R-009b R3), so a read while the flag is false is exempt only if the interpreter has never been seen initialised
   and is not finalising. Without a way to tell (Python older than 3.7), nothing is exempt. */
static int py_seen_initialized;

static int in_python_init(void) {
    if (py_seen_initialized) return 0;
    int (*init)(void) = (int (*)(void))dlsym(RTLD_DEFAULT, "Py_IsInitialized");
    if (init == 0) return 0;
    if (init()) {
        py_seen_initialized = 1;
        return 0;
    }
    int (*fin)(void) = (int (*)(void))dlsym(RTLD_DEFAULT, "Py_IsFinalizing");
    if (fin == 0) fin = (int (*)(void))dlsym(RTLD_DEFAULT, "_Py_IsFinalizing");
    if (fin == 0 || fin()) return 0;
    return 1;
}

static int realtime(clockid_t c) {
    return c == CLOCK_REALTIME || c == CLOCK_REALTIME_COARSE || c == 8 || c == 11;
}

int clock_gettime(clockid_t c, struct timespec *ts) {
    if (realtime(c) && !in_python_init())
        return syscall(SYS_clock_gettime, c, ts);
    int (*real)(clockid_t, struct timespec *) = (int (*)(clockid_t, struct timespec *))dlsym(RTLD_NEXT, "clock_gettime");
    return real ? real(c, ts) : syscall(SYS_clock_gettime, c, ts);
}

int gettimeofday(struct timeval *tv, void *tz) {
    if (in_python_init()) {
        int (*real)(struct timeval *, void *) = (int (*)(struct timeval *, void *))dlsym(RTLD_NEXT, "gettimeofday");
        if (real) return real(tv, tz);
    }
    return syscall(SYS_gettimeofday, tv, tz);
}

time_t time(time_t *t) {
    struct timespec ts;
    if (in_python_init()) {
        time_t (*real)(time_t *) = (time_t (*)(time_t *))dlsym(RTLD_NEXT, "time");
        if (real) return real(t);
    }
    syscall(SYS_clock_gettime, CLOCK_REALTIME, &ts);
    if (t) *t = ts.tv_sec;
    return ts.tv_sec;
}

int timespec_get(struct timespec *ts, int base) {
    if (base != TIME_UTC) return 0;
    if (syscall(SYS_clock_gettime, CLOCK_REALTIME, ts) != 0) return 0;
    return base;
}
"""

_tls = threading.local()


class Spawn:
    __slots__ = ("ctx", "prefix", "cwd", "exe", "argv", "detail", "clock_exempt")

    def __init__(self, ctx, prefix, cwd, exe, argv, detail, clock_exempt=False):
        self.ctx, self.prefix, self.cwd, self.exe, self.argv, self.detail = ctx, prefix, cwd, exe, argv, detail
        # ctypes.util.find_library's helpers: their result is a library path matched in their output
        self.clock_exempt = clock_exempt


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
        self.late: str | None = None  # a file read by the tree and changed after it started (set by the capture)


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
    if why is None:
        _PROBE["shim"], _PROBE["shim_why"] = build_shim(os.path.dirname(os.path.abspath(logdir)))
    return why


def build_shim(dirpath: str) -> tuple[str | None, str | None]:
    """The clock shim compiled into ``dirpath`` (once per source version), or (None, why not)."""
    import hashlib

    digest = hashlib.sha256(SHIM_SOURCE.encode()).hexdigest()[:16]
    so = os.path.join(dirpath, f"clockshim-{digest}.so")
    if os.path.exists(so):
        return so, None
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        return None, "no C compiler to build the clock shim"
    try:
        os.makedirs(dirpath, exist_ok=True)
        src = os.path.join(dirpath, f"clockshim-{digest}.{os.getpid()}.c")
        tmp = so + f".{os.getpid()}.tmp"
        with open(src, "w") as fh:
            fh.write(SHIM_SOURCE)
        p = subprocess.run([cc, "-O2", "-shared", "-fPIC", "-o", tmp, src, "-ldl"], capture_output=True, timeout=120)
        os.unlink(src)
        if p.returncode != 0:
            return None, "clock shim does not compile: " + p.stderr.decode(errors="replace").strip()[:200]
        os.replace(tmp, so)
        return so, None
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"clock shim not built: {e}"


# the logs of a spawn (``prefix.<pid>``, sorted) and whether one ends with its process's exit
_logs = _core.follow_logs
_complete = _core.follow_complete


def _wait_logs(prefix: str, timeout: float) -> list[str]:
    """The logs of ``prefix`` once every one ends with its process's exit (the detached tracer writes it)."""
    t_end = _mono() + timeout
    while True:
        logs = _logs(prefix)
        if logs and all(_complete(f) for f in logs):
            return logs
        if _mono() > t_end:
            return logs
        _sleep(0.01)


# ---------------------------------------------------------------------------
# the fork_exec wrapper
class Follower:
    def __init__(self, cap, logdir: str, follow: bool):
        self.cap = cap
        self.logdir = logdir
        self.spawns: list[Spawn] = []
        self.n = 0
        # with --det-cache-no-follow the wrapper still sees every fork_exec (multiprocessing's starters raise no
        # subprocess audit event) and refuses its context
        self.why_not = probe(logdir) if follow else "--det-cache-no-follow"
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
            pending = (cap._cur(), None, True, False)
        ctx, detail, follow_it, clock_exempt = pending
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
        if args[5] is None:
            # the child inherits this process's environment and its getenv calls are not observable: the whole
            # environment is an input. An explicit env= was built by recorded code from recorded reads.
            cap.env_read_ctx(ctx, "*")
        if exe is None:
            return args  # exec fails in the child: nothing runs
        if not self.enabled:
            cap.flag(ctx, "spawn", f"{detail} [not followed: {self.why_not}]")
            return args
        self.n += 1
        prefix = os.path.join(self.logdir, f"s{os.getpid()}-{self.n}")
        self.spawns.append(Spawn(ctx, prefix, cwd, exe, [os.fsdecode(a) for a in argv], detail, clock_exempt))
        argv0 = os.fsdecode(argv[0]) if argv else exe
        new_argv = [self.exe, "-DDD", "-ff", "-q", "-y", "-ttt", "-s", "1", "--seccomp-bpf", "-e",
                    "trace=" + STRACE_TRACE, "-e", "signal=none", "-o", prefix, "--argv0", argv0, "--", exe,
                    *[os.fsdecode(a) for a in argv[1:]]]
        shim = _PROBE.get("shim")
        if shim is None:
            cap.flag(ctx, "spawn", f"{detail} [clock not observable: {_PROBE.get('shim_why') or 'no clock shim'}]")
        env = args[5]
        if shim is not None:
            if env is None:
                env = [k + b"=" + v for k, v in dict(os.environb._data).items()]  # noqa: SLF001 (no env event)
            env = list(env)
            for i, kv in enumerate(env):
                if kv.startswith(b"LD_PRELOAD="):
                    env[i] = b"LD_PRELOAD=" + os.fsencode(shim) + b" " + kv[len(b"LD_PRELOAD="):]
                    break
            else:
                env.append(b"LD_PRELOAD=" + os.fsencode(shim))
        return (new_argv, (os.fsencode(self.exe),), *args[2:5], env, *args[6:])

    def announce(self, ctx: int, detail: str | None, follow_it: bool = True, clock_exempt: bool = False) -> None:
        """A ``subprocess.Popen`` audit event: the next fork_exec of this thread is that child (``follow_it``
        False: already accounted for, run it unchanged)."""
        _tls.pending = (ctx, detail, follow_it, clock_exempt)


# ---------------------------------------------------------------------------
# log parsing, in Rust (``crates/detpy-py/src/follow.rs``; the Python original is kept in
# ``tests/rust_hotpaths_ref/_ref_follow.py``)


def parse(paths: list[str], cwd: str) -> Result:
    """What the process tree whose strace logs are ``paths`` (started in ``cwd``) did."""
    ops, net, bad, unreadable, entropy, bound, clock, unshimmed, t0, t1 = _core.follow_parse(paths, cwd)
    if unreadable is not None:
        i, errno = unreadable
        bad = f"log unreadable: {OSError(errno, os.strerror(errno), paths[i])}"
    res = Result()
    res.ops, res.net, res.bad, res.entropy, res.clock, res.unshimmed, res.t0, res.t1 = (
        ops, net, bad, entropy, clock, unshimmed, t0, t1)
    res.pids = {path.rsplit(".", 1)[-1] for path in paths}
    res.bound = set(bound)
    return res


# paths a child may touch without them being inputs: 'skip' (not an input), 'entropy', 'proc' (refused) or None (an
# ordinary path)
special = _core.follow_special
# the interpreter of a ``#!`` script, or None
shebang = _core.follow_shebang
