# Reference copy (verbatim) of python/detpy/proofcache.py before round 2 moved its capture to Rust
# (crates/detpy-py/src/capture.rs), with the review R-009b R1/R2 fixes applied to it as on claude/cache-proof-step1
# (c872a13, a7359b9; R2's stale-check exception goes through the plan's stale_skip, the record being Rust here), and
# the review R-015b G1-G3 fixes as on claude/rust-hotpaths (7198773, 0007d42, ab2a069). Installed as detpy.proofcache by tests/rust_hotpaths_ref/_capref.py when
# DETPY_CAPTURE_REF=1, for the equivalence tests (tests/test_capture_rust.py).
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
import stat as _stat
import sys
import time
from types import CodeType, FunctionType

import pytest

from . import __version__, _codefacts, _core, _sites, _state, follow

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
                 "os.link", "ctypes.dlopen")
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
# a file's ctime comes from the kernel's coarse clock (one tick behind at most); strace -ttt from the fine one
_CTIME_SLACK = 0.02
_O_TMPFILE = getattr(os, "O_TMPFILE", 0)
# options that never change a test's result (output, reporting, selection by path, detpy's own files)
_VOLATILE_OPTIONS = {
    "file_or_dir", "verbose", "quiet", "color", "code_highlight", "reportchars", "tbstyle", "showlocals",
    "durations", "durations_min", "junitxml", "junitprefix", "resultlog", "basetemp", "det_cache",
    "det_cache_verify", "det_cache_receipts", "det_cache_shared", "det_trace", "det_outcomes", "det_compare", "det_max_events",
    "showcapture", "fulltrace", "collectonly", "markers", "fixtures", "show_fixtures_per_test", "help", "version",
    "debug", "traceconfig", "showlocals", "log_file", "log_cli_level", "pastebin", "usepdb", "usepdb_cls",
    "trace", "xmlpath", "htmlpath", "lf", "failedfirst", "last_failed_no_failures", "newfirst", "cacheclear",
    "cacheshow", "stepwise", "stepwise_skip", "maxfail", "exitfirst", "no_header", "no_summary", "override_ini",
    "inifilename", "rootdir", "confcutdir", "keyword", "markexpr", "deselect", "ignore", "ignore_glob",
    "continue_on_collection_errors", "numprocesses", "dist", "tx", "det_epoch", "det_cache_max_age",
    "det_cache_epoch_window",
    # parallel-proof: pytest-xdist's options and detpy's plan replay (same set as python/detpy/proofcache.py)
    "loadgroup", "looponfail", "distload", "maxprocesses", "maxworkerrestart", "loadscopereorder", "px",
    "testrunuid", "rsyncdir", "rsyncignore", "maxschedchunk", "det_plan", "det_plan_worker",
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


def rep_line(code) -> int | None:
    """Code-object level capture: the line that stands for every line of a plain function, its last one. A
    unit's range starts at its first body statement's ``lineno``, after the decorators of a decorated first
    statement (whose lines the function runs first), and ends at its last line: the last line of a function
    (the last statement's, or its implicit return) is inside its unit's range."""
    co = code.co_code
    r = 0
    while r < len(co) and co[r] in _PRELUDE:
        r += 2
    if r >= len(co) or co[r] != _RESUME:
        return None
    lines = [line for start, _end, line in code.co_lines() if start > r and line is not None]
    return max(lines) if lines else None


# Line capture granularity (experiment, DETPY_CACHE_LINES): "line" (default) arms every code object with LINE;
# "code" arms plain functions (not module or class bodies, not generators or coroutines) with PY_START only and
# records one location per start (rep_line), see REPORT-2.
_CODE_LEVEL = os.environ.get("DETPY_CACHE_LINES", "line") == "code"
_CO_PLAIN_EXCLUDE = 0x20 | 0x80 | 0x100 | 0x200  # CO_GENERATOR | CO_COROUTINE | CO_ITERABLE_COROUTINE | CO_ASYNC_GENERATOR
_CO_OPTIMIZED = 0x1


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
        # abs path -> whether it existed at its first exclusive create in the session, if nothing had written it
        self.excl_pre: dict[str, bool] = {}
        self._hashed: dict[str, str] = {}  # abs path -> dep at first read in the session
        # repository code file (abs path) -> stat key when its source was first read (open by the import system,
        # before the read) or its module body first ran: a file changed after that ran other code than the one
        # its digest at the end of the session says (review R-015 F1)
        self.code_stat: dict[str, tuple] = {}  # (stat key, resolved path)
        self.loaded_order: list[tuple[str, int]] = []  # (rel module file, index of the test after which it was seen)
        self._seen_mods: set[str] = set()
        self._nmods = 0
        self.basetemp: str | None = None
        self.site_dirs: tuple = ()
        self.stdlib_dirs: tuple = ()
        self.dist_info_ok: tuple = ()
        self.import_ctx = -1  # pseudo context for import-time data/env/flags
        self.active = False
        self._socks = _core.SocketScan()  # socket descriptors at the last scan
        self.follower: follow.Follower | None = None
        self.child_entropy = 0  # entropy draws of followed children (not controlled, not refused)
        self.children = 0  # followed children (spawn calls)
        self.timeline: list[tuple[float, int]] = [(_now(), 0)]  # (real time, context) at every switch

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
                prev = self.ctx_index(self.ctx) if self.ctx else None
                self._scan_sockets(prev)
                self._scan_maps(prev)
            finally:
                self.active = True
        self.ctx = name
        _core.l0_listener_reset()
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
                    link = self._code_link(filename)
                    if link is not None and self.import_ctx >= 0:
                        # review R-015b G2: the code is keyed on the link's target; the content read through the
                        # link (where the link points now) is an input of every test
                        self.read(self.import_ctx, link, "f")
            self._wanted[filename] = w
        return w

    def _code_link(self, filename: str) -> str | None:
        """The path of a code file through its first symlink inside the repository (a module that is a link, or
        is in a linked directory), or None. Links outside it (the root reached through a linked path) are
        resolved."""
        try:
            a = os.path.abspath(filename)
        except (OSError, ValueError):
            return None
        parts = a.split(os.sep)[1:]
        cur = os.sep
        for i, comp in enumerate(parts):
            q = os.path.join(cur, comp)
            if os.path.islink(q):
                if cur == self.root or cur.startswith(self.root_sep):
                    return os.path.join(q, *parts[i + 1:])
                cur = os.path.realpath(q)
            else:
                cur = q
        return None

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
            rep = None
            if _CODE_LEVEL and not module and c.co_flags & _CO_OPTIMIZED and not c.co_flags & _CO_PLAIN_EXCLUDE:
                rep = rep_line(c)
            if rep is not None:
                ev = START
                self._events[id(c)] = ev
                self.rec.add_code(c, self.fid[fn], -1, False, rep)
                set_local(tool, c, ev)
                stack.extend(k for k in c.co_consts if isinstance(k, CodeType))
                continue
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
        lst = _state._event_listener  # the object the Rust event path calls (a bound method is made per access)
        _core.l0_listener_memo(lst if lst is not None and lst == self.event else None, self.rec)
        _mon.register_callback(self.tool, _mon.events.LINE, self.rec.line)
        _mon.register_callback(self.tool, _mon.events.PY_START, self.rec.start)
        _mon.register_callback(self.tool, _mon.events.PY_RETURN, self.rec.ret)
        self.active = True
        _core.set_audit_hook(self._audit, _AUDIT_EVENTS)
        self._patch_sqlite()
        self._patch_stat()
        self._patch_lookups()
        self._installed_cb = self._installed
        self.active = False
        try:
            self._scan_maps(None)
        finally:
            self.active = True
        # code that exists before the start: modules already loaded become whole-content inputs
        pre = False
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f and self._want(f):
                self.preloaded.add(self.fnames[self.fid[f]])
                self._note_code(f)
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
        _core.l0_listener_memo(None)
        _core.set_audit_hook(None, ())
        for obj, name, v in getattr(self, "_sqlite_saved", ()):
            setattr(obj, name, v)
        self._sqlite_saved = []
        for obj, name, v in reversed(getattr(self, "_stat_saved", ())):
            setattr(obj, name, v)
        self._stat_saved = []
        f = getattr(self, "_lookup_finder", None)
        if f is not None and f in sys.meta_path:
            sys.meta_path.remove(f)
        if self.tool is not None:
            for ev in (_mon.events.LINE, _mon.events.PY_START, _mon.events.PY_RETURN):
                _mon.register_callback(self.tool, ev, None)
            _mon.set_events(self.tool, 0)
            _mon.free_tool_id(self.tool)
            self.tool = None

    # -- absent inputs (parallel-proof round 3, item 9) ---------------------------------
    def _patch_stat(self) -> None:
        cap = self
        self._stat_saved = []
        self._in_stat = False

        def wrap(name):
            orig = getattr(os, name, None)
            if orig is None:
                return

            link = name == "lstat"

            def checked(path, *args, **kwargs):
                if not cap._in_stat and not isinstance(path, int) and not kwargs.get("dir_fd"):
                    cap._in_stat = True
                    try:
                        cap.stat_check(path, link or kwargs.get("follow_symlinks") is False)
                    except Exception:
                        pass
                    finally:
                        cap._in_stat = False
                return orig(path, *args, **kwargs)

            checked.__name__ = orig.__name__
            checked.__wrapped__ = orig
            self._stat_saved.append((os, name, orig))
            setattr(os, name, checked)
            # LIMITS A3: references bound before the session
            for mod in list(sys.modules.values()):
                d = getattr(mod, "__dict__", None)
                if not isinstance(d, dict) or mod is os or getattr(mod, "__name__", "") in ("posix", "nt") \
                        or str(getattr(mod, "__file__", "") or "").startswith(_DETPY_DIR):
                    continue
                for k, v in list(d.items()):
                    if v is orig:
                        self._stat_saved.append((mod, k, orig))
                        try:
                            setattr(mod, k, checked)
                        except Exception:
                            pass

        for name in ("stat", "lstat", "access"):
            wrap(name)

    def stat_check(self, path, link=False) -> None:
        if not self.active:
            return
        p = self._abs(path)
        if p is None or self._ignored(p):
            return
        try:
            f = _getframe(1)
        except ValueError:
            f = None
        if self._kind_from(f) != "user":
            return
        self.read(self._cur(), p, "l" if link else "s")

    def _kind_from(self, f) -> str:
        while f is not None:
            fn = f.f_code.co_filename
            if fn.startswith("<frozen importlib") or fn.startswith("<frozen zipimport"):
                return "import"
            if fn.startswith(_DETPY_DIR):
                f = f.f_back
                continue
            kind, _ = _sites._classify(fn)
            if kind == _sites._USER:
                return "user"
            if kind == _sites._INFRA:
                return "infra"
            f = f.f_back
        return "user"

    def _patch_lookups(self) -> None:
        from importlib.machinery import all_suffixes

        cap = self
        suffixes = list(all_suffixes())

        class _LookupFinder:
            @staticmethod
            def find_spec(fullname, path=None, target=None):
                if cap._in_stat:
                    return None
                cap._in_stat = True
                try:
                    cap.lookup(fullname.rpartition(".")[2], sys.path if path is None else path, suffixes)
                except Exception:
                    pass
                finally:
                    cap._in_stat = False
                return None

            @staticmethod
            def invalidate_caches():
                pass

        self._lookup_finder = _LookupFinder
        sys.meta_path.insert(0, _LookupFinder)

    def lookup(self, tail, entries, suffixes) -> None:
        if not self.active:
            return
        try:
            f = _getframe(1)
        except ValueError:
            f = None
        while f is not None and (f.f_code.co_filename.startswith("<frozen ")
                                 or f.f_code.co_filename.startswith(_DETPY_DIR)
                                 or "/importlib/" in f.f_code.co_filename):
            f = f.f_back
        if f is not None and _sites._classify(f.f_code.co_filename)[0] != _sites._USER:
            return  # the immediate importer is the standard library, pytest, a plugin: not the test's input
        ctx = self._cur()
        n = len(suffixes)
        whole = tail.isidentifier() and all(x.endswith((".py", ".pyc", ".pyw", ".so", ".pyd")) for x in suffixes)
        for e in list(entries):
            if not isinstance(e, str):
                continue
            d = self._abs(e or ".")
            if d is None or not os.path.isdir(d) or self._ignored(d + os.sep):
                continue
            if whole:
                # one dependency on the directory's importable entries (proof::importable_digest)
                self.read(ctx, d, "i")
                regular, pkg_dir = _core.import_probe(d, tail, suffixes)
                if pkg_dir:
                    for c in _core.import_candidates(d, tail, suffixes)[1:1 + n]:
                        self.read(ctx, c, "s")
                        if os.path.isfile(c):
                            regular = True
                if regular:
                    break
                continue
            cands = _core.import_candidates(d, tail, suffixes)
            missing = not os.path.exists(cands[0])
            self.read(ctx, cands[0], "s")
            regular = False
            for c in (cands[1 + n:] if missing else cands[1:]):
                is_file = os.path.isfile(c)
                if not (is_file and c.endswith(".py") and c.startswith(self.root_sep)):
                    self.read(ctx, c, "s")
                if is_file:
                    regular = True
            if regular:
                break

    def _scan_maps(self, ctx) -> None:
        try:
            with open("/proc/self/maps", "rb") as fh:
                text = fh.read()
        except OSError:
            return
        if text == getattr(self, "_maps_text", None):
            return
        self._maps_text = text
        seen = self.__dict__.setdefault("_maps_seen", set())
        new = []
        for line in text.split(b"\n"):
            i = line.find(b"/")
            if i < 0:
                continue
            p = line[i:]
            if p in seen:
                continue
            seen.add(p)
            new.append(p)
        if self.__dict__.get("_maps_baseline", True):
            self._maps_baseline = False
            ctx = None
        if ctx is None:
            ctx = self.import_ctx
        for b in new:
            p = os.fsdecode(b)
            if p.endswith(" (deleted)") or self._ignored(p) or not os.path.isfile(p):
                continue
            self.read(ctx, p, "f")
            self._native(ctx, p)

    def _installed(self, p: str) -> bool:
        idx = getattr(self, "_dist_index", None)
        if idx is None:
            from detpy import distid

            was = self.active
            self.active = False
            try:
                idx = self._dist_index = distid.Index(self.root)
            except Exception:
                return False
            finally:
                self.active = was
        r = idx.owners(p)
        return r is not None and r[0] != [""]

    def _native(self, ctx, p) -> None:
        """LIMITS A1/A2: a library from the project root that no RECORD lists is the repository's native code."""
        if not p.startswith(self.root_sep) or p.startswith(_DETPY_DIR) or os.path.basename(p).startswith("clockshim-"):
            return
        inst = getattr(self, "_installed_cb", None)
        if inst is not None and inst(p):
            return
        self.flag(ctx, "native", p)

    # -- sockets opened in C ----------------------------------------------------------
    def _scan_sockets(self, ctx: int | None) -> None:
        """Internet sockets that appeared among this process's descriptors since the last scan.

        Sockets a C extension opens (libpq, grpc, libcurl, ...) raise no audit event; one still open when its
        test or fixture ends is seen here and makes the context uncacheable. (The scan of /proc is in Rust:
        ``_core.SocketScan``.)
        """
        if self._socks.scan() and ctx is not None:
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

    def _note_code(self, filename: str) -> None:
        p = self._abs(filename)
        if p is not None and p not in self.code_stat:
            self.code_stat[p] = _code_key(p)

    def changed_code(self) -> list:
        """Repository code files (relative paths) changed since their source was first read or their module body
        first ran in this session."""
        out = set()
        for p, (k, r) in self.code_stat.items():
            if _stat_key(p) == k:
                continue
            if r is not None and r.startswith(self.root_sep):
                out.add(r[len(self.root_sep):].replace(os.sep, "/"))
        return sorted(out)

    def _key(self, p: str) -> str:
        return p[len(self.root_sep):] if p.startswith(self.root_sep) else p

    def read(self, ctx: int, p: str, kind: str) -> None:
        """A read of ``p`` (kind f = file content, d = listing) in context ``ctx``."""
        if not _encodable(p):
            self.flags.setdefault(ctx, set()).add("badpath")
            return
        if kind == "i":
            hk = "i" + p
            dep = self._hashed.get(hk)
            if dep is None:
                dep = self._hashed[hk] = _core.importable_dep(p)
            self.data.setdefault(ctx, {}).setdefault(self._key(p) + "/\x01importable", dep)
            return
        if kind in ("s", "l"):
            # parallel-proof round 3, item 9: an existence or kind check; the project root and its ancestors are
            # directories for the whole session; a kind never replaces a content or listing read of the same path
            if self.root_sep.startswith(p.rstrip(os.sep) + os.sep) or p == os.sep:
                return
            if p in self.writers:
                self.flags.setdefault(ctx, set()).add("rw:" + p)
                return
            hk = kind + p
            dep = self._hashed.get(hk)
            if dep is None:
                dep = self._hashed[hk] = ("l:" + _core.lstat_kind(p)) if kind == "l" else ("s:" + _core.stat_kind(p))
            self.data.setdefault(ctx, {}).setdefault(self._key(p), dep)
            return
        if kind == "m":
            kind = "f"  # a machine identity file under /sys read on purpose (uuid.getnode): its content is the input
        elif kind == "a":
            # a child's exclusive create that succeeded: the path did not exist then (its state now is irrelevant)
            if p in self.writers:
                self.flags.setdefault(ctx, set()).add("rw:" + p)
            else:
                self.data.setdefault(ctx, {})[self._key(p)] = "missing"
            return
        elif _proc_alias(p) is not None:
            self.read(ctx, _proc_alias(p), kind)  # review R-023b N1: /proc/self/root/..., /dev/fd/N: the file itself
            return
        elif _process_state(p):
            self.flag(ctx, "pstate", p)  # this process's own state: counted in a test's own contexts only
            return
        elif p.startswith(("/proc/", "/sys/", "/dev/")) and not p.startswith("/dev/shm/") \
                and ((kind != "d" or p.startswith("/proc/")) and os.path.exists(p)):
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
        for k in ("f" + p, "d" + p, "d" + os.path.dirname(p), "s" + p, "l" + p, "i" + os.path.dirname(p)):
            self._hashed.pop(k, None)

    def _audit(self, event, args):
        if not self.active:
            return
        if event == "exec":
            # every module body (import, runpy, exec) passes here before it runs; the functions and classes
            # it defines are nested code objects, armed with it
            code = args[0] if args else None
            if isinstance(code, CodeType):
                if code.co_name == "<module>" and self._want(code.co_filename):
                    self._note_code(code.co_filename)
                if id(code) not in self._armed and self.tool is not None:
                    self.arm(code)
            return
        if event == "open":
            p = self._abs(args[0] if args else None)
            if p is None:
                return
            mode, flags = (args[1] if len(args) > 1 else None), (args[2] if len(args) > 2 else 0)
            if p.startswith(self.root_sep) and p not in self.code_stat and (
                    ("r" in mode and "+" not in mode) if isinstance(mode, str)
                    else isinstance(flags, int) and flags & _O_ACC == os.O_RDONLY) \
                    and not any(s in p for s in _SKIP_PARTS):
                # before the read: the source the import system (or pytest's rewrite, runpy...) is about to read.
                # Any file, not only .py: a doctest text file is read at collection and runs later (review R-015b
                # G3); the plan refuses only on files that are code inputs
                self.code_stat[p] = _code_key(p)
            if self._ignored(p):
                return
            if _O_TMPFILE and isinstance(flags, int) and flags & _O_TMPFILE == _O_TMPFILE:
                return  # an unnamed temporary file in that directory (NamedTemporaryFile): nothing visible changes
            if isinstance(mode, str):
                reads = "r" in mode or "+" in mode
                writes = any(ch in mode for ch in "wax+")
                excl = "x" in mode
                trunc = "w" in mode or excl
            else:
                acc = (flags or 0) & _O_ACC
                reads = acc in (os.O_RDONLY, os.O_RDWR)
                writes = acc in (os.O_WRONLY, os.O_RDWR) or bool((flags or 0) & os.O_CREAT)
                excl = (flags or 0) & (os.O_CREAT | os.O_EXCL) == (os.O_CREAT | os.O_EXCL)
                trunc = bool((flags or 0) & os.O_TRUNC) or excl
            kind = self._caller_kind()
            if kind == "import" and reads and not p.endswith((".py", ".pyc", ".pyw")) and os.path.isfile(p):
                self.read(self._cur(), p, "f")  # review R-019c E-7: a zip archive the import system reads
                return
            if kind in ("import", "infra"):
                return
            ctx = self._cur()
            if excl:
                # review R-009b R2: an exclusive create (a lock or pid file, mkstemp, mode "x") succeeds or fails on
                # whether the path exists, so that is an input: "missing", or the content it fails on. (The open has
                # not happened yet.) The first one in the session is remembered for the reuse decision (_decide).
                if p not in self.writers and p not in self.excl_pre:
                    self.excl_pre[p] = os.path.lexists(p)
                self.read(ctx, p, "f")
            elif reads and not trunc:
                self.read(ctx, p, "f")
            if writes:
                self.wrote(ctx, p)
        elif event == "sqlite3.connect":
            # sqlite opens the database read-write in C (no "open" event): its committed content is an input
            # review R-017b F2: only detpy's own schema query is not the test's read (it was every "file:" URI);
            # the patched connect says whether the name is a URI (unknown: both the literal name and the URI's file)
            db = args[0] if args else None
            mode = getattr(_SQL_CONNECT, "mode", 0)
            if mode != 1 and isinstance(db, (str, bytes, os.PathLike)) and os.fsdecode(db) not in ("", ":memory:"):
                is_uri = os.fsdecode(db).startswith("file:")
                files = []
                if not (is_uri and mode == 3):
                    files.append(self._abs(db))
                if is_uri and mode != 2:
                    files.append(_sqlite_file(db, True))
                self._sql_database([f for f in files if f is not None])
        elif event == "ctypes.dlopen":
            # LIMITS A2: a library opened through ctypes names its path
            name = args[0] if args else None
            if name is not None and "/" in str(name):
                p = self._abs(name)
                if p is not None and not self._ignored(p):
                    self._native(self._cur(), p)
        elif event in ("os.listdir", "os.scandir"):
            if self._caller_kind() != "user":
                return
            p = self._abs(args[0] if args and args[0] is not None else ".")
            if p is None or self._ignored(p):
                return
            self.read(self._cur(), p, "d")
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
            if _loopback_name(host) and _hosts_file_answers(host):
                # review R-023: a loopback name is answered by the host's resolver configuration, recorded as reads
                for f in ("/etc/hosts", "/etc/nsswitch.conf", "/etc/host.conf", "/etc/gai.conf"):
                    self.read(self._cur(), f, "f")
                return
            self.flag(self._cur(), "dns", f"{event} {host} at {_first_user_site()}")
        elif event == "ctypes.dlopen":
            name = args[0] if args else None
            if name is None or self._caller_kind() != "user":
                return
            n = os.fsdecode(name) if isinstance(name, (str, bytes)) else None
            if n is None:
                return
            ctx = self._cur()
            if "/" in n:
                p = self._abs(n)
                if p is not None and not self._ignored(p):
                    self.read(ctx, p, "s")
            else:
                self.read(ctx, "/etc/ld.so.cache", "f")
                for d in [x for x in os.environ.get("LD_LIBRARY_PATH", "").split(":") if x]:
                    c = d + "/" + n
                    if not self._ignored(c):
                        self.read(ctx, c, "s")
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
        the real clock makes its context uncacheable. (A trace callback the test sets itself replaces this one.)

        review R-009b R1: the schema evaluates such expressions too (a column default, a trigger, a view), while the
        statement says nothing about time. A statement that may evaluate the schema (anything but transaction
        control, PRAGMA, ATTACH/DETACH, DROP...) on a connection whose databases' schema may read the clock is
        refused in the same way."""
        try:
            import sqlite3
            import sqlite3.dbapi2 as dbapi2
        except ImportError:
            return
        real = sqlite3.connect
        cap = self
        self._sql_real_connect = real
        self._sql_schema: dict[str, tuple] = {}  # database file -> (signature, what reads the clock or None)

        def connect(*args, **kwargs):
            db = args[0] if args else kwargs.get("database")
            uri = kwargs.get("uri", args[7] if len(args) > 7 else False)
            from detpy import sqlvirt

            prev, _SQL_CONNECT.mode = getattr(_SQL_CONNECT, "mode", 0), (3 if uri else 2)
            sqlvirt.take_last()
            try:
                conn = real(*args, **kwargs)
            finally:
                _SQL_CONNECT.mode = prev
            virt = sqlvirt.take_last()
            # the state holds no reference to the connection (a cycle would delay closing it; no weak references)
            st = _SqlConn(_sqlite_file(db, bool(uri)))
            st.virtual = virt is not None  # parallel-proof round 3: Level 0's virtual 'now'
            try:
                sqlvirt.set_trace(conn, virt, lambda statement: cap._sql_trace(statement, st))
            except Exception:
                pass
            return conn

        connect.__wrapped__ = real
        self._sqlite_saved = [(sqlite3, "connect", real), (dbapi2, "connect", dbapi2.connect)]
        sqlite3.connect = connect
        dbapi2.connect = connect

    def _sql_database(self, files) -> None:
        files = [f for f in files if not self._ignored(f)]
        if files and self._caller_kind() not in ("import", "infra"):
            ctx = self._cur()
            for p in files:
                self.read(ctx, p, "f")
                self.wrote(ctx, p)

    def _sql_trace(self, statement, st=None) -> None:
        if not self.active or not isinstance(statement, str):
            return
        virtual = st is not None and getattr(st, "virtual", False)
        if not virtual and _SQL_REAL_CLOCK.search(statement):
            self.flag(self._cur(), "rclock", f"sqlite: {statement.strip()[:80]} at {_first_user_site()}")
            if st is not None and _SQL_DDL.match(statement):
                st.own = st.own or "this connection's schema"  # a temporary or uncommitted definition included
        if st is None:
            return
        m = _SQL_ATTACH.match(statement)
        if m:
            f = _sqlite_file(m.group(1)[1:-1].replace("''", "'"), True)
            if f is not None:
                self._sql_database([f])  # review R-017b F2: an attached database is an input too
                st.dbs.append(f)
            return
        if virtual or _SQL_NO_SCHEMA.match(statement):
            return
        why = st.own
        if why is None:
            for f in st.dbs:
                why = self._sql_schema_clock(f)
                if why is not None:
                    break
        if why is not None:
            self.flag(self._cur(), "rclock",
                      f"sqlite: {why} may read the real clock ({statement.strip()[:60]}) at {_first_user_site()}")

    def _sql_schema_clock(self, path: str) -> str | None:
        """What in the schema of database file ``path`` may read the real clock (None: nothing), memoised on the
        file's and its write-ahead log's identity."""
        sig = []
        for f in (path, path + "-wal"):
            try:
                st = os.stat(f)
                sig.append((st.st_ino, st.st_size, st.st_mtime_ns))
            except OSError:
                sig.append(None)
        if sig[0] is None:
            return None  # not created yet: no schema
        sig = tuple(sig)
        memo = self._sql_schema.get(path)
        if memo is not None and memo[0] == sig:
            return memo[1]
        from urllib.parse import quote
        why = None
        prev, _SQL_CONNECT.mode = getattr(_SQL_CONNECT, "mode", 0), 1  # detpy's own: not the test's read
        try:
            con = self._sql_real_connect(f"file:{quote(os.fsencode(path))}?mode=ro", uri=True, timeout=0)
            try:
                for name, sql in con.execute("select name, sql from sqlite_master where sql is not null"):
                    if isinstance(sql, str) and _SQL_REAL_CLOCK.search(sql):
                        why = f"the schema of {self._key(path)} ({name})"
                        break
            finally:
                con.close()
        except Exception as e:
            why = f"the schema of {self._key(path)} (unreadable: {e})"
        finally:
            _SQL_CONNECT.mode = prev
        self._sql_schema[path] = (sig, why)
        return why

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
        # a log is written only by its tracer: one whose tracer is gone is final now, so waiting for it cannot
        # change it. It is not waited for, but the wait is charged to the budget as if it had been (the decisions
        # about the other children stay those of waiting). None: unknown, every log is waited for.
        try:
            alive = _core.tracer_prefixes(fo.logdir + os.sep)
        except Exception:
            alive = None
        alive = None if alive is None else set(alive)
        for sp in fo.spawns:
            self.children += 1
            timeout = max(0.0, min(wait, budget_end - _mono()))
            if alive is None or sp.prefix in alive:
                logs = follow._wait_logs(sp.prefix, timeout)
            else:
                logs = follow._wait_logs(sp.prefix, 0.0)
                if not (logs and all(follow._complete(f) for f in logs)):
                    budget_end -= timeout
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
            res.late = self._changed_after_start(res)
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

    def _changed_after_start(self, res) -> str | None:
        """review R-015b G1: a file the tree read is digested now, at the end of the session. One whose ``ctime``
        (which ``utime`` cannot set back) is not before the tree's first system call may have been changed after
        the tree read it: the digest is then not that of the content the tree ran or read. Files the session wrote
        are left to the writers' rules."""
        if res.t0 is None:
            return None
        t0 = int((res.t0 - _CTIME_SLACK) * 1e9)
        written = {p for op, p in res.ops if op == "w"}
        seen = set()
        for op, p in res.ops:
            if op not in ("r", "x") or p in seen or p in written or p in self.writers:
                continue
            seen.add(p)
            if follow.special(p, res.pids) is not None or self.child_ignored(p):
                continue
            try:
                st = os.stat(p)
            except (OSError, ValueError):
                continue
            if _stat.S_ISREG(st.st_mode) and st.st_ctime_ns >= t0:
                return p
        return None

    def _credit_child(self, ctx: int, sp, res) -> None:
        """The inputs, writes and refusals of one followed process tree, as inputs of context ``ctx``."""
        if res.bad:
            self.flag(ctx, "spawn", f"{sp.detail} [not followed: {res.bad}]")
        if res.late:
            self.flag(ctx, "spawn", f"{sp.detail} [{res.late} changed during the session]")
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
            if op == "a":
                if not self.child_ignored(p):
                    self.read(ctx, p, "a")
                continue
            if op == "x":
                interp = follow.shebang(p)
                if interp:
                    self.child_read(ctx, interp)
            self.child_read(ctx, p, "d" if op == "d" else "f")


    def env_read(self, name: str) -> None:
        if self.active:
            self.env.setdefault(self._cur(), set()).add(name)

    def event(self, source: str, value: str) -> bool:
        """A Level 0 event (``detpy._state.record``) by user code. True when calling again for ``source`` changes
        nothing until the next switch (the Rust event path then skips the call): the source is flagged in a context
        that is not import time."""
        if not self.active:
            return False
        fl = self.flags.setdefault(self._cur(), set())
        if source == "net":
            if "record#" in value:
                fl.add("net-record")
            elif "replay" in value:
                fl.add("net-replay")
            return False
        fl.add(source)
        return not (self.rec is not None and self.rec.import_depth)

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
    if cap is None or not cap.active:
        return
    name = os.fsdecode(key) if isinstance(key, (str, bytes)) else repr(key)
    # a variable the current context already read: recording it again changes nothing, whoever reads it, so the
    # walk over the calling frames is skipped
    rec = cap.rec
    if rec is not None and not rec.import_depth:  # (during an import the context is found by a frame walk)
        seen = cap.env.get(cap.ctx_ix[cap.ctx])
        if seen is not None and name in seen:
            return
    if not _env_caller_is_user():
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
def _code_key(path: str):
    """(stat key, resolved path) at first sight: a link pointed elsewhere later changes the stat key, and the file
    that ran is the one it pointed to then (review R-015b G2)."""
    try:
        r = os.path.realpath(path)
    except (OSError, ValueError):
        r = None
    return _stat_key(path), r


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
            # name, version and RECORD digest read in Rust where the plain reading is certain to match
            # importlib.metadata's (simple header block); else importlib.metadata itself
            fast = _core.dist_identity(path) if type(d) is metadata.PathDistribution and path is not None else None
            if fast is not None:
                name = fast[0]
            else:
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
            elif fast is not None:
                hit = ["dist", f"{name.lower()}=={fast[1]}:{fast[2]}"]
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


def runtime_identity(root: str, memo_path: str | None = None) -> tuple[str, dict, list]:
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
        self.phases: dict[str, float] = {}  # seconds per phase of the end-of-session recording

    # -- setup ----------------------------------------------------------------
    def configure(self, config) -> None:
        self.config = config
        self.root = os.path.realpath(str(config.rootpath))
        self.config_digest, self.config_info = config_identity(config)
        os.makedirs(self.dir, exist_ok=True)
        self.runtime_digest, self.runtime_info, editable = runtime_identity(
            self.root, os.path.join(self.dir, "distributions.json"))
        self.runtime_digest, pth, spath = _core.runtime_with_paths(
            self.runtime_digest, self.root, list(_sites._site_dirs), [e for e in sys.path if isinstance(e, str)])
        self.runtime_info = {**self.runtime_info, "pth": pth, "sys_path": spath}
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
        # review R-009b R2: a path this session's code (import time, collection) created with an exclusive create
        # that found it missing: the recorded "missing" is compared with what that code saw, not with the file it
        # then created (a NamedTemporaryFile held in a module global); see the stale check in _record_all
        self.excl_seeded = {}
        for p, present in cap.excl_pre.items():
            if not present and p in cap.writers:
                store.observed(cap._key(p), "missing")
                self.excl_seeded[p] = set(cap.writers[p])
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
        # review R-023b N8: a reused writer whose output a running reader consumes is not reused
        for w, r in store.edges():
            if r in self.items and w in self.items and w in self.hits and r not in self.hits:
                del self.hits[w]
                self.misses[w] = f"reader: its output is read by {r}, which runs in this session"

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

    def _recheck_hit(self, nid) -> None:
        """review R-023 F2 (ported here in parallel-proof round 3): a reuse decided before a writer of this session
        wrote the test's input (its own or carried) is withdrawn at the test's turn."""
        cap = self.cap
        if not cap.writers:
            return
        e = json.loads(self.store.entry(nid))
        fixtures = set(e.get("fixtures") or ())

        def foreign(w):
            return (w.startswith("t|") and w[2:] != nid) or (w.startswith("f|") and w not in fixtures)

        names = cap.ctx_names
        for key, dep in e.get("data") or ():
            ab = key if key.startswith("/") else cap.root_sep + key
            hit = [names[c] for c in sorted(cap.writers.get(ab, ())) if c < len(names) and foreign(names[c])]
            if not hit and dep.startswith("d:"):
                for p, cs in cap.writers.items():
                    if os.path.dirname(p) == ab:
                        hit = [names[c] for c in sorted(cs) if c < len(names) and foreign(names[c])]
                        if hit:
                            break
            if hit:
                del self.hits[nid]
                self.misses[nid] = f"written: {key} was written by {hit[0]} earlier in this session"
                return

    def _wrap_protocol(self, item, nextitem):  # generator driven by _ProtocolWrapper
        nid = item.nodeid
        if nid in self.hits:
            self._recheck_hit(nid)
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
        if self.cap.rec is None:
            return
        t = _perf()
        self.cap.collect_children()
        self.phases["children"] = _perf() - t
        self._record_captured()

    def _record_captured(self) -> None:
        """Record every test that ran from the capture: the per-test assembly of inputs and the reasons a test is
        not cached are computed in Rust (``detpy_core::record``) from one plan of plain data."""
        store, ph = self.store, self.phases
        t = _perf()
        plan = json.dumps(self._plan())
        ph["plan"] = _perf() - t - ph.get("facts", 0.0)
        t = _perf()
        recorded, not_cached, stale, g_ctx_all = store.record_session(plan)
        ph["assemble"] = _perf() - t
        for nid, path in stale:
            self.stale_hits[nid] = path
        for nid, why, ctxs in not_cached:
            if ctxs:
                self.not_cached_where[nid] = self._where(why, ctxs)
            self.not_cached[nid] = why
        self.recorded += recorded
        t = _perf()
        store.save()
        ph["save"] = _perf() - t

    def _plan(self) -> dict:
        """The session's capture as plain data (``detpy_core::record::Plan``)."""
        cap, store = self.cap, self.store
        fcache: dict[str, int | None] = {}
        rels = cap.fnames
        # file facts for every executed or loaded repository file (new versions parsed in parallel)
        needed = set(rels) | {r for r, _ in cap.loaded_order} | cap.preloaded
        t = _perf()
        self._prefetch_facts(sorted(needed), fcache)
        for rel in needed:
            self._facts_index(rel, fcache)
        self.phases["facts"] = _perf() - t
        per, imp = cap.rec.fold(len(cap.ctx_names), cap.segs, store.unit_ranges([fcache.get(r) for r in rels]))
        tests, test_modules = [], {}
        for nid in self.items:
            tf = _ctx_file(nid)
            if tf not in test_modules:
                test_modules[tf] = _module_of(os.path.join(self.root, tf))[0]
        for nid in self.ran:
            item = self.items.get(nid)
            if item is None:
                continue
            p = self.parts.get(nid, {})
            whole = type(item).__name__ == "DoctestItem" or not hasattr(item, "obj")
            if whole:
                own = _ctx_file(nid)
                if fcache.get(own) is None:
                    self._facts_index(own, fcache)
            tests.append({"nodeid": nid, "outcome": _final(p), "report": {w: p[w] for w in ("setup", "call") if w in p},
                          "fingerprint": self.fingerprints.get(nid, ""), "duration": self.dur.get(nid, 0.0),
                          "index": self.test_index.get(nid, 0), "fixtures": self.fixture_ctx.get(nid, []),
                          "whole": whole})
        cfg = _state.STATE.config
        cassette = None
        if cfg.cassette_path:
            d = _core.file_digest(cfg.cassette_path)
            cassette = (cap._key(os.path.realpath(cfg.cassette_path)), f"f:{d}" if d else "missing")
        names = cap.ctx_names
        return {
            "ctx_names": names, "import_ctx": cap.import_ctx, "fnames": rels,
            "file_ix": {r: ix for r, ix in fcache.items() if ix is not None},
            "per": per, "imp": imp,
            "data": {c: list(d.items()) for c, d in cap.data.items()},
            "env": {c: [n for n in e if _encodable(n)] for c, e in cap.env.items()},
            "flags": {c: sorted(f) for c, f in cap.flags.items()} | {  # R-017 H3 (ported fix): refuse, not drop
                c: sorted(cap.flags.get(c, set()) | {"badenv"}) for c, e in cap.env.items()
                if not all(_encodable(n) for n in e)},
            "writers": {p: sorted(w) for p, w in cap.writers.items() if _encodable(p)},
            "session_written": {cap._key(p): sorted(names[c] for c in w) for p, w in cap.writers.items()
                                if _encodable(p)},
            "loaded_order": cap.loaded_order, "preloaded": sorted(cap.preloaded), "needed": sorted(needed),
            "stale_skip": sorted(cap._key(p) for p, w in getattr(self, "excl_seeded", {}).items()
                                 if cap.writers.get(p) == w),
            "changed": cap.changed_code(),
            "test_modules": test_modules, "tests": tests, "hits": list(self.hits),
            "root_sep": cap.root_sep, "control_urandom": bool(cfg.control_urandom),
            "time_controlled": "time" in cfg.controls, "epoch": self.epoch, "cassette": cassette,
            "env0": dict(cap.env0), "config": self.config_digest, "runtime": self.runtime_digest, "run": self.run_id,
            # review R-020 prefix rule: contexts in the order of their first activation
            "first_order": list(dict.fromkeys(c for _t, c in cap.timeline)),
        }

    def _where(self, why: str, ctxs) -> str:
        """``why`` with the first occurrence of its cause: what (command, address...) and in which context."""
        why = why.removeprefix("after an earlier test or fixture of this process: ")  # carried (prefix rule)
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
            "phase_seconds": {k: round(v, 3) for k, v in self.phases.items()},
            "config": self.config_digest,
            "runtime": self.runtime_digest,
            "epoch_ns": self.epoch,
            "verify_mismatches": [v for v in self.verify_results if not v["same"]],
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


# statements that evaluate no column default, trigger or view
_SQL_NO_SCHEMA = _re.compile(
    r"\s*(begin|commit|end|rollback|savepoint|release|pragma|attach|detach|drop|vacuum|analyze|reindex)\b", _re.I)
_SQL_DDL = _re.compile(r"\s*(create|alter)\b", _re.I)
_SQL_ATTACH = _re.compile(r"\s*attach\s+(?:database\s+)?('(?:[^']|'')*')", _re.I)


class _SqlConn:
    """What detpy knows of one sqlite connection: its database files (main, attached) and whether a definition it
    ran reads the real clock."""

    __slots__ = ("dbs", "own", "virtual")

    def __init__(self, main: str | None):
        self.dbs = [main] if main is not None else []
        self.own: str | None = None
        self.virtual = False


_SQL_CONNECT = __import__("threading").local()  # .mode: 0 unknown, 1 detpy's own, 2 plain, 3 URI (review R-017b F2)


def _sqlite_file(db, uri: bool) -> str | None:
    """The absolute path of the database file sqlite opens for ``db`` (None: in memory or not a file name)."""
    if not isinstance(db, (str, bytes, os.PathLike)):
        return None
    try:
        s = os.fsdecode(db)
    except (TypeError, ValueError):
        return None
    if uri and s.startswith("file:"):
        from urllib.parse import unquote_to_bytes
        s, _, query = s[5:].partition("?")
        if "mode=memory" in query.split("#")[0].split("&"):
            return None
        if s.startswith("//"):
            host, _, rest = s[2:].partition("/")
            s = "/" + rest if host in ("", "localhost") else ""
        s = s.split("#")[0]
        if "%" in s:  # review R-017b F2: bytes-exact, as sqlite decodes it (up to a decoded NUL)
            try:
                s = os.fsdecode(unquote_to_bytes(os.fsencode(s)).split(b"\0")[0])
            except UnicodeEncodeError:
                return None
    if s in ("", ":memory:"):
        return None
    try:
        return os.path.abspath(s)
    except (OSError, ValueError):
        return None


def _hosts_file_answers(name: str) -> bool:
    """review R-023b N2: nsswitch names `files` first for hosts and /etc/hosts lists the name."""
    n = name.rstrip(".").lower()
    try:
        ns = open("/etc/nsswitch.conf", "rb").read().decode("latin-1")
        hosts = open("/etc/hosts", "rb").read().decode("latin-1")
    except OSError:
        return False
    if not any(line.split("#")[0].split()[:2] == ["hosts:", "files"] for line in ns.splitlines()):
        return False
    return any(n in [w.lower() for w in line.split("#")[0].split()[1:]] for line in hosts.splitlines())


def _loopback_name(host: str) -> bool:
    """RFC 6761 loopback names (review R-023)."""
    n = host.split("%", 1)[0]
    n = (n[:-1] if n.endswith(".") else n).lower()
    return n in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback") or n.endswith(".localhost")


def _numeric_host(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


def _proc_alias(p):
    if p.startswith("/dev/fd/"):
        ok = True
    elif p.startswith("/proc/"):
        rest = p[len("/proc/"):]
        if "/" not in rest:
            return None
        after = rest.split("/", 1)[1]
        ok = after.startswith(("root/", "cwd/", "fd/")) or after in ("root", "cwd")
    else:
        return None
    if not ok:
        return None
    try:
        r = os.path.realpath(p, strict=True)
    except OSError:
        return None
    if r.startswith(("/proc/", "/sys/", "/dev/")) or not r.startswith("/"):
        return None
    return r


def _process_state(p):
    if not p.startswith("/proc/"):
        return False
    rest = p[len("/proc/"):]
    if "/" not in rest:
        return False
    who, after = rest.split("/", 1)
    if not (who in ("self", "thread-self") or who.isdigit()):
        return False
    return after.split("/", 1)[0] in ("fd", "fdinfo", "task", "stat", "statm", "io")


_FLAG_OF = {"native code from the repository": "native", "reads this process's state under /proc (descriptors, status counters, threads)": "pstate", "real clock read outside the virtual clock": "rclock", "subprocess": "spawn", "network connection": "connect", "host name lookup": "dns",
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
        ip = ipaddress.ip_address("127.0.0.1" if _loopback_name(str(host)) else str(host).split("%", 1)[0])
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
                    # review R-023b N3: a non-wildcard listener must hold the very address connected to
                    if set(laddr) <= {"0"} or (_loopback_hex(laddr) and laddr == _proc_net_hex(ip)):
                        return True
        except OSError:
            continue
    return False


def _proc_net_hex(ip) -> str:
    """The address as /proc/net/tcp{,6} writes it: each 32-bit word of the packed address in host order, hex."""
    import struct

    b = ip.packed
    return "".join(f"{struct.unpack('=I', b[i:i + 4])[0]:08X}" for i in range(0, len(b), 4))


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
    if "badenv" in flags:
        return "reads an environment variable whose name is not valid UTF-8"
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
    if "pstate" in flags:
        return "reads this process's state under /proc (descriptors, status counters, threads)"
    if "native" in flags:
        return "native code from the repository"
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
