"""Cache with proof (``pytest --det --det-cache=DIR``).

A test's previous result is reused only when every input it depended on is
unchanged; every reused result comes with a receipt (what was checked, the
digests). What counts as an input (each one recorded while the test runs):

* **code it executed**: per outermost function (``sys.monitoring`` LINE events
  attributed to the running test, its wider-scoped fixtures and the collection
  of its file); plus the module-level structure (*skeleton*) of every
  repository module it had loaded, the pytest hook surface of every conftest,
  and functions run at import time (those build module state any later reader
  depends on);
* **files it read**: content digest, read-write opens included; paths it found
  missing; directories it listed;
* **environment variables it read** (value digests; enumerating the environment
  makes the whole environment an input);
* **runtime identity**: interpreter (version and binary), platform, installed
  distributions;
* **everything an earlier context of the same process depended on** (review
  R-020, prefix rule): a test, fixture or collection that ran before the test
  can leave state it reads without any event (``functools.lru_cache``, a
  module-level dict, a registry filled on first use), so their code, files,
  environment variables, distributions and refusals are inputs too;
* **configuration**: pytest version, options and ini, plugins, the Level 0
  controls. Under ``--det`` the clock, randomness, hash seed and network are
  controlled, so they are configuration, not hidden inputs; the clock's epoch
  is an input of the tests that read the clock.

Never reused: a failure (only passed, skipped and xfailed results are
reused); a test that opened a network connection (loopback included) or
spawned a process; a test that drew OS entropy without ``--det-urandom``;
a test that read a file another test wrote in the same session.

The Rust core (``detpy._core``) records executed lines (``LineRecorder``),
filters audit events, hashes files, stores entries, computes the keys and
decides reuse (``ProofCache``). This module wires them into pytest.
"""

from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
from types import CodeType, FunctionType

import pytest

from . import __version__, _codefacts, _core, _sites, _state, distid, follow

# bound once: a test may remove sys._getframe (attrs' test_missing_sys_getframe) while detpy's hooks run
_getframe = sys._getframe
# real clocks, bound before Level 0 virtualises the time module
_perf = time.perf_counter
_now = time.time
_mon = getattr(sys, "monitoring", None)
AVAILABLE = _mon is not None

# context names: "" startup, "s" between tests, "c|<file>" collection of a file,
# "f|<scope>|<baseid>|<name>" setup of a wider-scoped fixture, "t|<nodeid>" a test
_GLOBAL_CTX = ("", "s")

_AUDIT_EVENTS = ("exec", "open", "ctypes.dlopen", "sqlite3.connect", "os.listdir", "os.scandir", "socket.connect", "socket.sendto", "socket.sendmsg",
                 "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "subprocess.Popen", "os.posix_spawn",
                 "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn", "os.remove", "os.rename", "os.mkdir",
                 "os.rmdir", "os.truncate", "shutil.rmtree", "shutil.copyfile", "shutil.move", "os.symlink",
                 "os.link")
_SPAWN = {"subprocess.Popen", "os.posix_spawn", "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn"}
_WRITE_EVENTS = {"os.remove": (0,), "os.rename": (0, 1), "os.mkdir": (0,), "os.rmdir": (0,),
                 "shutil.rmtree": (0,), "shutil.copyfile": (1,), "shutil.move": (0, 1), "os.symlink": (1,),
                 "os.link": (1,), "os.truncate": (0,)}
_SKIP_PARTS = (os.sep + "__pycache__" + os.sep, os.sep + ".git" + os.sep, os.sep + ".pytest_cache",
               os.sep + ".mypy_cache", os.sep + ".hypothesis" + os.sep, os.sep + ".detpy" + os.sep)
# data reads: the same, except .git/ (review R-009 F5: a test that reads HEAD and its ref in-process depends on
# them; objects are content-addressed, so a changed commit always comes with a changed ref file)
_SKIP_DATA = tuple(x for x in _SKIP_PARTS if x != os.sep + ".git" + os.sep)
_O_ACC = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
_O_TMPFILE = getattr(os, "O_TMPFILE", 0)
# options that never change a test's result (output, reporting, selection by path, detpy's own files)
_VOLATILE_OPTIONS = {
    "file_or_dir", "verbose", "quiet", "color", "code_highlight", "reportchars", "tbstyle", "showlocals",
    "durations", "durations_min", "junitxml", "junitprefix", "resultlog", "basetemp", "det_cache",
    "det_cache_verify", "det_cache_receipts", "det_trace", "det_outcomes", "det_compare", "det_max_events",
    "showcapture", "fulltrace", "collectonly", "markers", "fixtures", "show_fixtures_per_test", "help", "version",
    "debug", "traceconfig", "showlocals", "log_file", "log_cli_level", "pastebin", "usepdb", "usepdb_cls",
    "trace", "xmlpath", "htmlpath", "lf", "failedfirst", "last_failed_no_failures", "newfirst", "cacheclear",
    "cacheshow", "stepwise", "stepwise_skip", "maxfail", "exitfirst", "no_header", "no_summary", "override_ini",
    "inifilename", "rootdir", "confcutdir", "keyword", "markexpr", "deselect", "ignore", "ignore_glob",
    "continue_on_collection_errors", "numprocesses", "dist", "tx", "det_epoch", "det_cache_max_age",
    "det_cache_epoch_window",
}


# detpy's own bookkeeping variables (re-exec, bytecode cache): set by detpy itself, never a test input
_DETPY_OWN_ENV = frozenset({"DETPY_REEXEC", "DETPY_PRECOMPILE_S", "DETPY_PYC_CACHE", "DETPY_BLOCKED_PLUGINS"})
_DETPY_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep


def _ctx_file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


# ---------------------------------------------------------------------------
# entry line (as in the cache-skip study's tracer)
import opcode as _opcode  # noqa: E402

_RESUME = _opcode.opmap.get("RESUME", -1)
_PRELUDE = {_opcode.opmap[n] for n in ("MAKE_CELL", "COPY_FREE_VARS", "RETURN_GENERATOR", "POP_TOP")
            if n in _opcode.opmap}


def entry_line(code) -> int | None:
    """The line ``LINE`` alone never reports on entry (one-line functions, lambdas, docstring-only bodies)."""
    co = code.co_code
    r = 0
    while r < len(co) and co[r] in _PRELUDE:
        r += 2
    if r + 2 >= len(co) or co[r] != _RESUME:
        return None
    lr = ln = None
    for start, end, line in code.co_lines():
        if start <= r < end:
            lr = line
        if start <= r + 2 < end:
            ln = line
            break
    return ln if ln is not None and ln == lr else None


