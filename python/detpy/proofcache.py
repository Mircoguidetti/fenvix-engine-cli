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
* **runtime identity**: interpreter, native libraries, standard library and installed
  distributions, by content (``detpy.runtime_id``);
* **what start-up processes gave back**: a ``subprocess.Popen`` started by a plugin's
  ``pytest_configure`` or ``pytest_sessionstart`` (pytest-benchmark's ``file -b <python>``) is no
  spawn of any test only when its argv, cwd, exit code and output bytes are keyed (output read by
  ``subprocess.run``), it had no other channel and left nothing running (Linux); the *start-up
  digest* of all of them is an input of every test (``Capture._end_startup``);
* **configuration**: pytest version, options and ini, plugins, the Level 0
  controls. Under ``--det`` the clock, randomness, hash seed and network are
  controlled, so they are configuration, not hidden inputs; the clock's epoch
  is an input of the tests that read the clock.

Never reused: a failure (only passed, skipped and xfailed results are
reused); a test that opened a network connection (loopback included) or
spawned a process; a test that drew OS entropy without ``--det-urandom``;
a test that read a file another test wrote in the same session.

Cache audit (``--det-cache-audit=SHARE``, default 5%): a seeded random share of the results that would be
reused is run fresh instead and compared with the cached result (outcome and the set of test ids). A mismatch is
run once more: if the second fresh run gives what the first gave, the skip was **wrong** (the entry is dropped and
its proof key marked *untrusted*: no entry with that key is reused, here or through the shared cache, until a fresh
run records the key again); otherwise the test is **flaky with evidence**. The seed and the chosen tests are in the
receipts (first line), so ``--det-cache-audit-seed=SEED`` reproduces the choice. Audited tests ran: they are never
counted as skipped.

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

from . import __version__, _codefacts, _core, _sites, _state

# real clocks, bound before Level 0 virtualises the time module
_perf = time.perf_counter
_now = time.time
_urandom = os.urandom  # the audit's seed needs real entropy (``--det-urandom`` makes os.urandom deterministic)
_mon = getattr(sys, "monitoring", None)
AVAILABLE = _mon is not None

# context names: "" startup, "s" between tests, "c|<file>" collection of a file,
# "f|<scope>|<baseid>|<name>" setup of a wider-scoped fixture, "t|<nodeid>" a test
_GLOBAL_CTX = ("", "s")

_AUDIT_EVENTS = ("exec", "open", "sqlite3.connect", "os.listdir", "os.scandir", "socket.connect", "socket.sendto", "socket.sendmsg",
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
_O_ACC = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
# options that never change a test's result (output, reporting, selection by path, detpy's own files)
_VOLATILE_OPTIONS = {
    "file_or_dir", "verbose", "quiet", "color", "code_highlight", "reportchars", "tbstyle", "showlocals",
    "durations", "durations_min", "junitxml", "junitprefix", "resultlog", "basetemp", "det_cache",
    "det_cache_verify", "det_cache_audit", "det_cache_audit_seed", "det_cache_receipts", "det_trace", "det_outcomes", "det_compare", "det_max_events",
    "showcapture", "fulltrace", "collectonly", "markers", "fixtures", "show_fixtures_per_test", "help", "version",
    "debug", "traceconfig", "showlocals", "log_file", "log_cli_level", "pastebin", "usepdb", "usepdb_cls",
    "trace", "xmlpath", "htmlpath", "lf", "failedfirst", "last_failed_no_failures", "newfirst", "cacheclear",
    "cacheshow", "stepwise", "stepwise_skip", "maxfail", "exitfirst", "no_header", "no_summary", "override_ini",
    "inifilename", "rootdir", "confcutdir", "keyword", "markexpr", "deselect", "ignore", "ignore_glob",
    "continue_on_collection_errors", "numprocesses", "dist", "tx", "det_epoch",
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
        # start-up: from the start until the first collection, fixture or test context. Popen objects started then
        # are checked when it ends (see _end_startup); what an exempt one gave back is the start-up digest
        self.startup = True
        self._startup_popens: list[_Held] = []
        self._startup_infra: list = []  # Popen objects started by infrastructure code (pytest...): their pids
        self.startup_digest = ""
        self.startup_processes: list = []  # what each exempt start-up process gave back (for the reports)
        self.on_startup_end = None  # called with the start-up digest (the plugin hands it to the store)
        # start-up environment reads (id of the reading frame, its code, its instruction, context, name, group):
        # "*" = enumeration. The per-key reads made by the same instruction as an enumeration are one copy (a group,
        # dict(os.environ, LC_ALL='C') in platform._syscmd_file); a process started with an explicit env by that
        # frame takes one group as its input, unless the copy outlives start-up (then every test's input)
        self._startup_env: list = []
        self._taken: set = set()  # groups taken by a start-up process
        self._env_group: tuple | None = None  # (frame id, code, instruction, group) of the last enumeration
        self._n_groups = 0
        # Linux: detpy is the child subreaper during start-up, so a process a start-up process leaves running
        # (a daemon) becomes detpy's child and is seen when start-up ends
        self._subreaper_prev: int | None = None  # None: process tree not observable
        self._children0: set = set()
        self._adopted: set = set()
        # files under .pytest_cache this session's Python code wrote (reads of others there are inputs)
        self._cache_written: set = set()

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
        if self.startup and name not in _GLOBAL_CTX:
            self._end_startup()
        if self.active:
            # startup sockets (pytest, plugins, the runner) are the baseline; the scan's own reads are not inputs
            self.active = False
            try:
                self._scan_sockets(self.ctx_index(self.ctx) if self.ctx else None)
            finally:
                self.active = True
        self.ctx = name
        i = self.ctx_index(name)
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

    def _end_startup(self) -> None:
        """A process started at start-up, outside every test, is exempt from the spawn flag only when what it gave
        back is keyed and nothing else of it can reach a test:

        * it has finished, every pipe is closed, and each output pipe was read by ``subprocess.run`` (``run``,
          ``check_output``, ``getoutput``...), whose ``communicate`` detpy sees: its argv, cwd, exit code and output
          bytes go into the start-up digest, an input of every test;
        * it had no channel other than those pipes (no ``pass_fds``, no ``close_fds=False``, standard streams None,
          PIPE, DEVNULL or STDOUT);
        * nothing it started is still alive (Linux, child subreaper; elsewhere it is not observable).

        Otherwise the start-up context keeps the spawn: every test is uncached, as before."""
        self.startup = False
        held, self._startup_popens = self._startup_popens, []
        infra, self._startup_infra = self._startup_infra, []
        known = {p.pid for p in infra if p.returncode is None}
        procs = []
        for h in held:
            p = h.p
            why = None
            if h.error is not None:  # could not be started: nothing of it can reach a test but this error
                if not h.chan and self._subreaper_prev is not None:
                    procs.append({"argv": h.argv, "cwd": h.cwd, "error": h.error})
                    continue
                why = h.chan or "the processes it may leave running are not observable on this platform"
            elif p.returncode is None:
                why = "still running when the tests start"
                known.add(p.pid)
            elif any(f is not None and not f.closed for f in (p.stdin, p.stdout, p.stderr)):
                why = "a pipe still open when the tests start"
            elif h.chan:
                why = h.chan
            elif h.piped and h.comm is None:
                why = "its output read outside subprocess.run (not keyed)"
            elif self._subreaper_prev is None:
                why = "the processes it may leave running are not observable on this platform"
            if why is not None:
                self.flag(0, "spawn", f"{h.detail}, {why}")
            else:
                procs.append({"argv": h.argv, "cwd": h.cwd, "returncode": p.returncode,
                              "output": [[_out_digest(o), _out_digest(e)] for o, e in h.comm or ()]})
        if self._subreaper_prev is not None:
            left = _children() - self._children0 - known
            if left:
                self._adopted |= left
                self.flag(0, "spawn", f"a process left running by a start-up process (pid {min(left)})")
            self._reaper(self._subreaper_prev)
            self._reap()
        # environment copies: a group taken by a process whose env= dict nothing but detpy still holds is that
        # process's input; any other start-up read is an input of every test
        dropped = set()
        for h in held:
            if h.gid is not None and h.env is not None and sys.getrefcount(h.env) <= _ENV_REFS:
                dropped.add(h.gid)
            h.env = None
        for _fid, _code, _lasti, ctx, name, gid in self._startup_env:
            if gid is None or gid not in dropped:
                self.env.setdefault(ctx, set()).add(name)
        self._startup_env = []
        self._env_group = None
        self.startup_processes = procs
        if procs:
            self.startup_digest = _core.digest(json.dumps(procs, sort_keys=True).encode())
        if self.on_startup_end is not None:
            self.on_startup_end(self.startup_digest)

    def _hold(self, p, init_locals, args, detail: str) -> None:
        """A ``subprocess.Popen`` started at start-up: decided when start-up ends."""
        h = _Held(p, detail)
        loc = init_locals or {}
        try:
            argv = args[1] if len(args) > 1 else None
            argv = [argv] if isinstance(argv, (str, bytes, os.PathLike)) else list(argv or ())
            h.argv = [self._arg(a) for a in argv]
            if len(args) > 0 and args[0] is not None:
                h.argv.insert(0, "executable=" + self._arg(args[0]))
            cwd = args[2] if len(args) > 2 and args[2] is not None else os.getcwd()
            h.cwd = self._arg(os.path.abspath(os.fsdecode(cwd)))
        except (TypeError, ValueError, OSError):
            h.chan = "arguments not readable"
        if init_locals is None:
            h.chan = "its standard streams are not readable"
        else:
            if loc.get("pass_fds"):
                h.chan = "a descriptor passed with pass_fds"
            elif not loc.get("close_fds", True):
                h.chan = "descriptors inherited (close_fds=False)"
            else:
                for name in ("stdin", "stdout", "stderr"):
                    v = loc.get(name)
                    if not (v is None or v in (-1, -3) or (name == "stderr" and v == -2)):
                        h.chan = f"{name} connected to a descriptor or file (not keyed)"
                        break
            h.piped = loc.get("stdout") == -1 or loc.get("stderr") == -1
        env = args[3] if len(args) > 3 else None
        if env is not None:
            h.env = env
            spawner = _outer_frame(_SUBPROCESS_FILE)
            if spawner is not None:
                # the most recent copy of the environment made by the frame that starts the process
                fid, code = id(spawner), spawner.f_code
                for x in reversed(self._startup_env):
                    if x[5] is not None and x[0] == fid and x[1] is code and x[5] not in self._taken:
                        h.gid = x[5]
                        self._taken.add(x[5])
                        break
        self._startup_popens.append(h)

    def _arg(self, a) -> str:
        """One argument of a start-up process, with the paths of this checkout and the interpreter made portable
        (the same project in another directory, or on another machine, gives the same digest)."""
        s = os.fsdecode(a) if isinstance(a, (str, bytes, os.PathLike)) else repr(a)
        if s in (sys.executable, getattr(sys, "_base_executable", None)):
            return "<python>"
        if s == self.root or s.startswith(self.root_sep):
            return "<root>" + s[len(self.root):]
        return s

    def _note_startup_env(self, f, ctx: int, name: str) -> None:
        key = (id(f), f.f_code, f.f_lasti)
        if name == "*":
            gid = self._n_groups
            self._n_groups += 1
            self._env_group = key + (gid,)
        else:
            g = self._env_group
            gid = g[3] if g is not None and g[0] == key[0] and g[1] is key[1] and g[2] == key[2] else None
        self._startup_env.append((key[0], key[1], key[2], ctx, name, gid))

    def _reaper(self, value: int) -> bool:
        try:
            return _libc().prctl(_PR_SET_CHILD_SUBREAPER, value, 0, 0, 0) == 0
        except (OSError, AttributeError):
            return False

    def _start_reaper(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        try:
            import ctypes

            v = ctypes.c_int(0)
            if _libc().prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(v), 0, 0, 0) != 0:
                return
            prev = v.value
        except (OSError, AttributeError, ImportError):
            return
        self._children0 = _children()
        if self._reaper(1):
            self._subreaper_prev = prev

    def _reap(self) -> None:
        """Collect the exit status of the processes detpy adopted (never of a Popen's own child)."""
        for pid in list(self._adopted):
            try:
                done, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                done = pid
            except OSError:
                continue
            if done:
                self._adopted.discard(pid)

    def _cur(self) -> int:
        if self.rec is not None and self.rec.import_depth:
            return self._import_ctx()
        return self.ctx_ix[self.ctx]

    def _import_ctx(self) -> int:
        """Import time: the context of the innermost repository module body running (``i|<path>``).

        A test module's import-time reads serve only its own tests (unless another module imports it); any
        other module's are inputs of every test (``_record_all`` decides).
        """
        f = sys._getframe(2)
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
        _patch_communicate()
        self._start_reaper()
        _core.set_audit_hook(self._audit, _AUDIT_EVENTS)
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
        f = sys._getframe()
        while f is not None:
            self.arm(f.f_code)
            f = f.f_back

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        _core.set_audit_hook(None, ())
        if self.startup and self._subreaper_prev is not None:  # a session that never reached collection
            self._reaper(self._subreaper_prev)
        self._reap()
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
            f = sys._getframe(2)  # 0 this function, 1 the audit callback, 2 the code that raised the event
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
        if any(s in p for s in _SKIP_PARTS):
            return True
        if self.basetemp and (p == self.basetemp or p.startswith(self.basetemp + os.sep)):
            return True
        for d in self.site_dirs:
            if p.startswith(d):
                return not any(p.startswith(x) for x in self.dist_info_ok)
        return any(p.startswith(d) for d in self.stdlib_dirs) or p == os.devnull

    def _ignored_besides_cache(self, p: str) -> bool:
        """``p`` (under .pytest_cache) is ignored for another reason too (temporary directory, site, ...)."""
        if any(s in p for s in _SKIP_PARTS if s != _PYTEST_CACHE_PART):
            return True
        if self.basetemp and (p == self.basetemp or p.startswith(self.basetemp + os.sep)):
            return True
        return any(p.startswith(d) for d in self.site_dirs + self.stdlib_dirs)

    def _cache_open(self, p: str, args) -> None:
        """An open under .pytest_cache. pytest's own cache (``config.cache``) is infrastructure and stays out; a
        file user code reads there that this session's Python did not write (a start-up process generated it, an
        earlier session left it) is an input like any other file."""
        mode, flags = (args[1] if len(args) > 1 else None), (args[2] if len(args) > 2 else 0)
        if isinstance(mode, str):
            reads, writes, trunc = "r" in mode or "+" in mode, any(ch in mode for ch in "wax+"), "w" in mode
        else:
            acc = (flags or 0) & _O_ACC
            reads = acc in (os.O_RDONLY, os.O_RDWR)
            writes = acc in (os.O_WRONLY, os.O_RDWR) or bool((flags or 0) & os.O_CREAT)
            trunc = bool((flags or 0) & os.O_TRUNC)
        if self._caller_kind() in ("import", "infra"):
            return
        if writes:
            self._cache_written.add(p)
        elif reads and not trunc and p not in self._cache_written:
            self.read(self._cur(), p, "f")

    def _key(self, p: str) -> str:
        return p[len(self.root_sep):] if p.startswith(self.root_sep) else p

    def read(self, ctx: int, p: str, kind: str) -> None:
        """A read of ``p`` (kind f = file content, d = listing) in context ``ctx``."""
        if not _encodable(p):
            self.flags.setdefault(ctx, set()).add("badpath")
            return
        if p.startswith(("/proc/", "/sys/", "/dev/")):
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
        for k in ("f" + p, "d" + p, "d" + os.path.dirname(p)):
            self._hashed.pop(k, None)

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
            if self._ignored(p):
                if _in_pytest_cache(p) and not self._ignored_besides_cache(p):
                    self._cache_open(p, args)
                return
            mode, flags = (args[1] if len(args) > 1 else None), (args[2] if len(args) > 2 else 0)
            if isinstance(mode, str):
                reads = "r" in mode or "+" in mode
                writes = any(ch in mode for ch in "wax+")
                trunc = "w" in mode
            else:
                acc = (flags or 0) & _O_ACC
                reads = acc in (os.O_RDONLY, os.O_RDWR)
                writes = acc in (os.O_WRONLY, os.O_RDWR) or bool((flags or 0) & os.O_CREAT)
                trunc = bool((flags or 0) & os.O_TRUNC)
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
            if self._ignored(p):
                if _in_pytest_cache(p) and not self._ignored_besides_cache(p) and not any(
                        w.startswith(p + os.sep) for w in self._cache_written):
                    self.read(self._cur(), p, "d")
                return
            self.read(self._cur(), p, "d")
        elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            # every connection counts, loopback included: a loopback port can be an HTTP(S) proxy to the outside
            # (HTTPS_PROXY=http://127.0.0.1:...) or a service the test process tree did not start
            if self._caller_kind() == "infra":
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
                if self.startup and event == "subprocess.Popen":
                    p, _loc = _popen_being_started()
                    if p is not None:  # its pid is not a process left behind by a start-up process
                        self._startup_infra.append(p)
                return
            if event == "subprocess.Popen" and _is_find_library_ldconfig(args):
                # ctypes.util.find_library (uuid, ifaddr, ... at import time) asks `ldconfig -p`, which prints the
                # dynamic linker's cache: that file is the input
                self.read(self._cur(), _LD_SO_CACHE, "f")
                return
            ctx = self._cur()
            if self.startup and event == "subprocess.Popen" and self.ctx_names[ctx] in _GLOBAL_CTX:
                p, loc = _popen_being_started()
                if p is not None:  # start-up (pytest-benchmark's `file -b`): decided when start-up ends
                    self._hold(p, loc, args, _spawn_detail(event, args))
                    return
            self.flag(ctx, "spawn", _spawn_detail(event, args))
        else:
            idx = _WRITE_EVENTS.get(event)
            if idx is None or self._caller_kind() == "infra":
                return
            ctx = self._cur()
            for i in idx:
                p = self._abs(args[i] if len(args) > i else None)
                if p is None:
                    continue
                if not self._ignored(p):
                    self.wrote(ctx, p)
                elif _in_pytest_cache(p):
                    self._cache_written.add(p)

    def flag(self, ctx: int, flag: str, detail: str | None = None) -> None:
        fl = self.flags.setdefault(ctx, set())
        if flag not in fl:
            fl.add(flag)
            if detail is None:
                detail = _first_user_site()
            self.why[(ctx, flag)] = detail

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
        f = sys._getframe(3)
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
    name = os.fsdecode(key) if isinstance(key, (str, bytes)) else repr(key)
    if cap.startup:
        ctx = cap._cur()
        if cap.ctx_names[ctx] in _GLOBAL_CTX:  # start-up, not import time: decided when start-up ends
            f = _outer_frame(_ENV_ITER_FILES)
            if f is not None:
                cap._note_startup_env(f, ctx, name)
                return
    cap.env_read(name)


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
def _dist_infos(root: str):
    """(runtime digest part for installed distributions, dist-info dirs of editable installs of the project)."""
    from importlib import metadata

    parts, editable = [], []
    root_sep = os.path.realpath(root) + os.sep
    for d in metadata.distributions():
        name = (d.metadata.get("Name") or "?") if d.metadata is not None else "?"
        path = getattr(d, "_path", None)
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
            if path is not None:
                editable.append(os.path.realpath(str(path)) + os.sep)
            continue
        try:
            rec = d.read_text("RECORD") or ""
        except Exception:
            rec = ""
        parts.append(f"{name.lower()}=={d.version}:{_core.digest(rec.encode())}")
    return sorted(parts), editable


def runtime_identity(root: str, memo_path: str | None = "default") -> tuple[str, dict, list]:
    """The runtime identity, keyed on content (interpreter, native libraries, standard library, installed
    distributions, import path): see ``detpy.runtime_id``."""
    from . import runtime_id

    return runtime_id.runtime_identity(root, memo_path)


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
    }
    return _core.digest(json.dumps(d, sort_keys=True, default=str).encode()), d


# ---------------------------------------------------------------------------
class ProofCachePlugin:
    """pytest hooks of ``--det-cache``."""

    def __init__(self, cap: Capture, cache_dir: str, verify: float, receipts: str | None, audit=None,
                 audit_seed: str | None = None):
        self.cap = cap
        self.audit_share = audit_share(audit)
        self.audit_seed = audit_seed or _new_seed()
        self.auditing: dict[str, dict] = {}  # nodeid -> receipt of a reusable result run fresh by the audit
        self.audit_candidates = 0  # results that could be reused (audited or not)
        self.audit_results: dict[str, dict] = {}  # nodeid -> {"verdict", "cached", "fresh", "fresh2"}
        self.audit_keep: set[str] = set()  # audited tests whose fresh runs must not be recorded
        self.fresh_ids: dict[str, set] = {}  # nodeid -> test ids its reports carried
        self._running: str | None = None
        self.dir = os.path.abspath(cache_dir)
        self.verify = verify
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

    # -- setup ----------------------------------------------------------------
    def configure(self, config) -> None:
        self.config = config
        self.root = os.path.realpath(str(config.rootpath))
        self.config_digest, self.config_info = config_identity(config)
        self.runtime_digest, self.runtime_info, editable = runtime_identity(self.root)
        cap = self.cap
        cap.dist_info_ok = tuple(editable)
        cap.stdlib_dirs = tuple(d + os.sep for d in _sites._stdlib_dirs)
        cap.site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
        factory = getattr(config, "_tmp_path_factory", None)
        if factory is not None:
            try:
                cap.basetemp = os.path.realpath(str(factory.getbasetemp()))
            except Exception:
                cap.basetemp = None
        self.epoch = _state.STATE.config.epoch_ns
        self.store = _core.ProofCache(self.dir, self.root)
        self.store.begin(self.config_digest, self.runtime_digest, self.epoch, dict(cap.env0))
        # what the start-up processes gave back is known only when start-up ends (other plugins' pytest_configure
        # and pytest_sessionstart run after this one): handed to the store then, before any check
        cap.on_startup_end = self.store.set_startup
        if not cap.startup:
            self.store.set_startup(cap.startup_digest)

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        if self.cap.startup:  # no file was collected (start-up ends at the first collection otherwise)
            self.cap._end_startup()

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
        if self.cap.startup:
            self.cap._end_startup()
        for path, content in store.changed_code_files():
            mod, is_pkg = _module_of(os.path.join(self.root, path))
            f = _codefacts.read_facts(os.path.join(self.root, path), content, mod, is_pkg)
            if f is not None:
                store.set_fresh(path, content, f[0], f[1], f[2], f[3])
        rng = random.Random(f"detpy-cache-verify:{self.run_id}")
        for i, item in enumerate(items):
            nid = item.nodeid
            self.items[nid] = item
            self.test_index[nid] = i
            ok, info = store.check(nid)
            if ok:
                receipt = json.loads(info)
                self.audit_candidates += 1
                if _core.audit_chosen(self.audit_seed, nid, self.audit_share):
                    self.auditing[nid] = receipt
                elif self.verify and rng.random() < self.verify:
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
        self._running = nid
        t = _perf()
        try:
            yield
        finally:
            self._running = None
            self.dur[nid] = _perf() - t
            self.cap.switch("s")
            self.cap.scan_modules(self.test_index.get(nid, len(self.ran)), self._conftests())
            self.ran.append(nid)

    def pytest_runtest_logreport(self, report):
        if report.nodeid in self.hits:
            return
        self.fresh_ids.setdefault(self._running or report.nodeid, set()).add(report.nodeid)
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

    # -- cache audit ---------------------------------------------------------------
    def audit_after_run(self, item, rerun) -> None:
        """Compare an audited test's fresh run with its cached result; on a mismatch run it once more (``rerun()``
        gives (outcome, test ids)) to tell a wrong skip from a flaky test. Never breaks the session."""
        nid = item.nodeid
        r = self.auditing[nid]
        cached = (r["outcome"], [nid])
        first = (_final(self.parts.get(nid, {})), sorted(self.fresh_ids.get(nid, set()) or {nid}))
        res = {"key": r["key"], "cached": {"outcome": cached[0], "ids": cached[1]},
               "fresh": {"outcome": first[0], "ids": first[1]}}
        try:
            v = _core.audit_verdict(cached, first)
            if v == "needs-second-run":
                second = rerun()
                res["fresh2"] = {"outcome": second[0], "ids": list(second[1])}
                v = _core.audit_verdict(cached, first, (second[0], list(second[1])))
        except Exception as e:  # the second run could not be made: the mismatch stays unexplained, never trusted
            res["error"] = f"{type(e).__name__}: {e}"
            v = "wrong"
        res["verdict"] = v
        self.audit_results[nid] = res
        if v == "wrong":
            why = (f"cached {cached[0]} {cached[1]}, fresh {first[0]} {first[1]}"
                   + (f", again {res['fresh2']['outcome']}" if "fresh2" in res else ""))
            self.store.mark_untrusted(r["key"], nid, self.run_id, why)
            self.audit_keep.add(nid)
        elif v == "flaky-evidence":
            self.audit_keep.add(nid)  # two fresh runs disagree: neither is recorded, the entry stays as it was

    def audit_summary(self) -> dict:
        res = self.audit_results
        wrong = [n for n, x in res.items() if x["verdict"] == "wrong"]
        flaky = [n for n, x in res.items() if x["verdict"] == "flaky-evidence"]
        checked = len(res)
        return {"share": self.audit_share, "seed": self.audit_seed, "candidates": self.audit_candidates,
                "chosen": len(self.auditing), "checked": checked, "matched": checked - len(wrong) - len(flaky),
                "wrong": len(wrong), "flaky_evidence": len(flaky),
                "not_run": sorted(set(self.auditing) - set(res)),
                "wrong_tests": [{"nodeid": n, **res[n]} for n in sorted(wrong)],
                "flaky_tests": [{"nodeid": n, **res[n]} for n in sorted(flaky)],
                "upper_bound_95": _core.audit_upper_bound(checked, len(wrong))}

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

    def _record_all(self) -> None:
        cap, store = self.cap, self.store
        if cap.rec is None:
            return
        fcache: dict[str, int | None] = {}
        rels = cap.fnames
        # file facts for every executed or loaded repository file
        needed = set(rels) | {r for r, _ in cap.loaded_order} | cap.preloaded
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
        g_data, g_env, g_flags = {}, set(), set()
        for c in g_ctx_all:
            g_data.update(cap.data.get(c, {}))
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
                if path in session_written and not set(session_written[path]) <= own:
                    self.stale_hits[nid] = path
                    store.remove(nid)
                    break
        loaded_idx = cap.loaded_order  # (rel, index)
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

        for nid in self.ran:
            item = self.items.get(nid)
            if item is None:
                continue
            if nid in self.audit_keep:
                v = self.audit_results.get(nid, {}).get("verdict")
                if v == "wrong":
                    self._not_cached(nid, "audit: wrong skip (key marked untrusted)")
                else:
                    self.not_cached[nid] = "audit: flaky with evidence (two fresh runs disagree)"
                continue
            p = self.parts.get(nid, {})
            outcome = _final(p)
            if outcome not in ("passed", "skipped", "xfailed"):
                self._not_cached(nid, f"outcome {outcome}")
                continue
            own = _ctx_file(nid)
            ctxs = [ctx_of[c] for c in ["t|" + nid, "c|" + own, *self.fixture_ctx.get(nid, [])] if c in ctx_of]
            if own in own_import:
                ctxs.append(own_import[own])
            flags = set(g_flags)
            data = dict(g_data)
            env = set(g_env)
            units = set()
            content = set(pre_ix) | g_unparsable
            for c in ctxs:
                flags |= cap.flags.get(c, set())
                data.update(cap.data.get(c, {}))
                env |= cap.env.get(c, set())
                units |= units_of(per[c][0])
                content |= unparsable(per[c][1])
            why = _uncacheable(flags, cfg)
            if why is not None:
                self.not_cached_where[nid] = self._where(why, g_ctx_all + ctxs)
            if why is None:
                # writers credited to the test: its own contexts and the global ones (startup, between tests,
                # import time), whose code is an input of every test
                credited = set(ctxs) | set(g_ctx_all)
                names = {names_of[c] for c in credited}
                for f in sorted(flags):
                    if f.startswith("rw:") and not cap.writers.get(f[3:], set()) <= credited:
                        why = f"reads a file another test or fixture wrote: {cap._key(f[3:])}"
                        break
                if why is None:
                    for path in data:
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
            report = {w: p[w] for w in ("setup", "call") if w in p}
            store.record(nid, outcome, json.dumps(report), self.fingerprints.get(nid, ""), self.dur.get(nid, 0.0),
                         self.run_id, self.config_digest, self.runtime_digest, epoch, env_deps,
                         sorted(data.items()), sorted(content), sorted(skeleton), sorted(hooks), sorted(units),
                         startup=cap.startup_digest)
            self.recorded += 1
        store.save()

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
                # first line: the audit's seed, share and choice (reproduce with --det-cache-audit-seed)
                fh.write(json.dumps({"nodeid": None, "reused": False, "kind": "audit", "seed": self.audit_seed,
                                     "share": self.audit_share, "candidates": self.audit_candidates,
                                     "chosen": sorted(self.auditing), "run": self.run_id}) + "\n")
                for nid, r in self.hits.items():
                    fh.write(json.dumps({"nodeid": nid, "reused": True, **r}) + "\n")
                for nid, r in self.auditing.items():
                    # the reuse decision (receipt) and what the fresh run(s) gave
                    fh.write(json.dumps({"nodeid": nid, "reused": False, "audited": True, **r,
                                         "audit": self.audit_results.get(nid, {"verdict": "not-run"})}) + "\n")
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
            "reused_recorded_seconds": round(sum(self._entry_duration(n) for n in self.hits), 3),
            "check_seconds": round(self.t_check, 3),
            "record_seconds": round(self.t_record, 3),
            "config": self.config_digest,
            "runtime": self.runtime_digest,
            "verify_mismatches": [v for v in self.verify_results if not v["same"]],
            "audit": self.audit_summary(),
            "stale_reuses": self.stale_hits,
            "error": self.error,
            "receipts": self.receipts_path,
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
        a = s["audit"]
        if a["share"] > 0:
            tr.write_line(f"cache audit (share {a['share']:.1%}, seed {a['seed']}): {a['checked']} reusable result(s) "
                          f"run fresh, {a['matched']} matched, {a['wrong']} wrong, {a['flaky_evidence']} flaky with "
                          f"evidence; 95% upper bound on the wrong-skip rate {a['upper_bound_95']:.2%}",
                          red=bool(a["wrong"]))
            for w in a["wrong_tests"]:
                tr.write_line(f"  WRONG SKIP {w['nodeid']}: cached {w['cached']['outcome']}, fresh "
                              f"{w['fresh']['outcome']}" + (f" and {w['fresh2']['outcome']}" if "fresh2" in w else "")
                              + f"; key {w['key']} marked untrusted", red=True)
            for w in a["flaky_tests"]:
                tr.write_line(f"  FLAKY {w['nodeid']}: cached {w['cached']['outcome']}, fresh "
                              f"{w['fresh']['outcome']}, then {w.get('fresh2', {}).get('outcome')}", yellow=True)
        tr.write_line(f"receipts: {s['receipts']}")


def audit_share(value) -> float:
    """``--det-cache-audit`` value as a fraction: ``0.05``, ``5%``; None -> ``FENVIX_AUDIT_SHARE``, else 5%."""
    if value is None or value == "":
        value = os.environ.get("FENVIX_AUDIT_SHARE", "") or "0.05"
    v = str(value).strip()
    try:
        x = float(v[:-1]) / 100 if v.endswith("%") else float(v)
    except ValueError:
        raise pytest.UsageError(f"--det-cache-audit: not a share: {value!r} (e.g. 0.05 or 5%)") from None
    if not 0.0 <= x <= 1.0:
        raise pytest.UsageError(f"--det-cache-audit: {value!r} is not between 0 and 1 (0% and 100%)")
    return x


def _new_seed() -> str:
    try:
        return _urandom(8).hex()
    except Exception:  # pragma: no cover - no OS entropy: time and pid still differ between runs
        return f"{time.time_ns():x}{os.getpid():x}"


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


def _is_find_library_ldconfig(args) -> bool:
    """``subprocess.Popen(['/sbin/ldconfig', '-p'])`` called by ``ctypes.util.find_library``."""
    try:
        argv = list(args[1]) if len(args) > 1 and not isinstance(args[1], (str, bytes)) else None
    except TypeError:
        return False
    if not argv or len(argv) != 2 or os.path.basename(os.fsdecode(argv[0])) != "ldconfig" or argv[1] != "-p":
        return False
    f = sys._getframe(2)
    while f is not None:
        fn = f.f_code.co_filename
        if fn.endswith(os.sep + os.path.join("ctypes", "util.py")):
            return True
        f = f.f_back
    return False


_SUBPROCESS_FILE = ("subprocess.py",)
_ENV_ITER_FILES = ("<frozen _collections_abc>", "_collections_abc.py", "<frozen os>", "os.py")


def _outer_frame(skip: tuple):
    """The innermost calling frame outside detpy and the files named in ``skip`` (the code that enumerates the
    environment, or that starts a process)."""
    f = sys._getframe(2)
    while f is not None:
        fn = f.f_code.co_filename
        if not fn.startswith(_DETPY_DIR) and not (fn in skip or os.path.basename(fn) in skip):
            return f
        f = f.f_back
    return None


def _popen_being_started():
    """The ``subprocess.Popen`` whose ``__init__`` raised the ``subprocess.Popen`` audit event and the arguments of
    that ``__init__`` (standard streams, ``pass_fds``, ``close_fds``); ``(None, None)`` if there is none."""
    import subprocess

    f = sys._getframe(2)
    found = None
    for _ in range(8):
        if f is None:
            break
        if f.f_code.co_name in ("_execute_child", "__init__"):
            p = f.f_locals.get("self")
            if isinstance(p, subprocess.Popen):
                found = p
                # subprocess's own __init__ (Level 0 wraps it: detpy.clock)
                if f.f_code.co_name == "__init__" and f.f_code.co_filename == subprocess.__file__:
                    loc = f.f_locals
                    return p, {k: loc.get(k) for k in ("stdin", "stdout", "stderr", "pass_fds", "close_fds")}
        f = f.f_back
    return found, None


class _Held:
    """A ``subprocess.Popen`` started at start-up, until start-up ends."""

    __slots__ = ("p", "detail", "argv", "cwd", "chan", "piped", "env", "gid", "comm", "error")

    def __init__(self, p, detail: str):
        self.p = p
        self.detail = detail
        self.argv: list = []
        self.cwd = ""
        self.chan: str | None = None  # a channel to the tests other than its pipes (then never exempt)
        self.piped = False  # stdout or stderr is a pipe
        self.env = None  # the env= mapping handed to it (dropped when start-up ends)
        self.gid: int | None = None  # the environment copy (group of start-up reads) it took
        self.comm: list | None = None  # [(stdout, stderr)] returned by communicate() called from subprocess.run
        self.error: str | None = None  # the exception Popen() raised (the program could not be started)


# references to an env= mapping when only detpy holds it (the _Held attribute and getrefcount's argument)
_ENV_REFS = 2
_PYTEST_CACHE_PART = os.sep + ".pytest_cache"
_PR_SET_CHILD_SUBREAPER, _PR_GET_CHILD_SUBREAPER = 36, 37
_LIBC: list = []
_COMM_PATCHED = False


def _in_pytest_cache(p: str) -> bool:
    return _PYTEST_CACHE_PART + os.sep in p + os.sep


def _libc():
    if not _LIBC:
        import ctypes

        _LIBC.append(ctypes.CDLL(None, use_errno=True))
    return _LIBC[0]


def _children() -> set:
    """Pids of this process's children (every thread's), from /proc."""
    out = set()
    try:
        tasks = os.listdir("/proc/self/task")
    except OSError:
        tasks = []
    ok = False
    for t in tasks:
        try:
            with open(f"/proc/self/task/{t}/children", "rb") as fh:
                out.update(int(x) for x in fh.read().split())
            ok = True
        except (OSError, ValueError):
            continue
    if ok:
        return out
    me = os.getpid()  # kernels without CONFIG_PROC_CHILDREN: the parent field of every process
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open(f"/proc/{d}/stat", "rb") as fh:
                    st = fh.read()
                if int(st[st.rindex(b")") + 2:].split()[1]) == me:
                    out.add(int(d))
            except (OSError, ValueError, IndexError):
                continue
    return out


def _out_digest(v) -> str | None:
    """Digest of one output stream as ``communicate`` returned it (bytes, or text decoded from them)."""
    if v is None:
        return None
    if isinstance(v, str):
        return "t:" + _core.digest(v.encode("utf-8", "surrogatepass"))
    return "b:" + _core.digest(bytes(v))


def _patch_communicate() -> None:
    """``Popen.communicate`` as called by ``subprocess.run`` (``check_output``, ``run``, ``getoutput``,
    ``platform._syscmd_file``...): nothing can read the pipes between the start and this call, so what it returns is
    all the process wrote to them. Seen for the processes held at start-up only."""
    global _COMM_PATCHED
    if _COMM_PATCHED:
        return
    _COMM_PATCHED = True
    import subprocess

    orig = subprocess.Popen.communicate
    run_code = subprocess.run.__code__
    orig_init = subprocess.Popen.__init__

    def __init__(self, *a, **k):
        try:
            orig_init(self, *a, **k)
        except BaseException as e:
            cap = CAPTURE
            if cap is not None and cap.startup:
                h = next((x for x in cap._startup_popens if x.p is self), None)
                if h is not None:  # what it gave back is this error (a missing `file`: platform._syscmd_file)
                    h.error = f"{type(e).__name__}:{getattr(e, 'errno', '')}:" \
                              f"{cap._arg(getattr(e, 'filename', None) or '')}"
            raise

    __init__.__wrapped__ = orig_init
    __init__.__doc__ = orig_init.__doc__
    subprocess.Popen.__init__ = __init__

    def communicate(self, *a, **k):
        cap = CAPTURE
        if cap is None or not cap.startup or not cap._startup_popens:
            return orig(self, *a, **k)
        h = next((x for x in cap._startup_popens if x.p is self), None)
        if h is None:
            return orig(self, *a, **k)
        caller = sys._getframe(1).f_code
        first = not self._communication_started
        r = orig(self, *a, **k)
        if caller is run_code and first and h.comm is None:
            h.comm = [r]
        elif h.piped:
            h.chan = h.chan or "its output read outside subprocess.run (not keyed)"
        return r

    communicate.__wrapped__ = orig
    communicate.__doc__ = orig.__doc__
    subprocess.Popen.communicate = communicate


def _numeric_host(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


_FLAG_OF = {"subprocess": "spawn", "network connection": "connect", "host name lookup": "dns",
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
        f = sys._getframe(1)
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


def _addr(args) -> str:
    try:
        a = args[1]
        return f"{a[0]}:{a[1]}" if isinstance(a, tuple) else str(a)
    except (IndexError, TypeError):
        return "?"


def _uncacheable(flags: set, cfg) -> str | None:
    if "badpath" in flags:
        return "reads a path that is not valid UTF-8"
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
    cap.start()


def install(config) -> None:
    """Register the plugin hooks (from ``pytest_configure``)."""
    global PLUGIN
    cap = CAPTURE
    if cap is None or PLUGIN is not None:
        return
    opt = config.option
    plugin = ProofCachePlugin(cap, opt.det_cache, opt.det_cache_verify, opt.det_cache_receipts,
                              getattr(opt, "det_cache_audit", None), getattr(opt, "det_cache_audit_seed", None))
    plugin.configure(config)
    PLUGIN = plugin
    config.pluginmanager.register(plugin, "detpy-cache")
    config.pluginmanager.register(_ProtocolWrapper(plugin), "detpy-cache-wrapper")
    cap.switch("s")


def uninstall() -> None:
    global CAPTURE, PLUGIN, _ENV_CAPTURE
    if CAPTURE is not None:
        CAPTURE.stop()
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