# ---------------------------------------------------------------------------
class Capture:
    """Records, per context, executed code, data reads, environment reads and events."""

    def __init__(self, root: str, env0: dict, hot: int = 16):
        self.root = os.path.realpath(root)
        self.root_sep = self.root + os.sep
        self.env0 = env0
        self.ctx = ""
        self.ctx_ix: dict[str, int] = {"": 0}
        self.ctx_names: list[str] = [""]
        self.segs: list[tuple[int, int]] = [(0, 0)]
        self.tool = None
        self.rec = None
        self.hot = hot
        self._wanted: dict[str, bool] = {}
        self.fid: dict[str, int] = {}
        self.fnames: list[str] = []  # fid -> path relative to root
        self._armed: set[int] = set()
        self._events: dict[int, int] = {}
        self.preloaded: set[str] = set()
        # per context: data deps {path: dep}, flags
        self.data: dict[int, dict[str, str]] = {}
        # per context: existence checks {path: "s:<kind>"} (review R-020b N3, O2); kept apart from
        # ``data`` so that a check never replaces the content digest of a file another context read
        self.sdata: dict[int, dict[str, str]] = {}
        self._stat_saved: list = []
        self._in_stat = False
        self.env: dict[int, set] = {}
        self.flags: dict[int, set] = {}  # "net", "spawn", "proc", "time", "entropy", "netrec", "foreign:<path>"
        self.why: dict[tuple, str] = {}  # (context, flag) -> first occurrence (what and where), for the reports
        self.writers: dict[str, set] = {}  # abs path -> context indices that wrote it
        self._hashed: dict[str, str] = {}  # abs path -> dep at first read in the session
        self.loaded_order: list[tuple[str, int]] = []  # (rel module file, index of the test after which it was seen)
        self._seen_mods: set[str] = set()
        self._nmods = 0
        self.basetemp: str | None = None
        self.site_dirs: tuple = ()
        self.stdlib_dirs: tuple = ()
        self.dist_info_ok: tuple = ()
        self.import_ctx = -1  # pseudo context for import-time data/env/flags
        self.active = False
        self._socks: dict | None = None  # fd -> socket inode at the last scan
        self.follower: follow.Follower | None = None
        self.child_entropy = 0  # entropy draws of followed children (not controlled, not refused)
        self.children = 0  # followed children (spawn calls)
        self.timeline: list[tuple[float, int]] = [(_now(), 0)]  # (real time, context) at every switch
        self.dists: distid.Tracker | None = None  # --det-cache-dists (prototype): per-distribution identity

    # -- contexts -------------------------------------------------------------
    def ctx_index(self, name: str) -> int:
        i = self.ctx_ix.get(name)
        if i is None:
            i = self.ctx_ix[name] = len(self.ctx_names)
            self.ctx_names.append(name)
        return i

    def switch(self, name: str) -> None:
        if name == self.ctx:
            return
        if self.active:
            # startup sockets (pytest, plugins, the runner) are the baseline; the scan's own reads are not inputs
            self.active = False
            try:
                self._scan_sockets(self.ctx_index(self.ctx) if self.ctx else None)
            finally:
                self.active = True
        self.ctx = name
        i = self.ctx_index(name)
        self.timeline.append((_now(), i))
        if self.rec is None:
            return
        n = len(self.rec)
        if self.segs[-1][1] == n:
            self.segs[-1] = (i, n)
        else:
            self.segs.append((i, n))
        hot = self.rec.switch()
        if hot:
            set_local, tool, ev = _mon.set_local_events, self.tool, self._events
            for code in hot:
                set_local(tool, code, 0)
                set_local(tool, code, ev[id(code)])

    def _cur(self) -> int:
        if self.rec is not None and self.rec.import_depth:
            return self._import_ctx()
        return self.ctx_ix[self.ctx]

    def _import_ctx(self) -> int:
        """Import time: the context of the innermost repository module body running (``i|<path>``).

        A test module's import-time reads serve only its own tests (unless another module imports it); any
        other module's are inputs of every test (``_record_all`` decides).
        """
        f = _getframe(2)
        while f is not None:
            c = f.f_code
            if c.co_name == "<module>" and self._want(c.co_filename):
                return self.ctx_index("i|" + self.fnames[self.fid[c.co_filename]])
            f = f.f_back
        return self.import_ctx

    # -- code ---------------------------------------------------------------------
    def _want(self, filename: str) -> bool:
        w = self._wanted.get(filename)
        if w is None:
            w = False
            if filename and not filename.startswith("<"):
                try:
                    p = os.path.realpath(os.path.abspath(filename))
                except (OSError, ValueError):
                    p = ""
                w = p.startswith(self.root_sep) and not any(s in p for s in _SKIP_PARTS)
                if w:
                    self.fid[filename] = len(self.fnames)
                    self.fnames.append(p[len(self.root_sep):].replace(os.sep, "/"))
            self._wanted[filename] = w
        return w

    def arm(self, code) -> None:
        stack = [code]
        set_local, tool = _mon.set_local_events, self.tool
        LINE, START, RET = _mon.events.LINE, _mon.events.PY_START, _mon.events.PY_RETURN
        while stack:
            c = stack.pop()
            if id(c) in self._armed:
                continue
            fn = c.co_filename
            w = self._wanted.get(fn)
            if w is None:
                w = self._want(fn)
            if not w:
                continue
            self._armed.add(id(c))
            e = entry_line(c)
            module = c.co_name == "<module>"
            ev = LINE
            if e is not None or module:
                ev |= START
            if module:
                ev |= RET
            self._events[id(c)] = ev
            self.rec.add_code(c, self.fid[fn], -1 if e is None else e, module)
            set_local(tool, c, ev)
            stack.extend(k for k in c.co_consts if isinstance(k, CodeType))

    def start(self) -> None:
        for tid in (_mon.COVERAGE_ID, 4, 3, 2, 5):
            if _mon.get_tool(tid) is None:
                self.tool = tid
                break
        else:
            raise RuntimeError("detpy --det-cache: sys.monitoring has no free tool id")
        _mon.use_tool_id(self.tool, "detpy-cache")
        self.rec = _core.LineRecorder(_mon.DISABLE, self.hot)
        self.import_ctx = self.ctx_index("i")
        self.ctx = ""
        _mon.register_callback(self.tool, _mon.events.LINE, self.rec.line)
        _mon.register_callback(self.tool, _mon.events.PY_START, self.rec.start)
        _mon.register_callback(self.tool, _mon.events.PY_RETURN, self.rec.ret)
        self.active = True
        _core.set_audit_hook(self._audit, _AUDIT_EVENTS)
        self._patch_sqlite()
        self._patch_stat()
        # code that exists before the start: modules already loaded become whole-content inputs
        pre = False
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f and self._want(f):
                self.preloaded.add(self.fnames[self.fid[f]])
                pre = True
        if pre:
            import gc

            for o in gc.get_objects():
                if type(o) is FunctionType:
                    self.arm(o.__code__)
        f = _getframe()
        while f is not None:
            self.arm(f.f_code)
            f = f.f_back

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        _core.set_audit_hook(None, ())
        for obj, name, v in getattr(self, "_sqlite_saved", ()):
            setattr(obj, name, v)
        self._sqlite_saved = []
        for obj, name, v in reversed(self._stat_saved):
            setattr(obj, name, v)
        self._stat_saved = []
        if self.tool is not None:
            for ev in (_mon.events.LINE, _mon.events.PY_START, _mon.events.PY_RETURN):
                _mon.register_callback(self.tool, ev, None)
            _mon.set_events(self.tool, 0)
            _mon.free_tool_id(self.tool)
            self.tool = None

    # -- sockets opened in C ----------------------------------------------------------
    def _scan_sockets(self, ctx: int | None) -> None:
        """Internet sockets that appeared among this process's descriptors since the last scan.

        Sockets a C extension opens (libpq, grpc, libcurl, ...) raise no audit event; one still open when its
        test or fixture ends is seen here and makes the context uncacheable.
        """
        try:
            fds = os.listdir("/proc/self/fd")
        except OSError:
            return
        cur = {}
        for fd in fds:
            try:
                link = os.readlink("/proc/self/fd/" + fd)
            except OSError:
                continue
            if link.startswith("socket:["):
                cur[fd] = link[8:-1]
        prev, self._socks = self._socks, cur
        if prev is None:
            return
        new = {ino for fd, ino in cur.items() if prev.get(fd) != ino}
        if not new:
            return
        inet = set()
        for t in ("tcp", "tcp6", "udp", "udp6"):
            try:
                with open("/proc/self/net/" + t, "rb") as fh:
                    next(fh, None)
                    for line in fh:
                        parts = line.split()
                        if len(parts) > 9:
                            inet.add(parts[9].decode())
            except OSError:
                continue
        if ctx is not None and new & inet:
            self.flag(ctx, "csock", "an internet socket left open")

    # -- data, environment, events ------------------------------------------------------
    def _caller_kind(self) -> str:
        """'import' (the import system), 'infra' (pytest, detpy, ...) or 'user', from the calling frames."""
        try:
            f = _getframe(2)  # 0 this function, 1 the audit callback, 2 the code that raised the event
        except ValueError:
            return "user"
        while f is not None:
            fn = f.f_code.co_filename
            if fn.startswith("<frozen importlib") or fn.startswith("<frozen zipimport"):
                return "import"
            if fn.startswith(_DETPY_DIR):  # detpy's own wrappers (network, fsorder, ...) are transparent
                f = f.f_back
                continue
            kind, _ = _sites._classify(fn)
            if kind == _sites._USER:
                return "user"
            if kind == _sites._INFRA:
                return "infra"
            f = f.f_back
        return "user"

    def _abs(self, p) -> str | None:
        if isinstance(p, int) or p is None:
            return None
        try:
            s = os.fsdecode(os.fspath(p))
        except (TypeError, ValueError):
            return None
        if not s:
            return None
        if not os.path.isabs(s):
            try:
                s = os.path.join(os.getcwd(), s)
            except OSError:
                return None
        return os.path.normpath(s)

    def _ignored(self, p: str) -> bool:
        if any(s in p for s in _SKIP_DATA):
            return True
        if self.basetemp and (p == self.basetemp or p.startswith(self.basetemp + os.sep)):
            return True
        for d in self.site_dirs:
            if p.startswith(d):
                return not any(p.startswith(x) for x in self.dist_info_ok)
        return any(p.startswith(d) for d in self.stdlib_dirs) or p == os.devnull

    def _key(self, p: str) -> str:
        return p[len(self.root_sep):] if p.startswith(self.root_sep) else p

    def read(self, ctx: int, p: str, kind: str) -> None:
        """A read of ``p`` (kind f = file content, d = listing) in context ``ctx``."""
        if not _encodable(p):
            self.flags.setdefault(ctx, set()).add("badpath")
            return
        if kind == "m":
            kind = "f"  # a machine identity file under /sys read on purpose (uuid.getnode): its content is the input
        elif p.startswith(("/proc/", "/sys/", "/dev/")) and not p.startswith("/dev/shm/") \
                and (kind != "d" and os.path.exists(p)):
            # the content of a pseudo-file (process state, kernel tunables, a device) is not a file's content;
            # a listing (device enumeration such as /dev/bus/usb) and a missing path are ordinary inputs
            self.flag(ctx, "proc", p)
            return
        if p in self.writers:
            # reads what code of this session wrote: allowed only if every writer is credited to the reader
            self.flags.setdefault(ctx, set()).add("rw:" + p)
            return
        hk = kind + p
        dep = self._hashed.get(hk)
        if dep is None:
            if kind == "d":
                d = _core.listing_digest(p)
                dep = f"d:{d}" if d is not None else "missing"
            else:
                d = _core.file_digest(p)
                dep = f"f:{d}" if d is not None else ("missing" if not os.path.exists(p) else "s:" + (
                    "dir" if os.path.isdir(p) else "other"))
            self._hashed[hk] = dep
        self.data.setdefault(ctx, {})[self._key(p)] = dep

    def wrote(self, ctx: int, p: str) -> None:
        self.writers.setdefault(p, set()).add(ctx)
        for k in ("f" + p, "d" + p, "d" + os.path.dirname(p), "s" + p):
            self._hashed.pop(k, None)

    # -- existence checks ---------------------------------------------------------------
    def _patch_stat(self) -> None:
        """review R-020b N3 / O2: ``os.path.exists``, ``isfile``, ``isdir``, ``Path.exists``, ``shutil.which`` and
        ``glob`` on a literal path ask ``os.stat``, ``os.lstat`` or ``os.access``, which raise no audit event. The
        answer is an input: the path's kind ("s:missing", "s:file", "s:dir", "s:other") is recorded, so a file that
        appears (a console script a bump adds, an optional config file) or disappears invalidates the test.
        (Code that bound ``from os import stat`` before the session keeps the original: not seen.)"""
        cap = self

        def wrap(name):
            orig = getattr(os, name, None)
            if orig is None:
                return

            def checked(path, *args, **kwargs):
                if cap.active and not cap._in_stat and not kwargs.get("dir_fd") \
                        and not isinstance(path, int):
                    cap._in_stat = True
                    try:
                        cap.exists_check(path)
                    except Exception:
                        pass
                    finally:
                        cap._in_stat = False
                return orig(path, *args, **kwargs)

            checked.__name__ = orig.__name__
            checked.__doc__ = orig.__doc__
            checked.__wrapped__ = orig
            self._stat_saved.append((os, name, orig))
            setattr(os, name, checked)

        for name in ("stat", "lstat", "access"):
            wrap(name)

    def exists_check(self, path) -> None:
        """An existence or kind check of ``path`` by user code (not the import system, pytest or detpy)."""
        p = self._abs(path)
        if p is None or self._caller_kind() != "user":
            return
        tr = self.dists
        if tr is not None and tr.in_site(p) and not any(p.startswith(x) for x in self.dist_info_ok):
            pass  # --det-cache-dists: a file a bump adds or removes under a site directory is an input
        elif self._ignored(p):
            return
        if not _encodable(p):
            return
        if p in self.writers:
            # a path code of this session created or wrote (a TemporaryDirectory, an output file): its kind is
            # that code's doing. As for a read of it, the test is cached only if every writer is credited to it.
            self.flags.setdefault(self._cur(), set()).add("rw:" + p)
            return
        hk = "s" + p
        dep = self._hashed.get(hk)
        if dep is None:
            dep = self._hashed[hk] = _core.stat_dep(p)
        self.sdata.setdefault(self._cur(), {}).setdefault(self._key(p), dep)

    def _audit(self, event, args):
        if not self.active:
            return
        if event == "exec":
            # every module body (import, runpy, exec) passes here before it runs; the functions and classes
            # it defines are nested code objects, armed with it
            code = args[0] if args else None
            if isinstance(code, CodeType) and id(code) not in self._armed and self.tool is not None:
                self.arm(code)
            return
        if event == "open":
            p = self._abs(args[0] if args else None)
            if p is None:
                return
            if self.dists is not None and self._dist_read(p):
                return
            if self._ignored(p):
                return
            mode, flags = (args[1] if len(args) > 1 else None), (args[2] if len(args) > 2 else 0)
            if _O_TMPFILE and isinstance(flags, int) and flags & _O_TMPFILE == _O_TMPFILE:
                return  # an unnamed temporary file in that directory (NamedTemporaryFile): nothing visible changes
            if isinstance(mode, str):
                reads = "r" in mode or "+" in mode
                writes = any(ch in mode for ch in "wax+")
                trunc = "w" in mode or "x" in mode  # "x": created here, nothing to read
            else:
                acc = (flags or 0) & _O_ACC
                reads = acc in (os.O_RDONLY, os.O_RDWR)
                writes = acc in (os.O_WRONLY, os.O_RDWR) or bool((flags or 0) & os.O_CREAT)
                # O_CREAT|O_EXCL (NamedTemporaryFile, mkstemp): the file did not exist, so it is an output only
                trunc = bool((flags or 0) & os.O_TRUNC) or (flags or 0) & (os.O_CREAT | os.O_EXCL) == (
                    os.O_CREAT | os.O_EXCL)
            kind = self._caller_kind()
            if kind in ("import", "infra"):
                return
            ctx = self._cur()
            if reads and not trunc:
                self.read(ctx, p, "f")
            if writes:
                self.wrote(ctx, p)
        elif event == "sqlite3.connect":
            # sqlite opens the database read-write in C (no "open" event): its committed content is an input
            db = args[0] if args else None
            if isinstance(db, (str, bytes, os.PathLike)) and os.fsdecode(db) not in ("", ":memory:") \
                    and not os.fsdecode(db).startswith("file:"):
                p = self._abs(db)
                if p is not None and not self._ignored(p) and self._caller_kind() not in ("import", "infra"):
                    ctx = self._cur()
                    self.read(ctx, p, "f")
                    self.wrote(ctx, p)
        elif event in ("os.listdir", "os.scandir"):
            if self._caller_kind() != "user":
                return
            p = self._abs(args[0] if args and args[0] is not None else ".")
            if p is None:
                return
            if self.dists is not None and self._dist_read(p, listing=True):
                return
            if self._ignored(p):
                return
            self.read(self._cur(), p, "d")
        elif event == "ctypes.dlopen":
            if self.dists is not None:
                self.dists._dlopen = True
        elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            # every connection counts, loopback included: a loopback port can be an HTTP(S) proxy to the outside
            # (HTTPS_PROXY=http://127.0.0.1:...) or a service the test process tree did not start
            if self._caller_kind() == "infra":
                return
            if event == "socket.sendmsg" and len(args) > 1 and args[1] is None and self._both_ends_mine(args[0]):
                return  # a write on a connected socket whose peer is a socket of this process
            if event == "socket.connect" and self._own_listener(args):
                # a server this process runs (aiohttp's test server, an in-process HTTP stub): what it answers is
                # computed by recorded code from recorded inputs. A loopback port of another process (a proxy, a
                # database, a sidecar) stays a network input.
                return
            self.flag(self._cur(), "connect", f"{event} {_addr(args)} at {_first_user_site()}")
        elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"):
            # a name lookup (DNS, /etc/hosts) is an input from outside; numeric addresses are not
            host = args[0] if args else None
            if isinstance(host, bytes):
                host = host.decode("ascii", "replace")
            if not isinstance(host, str) or not host or _numeric_host(host) or self._caller_kind() == "infra":
                return
            self.flag(self._cur(), "dns", f"{event} {host} at {_first_user_site()}")
        elif event in _SPAWN or event.startswith("os.spawn") or event.startswith("os.exec"):
            if self._caller_kind() == "infra":
                return
            fo = self.follower
            if event == "subprocess.Popen" and _is_find_library_ldconfig(args):
                # ctypes.util.find_library (uuid, ifaddr, ... at import time) asks `ldconfig -p`, which prints the
                # dynamic linker's cache: that file is the input. (Not followed: ldconfig is a static binary, so the
                # clock shim cannot load into it.)
                self.read(self._cur(), _LD_SO_CACHE, "f")
                if fo is not None:
                    fo.announce(self._cur(), None, False)
                return
            if event == "subprocess.Popen" and _called_from(_UUID_PY):
                # uuid.getnode() runs `ip link`, `ifconfig`, `arp`... to find this machine's MAC address: the
                # machine's network identity is the input (each interface's name and address), not a process
                ctx = self._cur()
                self.read(ctx, "/sys/class/net", "d")
                try:
                    for name in sorted(os.listdir("/sys/class/net")):
                        self.read(ctx, f"/sys/class/net/{name}/address", "m")
                except OSError:
                    pass
                if fo is not None:
                    fo.announce(ctx, None, False)
                return
            if event == "subprocess.Popen" and fo is not None:
                # the fork_exec that follows runs it under strace and records its inputs (or refuses the context
                # when following is off or unavailable). find_library's helpers (gcc, ld, objdump) are followed for
                # their files, but a real-clock read there is not refused: find_library returns the path of a
                # library file matched in their output (DECLARED by ctypes/util.py)
                fo.announce(self._cur(), _spawn_detail(event, args), True, _called_from(_CTYPES_UTIL))
                return
            self.flag(self._cur(), "spawn", _spawn_detail(event, args))
        else:
            idx = _WRITE_EVENTS.get(event)
            if idx is None or self._caller_kind() == "infra":
                return
            ctx = self._cur()
            for i in idx:
                p = self._abs(args[i] if len(args) > i else None)
                if p is not None and not self._ignored(p):
                    self.wrote(ctx, p)

    def _dist_read(self, p: str, listing: bool = False) -> bool:
        """--det-cache-dists: a read under a site directory becomes a dependency on the distribution that owns
        it (True = handled). Reads by the import system and by pytest/detpy are not inputs, as without the flag."""
        tr = self.dists
        if not tr.in_site(p) or any(p.startswith(x) for x in self.dist_info_ok):
            return False
        if not listing:
            kind = self._caller_kind()
            if kind in ("import", "infra"):
                return True
        tr.path(self._cur(), p)
        return True

    def _own_listener(self, args) -> bool:
        self.active = False  # the check's own /proc reads are not inputs
        try:
            return _own_listener(args)
        finally:
            self.active = True

    def _both_ends_mine(self, sock) -> bool:
        self.active = False
        try:
            return _both_ends_mine(sock)
        finally:
            self.active = True

    def _patch_sqlite(self) -> None:
        """review R-009 F4: sqlite evaluates 'now' (date('now'), CURRENT_TIMESTAMP, date() without a time value) on
        the real clock in C. Every connection made through sqlite3.connect traces its statements; one that may read
        the real clock makes its context uncacheable. (A trace callback the test sets itself replaces this one.)"""
        try:
            import sqlite3
            import sqlite3.dbapi2 as dbapi2
        except ImportError:
            return
        real = sqlite3.connect
        cap = self

        def connect(*args, **kwargs):
            conn = real(*args, **kwargs)
            try:
                conn.set_trace_callback(cap._sql_trace)
            except Exception:
                pass
            return conn

        connect.__wrapped__ = real
        self._sqlite_saved = [(sqlite3, "connect", real), (dbapi2, "connect", dbapi2.connect)]
        sqlite3.connect = connect
        dbapi2.connect = connect

    def _sql_trace(self, statement) -> None:
        if self.active and isinstance(statement, str) and _SQL_REAL_CLOCK.search(statement):
            self.flag(self._cur(), "rclock", f"sqlite: {statement.strip()[:80]} at {_first_user_site()}")

    def flag(self, ctx: int, flag: str, detail: str | None = None) -> None:
        fl = self.flags.setdefault(ctx, set())
        if flag not in fl:
            fl.add(flag)
            if detail is None:
                detail = _first_user_site()
            self.why[(ctx, flag)] = detail

    def env_read_ctx(self, ctx: int, name: str) -> None:
        self.env.setdefault(ctx, set()).add(name)

    def child_ignored(self, p: str) -> bool:
        """Paths a followed child touches that are not inputs: bytecode caches (their source is probed), pytest's
        temporary directory, this interpreter's standard library and installed distributions (runtime identity)."""
        if os.sep + "__pycache__" + os.sep in p:
            return True
        if self.basetemp and (p == self.basetemp or p.startswith(self.basetemp + os.sep)):
            return True
        if self.follower is not None and p.startswith(self.follower.logdir):
            return True
        for d in self.site_dirs:
            if p.startswith(d):
                return not any(p.startswith(x) for x in self.dist_info_ok)
        return any(p.startswith(d) for d in self.stdlib_dirs) or p == os.devnull

    def child_read(self, ctx: int, p: str, kind: str = "f") -> None:
        tr = self.dists
        if tr is not None and tr.in_site(p) and not any(p.startswith(x) for x in self.dist_info_ok) \
                and os.sep + "__pycache__" + os.sep not in p:
            tr.path(ctx, p)
            return
        if not self.child_ignored(p):
            self.read(ctx, p, kind)

    def collect_children(self) -> None:
        """Turn the strace logs of the followed children into inputs (or refusals) of the contexts that started them."""
        fo = self.follower
        if fo is None:
            return
        _mono = follow._mono

        # a log is complete once the detached tracer wrote its process's exit, normally within milliseconds of the
        # exit; a process still running (a daemon, multiprocessing's resource tracker) never completes: wait for it
        # once, briefly, then not at all
        budget_end = _mono() + 3.0
        wait = 1.0
        for sp in fo.spawns:
            self.children += 1
            logs = follow._wait_logs(sp.prefix, max(0.0, min(wait, budget_end - _mono())))
            if logs and not all(follow._complete(f) for f in logs):
                wait = 0.05
            ctx = sp.ctx
            if not logs:
                self.flag(ctx, "spawn", f"{sp.detail} [not followed: no trace log]")
                continue
            res = follow.parse(logs, sp.cwd)
            for f in logs:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            # review R-009 F1: a process kept alive across contexts (a persistent shell, a language server, a pool
            # held in a module global) works for whichever test talks to it; that test raises no event. Every test,
            # fixture or collection context that ran during the tree's lifetime (strace -ttt, real clock) gets the
            # tree's inputs and refusals, as the context that started it does.
            t1 = float("inf") if res.bad and "still running" in res.bad else res.t1
            targets = [ctx] + sorted(self._contexts_during(res.t0, t1) - {ctx})
            for c in targets:
                self._credit_child(c, sp, res)
        try:
            os.rmdir(fo.logdir)
        except OSError:
            pass

    def _contexts_during(self, t0: float | None, t1: float | None) -> set:
        """Non-global contexts (tests, fixtures, collection of a file) active at some time in [t0, t1]."""
        if t0 is None or t1 is None:
            return set()
        out = set()
        tl = self.timeline
        glob = {self.ctx_ix.get(n) for n in _GLOBAL_CTX}
        for k, (tk, ck) in enumerate(tl):
            nxt = tl[k + 1][0] if k + 1 < len(tl) else float("inf")
            if tk <= t1 and nxt > t0 and ck not in glob:
                out.add(ck)
        return out

    def _credit_child(self, ctx: int, sp, res) -> None:
        """The inputs, writes and refusals of one followed process tree, as inputs of context ``ctx``."""
        if res.bad:
            self.flag(ctx, "spawn", f"{sp.detail} [not followed: {res.bad}]")
        if res.net:
            self.flag(ctx, "spawn", f"{sp.detail} [network: {res.net}]")
        if res.clock and not sp.clock_exempt:
            # review R-009 F4: the clock shim turned a real-time read into a system call
            self.flag(ctx, "spawn", f"{sp.detail} [{res.clock}]")
        if res.unshimmed:
            self.flag(ctx, "spawn", f"{sp.detail} [clock not observable: {res.unshimmed} ran without the clock shim]")
        self.child_entropy += res.entropy
        self.child_read(ctx, sp.exe)
        own = set()
        for op, p in res.ops:
            sk = follow.special(p, res.pids)
            if sk == "skip":
                continue
            if sk == "entropy":
                self.child_entropy += 1
                continue
            if sk == "proc":
                if op == "d" or (op != "w" and not os.path.exists(p)):
                    self.read(ctx, p, "d" if op == "d" else "f")  # a listing or a missing path: an input
                else:
                    self.flag(ctx, "spawn", f"{sp.detail} [reads {p}]")
                continue
            if op == "w":
                own.add(p)
                if not self.child_ignored(p):
                    self.wrote(ctx, p)
                continue
            if p in own:
                continue  # the tree wrote it first: internal
            if op == "x":
                interp = follow.shebang(p)
                if interp:
                    self.child_read(ctx, interp)
            self.child_read(ctx, p, "d" if op == "d" else "f")


    def env_read(self, name: str) -> None:
        if self.active:
            self.env.setdefault(self._cur(), set()).add(name)

    def event(self, source: str, value: str) -> None:
        """A Level 0 event (``detpy._state.record``) by user code."""
        if not self.active:
            return
        fl = self.flags.setdefault(self._cur(), set())
        if source == "net":
            if "record#" in value:
                fl.add("net-record")
            elif "replay" in value:
                fl.add("net-replay")
        else:
            fl.add(source)

    def scan_modules(self, index: int, plugins=()) -> None:
        """Note the repository modules loaded so far (``sys.modules`` and conftest plugins, which pytest keeps
        out of ``sys.modules``) as loaded after the test at ``index`` (-1 = collection)."""
        if self.dists is not None:
            was, self.active = self.active, False  # the scan's own reads (/proc/self/maps) are not inputs
            try:
                self.dists.scan(index)
            finally:
                self.active = was
        for m in plugins:
            f = getattr(m, "__file__", None)
            if isinstance(f, str) and self._want(f):
                rel = self.fnames[self.fid[f]]
                if rel not in self._seen_mods:
                    self._seen_mods.add(rel)
                    self.loaded_order.append((rel, index))
        mods = sys.modules
        if len(mods) == self._nmods:
            return
        self._nmods = len(mods)
        for m in list(mods.values()):
            f = getattr(m, "__file__", None)
            if not f:
                continue
            if f in self._wanted and not self._wanted[f]:
                continue
            if self._want(f):
                rel = self.fnames[self.fid[f]]
                if rel not in self._seen_mods:
                    self._seen_mods.add(rel)
                    self.loaded_order.append((rel, index))


# ---------------------------------------------------------------------------
# environment reads
_ENV_CAPTURE: Capture | None = None
_ENV_PATCHED = False


def _env_caller_is_user() -> bool:
    try:
        f = _getframe(3)
    except ValueError:
        return True
    while f is not None:
        fn = f.f_code.co_filename
        if fn.startswith(_DETPY_DIR):
            f = f.f_back
            continue
        kind, _ = _sites._classify(fn)
        if kind == _sites._USER:
            return True
        if kind == _sites._INFRA:
            return False
        f = f.f_back
    return True


def _note_env(key) -> None:
    cap = _ENV_CAPTURE
    if cap is None or not cap.active or not _env_caller_is_user():
        return
    cap.env_read(os.fsdecode(key) if isinstance(key, (str, bytes)) else repr(key))


def _patch_environ() -> None:
    global _ENV_PATCHED
    if _ENV_PATCHED:
        return
    _ENV_PATCHED = True

    def make(base):
        class _Recorded(base):
            def __getitem__(self, key):
                _note_env(key)
                return base.__getitem__(self, key)

            def __contains__(self, key):
                _note_env(key)
                return base.__contains__(self, key)

            def __iter__(self):
                _note_env("*")
                return base.__iter__(self)

        _Recorded.__name__ = base.__name__
        _Recorded.__qualname__ = base.__qualname__
        return _Recorded

    for name in ("environ", "environb"):
        o = getattr(os, name, None)
        if o is not None:
            try:
                o.__class__ = make(type(o))
            except TypeError:
                pass


# ---------------------------------------------------------------------------
# identities
def _stat_key(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]


def _dist_infos(root: str, memo_path: str | None = None):
    """(runtime digest part for installed distributions, dist-info dirs of editable installs of the project).

    Reading every distribution's metadata and RECORD takes seconds where thousands are installed: each one's
    result is memoised in ``memo_path`` under the size, mtime, ctime and inode of its metadata files (an installer
    rewrites them, which changes the ctime), so an unchanged environment is not read again.
    """
    from importlib import metadata

    memo: dict = {}
    if memo_path:
        try:
            with open(memo_path) as fh:
                memo = json.load(fh)
        except (OSError, ValueError):
            memo = {}
    fresh: dict = {}
    parts, editable = [], []
    root_sep = os.path.realpath(root) + os.sep
    for d in metadata.distributions():
        path = getattr(d, "_path", None)
        key = None
        if path is not None:
            base = os.path.realpath(str(path))
            key = json.dumps([base, root_sep] + [_stat_key(os.path.join(base, f)) for f in (
                "METADATA", "PKG-INFO", "RECORD", "direct_url.json")])
        hit = memo.get(key) if key is not None else None
        if hit is None:
            name = (d.metadata.get("Name") or "?") if d.metadata is not None else "?"
            project = False
            try:
                du = d.read_text("direct_url.json")
                if du:
                    info = json.loads(du)
                    url = info.get("url", "")
                    if url.startswith("file://") and (os.path.realpath(url[7:]) + os.sep).startswith(root_sep):
                        project = True
            except Exception:
                pass
            if project:
                hit = ["project", os.path.realpath(str(path)) + os.sep if path is not None else None]
            else:
                try:
                    rec = d.read_text("RECORD") or ""
                except Exception:
                    rec = ""
                hit = ["dist", f"{name.lower()}=={d.version}:{_core.digest(rec.encode())}"]
        if key is not None:
            fresh[key] = hit
        if hit[0] == "project":
            if hit[1] is not None:
                editable.append(hit[1])
        else:
            parts.append(hit[1])
    if memo_path and fresh != memo:
        try:
            tmp = f"{memo_path}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                json.dump(fresh, fh)
            os.replace(tmp, memo_path)
        except OSError:
            pass
    return sorted(parts), editable


def runtime_identity(root: str, memo_path: str | None = None, per_dist: bool = False) -> tuple[str, dict, list]:
    import sysconfig

    exe = os.path.realpath(sys.executable)
    lib = None
    libdir, ldlib = sysconfig.get_config_var("LIBDIR"), sysconfig.get_config_var("LDLIBRARY")
    if libdir and ldlib and os.path.exists(os.path.join(libdir, ldlib)):
        lib = os.path.join(libdir, ldlib)
    dists, editable = _dist_infos(root, memo_path)
    d = {
        "python": sys.version,
        "cache_tag": sys.implementation.cache_tag,
        "executable": _core.file_digest(exe),
        "libpython": _core.file_digest(lib) if lib else None,
        "system": platform.system(),
        "machine": platform.machine(),
        "libc": "-".join(platform.libc_ver()),
        "stdlib": _core.listing_digest(os.path.dirname(os.__file__)),
        "distributions": _core.digest("\n".join(dists).encode()),
        "n_distributions": len(dists),
    }
    if per_dist:
        # --det-cache-dists: each test depends on the distributions it used (distid), not on all of them
        d["distributions"] = "per-test"
        d["n_distributions"] = None
    return _core.digest(json.dumps(d, sort_keys=True).encode()), d, editable


_LOCALE_VARS = ("TZ", "TZDIR", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_COLLATE",
                "LC_MONETARY", "LC_MESSAGES", "LC_PAPER", "LC_NAME", "LC_ADDRESS", "LC_TELEPHONE",
                "LC_MEASUREMENT", "LC_IDENTIFICATION")


def tz_locale_identity() -> dict:
    """Time zone and locale as C sees them: the variables, /etc/localtime's content and the zone file TZ names."""
    env = dict(os.environ._data) if hasattr(os.environ, "_data") else dict(os.environ)  # noqa: SLF001 (no event)
    dec = {os.fsdecode(k) if isinstance(k, bytes) else k: os.fsdecode(v) if isinstance(v, bytes) else v
           for k, v in env.items()}
    d = {k: dec.get(k) for k in _LOCALE_VARS}
    d["/etc/localtime"] = _core.file_digest("/etc/localtime")
    tz = dec.get("TZ")
    if tz:
        name = tz[1:] if tz.startswith(":") else tz
        zdir = dec.get("TZDIR") or "/usr/share/zoneinfo"
        path = name if os.path.isabs(name) else os.path.join(zdir, name)
        d["tzfile"] = _core.file_digest(path) if os.path.isfile(path) else None
    return d


def config_identity(config) -> tuple[str, dict]:
    cfg = _state.STATE.config
    plugins = sorted({f"{dist.project_name}=={dist.version}"
                      for _, dist in config.pluginmanager.list_plugin_distinfo()})
    ini = getattr(config, "_inicfg", None)
    if ini is None:
        ini = {}
    ini_items = sorted((str(k), repr(getattr(v, "value", v))) for k, v in dict(ini).items())
    opts = []
    for k, v in sorted(vars(config.option).items()):
        if k in _VOLATILE_OPTIONS:
            continue
        r = repr(v)
        if " at 0x" in r:
            r = type(v).__name__
        opts.append((k, r))
    root = str(config.rootpath)
    inipath = getattr(config, "inipath", None)
    d = {
        "pytest": pytest.__version__,
        "detpy": __version__,
        "encoding": _core.ENCODING_VERSION,
        "plugins": plugins,
        "ini": ini_items,
        "inifile": os.path.relpath(str(inipath), root) if inipath else None,
        "options": opts,
        "level0": {
            "seed": cfg.seed, "shuffle": cfg.shuffle, "controls": sorted(cfg.controls), "tick": cfg.tick_ns,
            "tick_adapt": cfg.tick_adapt, "sleep": cfg.sleep, "urandom": cfg.control_urandom,
            "record_net": cfg.record_net, "allow_hosts": list(cfg.allow_hosts),
            "hashseed": os.environ.get("PYTHONHASHSEED"),
        },
        # review R-009 F3: the time zone and locale are read by C (getenv, tzset, /etc/localtime), never through
        # os.environ: they are configuration of every test
        "tz_locale": tz_locale_identity(),
    }
    return _core.digest(json.dumps(d, sort_keys=True, default=str).encode()), d


# ---------------------------------------------------------------------------
class ProofCachePlugin:
    """pytest hooks of ``--det-cache``."""

    def __init__(self, cap: Capture, cache_dir: str, verify: float, receipts: str | None):
        self.cap = cap
        self.dir = os.path.abspath(cache_dir)
        self.verify = verify
        self.max_age_s: float | None = None
        self.receipts_path = receipts or os.path.join(self.dir, "receipts.jsonl")
        self.store = None
        self.config = None
        self.root = cap.root
        self.config_digest = ""
        self.runtime_digest = ""
        self.runtime_info: dict = {}
        self.epoch = 0
        self.hits: dict[str, dict] = {}  # nodeid -> receipt
        self.verifying: dict[str, dict] = {}  # nodeid -> receipt of a hit re-run for verification
        self.misses: dict[str, str] = {}
        self.items: dict[str, object] = {}
        self.test_index: dict[str, int] = {}
        self.fixture_ctx: dict[str, list] = {}
        self.ran: list[str] = []
        self.parts: dict[str, dict] = {}
        self.dur: dict[str, float] = {}
        self.fingerprints: dict[str, str] = {}
        self.verify_results: list[dict] = []
        self.summary: dict = {}
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime(_now()))}-{os.getpid()}"
        self.t_check = 0.0
        self.t_record = 0.0
        self.recorded = 0
        self.not_cached: dict[str, str] = {}
        self.not_cached_where: dict[str, str] = {}  # nodeid -> first occurrence of the cause (what, where, context)
        self.stale_hits: dict[str, str] = {}
        self.error: str | None = None
        self.dist_keys_n: list[int] = []
        self.dist_all_n = 0

    # -- setup ----------------------------------------------------------------
    def configure(self, config) -> None:
        self.config = config
        self.root = os.path.realpath(str(config.rootpath))
        self.config_digest, self.config_info = config_identity(config)
        os.makedirs(self.dir, exist_ok=True)
        self.runtime_digest, self.runtime_info, editable = runtime_identity(
            self.root, os.path.join(self.dir, "distributions.json"), per_dist=self.cap.dists is not None)
        cap = self.cap
        cap.dist_info_ok = tuple(editable)
        cap.stdlib_dirs = tuple(d + os.sep for d in _sites._stdlib_dirs)
        cap.site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
        if cap.dists is not None:
            cap.dists.site_dirs = tuple(sorted(set(cap.site_dirs) | set(cap.dists.site_dirs)))
        factory = getattr(config, "_tmp_path_factory", None)
        if factory is not None:
            try:
                cap.basetemp = os.path.realpath(str(factory.getbasetemp()))
            except Exception:
                cap.basetemp = None
        self.epoch = _state.STATE.config.epoch_ns
        self.store = _core.ProofCache(self.dir, self.root)
        self.store.begin(self.config_digest, self.runtime_digest, self.epoch, dict(cap.env0))

    # -- collection -------------------------------------------------------------
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_make_collect_report(self, collector):
        if not isinstance(collector, (pytest.File, pytest.Class)):
            yield
            return
        prev = self.cap.ctx
        self.cap.switch("c|" + _ctx_file(collector.nodeid))
        try:
            yield
        finally:
            self.cap.switch(prev)

    @pytest.hookimpl(trylast=True)
    def pytest_collection_finish(self, session):
        self.cap.switch("s")
        self.cap.scan_modules(-1, self._conftests())
        t0 = _perf()
        try:
            self._decide(session.items)
        finally:
            self.t_check = _perf() - t0

    def _decide(self, items) -> None:
        store = self.store
        changed = list(store.changed_code_files())
        jobs = []
        for path, content in changed:
            mod, is_pkg = _module_of(os.path.join(self.root, path))
            jobs.append((os.path.join(self.root, path), content, mod, is_pkg))
        cap, was = self.cap, self.cap.active
        cap.active = False  # detpy's own reads and workers are not inputs of any test
        try:
            facts = _codefacts.read_many(jobs, os.path.join(self.dir, "tmp"))
        finally:
            cap.active = was
        for (path, content), f in zip(changed, facts):
            if f is not None:
                store.set_fresh(path, content, f[0], f[1], f[2], f[3])
        rng = random.Random(f"detpy-cache-verify:{self.run_id}")
        for i, item in enumerate(items):
            nid = item.nodeid
            self.items[nid] = item
            self.test_index[nid] = i
            ok, info = store.check(nid)
            if ok and self.max_age_s is not None:
                # review R-009 F4: real-clock reads outside the virtual clock that detpy cannot see (C code such as
                # OpenSSL's certificate validity) are bounded: an entry older than --det-cache-max-age (real time)
                # is not reused
                age = _now() - _run_time(json.loads(info).get("run", ""))
                if age > self.max_age_s:
                    ok, info = False, f"expired: recorded {age / 86400:.1f} days ago (--det-cache-max-age)"
            if ok:
                receipt = json.loads(info)
                if self.verify and rng.random() < self.verify:
                    self.verifying[nid] = receipt
                else:
                    self.hits[nid] = receipt
            else:
                self.misses[nid] = info

    # -- fixtures and tests ------------------------------------------------------
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_fixture_setup(self, fixturedef, request):
        if fixturedef.scope == "function":
            yield
            return
        prev = self.cap.ctx
        self.cap.switch(f"f|{fixturedef.scope}|{fixturedef.baseid}|{fixturedef.argname}")
        try:
            yield
        finally:
            self.cap.switch(prev)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        receipt = self.hits.get(item.nodeid)
        if receipt is None:
            return None
        self._reuse(item, nextitem, receipt)
        return True

    def _wrap_protocol(self, item, nextitem):  # generator driven by _ProtocolWrapper
        nid = item.nodeid
        if nid in self.hits:
            yield
            return
        fx = []
        info = getattr(item, "_fixtureinfo", None)
        if info is not None:
            for name in item.fixturenames:
                defs = info.name2fixturedefs.get(name)
                if defs and defs[-1].scope != "function":
                    d = defs[-1]
                    fx.append(f"f|{d.scope}|{d.baseid}|{d.argname}")
        self.fixture_ctx[nid] = sorted(set(fx))
        self.cap.switch("t|" + nid)
        t = _perf()
        try:
            yield
        finally:
            self.dur[nid] = _perf() - t
            self.cap.switch("s")
            self.cap.scan_modules(self.test_index.get(nid, len(self.ran)), self._conftests())
            self.ran.append(nid)

    def pytest_runtest_logreport(self, report):
        if report.nodeid in self.hits:
            return
        p = self.parts.setdefault(report.nodeid, {})
        info = {"outcome": report.outcome}
        if hasattr(report, "wasxfail"):
            info["wasxfail"] = report.wasxfail
        if report.skipped and isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
            info["longrepr"] = [str(report.longrepr[0]), report.longrepr[1], str(report.longrepr[2])]
        p[report.when] = info
        for k, v in report.user_properties:
            if k == "detpy_fingerprint":
                self.fingerprints[report.nodeid] = v

    def _conftests(self):
        pm = self.config.pluginmanager
        n = len(getattr(pm, "_conftest_plugins", ()))
        if n == getattr(self, "_n_conftests", -1):
            return ()
        self._n_conftests = n
        return list(getattr(pm, "_conftest_plugins", ()))

    def _reuse(self, item, nextitem, receipt) -> None:
        from _pytest.reports import TestReport
        from _pytest.runner import CallInfo

        e = json.loads(self.store.entry(item.nodeid))
        rep = e.get("report") or {}
        ihook = item.ihook
        ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        now = _now()
        kw = {k: 1 for k in item.keywords}
        props = [("detpy_cache", "reused"), ("detpy_cache_key", receipt["key"]),
                 ("detpy_fingerprint", e.get("fingerprint", ""))]
        reports = []
        for when in ("setup", "call"):
            p = rep.get(when)
            if p is None:
                continue
            lr = p.get("longrepr")
            r = TestReport(item.nodeid, item.location, kw, p["outcome"], tuple(lr) if lr else None, when,
                           (), 0.0, now, now, list(props))
            if "wasxfail" in p:
                r.wasxfail = p["wasxfail"]
            reports.append(r)
        for r in reports:
            ihook.pytest_runtest_logreport(report=r)
        call = CallInfo.from_call(lambda: item.session._setupstate.teardown_exact(nextitem), when="teardown")
        if call.excinfo is None:
            td = TestReport(item.nodeid, item.location, kw, "passed", None, "teardown", (), 0.0, now, now,
                            list(props))
        else:
            td = TestReport.from_item_and_call(item, call)
        ihook.pytest_runtest_logreport(report=td)
        ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)

    # -- end of session ------------------------------------------------------------
    def finish(self, session) -> None:
        from . import plugin as _plugin  # the fingerprints of the tests that ran (Level 0 recorder)

        for nid, fp in _plugin.S.fingerprints.items():
            if nid not in self.hits:
                self.fingerprints[nid] = fp
        cap = self.cap
        cap.switch("s")
        cap.stop()
        t0 = _perf()
        try:
            self._record_all()
        except Exception as e:  # never break the test session: nothing is recorded this time
            import traceback
            import warnings

            self.error = f"{type(e).__name__}: {e}"
            warnings.warn(f"detpy --det-cache: results not recorded: {self.error}\n{traceback.format_exc()}")
        finally:
            self.t_record = _perf() - t0
        self.compare_verified({n: _final(p) for n, p in self.parts.items()})
        self._write_receipts()

    def _facts_index(self, rel: str, cache: dict) -> int | None:
        """Store index of the facts of the current version of ``rel`` (computed once per file)."""
        if rel in cache:
            return cache[rel]
        p = os.path.join(self.root, rel)
        content = _core.file_digest(p)
        ix = None
        if content is not None:
            ix = self.store.file_index(rel, content)
            if ix is None:
                mod, is_pkg = _module_of(p)
                f = _codefacts.read_facts(p, content, mod, is_pkg)
                if f is not None:
                    ix = self.store.add_file(rel, content, f[0], f[1], f[2], f[3])
        cache[rel] = ix
        return ix

    def _prefetch_facts(self, rels, cache: dict) -> None:
        """Facts of every file in ``rels`` whose current version the store does not have yet, computed together."""
        jobs, meta = [], []
        for rel in rels:
            if rel in cache:
                continue
            p = os.path.join(self.root, rel)
            content = _core.file_digest(p)
            if content is None:
                cache[rel] = None
                continue
            ix = self.store.file_index(rel, content)
            if ix is not None:
                cache[rel] = ix
                continue
            mod, is_pkg = _module_of(p)
            jobs.append((p, content, mod, is_pkg))
            meta.append((rel, content))
        if not jobs:
            return
        for (rel, content), f in zip(meta, _codefacts.read_many(jobs, os.path.join(self.dir, "tmp"))):
            cache[rel] = None if f is None else self.store.add_file(rel, content, f[0], f[1], f[2], f[3])

    def _record_all(self) -> None:
        cap, store = self.cap, self.store
        if cap.rec is None:
            return
        cap.collect_children()
        fcache: dict[str, int | None] = {}
        rels = cap.fnames
        # file facts for every executed or loaded repository file (new versions parsed in parallel)
        needed = set(rels) | {r for r, _ in cap.loaded_order} | cap.preloaded
        self._prefetch_facts(sorted(needed), fcache)
        for rel in needed:
            self._facts_index(rel, fcache)
        ranges = []
        for rel in rels:
            ix = fcache.get(rel)
            if ix is None:
                ranges.append([])
            else:
                ranges.append([(a, b) for _, a, b, _ in store.file_facts(ix)[4]])
        per, imp = cap.rec.fold(len(cap.ctx_names), cap.segs, ranges)
        names = cap.ctx_names
        ctx_of = {n: i for i, n in enumerate(names)}

        def units_of(fids_units):
            out = set()
            for v in fids_units:
                fid, u = v >> 32, v & 0xFFFFFFFF
                ix = fcache.get(rels[fid])
                if ix is not None:
                    out.add((ix, u))
            return out

        def unparsable(fids):
            out = set()
            for fid in fids:
                ix = fcache.get(rels[fid])
                if ix is None or not store.file_facts(ix)[4]:
                    if ix is not None:
                        f = store.file_facts(ix)
                        if f[2] == f[1]:  # not Python: whole content
                            out.add(ix)
            return out

        conftests = {r for r in needed if r.rsplit("/", 1)[-1] == "conftest.py"}
        test_files = {_ctx_file(n) for n in self.items}
        # import graph: test modules imported by any loaded module are shared, others only serve their own tests
        imported_names = set()
        for rel in needed:
            ix = fcache.get(rel)
            if ix is not None:
                imported_names.update(store.file_facts(ix)[5])
        shared_test_files = set()
        for tf in test_files:
            mod, _ = _module_of(os.path.join(self.root, tf))
            if mod and (mod in imported_names or mod.rsplit(".", 1)[-1] in imported_names):
                shared_test_files.add(tf)

        # global contexts: startup, between tests, import time
        g_ctx = [ctx_of[c] for c in _GLOBAL_CTX if c in ctx_of]
        g_units = units_of(imp[0])
        g_unparsable = unparsable(imp[1])
        for c in g_ctx:
            g_units |= units_of(per[c][0])
            g_unparsable |= unparsable(per[c][1])
        # import-time reads of a test module that no other module imports serve only its own tests
        own_import = {tf: ctx_of["i|" + tf] for tf in test_files - shared_test_files if "i|" + tf in ctx_of}
        own_import_ix = set(own_import.values())
        g_ctx_all = g_ctx + [cap.import_ctx] + [i for n, i in ctx_of.items()
                                                if n.startswith("i|") and i not in own_import_ix]
        g_data, g_env, g_flags, g_sdata = {}, set(), set(), {}
        for c in g_ctx_all:
            g_data.update(cap.data.get(c, {}))
            for k, v in cap.sdata.get(c, {}).items():
                g_sdata.setdefault(k, v)
            g_env |= cap.env.get(c, set())
            g_flags |= {f for f in cap.flags.get(c, set()) if f != "proc"}

        pre_ix = {fcache[r] for r in cap.preloaded if fcache.get(r) is not None}
        names_of = cap.ctx_names
        session_written = {cap._key(p): sorted(names_of[c] for c in w) for p, w in cap.writers.items()
                           if _encodable(p)}
        written = {p: set(w) for p, w in store.written().items()}
        for p, w in session_written.items():
            written.setdefault(p, set()).update(w)
        # persisted for the next sessions: paths in the repository only (temporary files have fresh names)
        store.add_written({p: w for p, w in session_written.items() if not os.path.isabs(p)})
        # results reused in this session whose input files code of this session then wrote: drop them
        for nid in self.hits:
            if not session_written:
                break
            try:
                deps = json.loads(store.entry(nid)).get("data", [])
            except KeyError:
                continue
            own = {"t|" + nid}
            for path, _dep in deps:
                if _dep.startswith("s:"):
                    continue  # an existence check: its kind is compared with the disk before any reuse
                if path in session_written and not set(session_written[path]) <= own:
                    self.stale_hits[nid] = path
                    store.remove(nid)
                    break
        loaded_idx = cap.loaded_order  # (rel, index)
        tr = cap.dists
        g_dist: set = set()
        dist_sets = {} if (tr is not None and os.environ.get("DETPY_DIST_SETS")) else None
        if tr is not None:
            g_dist |= tr.global_keys
            for c in g_ctx_all:
                g_dist |= tr.deps.get(c, set())
        cfg = _state.STATE.config
        file_of_ix = {}
        for rel, ix in fcache.items():
            if ix is not None:
                file_of_ix[ix] = rel

        def in_scope(rel: str, own: str) -> bool:
            if rel in test_files:
                return rel == own or rel in shared_test_files
            if rel in conftests:
                d = rel.rsplit("/", 1)[0] if "/" in rel else ""
                return d == "" or own == d or own.startswith(d + "/")
            return True

        # review R-020 H1/O1 (prefix rule): a test, fixture or collection that ran before a test in this process
        # can leave state that test reads without any event (functools.lru_cache, a module-level dict, a registry
        # filled on first use): everything it depended on (code executed, files, environment variables,
        # distributions, refusals) is an input of every later test of the process. Contexts in order of first
        # activation; import contexts of test modules at the collection of their file.
        first: dict[int, int] = {}
        for k, (_t, c) in enumerate(cap.timeline):
            first.setdefault(c, k)
        g_set = set(g_ctx_all)
        for n, i in ctx_of.items():
            if n.startswith("i|") and i in own_import_ix:
                first.setdefault(i, first.get(ctx_of.get("c|" + n[2:]), 0))
        carry_order = sorted((k, c) for c, k in first.items() if c not in g_set)
        carry_pos = 0
        c_data: dict = {}
        c_sdata: dict = {}
        c_env: set = set()
        c_flags: set = set()
        c_units: set = set()
        c_content: set = set()
        c_dist: set = set()
        c_ctxs: list = []

        for nid in self.ran:
            item = self.items.get(nid)
            if item is None:
                continue
            tpos = first.get(ctx_of.get("t|" + nid), len(cap.timeline))
            while carry_pos < len(carry_order) and carry_order[carry_pos][0] < tpos:
                c = carry_order[carry_pos][1]
                carry_pos += 1
                c_ctxs.append(c)
                c_data.update(cap.data.get(c, {}))
                for k, v in cap.sdata.get(c, {}).items():
                    c_sdata.setdefault(k, v)
                c_env |= cap.env.get(c, set())
                c_flags |= cap.flags.get(c, set())
                if c < len(per):
                    c_units |= units_of(per[c][0])
                    c_content |= unparsable(per[c][1])
                if tr is not None:
                    c_dist |= tr.deps.get(c, set())
            p = self.parts.get(nid, {})
            outcome = _final(p)
            if outcome not in ("passed", "skipped", "xfailed"):
                self._not_cached(nid, f"outcome {outcome}")
                continue
            own = _ctx_file(nid)
            ctxs = [ctx_of[c] for c in ["t|" + nid, "c|" + own, *self.fixture_ctx.get(nid, [])] if c in ctx_of]
            if own in own_import:
                ctxs.append(own_import[own])
            def own_reads(path, _ctxs=ctxs):
                return path in g_data or any(path in cap.data.get(c, ()) for c in _ctxs)

            flags = set(g_flags)
            data = dict(c_data)
            data.update(g_data)
            env = set(g_env) | c_env
            units = set(c_units)
            content = set(pre_ix) | g_unparsable | c_content
            for c in ctxs:
                flags |= cap.flags.get(c, set())
                data.update(cap.data.get(c, {}))
                env |= cap.env.get(c, set())
                units |= units_of(per[c][0])
                content |= unparsable(per[c][1])
            why = _uncacheable(flags, cfg)
            own_flags = set(flags)
            if why is not None:
                self.not_cached_where[nid] = self._where(why, g_ctx_all + ctxs)
            elif c_flags:
                why = _uncacheable(c_flags, cfg)
                if why is not None:
                    self.not_cached_where[nid] = self._where(why, c_ctxs)
                    why = f"after an earlier test or fixture of this process: {why}"
                else:
                    flags |= c_flags
            if why is None:
                # writers credited to the test: its own contexts and the global ones (startup, between tests,
                # import time), whose code is an input of every test. (Contexts that ran earlier are not credited:
                # a file one of them wrote is not there when that context is reused instead of run.)
                credited = set(ctxs) | set(g_ctx_all)
                names = {names_of[c] for c in credited}
                # a carried read of a file written in this session: its writers ran before that read, so before
                # this test; their inputs are carried too, which credits them as for the test's own contexts
                carried_credit = credited | set(c_ctxs)
                for f in sorted(flags):
                    if f.startswith("rw:") and not cap.writers.get(f[3:], set()) <= (
                            credited if f in own_flags else carried_credit):
                        why = f"reads a file another test or fixture wrote: {cap._key(f[3:])}"
                        break
                if why is None:
                    # reads carried from earlier contexts are not checked here: that context read the file itself,
                    # and its recorded digest is compared with the file on disk before any reuse
                    for path in data:
                        if path in c_data and c_data[path] == data[path] and not own_reads(path):
                            continue
                        w = written.get(path)
                        if w and not w <= names:
                            why = f"reads a file another test or fixture wrote: {path}"
                            break
            if why is None and "net-replay" in flags and cfg.cassette_path:
                d = _core.file_digest(cfg.cassette_path)
                data[cap._key(os.path.realpath(cfg.cassette_path))] = f"f:{d}" if d else "missing"
            if why:
                self._not_cached(nid, why)
                continue
            # existence checks: an input unless the same path's content (or listing) already is one
            for src in (g_sdata, c_sdata, *(cap.sdata.get(c, {}) for c in ctxs)):
                for k, v in src.items():
                    data.setdefault(k, v)
            idx = self.test_index.get(nid, 0)
            skeleton, hooks = set(), set()
            for rel, seen_at in loaded_idx:
                if seen_at > idx:
                    continue
                ix = fcache.get(rel)
                if ix is None:
                    continue
                if rel in conftests:
                    hooks.add(ix)
                if in_scope(rel, own):
                    skeleton.add(ix)
            for ix, u in g_units:
                rel = file_of_ix.get(ix)
                # hooks run outside tests can act on any test; test modules serve their own tests
                if rel is not None and (rel in conftests or in_scope(rel, own)):
                    units.add((ix, u))
            if type(item).__name__ == "DoctestItem" or not hasattr(item, "obj"):
                ix = fcache.get(own)
                if ix is None:
                    ix = self._facts_index(own, fcache)
                if ix is not None:
                    content.add(ix)
            epoch = self.epoch if ("time" in flags and "time" in cfg.controls) else None
            if "time" in flags and "time" not in cfg.controls:
                self._not_cached(nid, "real clock")
                continue
            env_deps = []
            for name in sorted(n for n in env if _encodable(n)):
                if name == "*":
                    env_deps.append(("*", _core.env_all_digest(dict(cap.env0))))
                else:
                    env_deps.append((name, _core.env_value_digest(cap.env0.get(name))))  # env0 is sanitised
            if tr is not None:
                keys = set(g_dist) | c_dist
                for c in ctxs:
                    keys |= tr.deps.get(c, set())
                for k, seen_at in tr.loaded:
                    if seen_at <= idx:
                        keys.add(k)
                data.update(tr.data_deps(sorted(keys)))
                self.dist_keys_n.append(len(keys))
                self.dist_all_n += distid.ALL in keys
                if dist_sets is not None:
                    own = set(g_dist)
                    for c in ctxs:
                        own |= tr.deps.get(c, set())
                    own |= {k for k, seen_at in tr.loaded if seen_at in (-1, idx)}
                    dist_sets[nid] = {"proof": sorted(keys), "own": sorted(own)}
            report = {w: p[w] for w in ("setup", "call") if w in p}
            store.record(nid, outcome, json.dumps(report), self.fingerprints.get(nid, ""), self.dur.get(nid, 0.0),
                         self.run_id, self.config_digest, self.runtime_digest, epoch, env_deps,
                         sorted(data.items()), sorted(content), sorted(skeleton), sorted(hooks), sorted(units))
            self.recorded += 1
        store.save()
        if dist_sets is not None:
            try:
                with open(os.path.join(self.dir, f"dist-sets-{self.run_id}.json"), "w") as fh:
                    json.dump({"identity": {k: open(os.path.join(tr.dir, k)).read() if os.path.exists(
                        os.path.join(tr.dir, k)) else None for k in sorted({k for v in dist_sets.values()
                                                                           for k in v["proof"] + v["own"]})},
                               "tests": dist_sets}, fh)
            except OSError:
                pass

    def _where(self, why: str, ctxs) -> str:
        """``why`` with the first occurrence of its cause: what (command, address...) and in which context."""
        flag = _FLAG_OF.get(why)
        if flag is None:
            return why
        for c in ctxs:
            d = self.cap.why.get((c, flag))
            if d is not None:
                return f"{d} ({_ctx_label(self.cap.ctx_names[c])})"
        return ""

    def _not_cached(self, nid: str, why: str) -> None:
        self.not_cached[nid] = why
        self.store.remove(nid)

    def _write_receipts(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.receipts_path)), exist_ok=True)
            with open(self.receipts_path, "w") as fh:
                for nid, r in self.hits.items():
                    fh.write(json.dumps({"nodeid": nid, "reused": True, **r}) + "\n")
                for nid, why in self.misses.items():
                    fh.write(json.dumps({"nodeid": nid, "reused": False, "why": why}) + "\n")
        except OSError:
            pass

    # -- reporting --------------------------------------------------------------------
    def summary_data(self) -> dict:
        kinds: dict[str, int] = {}
        for why in self.misses.values():
            k = why.split(":", 1)[0]
            kinds[k] = kinds.get(k, 0) + 1
        nc: dict[str, int] = {}
        detail: dict[str, int] = {}
        for nid, why in self.not_cached.items():
            k = why.split(" ", 1)[0] if why.startswith("outcome") else why.split(":", 1)[0]
            nc[k] = nc.get(k, 0) + 1
            if not why.startswith("outcome"):
                w = self.not_cached_where.get(nid)
                full = f"{why}: {w}" if w else why
                detail[full] = detail.get(full, 0) + 1
        top = dict(sorted(detail.items(), key=lambda kv: (-kv[1], kv[0]))[:40])
        return {
            "reused": len(self.hits),
            "verified": len(self.verifying),
            "ran": len(self.ran),
            "recorded": self.recorded,
            "miss_reasons": kinds,
            "not_cached": nc,
            "not_cached_detail": top,
            "children": self.cap.children,
            "children_not_followed": (self.cap.follower.why_not if self.cap.follower is not None else None),
            "child_entropy_draws": self.cap.child_entropy,
            "reused_recorded_seconds": round(sum(self._entry_duration(n) for n in self.hits), 3),
            "check_seconds": round(self.t_check, 3),
            "record_seconds": round(self.t_record, 3),
            "config": self.config_digest,
            "runtime": self.runtime_digest,
            "epoch_ns": self.epoch,
            "verify_mismatches": [v for v in self.verify_results if not v["same"]],
            "stale_reuses": self.stale_hits,
            "error": self.error,
            "receipts": self.receipts_path,
            "dists": self._dist_summary(),
        }

    def _dist_summary(self) -> dict | None:
        tr = self.cap.dists
        if tr is None:
            return None
        by_key: dict[str, int] = {}
        pre = tr.dir + os.sep
        for why in self.misses.values():
            if why.startswith("data:") and pre in why:
                k = why.split(pre, 1)[1].split(" ", 1)[0]
                by_key[k] = by_key.get(k, 0) + 1
        n = self.dist_keys_n
        return {
            "identity_dir": tr.dir,
            "installed": len(tr.index.ident),
            "miss_by_identity": dict(sorted(by_key.items(), key=lambda kv: -kv[1])[:40]),
            "recorded_keys_mean": round(sum(n) / len(n), 1) if n else None,
            "recorded_with_all": self.dist_all_n,
            "unmapped": dict(sorted(tr.unmapped.items(), key=lambda kv: -kv[1])[:20]),
            "loaded": len(tr.loaded),
            "index_seconds": round(tr.index_seconds, 3),
        }

    def _entry_duration(self, nid: str) -> float:
        return float(self.hits[nid].get("duration", 0.0) or 0.0)

    def compare_verified(self, outcomes: dict) -> None:
        for nid, r in self.verifying.items():
            o = outcomes.get(nid)
            fp = self.fingerprints.get(nid)
            self.verify_results.append({"nodeid": nid, "cached": r["outcome"], "fresh": o,
                                        "same": o == r["outcome"], "same_fingerprint": fp == r["fingerprint"]})

    def terminal_summary(self, tr) -> None:
        s = self.summary_data()
        tr.section("detpy cache with proof")
        tr.write_line(f"reused {s['reused']} result(s) with proof, ran {s['ran']}, recorded {s['recorded']} "
                      f"(check {s['check_seconds']}s, record {s['record_seconds']}s); config {s['config']}, "
                      f"runtime {s['runtime']}")
        if s["miss_reasons"]:
            tr.write_line("not reused: " + ", ".join(f"{k} {v}" for k, v in sorted(s["miss_reasons"].items())))
        if s["not_cached"]:
            tr.write_line("not cacheable: " + ", ".join(f"{k} {v}" for k, v in sorted(s["not_cached"].items())))
        for nid, path in self.stale_hits.items():
            tr.write_line(f"WARNING reused {nid}, but this session then wrote its input {path}: entry dropped",
                          yellow=True)
        if self.verify_results:
            bad = s["verify_mismatches"]
            tr.write_line(f"verified {len(self.verify_results)} reusable result(s) by running them: "
                          f"{len(bad)} mismatch(es)", red=bool(bad))
            for b in bad:
                tr.write_line(f"  MISMATCH {b['nodeid']}: cached {b['cached']}, fresh {b['fresh']}", red=True)
        if tr.config.option.verbose > 0:
            for nid, r in self.hits.items():
                tr.write_line(f"REUSED {nid} key={r['key']} run={r['run']} outcome={r['outcome']}: checked "
                              f"{r['n_units']} functions, {r['n_skeleton']} modules, {r['n_hooks']} conftest hook "
                              f"sets, {r['n_content']} whole files, {r['n_data']} data paths, {r['n_env']} env "
                              f"vars; runtime {r['runtime']}, config {r['config']}"
                              f"{'' if r['epoch'] is None else ', epoch ' + str(r['epoch'])}")
        tr.write_line(f"receipts: {s['receipts']}")


def _run_time(run: str) -> float:
    """Real time (seconds) of a run id ``YYYYmmddTHHMMSS-pid``; 0 when unreadable (then the entry has expired)."""
    import calendar

    try:
        return float(calendar.timegm(time.strptime(run.split("-", 1)[0], "%Y%m%dT%H%M%S")))
    except (ValueError, IndexError):
        return 0.0


def _final(parts: dict) -> str:
    setup, call, teardown = parts.get("setup"), parts.get("call"), parts.get("teardown")
    so = setup and setup["outcome"]
    if so and so != "passed":
        if so == "skipped":
            return "xfailed" if "wasxfail" in setup else "skipped"
        return "error"
    if call is None:
        return "unknown"
    co = call["outcome"]
    if teardown and teardown["outcome"] == "failed":
        return "error"
    if co == "skipped" and "wasxfail" in call:
        return "xfailed"
    if co == "passed" and "wasxfail" in call:
        return "xpassed"
    return co


def _safe(s: str) -> str:
    """``s`` as valid UTF-8 text (undecodable bytes of environment strings escaped)."""
    return s if _encodable(s) else s.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def _encodable(s: str) -> bool:
    try:
        s.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


_LD_SO_CACHE = "/etc/ld.so.cache"


_CTYPES_UTIL = os.sep + os.path.join("ctypes", "util.py")
_UUID_PY = os.sep + "uuid.py"


def _called_from(suffix: str) -> bool:
    """Whether a frame of the running call stack is in a standard-library file ending with ``suffix``."""
    f = _getframe(2)
    while f is not None:
        fn = f.f_code.co_filename
        if fn.endswith(suffix) and _sites._classify(fn)[0] != _sites._USER:
            return True
        f = f.f_back
    return False


def _is_find_library_ldconfig(args) -> bool:
    """``subprocess.Popen(['/sbin/ldconfig', '-p'])`` called by ``ctypes.util.find_library``."""
    try:
        argv = list(args[1]) if len(args) > 1 and not isinstance(args[1], (str, bytes)) else None
    except TypeError:
        return False
    if not argv or len(argv) != 2 or os.path.basename(os.fsdecode(argv[0])) != "ldconfig" or argv[1] != "-p":
        return False
    f = _getframe(2)
    while f is not None:
        fn = f.f_code.co_filename
        if fn.endswith(os.sep + os.path.join("ctypes", "util.py")):
            return True
        f = f.f_back
    return False


import re as _re  # noqa: E402

# sqlite reads the real clock for 'now', CURRENT_TIMESTAMP/DATE/TIME and the date functions called without a time
# value (date(), datetime(), time(), julianday(), unixepoch(), strftime(format))
_SQL_REAL_CLOCK = _re.compile(
    r"""'now'|"now"|\bcurrent_(timestamp|date|time)\b|\b(date|time|datetime|julianday|unixepoch)\s*\(\s*\)"""
    r"""|\bstrftime\s*\(\s*('[^']*'|"[^"]*")\s*\)""", _re.I)


def _numeric_host(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


_FLAG_OF = {"real clock read outside the virtual clock": "rclock", "subprocess": "spawn", "network connection": "connect", "host name lookup": "dns",
            "network socket opened outside Python (C extension)": "csock", "reads /proc, /sys or /dev": "proc"}


def _ctx_label(name: str) -> str:
    if name == "":
        return "startup"
    if name == "s":
        return "between tests"
    if name == "i":
        return "import time"
    kind, _, rest = name.partition("|")
    if kind == "i":
        return "import of " + rest
    if kind == "c":
        return "collection of " + rest
    if kind == "f":
        return "fixture " + rest.rsplit("|", 1)[-1]
    return "test"


def _first_user_site() -> str:
    """``file:line`` of the innermost frame outside detpy and the standard library (else the innermost one)."""
    try:
        f = _getframe(1)
    except ValueError:
        return "?"
    first = None
    while f is not None:
        fn = f.f_code.co_filename
        if not fn.startswith(_DETPY_DIR):
            kind, norm = _sites._classify(fn)
            if first is None:
                first = f"{norm}:{f.f_lineno}"
            if kind == _sites._USER:
                return f"{norm}:{f.f_lineno}"
        f = f.f_back
    return first or "?"


def _spawn_detail(event: str, args) -> str:
    """The program a spawn event starts and where it was called from."""
    prog = None
    try:
        if event == "subprocess.Popen":
            prog = args[0] if args[0] is not None else (args[1] if isinstance(args[1], (str, bytes)) else list(args[1])[0])
        elif event == "os.system":
            prog = os.fsdecode(args[0]).split()[0]
        elif event.startswith("os.spawn"):
            prog = args[1]
        elif event in ("os.posix_spawn", "os.exec") or event.startswith("os.exec"):
            prog = args[0]
    except (IndexError, TypeError, ValueError):
        prog = None
    name = os.path.basename(os.fsdecode(prog)) if isinstance(prog, (str, bytes, os.PathLike)) else event
    return f"{name} ({event}) at {_first_user_site()}"


def _own_listener(args) -> bool:
    """A TCP connect to a numeric loopback address whose port a listening socket of this very process holds."""
    import ipaddress
    import socket as _socket

    try:
        sock, addr = args[0], args[1]
        if sock.family not in (_socket.AF_INET, _socket.AF_INET6) or sock.type & 0xF != _socket.SOCK_STREAM:
            return False
        host, port = addr[0], int(addr[1])
        ip = ipaddress.ip_address(str(host).split("%", 1)[0])
    except (AttributeError, IndexError, TypeError, ValueError, OSError):
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if not (ip.is_loopback or (mapped is not None and mapped.is_loopback)):
        return False
    mine = _own_socket_inodes()
    want = f"{port:04X}"
    for t in ("tcp", "tcp6"):
        try:
            with open("/proc/self/net/" + t, "rb") as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    if len(parts) < 10 or parts[3] != b"0A":  # LISTEN
                        continue
                    laddr, _, lport = parts[1].decode().rpartition(":")
                    if lport != want or parts[9].decode() not in mine:
                        continue
                    if set(laddr) <= {"0"} or _loopback_hex(laddr):
                        return True
        except OSError:
            continue
    return False


def _both_ends_mine(sock) -> bool:
    """A connected TCP socket whose peer address is the local address of a socket this process holds."""
    import socket as _socket

    try:
        if sock.family not in (_socket.AF_INET, _socket.AF_INET6) or sock.type & 0xF != _socket.SOCK_STREAM:
            return False
        peer = sock.getpeername()
    except (AttributeError, OSError):
        return False
    try:
        import ipaddress

        ip = ipaddress.ip_address(str(peer[0]).split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if not (ip.is_loopback or (mapped is not None and mapped.is_loopback)):
        return False
    mine = _own_socket_inodes()
    want = f"{int(peer[1]):04X}"
    for t in ("tcp", "tcp6"):
        try:
            with open("/proc/self/net/" + t, "rb") as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    laddr, _, lport = parts[1].decode().rpartition(":")
                    if lport == want and parts[9].decode() in mine and _loopback_hex(laddr):
                        return True
        except OSError:
            continue
    return False


def _own_socket_inodes() -> set:
    mine = set()
    try:
        fds = os.listdir("/proc/self/fd")
    except OSError:
        return mine
    for fd in fds:
        try:
            link = os.readlink("/proc/self/fd/" + fd)
        except OSError:
            continue
        if link.startswith("socket:["):
            mine.add(link[8:-1])
    return mine


def _loopback_hex(laddr: str) -> bool:
    """A /proc/net/tcp{,6} local address (hex, host byte order per 32-bit word) that is loopback."""
    try:
        b = bytes.fromhex(laddr)
    except ValueError:
        return False
    if len(b) == 4:
        return b[3] == 127  # little-endian 127.x.y.z
    if len(b) == 16:
        words = [b[i:i + 4][::-1] for i in range(0, 16, 4)]
        raw = b"".join(words)
        if raw == b"\0" * 15 + b"\1":
            return True
        return raw[:12] == b"\0" * 10 + b"\xff\xff" and raw[12] == 127
    return False


def _addr(args) -> str:
    try:
        a = args[1]
        return f"{a[0]}:{a[1]}" if isinstance(a, tuple) else str(a)
    except (IndexError, TypeError):
        return "?"


def _uncacheable(flags: set, cfg) -> str | None:
    if "badpath" in flags:
        return "reads a path that is not valid UTF-8"
    if "rclock" in flags:
        return "real clock read outside the virtual clock"
    if "spawn" in flags:
        return "subprocess"
    if "connect" in flags:
        return "network connection"
    if "csock" in flags:
        return "network socket opened outside Python (C extension)"
    if "dns" in flags:
        return "host name lookup"
    if "net-record" in flags:
        return "network recording (--det-record)"
    if "entropy" in flags and not cfg.control_urandom:
        return "os entropy (not controlled; use --det-urandom)"
    if "proc" in flags:
        return "reads /proc, /sys or /dev"
    return None


_MODMAP: dict = {}
_MODMAP_N = [-1]


def _module_of(path: str) -> tuple[str | None, bool]:
    """Module name of a file (from ``sys.modules``) and whether it is a package ``__init__``."""
    if _MODMAP_N[0] != len(sys.modules):
        _MODMAP.clear()
        for name, m in list(sys.modules.items()):
            f = getattr(m, "__file__", None)
            if isinstance(f, str):
                try:
                    _MODMAP.setdefault(os.path.realpath(f), name)
                except (OSError, ValueError):
                    pass
        _MODMAP_N[0] = len(sys.modules)
    p = os.path.realpath(path)
    return _MODMAP.get(p), os.path.basename(p) == "__init__.py"


# ---------------------------------------------------------------------------
def cache_epoch(cache_dir: str, head_ns: int, window_ns: int) -> int:
    """The epoch the cache in ``cache_dir`` runs its tests at (``epoch.json``).

    The HEAD commit time when the cache took it, kept while the current HEAD commit time ``head_ns`` is at most
    ``window_ns`` later; otherwise (no epoch yet, or older than the window) the epoch moves to ``head_ns``. An older
    checkout keeps the cache's epoch (later than its commit, as for any run after the commit). The epoch is part of
    the key of every test that read the clock, so moving it reruns those tests.
    """
    path = os.path.join(os.path.abspath(cache_dir), "epoch.json")
    try:
        with open(path) as fh:
            kept = int(json.load(fh)["epoch_ns"])
    except (OSError, ValueError, KeyError, TypeError):
        kept = None
    if kept is not None and head_ns - kept <= window_ns:
        return kept
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump({"epoch_ns": head_ns, "taken_from": "git HEAD commit time"}, fh)
        os.replace(tmp, path)
    except OSError:
        pass
    return head_ns


CAPTURE: Capture | None = None
PLUGIN: ProofCachePlugin | None = None


def start(early_config, ns) -> None:
    """Start recording (from ``pytest_load_initial_conftests``, before conftests are imported)."""
    global CAPTURE, _ENV_CAPTURE
    if not AVAILABLE:
        raise pytest.UsageError("--det-cache needs Python 3.12+ (sys.monitoring)")
    if CAPTURE is not None and CAPTURE.active:
        return  # nested in-process session: the outer one records
    root = str(early_config.rootpath)
    # detpy's own variables (set by its re-exec, e.g. the precompile time) are configuration, not inputs
    env0 = {_safe(k): _safe(v) for k, v in os.environ.items() if k not in _DETPY_OWN_ENV}
    cap = Capture(root, env0)
    CAPTURE = cap
    _ENV_CAPTURE = cap
    _patch_environ()
    _state.set_event_listener(cap.event)
    # probed before recording starts: the probe's own strace run is not a child of any test
    cap.follower = follow.Follower(cap, os.path.join(os.path.abspath(ns.det_cache), f"follow-{os.getpid()}"),
                                   not getattr(ns, "det_cache_no_follow", False))
    cap.follower.install()
    if getattr(ns, "det_cache_dists", False) or os.environ.get("DETPY_CACHE_DISTS") == "1":
        # prototype: per-distribution identity (distid); built before recording starts, so its reads are not inputs
        t0 = _perf()
        index = distid.Index(root)
        ident_dir = os.path.join(os.path.abspath(ns.det_cache), "dist-identity")
        site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
        index.write(ident_dir, site_dirs)
        tr = distid.Tracker(cap, index, ident_dir)
        tr.site_dirs = site_dirs
        tr.index_seconds = _perf() - t0
        tr.install()
        cap.dists = tr
    cap.start()


def install(config) -> None:
    """Register the plugin hooks (from ``pytest_configure``)."""
    global PLUGIN
    cap = CAPTURE
    if cap is None or PLUGIN is not None:
        return
    opt = config.option
    plugin = ProofCachePlugin(cap, opt.det_cache, opt.det_cache_verify, opt.det_cache_receipts)
    age = getattr(opt, "det_cache_max_age", 30.0)
    plugin.max_age_s = age * 86400 if age and age > 0 else None
    plugin.configure(config)
    PLUGIN = plugin
    config.pluginmanager.register(plugin, "detpy-cache")
    config.pluginmanager.register(_ProtocolWrapper(plugin), "detpy-cache-wrapper")
    cap.switch("s")


def uninstall() -> None:
    global CAPTURE, PLUGIN, _ENV_CAPTURE
    if CAPTURE is not None:
        CAPTURE.stop()
        if CAPTURE.dists is not None:
            CAPTURE.dists.uninstall()
        if CAPTURE.follower is not None:
            CAPTURE.follower.uninstall()
    _state.set_event_listener(None)
    CAPTURE = None
    PLUGIN = None
    _ENV_CAPTURE = None


class _ProtocolWrapper:
    def __init__(self, plugin):
        self.plugin = plugin

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        gen = self.plugin._wrap_protocol(item, nextitem)
        next(gen)
        try:
            yield
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
