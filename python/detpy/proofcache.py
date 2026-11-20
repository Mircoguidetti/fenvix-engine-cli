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
import sys
import time
from types import FunctionType

import pytest

from . import __version__, _codefacts, _core, _sites, _state, follow

_sql_connect_mode = _core.sql_connect_mode

# bound once: a test may remove sys._getframe (attrs' test_missing_sys_getframe) while detpy's hooks run
_getframe = sys._getframe
# real clocks, bound before Level 0 virtualises the time module
_perf = time.perf_counter
_now = time.time
_mon = getattr(sys, "monitoring", None)
AVAILABLE = _mon is not None

# context names: "" startup, "s" between tests, "c|<file>" collection of a file, "f|<scope>|<baseid>|<name>" setup
# of a wider-scoped fixture, "t|<nodeid>" a test, "i" / "i|<file>" import time. The capture's rules (skipped
# paths, write events, spawn events, ...) are in crates/detpy-py/src/capture.rs.
_AUDIT_EVENTS = ("exec", "open", "ctypes.dlopen", "sqlite3.connect", "os.listdir", "os.scandir", "socket.connect", "socket.sendto", "socket.sendmsg",
                 "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "subprocess.Popen", "os.posix_spawn",
                 "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn", "os.remove", "os.rename", "os.mkdir",
                 "os.rmdir", "os.truncate", "shutil.rmtree", "shutil.copyfile", "shutil.move", "os.symlink",
                 "os.link")
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
    # pytest-xdist's options (set differently in its controller, its workers and a serial session) and detpy's
    # plan replay: under --det the plan is not an input of a test's result (docs/PARALLEL-PROOF-DESIGN.md 2.5)
    "loadgroup", "looponfail", "distload", "maxprocesses", "maxworkerrestart", "loadscopereorder", "px",
    "testrunuid", "rsyncdir", "rsyncignore", "maxschedchunk", "det_plan", "det_plan_worker",
}


# detpy's own bookkeeping variables (re-exec, bytecode cache): set by detpy itself, never a test input
_DETPY_OWN_ENV = frozenset({"DETPY_REEXEC", "DETPY_PRECOMPILE_S", "DETPY_PYC_CACHE", "DETPY_BLOCKED_PLUGINS",
                            "DETPY_XDIST_ENV"})
_DETPY_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep


def _ctx_file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


# Line capture granularity (experiment, DETPY_CACHE_LINES): "line" (default) arms every code object with LINE;
# "code" arms plain functions (not module or class bodies, not generators or coroutines) with PY_START only and
# records one location per start (the function's last line), see REPORT-2. The entry line and that line are read
# from the bytecode in Rust (CaptureCore.arm): the opcodes it needs are passed in.
_CODE_LEVEL = os.environ.get("DETPY_CACHE_LINES", "line") == "code"
import opcode as _opcode  # noqa: E402

_RESUME = _opcode.opmap.get("RESUME", -1)
_PRELUDE = {_opcode.opmap[n] for n in ("MAKE_CELL", "COPY_FREE_VARS", "RETURN_GENERATOR", "POP_TOP")
            if n in _opcode.opmap}


# existence and kind checks that ask os.stat (their answer is the kind, not the size): genericpath, posixpath, pathlib,
# glob, shutil
_KIND_FUNCS = frozenset({"exists", "lexists", "isfile", "isdir", "islink", "ismount", "isjunction", "is_file", "is_dir",
                         "is_symlink", "is_mount", "is_junction", "is_socket", "is_fifo", "is_block_device",
                         "is_char_device", "samefile", "_lexists", "_isdir", "which", "_access_check", "isdevdrive"})
_STDLIB_PATH_MODULES = frozenset({"genericpath", "posixpath", "ntpath", "pathlib", "pathlib._local",
                                  "pathlib._abc", "glob", "shutil", "os"})


def _kind_check_caller() -> bool:
    """True when os.stat was called by an existence or kind check of the standard library."""
    f = _getframe(2)
    while f is not None:
        mod = f.f_globals.get("__name__", "")
        if mod not in _STDLIB_PATH_MODULES:
            return False
        if f.f_code.co_name in _KIND_FUNCS:
            return True
        f = f.f_back
    return False


def _user_stat_caller() -> bool:
    """True when os.stat / os.lstat was asked by repository or library code for its result (not by a standard
    library helper: shutil.copystat copies times, it does not decide on them); Path.stat() counts as its caller's."""
    f = _getframe(2)
    while f is not None:
        mod = f.f_globals.get("__name__", "")
        if mod in ("pathlib", "pathlib._local", "pathlib._abc") and f.f_code.co_name in ("stat", "lstat"):
            f = f.f_back
            continue
        fn = f.f_code.co_filename
        if fn.startswith(_DETPY_DIR):
            return False  # detpy's own stat (its digests, its reference implementations): never the test's
        return not (mod in _STDLIB_PATH_MODULES or fn.startswith(_STDLIB_DIR) or fn.startswith("<frozen"))
    return False


# standard-library helpers that return a time from os.stat themselves: their caller reads a time
_TIME_HELPERS = frozenset({"getmtime", "getctime", "getatime"})


def _time_helper_caller() -> str | None:
    """The name of os.path.getmtime/getctime/getatime when one of them called os.stat (the time goes to its caller)."""
    f = _getframe(2)
    if (f is not None and f.f_code.co_name in _TIME_HELPERS
            and f.f_globals.get("__name__", "") in ("genericpath", "posixpath", "ntpath")):
        return f.f_code.co_name
    return None


_STDLIB_DIR = os.path.dirname(os.__file__) + os.sep
# st_atime, st_mtime, st_ctime (indices 7, 8, 9) and their _ns, birthtime variants
_TIME_FIELDS = ("st_atime", "st_mtime", "st_ctime", "st_birthtime")


class _TimedStat:
    """An ``os.stat_result`` given to user code (review R-032b F2, round 4): reading ``st_mtime``/``st_ctime`` (their
    ``_ns`` variants, indices 8 and 9) makes the file's modification and change times an input ("y:", keyed);
    reading ``st_atime`` or ``st_birthtime`` (index 7; unpacking, equality, hashing give every field) refuses the
    test ("mtime": the access time changes when the file is read). Everything else is the result's own."""

    __slots__ = ("_r", "_cap", "_path")

    def __init__(self, r, cap, path):
        self._r = r
        self._cap = cap
        self._path = path

    def _p(self):
        return os.fsdecode(os.fspath(self._path)) if not isinstance(self._path, int) else str(self._path)

    def _timed(self):
        try:
            self._cap.flag(self._cap._cur(), "mtime", self._p())
        except Exception:
            pass

    def _keyed(self):
        if isinstance(self._path, int):
            return self._timed()
        try:
            self._cap.time_check(self._path)
        except Exception:
            self._timed()

    def __getattr__(self, name):
        if name.startswith(("st_mtime", "st_ctime")):
            self._keyed()
        elif name.startswith(("st_atime", "st_birthtime")):
            self._timed()
        return getattr(self._r, name)

    def __getitem__(self, i):
        idx = range(len(self._r))[i]
        idx = list(idx) if isinstance(idx, range) else [idx]
        if 7 in idx:
            self._timed()
        elif 8 in idx or 9 in idx:
            self._keyed()
        return self._r[i]

    def __iter__(self):
        self._timed()  # unpacking gives every field, the access time among them
        return iter(self._r)

    def __len__(self):
        return len(self._r)

    def __eq__(self, other):
        self._timed()
        return self._r == (other._r if isinstance(other, _TimedStat) else other)

    def __hash__(self):
        self._timed()
        return hash(self._r)

    def __repr__(self):
        return repr(self._r)

    def __reduce__(self):
        self._timed()
        return self._r.__reduce__()


class _ScandirEntry:
    """An ``os.DirEntry`` of user code's ``os.scandir`` whose ``stat()`` and kind checks are inputs (review R-032b F2)."""

    __slots__ = ("_e", "_cap")

    def __init__(self, e, cap):
        self._e = e
        self._cap = cap

    def _check(self, sized, follow=True):
        cap = self._cap
        if cap._in_stat:
            return
        cap._in_stat = True
        try:
            cap.stat_check(self._e.path, not follow, sized and follow)
        except Exception:
            pass
        finally:
            cap._in_stat = False

    def stat(self, *, follow_symlinks=True):
        self._check(True, follow_symlinks)
        return _TimedStat(self._e.stat(follow_symlinks=follow_symlinks), self._cap, self._e.path)

    def is_file(self, *, follow_symlinks=True):
        self._check(False, follow_symlinks)
        return self._e.is_file(follow_symlinks=follow_symlinks)

    def is_dir(self, *, follow_symlinks=True):
        self._check(False, follow_symlinks)
        return self._e.is_dir(follow_symlinks=follow_symlinks)

    def is_symlink(self):
        self._check(False, False)
        return self._e.is_symlink()

    def __fspath__(self):
        return self._e.__fspath__()

    def __getattr__(self, name):
        return getattr(self._e, name)

    def __repr__(self):
        return repr(self._e)


class _ScandirIter:
    __slots__ = ("_it", "_cap")

    def __init__(self, it, cap):
        self._it = it
        self._cap = cap

    def __iter__(self):
        return self

    def __next__(self):
        return _ScandirEntry(next(self._it), self._cap)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._it.close()
        return False

    def close(self):
        self._it.close()


# ---------------------------------------------------------------------------
class Capture(_core.CaptureCore):
    """Records, per context, executed code, data reads, environment reads and events.

    The capture itself is Rust (``_core.CaptureCore``, ``crates/detpy-py/src/capture.rs``): the audit hook, reads
    and writes, contexts and switches, environment reads, Level 0 events, the arming of code objects. This class
    keeps what is interface: ``sys.monitoring`` and audit-hook registration, the ``sqlite3.connect`` patch and the
    child follower's crediting. The Python original is ``tests/rust_hotpaths_ref/_ref_proofcache.py``.
    """

    def __new__(cls, root: str, env0: dict, hot: int = 16):
        return super().__new__(cls, os.path.realpath(root), env0, hot, _DETPY_DIR, _RESUME, sorted(_PRELUDE),
                               _CODE_LEVEL, (os.O_RDONLY, os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_EXCL, os.O_TRUNC,
                                             _O_TMPFILE))

    def __init__(self, root: str, env0: dict, hot: int = 16):
        self.hot = hot
        self.follower: follow.Follower | None = None
        self._sqlite_saved: list = []

    # -- start and stop -----------------------------------------------------------------
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
        lst = _state._event_listener  # the object the Rust event path calls (a bound method is made per access)
        _core.l0_listener_memo(lst if lst is not None and lst == self.event else None, self.rec)
        _mon.register_callback(self.tool, _mon.events.LINE, self.rec.line)
        _mon.register_callback(self.tool, _mon.events.PY_START, self.rec.start)
        _mon.register_callback(self.tool, _mon.events.PY_RETURN, self.rec.ret)
        self.active = True
        _core.set_audit_hook(self.audit, _AUDIT_EVENTS)
        self._patch_sqlite()
        self._patch_stat()
        self._patch_lookups()
        self.set_installed(self._installed)
        self.scan_maps()  # the libraries mapped before the start: inputs of every test (Rust, review R-019c E-8)
        # code that exists before the start: modules already loaded become whole-content inputs
        pre = False
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f and self.note_preloaded(f):
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

    # -- absent inputs: existence checks and module lookups ------------------------------
    def _patch_stat(self) -> None:
        """``os.path.exists``, ``isfile``, ``isdir``, ``Path.exists``, ``shutil.which`` and ``glob`` on a literal path
        ask ``os.stat``, ``os.lstat`` or ``os.access``, which raise no audit event. The answer is an input: the
        path's kind is recorded (``CaptureCore.stat_check``, Rust), so a file that appears later invalidates the
        test. ``os.lstat`` records the kind without following a final symlink (LIMITS K4). References bound before
        the session (``from os import stat`` in a plugin loaded at startup) are rebound to the wrapper too (LIMITS
        K3); the import system's own ``posix`` module is left alone (the module-lookup finder records its probes)."""
        cap = self
        self._stat_saved = []
        self._in_stat = False

        def wrap(name):
            orig = getattr(os, name, None)
            if orig is None:
                return

            link = name == "lstat"

            def checked(path, *args, **kwargs):
                timed = False
                if not cap._in_stat and not isinstance(path, int) and not kwargs.get("dir_fd"):
                    cap._in_stat = True
                    try:
                        nolink = link or kwargs.get("follow_symlinks") is False
                        # review R-032b F2: os.stat asked for its own sake (st_size: Path.stat(), os.stat(p)) is keyed
                        # by the size; asked by an existence or kind check (exists, isfile, is_dir, glob) by the kind
                        sized = name == "stat" and not nolink and not _kind_check_caller()
                        cap.stat_check(path, nolink, sized)
                        # pytest's assertion rewriting compares source mtimes: infrastructure, not the test's
                        timed = name in ("stat", "lstat") and _user_stat_caller() and cap._caller_kind() == "user"
                        helper = _time_helper_caller()
                        if helper and cap._caller_kind() == "user":
                            # os.path.getmtime & co.: the time is read inside the helper, for its caller
                            if helper == "getatime":
                                cap.flag(cap._cur(), "mtime", os.fsdecode(os.fspath(path)))
                            else:
                                cap.time_check(path)
                    except Exception:
                        pass
                    finally:
                        cap._in_stat = False
                    if timed:
                        return _TimedStat(orig(path, *args, **kwargs), cap, path)
                return orig(path, *args, **kwargs)

            checked.__name__ = orig.__name__
            checked.__doc__ = orig.__doc__
            checked.__wrapped__ = orig
            self._stat_saved.append((os, name, orig))
            setattr(os, name, checked)
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

        # review R-032b F2: os.scandir's entries answer stat() without os.stat: user code iterating os.scandir gets
        # entries whose stat() is keyed like os.stat (by size), whose is_file()/is_dir() like a kind check
        orig_scandir = os.scandir

        def scandir(path=".", *args, **kwargs):
            it = orig_scandir(path, *args, **kwargs)
            if isinstance(path, int) or cap._in_stat:
                return it
            try:
                if cap._caller_kind() != "user":
                    return it
            except Exception:
                return it
            return _ScandirIter(it, cap)

        scandir.__name__ = "scandir"
        scandir.__wrapped__ = orig_scandir
        self._stat_saved.append((os, "scandir", orig_scandir))
        os.scandir = scandir

    def _installed(self, p: str) -> bool:
        """Whether a distribution's RECORD lists ``p`` (an installed wheel's library in an environment that lives
        under the project root): a dependency, not the repository's native code (LIMITS K1). The file index (Rust:
        distfiles.rs) is built on first use, with the capture inactive."""
        idx = getattr(self, "_dist_index", None)
        if idx is None:
            from . import distid

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

    def _patch_lookups(self) -> None:
        """A module the import system did *not* find is an input too (``try: import optional``, a namespace package
        without ``__init__.py``, a module a new file earlier on ``sys.path`` would shadow). A finder in front of
        ``sys.meta_path`` hands every lookup to ``CaptureCore.lookup`` (Rust: the probed paths and their kinds). It
        finds nothing itself."""
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

    # -- sqlite ----------------------------------------------------------------------------
    def _patch_sqlite(self) -> None:
        """review R-009 F4 / R-009b R1: every connection made through sqlite3.connect traces its statements with a
        ``_core.SqlTrace`` (crates/detpy-py/src/sqlcap.rs): a statement, or a schema it evaluates, that may read the
        real clock makes its context uncacheable. (A trace callback the test sets itself replaces this one.)"""
        try:
            import sqlite3
            import sqlite3.dbapi2 as dbapi2
        except ImportError:
            return
        real = self._sql_real_connect = sqlite3.connect
        cap = self

        def connect(*args, **kwargs):
            # review R-017b F2: the audit event does not say whether ``database`` is a URI; the capture's audit arm
            # reads it here (crates/detpy-py/src/sqlcap.rs, connect modes)
            uri = kwargs.get("uri", args[7] if len(args) > 7 else False)
            from . import sqlvirt

            prev = _sql_connect_mode(3 if uri else 2)
            sqlvirt.take_last()
            try:
                conn = real(*args, **kwargs)
            finally:
                _sql_connect_mode(prev)
            virt = sqlvirt.take_last()
            # a connection Level 0 virtualised (detpy/sqlvirt.py): its 'now' is the virtual clock
            tr = _core.SqlTrace(cap, args[0] if args else kwargs.get("database"), uri, virt is not None)
            try:
                sqlvirt.set_trace(conn, virt, tr)
            except Exception:
                pass
            return conn

        connect.__wrapped__ = real
        self._sqlite_saved = [(sqlite3, "connect", real), (dbapi2, "connect", dbapi2.connect)]
        sqlite3.connect = connect
        dbapi2.connect = connect

    def _sql_schema_read(self, path: str) -> str | None:
        """What in the schema of database file ``path`` may read the real clock (None: nothing): the read-only query
        through the real connect, on a miss of the trace's memo."""
        from urllib.parse import quote
        prev = _sql_connect_mode(1)  # detpy's own connection: the audit hook does not take it as the test's read
        try:
            # a URI of the path's bytes (a name that is not valid UTF-8 included)
            con = self._sql_real_connect(f"file:{quote(os.fsencode(path))}?mode=ro", uri=True, timeout=0)
            try:
                for name, sql in con.execute("select name, sql from sqlite_master where sql is not null"):
                    if isinstance(sql, str) and _core.sql_real_clock(sql):
                        return f"the schema of {self._key(path)} ({name})"
            finally:
                con.close()
        except Exception as e:
            return f"the schema of {self._key(path)} (unreadable: {e})"
        finally:
            _sql_connect_mode(prev)
        return None

    # child_ignored, child_read, collect_children, _credit_child: Rust (CaptureCore)


# ---------------------------------------------------------------------------
# environment reads: the recorded os.environ calls _note_env (Rust: CaptureCore.note_env of the capture set by
# _core.cap_set_env_capture)
_ENV_PATCHED = False
_note_env = _core.cap_note_env


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
# identities: Rust (crates/detpy-py/src/identity.rs). Python keeps importlib.metadata's discovery (its finders are
# Python's rules) and its reading of a distribution Rust cannot read. Original: tests/rust_hotpaths_ref/_ref_identity.py
def _dist_name(d) -> str:
    return (d.metadata.get("Name") or "?") if d.metadata is not None else "?"


def _dist_part(d, name: str) -> str:
    try:
        rec = d.read_text("RECORD") or ""
    except Exception:
        rec = ""
    return f"{name.lower()}=={d.version}:{_core.digest(rec.encode())}"


def _discovery() -> tuple:
    from importlib import metadata

    return metadata.distributions(), metadata.PathDistribution, _dist_name, _dist_part


def _dist_infos(root: str, memo_path: str | None = None):
    """(runtime digest part for installed distributions, dist-info dirs of editable installs of the project).

    Each distribution's result is memoised in ``memo_path`` under the size, mtime, ctime and inode of its metadata
    files (an installer rewrites them, which changes the ctime), so an unchanged environment is not read again.
    """
    return _core.dist_infos(root, memo_path, *_discovery())


def runtime_identity(root: str, memo_path: str | None = None, per_dist: bool = False) -> tuple[str, dict, list]:
    import sysconfig

    state = (sys.version, sys.implementation.cache_tag, sys.executable, sysconfig.get_config_var("LIBDIR"),
             sysconfig.get_config_var("LDLIBRARY"), platform.system(), platform.machine(), platform.libc_ver(),
             os.__file__)
    digest, info, editable = _core.runtime_identity(root, memo_path, _discovery(), state)
    if per_dist:
        # --det-cache-dists: each test depends on the distributions it used (distid), not on all of them
        info = {**info, "distributions": "per-test", "n_distributions": None}
        digest = _core.digest(json.dumps(info, sort_keys=True, default=str).encode())
    return digest, info, editable


def tz_locale_identity() -> dict:
    """Time zone and locale as C sees them: the variables, /etc/localtime's content and the zone file TZ names."""
    return _core.tz_locale_identity(os.environ)  # os.environ._data: no recorded-environ event


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
    """pytest hooks of ``--det-cache``. The session's bookkeeping (decisions, reports, the record plan, the reasons
    and the summary) is Rust (``_core.CacheSession``, ``crates/detpy-py/src/session.rs``); this class hands it
    pytest's objects."""

    def __init__(self, cap: Capture, cache_dir: str, verify: float, receipts: str | None):
        self.cap = cap
        self.dir = os.path.abspath(cache_dir)
        self.verify = verify
        self.max_age_s: float | None = None
        self.receipts_path = receipts or os.path.join(self.dir, "receipts.jsonl")
        # shared store (P4, --det-cache-shared): pull before the decision, push after the record (or the merge)
        self.shared: str | None = None
        self.shared_stats: dict | None = None
        self.store = None
        self.config = None
        self.root = cap.root
        self.config_digest = ""
        self.runtime_digest = ""
        self.runtime_info: dict = {}
        self.epoch = 0
        self.items: dict[str, object] = {}
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime(_now()))}-{os.getpid()}"
        self.sess = _core.CacheSession(self.run_id, self.receipts_path)
        # pytest-xdist under --det: "controller" (decides, reports hits, merges the shards), "worker" (runs what the
        # plan sends, records a shard), "serial"
        self.role = "serial"
        self.worker = None
        self.shard_path = None
        self.merge_result: dict | None = None
        # --det-isolate (isolate.py): tests run in forked children, each records a one-test shard; this process
        # merges them (serial) or hands them to the controller (worker)
        self.isolate = False
        self.iso_child = False
        self.iso_shards: list[str] = []
        self.iso_forked: set[str] = set()
        self.iso_summaries: list = []
        self.iso_new_facts: list = []
        self.iso_warm = False

    # -- setup ----------------------------------------------------------------
    def configure(self, config) -> None:
        self.config = config
        self.root = os.path.realpath(str(config.rootpath))
        self.config_digest, self.config_info = config_identity(config)
        os.makedirs(self.dir, exist_ok=True)
        self.runtime_digest, self.runtime_info, editable = runtime_identity(
            self.root, os.path.join(self.dir, "distributions.json"), per_dist=getattr(self.cap, "dists", None) is not None)
        # sys.path and the .pth files of the site directories (Rust; review R-019c E-1/E-9)
        self.runtime_digest, pth, spath = _core.runtime_with_paths(
            self.runtime_digest, self.root, list(_sites._site_dirs), [e for e in sys.path if isinstance(e, str)])
        self.runtime_info = {**self.runtime_info, "pth": pth, "sys_path": spath}
        cap = self.cap
        cap.dist_info_ok = tuple(editable)
        cap.stdlib_dirs = tuple(d + os.sep for d in _sites._stdlib_dirs)
        cap.site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
        if getattr(cap, "dists", None) is not None:
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
        self.sess.configure(self.config_digest, self.runtime_digest, self.epoch)

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
        if getattr(self.cap, "dists", None) is not None:
            self.cap.dists.scan(-1)
        if self.role == "worker":
            # the controller decided; this worker runs (and records) every test the plan sends it
            self.items = {item.nodeid: item for item in session.items}
            self.sess.set_test_index(list(self.items))
            return
        t0 = _perf()
        try:
            self._decide(session.items)
        finally:
            self.sess.t_check = _perf() - t0

    def _decide(self, items) -> None:
        store, cap = self.store, self.cap
        nids = [item.nodeid for item in items]
        self._shared_fetch(nids)
        changed = list(store.changed_code_files())
        for (path, content), f in zip(changed, self._read_facts([os.path.join(self.root, p) for p, _ in changed],
                                                                 [c for _, c in changed])):
            if f is not None:
                store.set_fresh(path, content, *f)
        self._shared_adopt()
        self.sess.seed_exclusive(store, cap)  # review R-009b R2
        self.items = dict(zip(nids, items))
        # the checks, the expiry (review R-009 F4: an entry older than --det-cache-max-age is not reused), the
        # receipts and the verification draw (Python's Mersenne Twister, seeded per run) are Rust
        rng = random.Random(f"detpy-cache-verify:{self.run_id}")
        self.sess.decide(store, nids, self.max_age_s, _now(), _run_time, self.verify, rng.random)
        self._demote_writers_of_running_readers(nids)

    # -- pytest-xdist under --det: the controller --------------------------------------------------------------
    def decide_controller(self, nids: list) -> set:
        """The reuse decision of every collected test, once, in the controller (before the plan). The environment
        a worker of this run sees, the deferred check of ``PYTEST_XDIST_WORKER`` (compared with this run's plan in
        ``check_workers``) and the verification draw (seeded by ``derive_seed`` over the seed, the order and the
        configuration: two runs on the same inputs verify the same tests) are Rust. Returns the reused ids."""
        from . import plugin as _plugin

        t0 = _perf()
        try:
            ctl = _plugin.S.controller
            env0 = ctl.spawn_env if ctl is not None and ctl.spawn_env is not None else self.cap.env0
            self.store.begin_controller(self.config_digest, self.runtime_digest, self.epoch, dict(env0),
                                        len(self.config.getoption("tx") or ()),
                                        ctl.testrunuid if ctl is not None else None)
            store = self.store
            self._shared_fetch(list(nids))
            changed = list(store.changed_code_files())
            for (path, content), f in zip(changed, self._read_facts([os.path.join(self.root, p) for p, _ in changed],
                                                                     [c for _, c in changed])):
                if f is not None:
                    store.set_fresh(path, content, *f)
            self._shared_adopt()
            self.sess.seed_exclusive(store, self.cap)
            seed = _core.CacheSession.controller_verify_seed(_state.STATE.config.seed, list(nids), self.config_digest)
            self.sess.decide(store, list(nids), self.max_age_s, _now(), _run_time, self.verify, seed)
            self._demote_writers_of_running_readers(list(nids))
            return set(self.sess.hit_ids)
        finally:
            self.sess.t_check = _perf() - t0

    def _demote_writers_of_running_readers(self, nids) -> None:
        """review R-023b N8: a test whose output another test read (a data edge (writer, reader) of an earlier session:
        a spool file the reader consumes, a lock file) is not reused while that reader runs in this session: reused,
        the writer would not write, and the reader would not find what a serial session gives it."""
        present = set(nids)
        for w, r in self.store.edges():
            if r in present and w in present and self.sess.is_hit(w) and not self.sess.is_hit(r):
                self.sess.demote(w, f"reader: its output is read by {r}, which runs in this session")

    # -- shared store (P4): Rust (detpy_core::shared); here only the calls ------------------------------------
    def _shared_fetch(self, nids: list) -> None:
        if not self.shared or self.role == "worker":
            return  # a worker never talks to the shared store: its controller pulls and pushes
        t0 = _perf()
        cap, was = self.cap, self.cap.active
        cap.active = False  # detpy's own reads of the shared store are not inputs
        try:
            tests, cands, rejected, torn = self.store.shared_fetch(self.shared, list(nids), 3)
        except Exception as e:  # never break the session: the local store decides alone
            self.shared_stats = {"error": f"{type(e).__name__}: {e}"}
            return
        finally:
            cap.active = was
        kinds: dict = {}
        for _nid, _doc, kind, _detail in rejected:
            kinds[kind] = kinds.get(kind, 0) + 1
        self.shared_stats = {"tests": tests, "candidates": cands, "rejected": kinds, "rejected_detail": rejected[:20],
                             "torn": torn, "adopted": 0, "pushed": 0, "fetch_s": round(_perf() - t0, 3)}

    def _shared_adopt(self) -> None:
        if self.shared_stats is None or "error" in self.shared_stats:
            return
        adopted = self.store.shared_adopt()
        self.shared_stats["adopted"] = len(adopted)

    def _shared_push(self) -> None:
        if not self.shared or self.role == "worker":
            return
        st = self.shared_stats if self.shared_stats is not None else {}
        try:
            n, docs = self.store.shared_push(self.shared, self.receipts_path, self.run_id)
            st.update(pushed=n, documents=docs)
        except Exception as e:
            st["push_error"] = f"{type(e).__name__}: {e}"
        self.shared_stats = st

    def check_workers(self, nids: list, assign: dict) -> list:
        """After the plan: reused results that read ``PYTEST_XDIST_WORKER`` and that this run's plan places on
        another worker are withdrawn (they run). Returns the withdrawn ids (review R-023 F3)."""
        out = []
        for nid, why in self.store.worker_check([n for n in nids if self.sess.is_hit(n)], dict(assign)):
            if self.sess.demote(nid, why):
                out.append(nid)
        return out

    def written_hits(self, shard_paths: list, order: list) -> list:
        """After every worker finished: the reused results whose input a test that comes before them in the serial
        order wrote in this session (``ProofCache.hits_written``). They are withdrawn; the controller runs them again.
        Returns ``[(nodeid, reason)]`` (review R-023 F2)."""
        out = []
        hits = [n for n in order if self.sess.is_hit(n)]
        for nid, key, writer in self.store.hits_written(list(shard_paths), hits, list(order)):
            why = f"written: {key} was written by {writer}, which comes before the test, in this session"
            if self.sess.demote(nid, why):
                out.append((nid, why))
        return out

    def report_hits(self, nids: list) -> None:
        """Reports of the reused results among ``nids``, from the controller (they are never sent to a worker):
        logstart, the recorded setup/call reports, a passed teardown, logfinish."""
        from _pytest.reports import TestReport

        hook = self.config.hook
        now = _now()
        for nid in nids:
            if not self.sess.is_hit(nid):
                continue
            receipt = self.sess.hit(nid)
            rep, fingerprint = self.store.reuse_info(nid)
            location = _location_of(nid)
            hook.pytest_runtest_logstart(nodeid=nid, location=location)
            props = [("detpy_cache", "reused"), ("detpy_cache_key", receipt["key"]), ("detpy_fingerprint", fingerprint)]
            for when in ("setup", "call"):
                p = rep.get(when)
                if p is None:
                    continue
                lr = p.get("longrepr")
                r = TestReport(nid, location, {}, p["outcome"], tuple(lr) if lr else None, when, (), 0.0, now, now,
                               list(props))
                if "wasxfail" in p:
                    r.wasxfail = p["wasxfail"]
                hook.pytest_runtest_logreport(report=r)
            hook.pytest_runtest_logreport(report=TestReport(nid, location, {}, "passed", None, "teardown", (), 0.0,
                                                            now, now, list(props)))
            hook.pytest_runtest_logfinish(nodeid=nid, location=location)
            if fingerprint:
                from . import plugin as _plugin

                _plugin.S.fingerprints[nid] = fingerprint

    def report_unrun(self, nids_reasons: list) -> None:
        """Withdrawn reuses the controller could not run again (no worker to run them): reported as errors, never
        as their recorded result."""
        from _pytest.reports import TestReport

        hook = self.config.hook
        now = _now()
        for nid, why in nids_reasons:
            location = _location_of(nid)
            hook.pytest_runtest_logstart(nodeid=nid, location=location)
            hook.pytest_runtest_logreport(report=TestReport(
                nid, location, {}, "failed", f"detpy --det-cache: the reused result was withdrawn ({why}) and no "
                f"worker was left to run the test again", "setup", (), 0.0, now, now, []))
            hook.pytest_runtest_logfinish(nodeid=nid, location=location)

    def durations(self, nids: list) -> dict:
        """``{nodeid: recorded duration}`` of the tests that have an entry: the plan's cache costs."""
        return {n: d for n, d in zip(nids, self.store.durations(list(nids))) if d is not None}

    def merge_workers(self, workeroutput: dict, sent: dict, edges: list = (), lists: dict | None = None) -> None:
        """The controller's end of session: the workers' summaries, then the cross-worker write rule and one merge of
        their shards into the store (``ProofCache.merge_shards``)."""
        t0 = _perf()
        paths = list(self.iso_shards) if self.isolate else []
        for wid in sorted(workeroutput):
            out = workeroutput[wid]
            summ = out.get("detpy_cache_summary")
            if summ:
                ran, recorded, not_cached = summ[:3]
                where = [tuple(x) for x in summ[3]] if len(summ) > 3 else None
                self.sess.merge_worker(list(ran), int(recorded), [tuple(x) for x in not_cached], where)
            if out.get("detpy_cache_error"):
                self.sess.error = out["detpy_cache_error"]
            if out.get("detpy_cache_shard"):
                paths.append(out["detpy_cache_shard"])
            paths.extend(out.get("detpy_cache_shards") or ())  # --det-isolate: the worker's children
            if out.get("detpy_isolate"):
                from . import isolate as _isolate

                for k, v in out["detpy_isolate"].items():
                    _isolate.STATS[k] = _isolate.STATS.get(k, 0) + v
        try:
            res = json.loads(self.store.merge_shards(paths, list(self.sess.hit_ids), [tuple(e) for e in edges],
                                                     {w: list(v) for w, v in (lists or {}).items()}))
        except Exception as e:  # never break the session: nothing is recorded this time
            self.sess.error = f"merge of the workers' shards: {type(e).__name__}: {e}"
            res = {"merged": 0, "dropped": [], "stale": [], "unreadable": paths}
        self.sess.apply_merge([tuple(x) for x in res["dropped"]], [tuple(x) for x in res["stale"]])
        self.merge_result = res
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass
        self.sess.set_phase("merge", _perf() - t0)

    # -- pytest-xdist under --det: a worker ----------------------------------------------------------------------
    def worker_output(self) -> dict:
        self.iso_merge_summaries()
        out = {"detpy_cache_summary": list(self.sess.worker_summary())}
        if self.shard_path:
            out["detpy_cache_shard"] = self.shard_path
        if self.iso_shards:
            out["detpy_cache_shards"] = list(self.iso_shards)
        if self.isolate:
            from . import isolate as _isolate

            out["detpy_isolate"] = dict(_isolate.STATS)
        err = self.sess.summary_data(self.cap).get("error")
        if err:
            out["detpy_cache_error"] = err
        return out

    def _read_facts(self, paths, contents) -> list:
        """Facts of code files (``_codefacts``: CPython's parser), detpy's own reads not being inputs."""
        if not paths:
            return []
        cap, was = self.cap, self.cap.active
        cap.active = False
        try:
            return _codefacts.read_many([(p, c, *_module_of(p)) for p, c in zip(paths, contents)],
                                        os.path.join(self.dir, "tmp"))
        finally:
            cap.active = was

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
        receipt = self.sess.hit(item.nodeid)
        if receipt is None:
            return None
        self._reuse(item, nextitem, receipt)
        return True

    def _wrap_protocol(self, item, nextitem):  # generator driven by _ProtocolWrapper
        nid = item.nodeid
        if self.role == "serial" and self.sess.is_hit(nid):
            # review R-023 F2: a reuse decided before a writer of this session wrote the test's input is withdrawn
            self.sess.recheck_hit(self.store, self.cap, nid)
        if self.sess.is_hit(nid) or (self.isolate and not self.iso_child):
            # a reused result; or --det-isolate's parent: the child does iso_begin / iso_end
            yield
            return
        t = self.iso_begin(item)
        try:
            yield
        finally:
            self.iso_end(item, t)

    def iso_begin(self, item) -> float:
        """The cache's start of a test that runs (the protocol wrapper's, or a --det-isolate child's)."""
        nid = item.nodeid
        fx = []
        info = getattr(item, "_fixtureinfo", None)
        if info is not None:
            for name in item.fixturenames:
                defs = info.name2fixturedefs.get(name)
                if defs and defs[-1].scope != "function":
                    d = defs[-1]
                    fx.append(f"f|{d.scope}|{d.baseid}|{d.argname}")
        self.sess.start_test(nid, fx)
        self.cap.switch("t|" + nid)
        # review R-023b N9: xdist's worker_id and testrun_uid fixtures read config.workerinput, not the environment;
        # they carry the same values as PYTEST_XDIST_WORKER / _TESTRUNUID, which are inputs (the worker one is
        # checked against this run's plan, Checker::worker_check)
        names = getattr(item, "fixturenames", ())
        if "worker_id" in names:
            self.cap.env_read("PYTEST_XDIST_WORKER")
        if "testrun_uid" in names:
            self.cap.env_read("PYTEST_XDIST_TESTRUNUID")
        return _perf()

    def iso_end(self, item, t: float) -> None:
        nid = item.nodeid
        dur = _perf() - t
        self.cap.switch("s")
        index = self.sess.end_test(nid, dur)
        self.cap.scan_modules(index, self._conftests())
        if getattr(self.cap, "dists", None) is not None:
            self.cap.dists.scan(index, self.cap.ctx_index("t|" + nid))

    def iso_record(self) -> tuple:
        """In a --det-isolate child, after its test: record it as a one-test shard (no placement: the test ran
        alone from the session's snapshot); returns (shard path or None, the child's summary)."""
        from . import plugin as _plugin

        self.role = "worker"
        self.worker = f"iso{os.getpid()}"
        self.sess.add_fingerprints(_plugin.S.fingerprints)
        self.cap.switch("s")
        self.cap.stop()
        self._record_all()
        return self.shard_path, list(self.sess.worker_summary())

    def iso_prepare(self) -> None:
        """--det-isolate's parent, before its first child: the facts of the repository files executed so far
        (collection, imports) are parsed once here; the children inherit them."""
        if self.iso_warm:
            return
        self.iso_warm = True
        try:
            needed, whole = self.sess.files_needed(self.cap, self.items)
            fc: dict = {}
            self._facts(needed, fc)
            self._facts(whole, fc)
        except Exception:
            pass

    def iso_add_facts(self, facts) -> None:
        """Facts a child parsed (files first executed by its test): kept, so the next children need not parse them."""
        for rel, content, f in facts or ():
            try:
                if self.store.file_index(rel, content) is None:
                    self.store.add_file(rel, content, *f)
            except Exception:
                pass

    def iso_child_done(self, nodeid: str, shard, summary) -> None:
        """The parent's side: the child's summary joins this session's at the end (merged now, the next children
        would inherit it and record those tests again), its shard is merged at the end."""
        self.iso_forked.add(nodeid)
        if summary:
            self.iso_summaries.append(summary)
        if shard:
            self.iso_shards.append(shard)

    def iso_merge_summaries(self) -> None:
        for summary in self.iso_summaries:
            ran, recorded, not_cached = summary[:3]
            where = [tuple(x) for x in summary[3]] if len(summary) > 3 else None
            self.sess.merge_worker(list(ran), int(recorded), [tuple(x) for x in not_cached], where)
        self.iso_summaries = []

    def pytest_runtest_logreport(self, report):
        if self.isolate and not self.iso_child and report.nodeid in self.iso_forked:
            return  # the child reported it to its own session
        self.sess.report(report)

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

        rep, fingerprint = self.store.reuse_info(item.nodeid)
        ihook = item.ihook
        ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        now = _now()
        kw = {k: 1 for k in item.keywords}
        props = [("detpy_cache", "reused"), ("detpy_cache_key", receipt["key"]),
                 ("detpy_fingerprint", fingerprint)]
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

        sess, cap = self.sess, self.cap
        sess.add_fingerprints(_plugin.S.fingerprints)
        cap.switch("s")
        cap.stop()
        if self.role == "controller":
            # no test ran here: the workers recorded, the merge happened in merge_workers
            sess.t_record = self.sess.phase("merge")
            sess.compare_verified()
            sess.write_receipts(self.store)
            self._shared_push()
            self._write_quarantine()
            return
        if self.isolate and not self.iso_child:
            # --det-isolate: nothing ran in this process; the children's shards are merged here (serial) or by the
            # controller (worker)
            if self.role == "worker":
                return
            self.iso_merge_summaries()
            self.merge_workers({}, {}, (), {})
            sess.t_record = self.sess.phase("merge")
            sess.compare_verified()
            sess.write_receipts(self.store)
            self._shared_push()
            self._write_quarantine()
            return
        t0 = _perf()
        try:
            self._record_all()
        except Exception as e:  # never break the test session: nothing is recorded this time
            import traceback
            import warnings

            sess.error = f"{type(e).__name__}: {e}"
            warnings.warn(f"detpy --det-cache: results not recorded: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        finally:
            sess.t_record = _perf() - t0
        if self.role == "worker":
            return  # the controller compares verified results and writes the receipts
        sess.compare_verified()
        sess.write_receipts(self.store)
        self._shared_push()
        self._write_quarantine()

    # refusals that are not a test's own non-file inputs (those of an earlier test, a file another test wrote, a code
    # change during the session). A test that did not pass is quarantined too: its flags are not evaluated (it is
    # not recorded) but carried into the tests after it
    _NOT_QUARANTINED = ("after an earlier test", "reads a file another test", "source changed")

    def _write_quarantine(self) -> None:
        """The tests this session refused for inputs of their own that are not files (a network connection, a
        process-state read, ...): the next ``-n`` plan runs their atoms on a worker of their own, so that no other
        test of a worker carries their refusal (the carried-set rule; ``schedule::ControllerInput::quarantine``)."""
        try:
            nc = self.sess.outcomes_data(self.cap).get("not_cached_ids") or {}
            # cumulative while refused: a quarantined test refused for a carried input (it runs after another
            # quarantined one) stays, else it would leave the quarantine worker and carry the refusal back out; one
            # that is recorded (or not run) leaves it
            prev = set(self.quarantine())
            ids = sorted(n for n, why in nc.items() if n in prev or not str(why).startswith(self._NOT_QUARANTINED))
            os.makedirs(self.dir, exist_ok=True)
            tmp = os.path.join(self.dir, f"quarantine.json.{os.getpid()}")
            with open(tmp, "w") as fh:
                json.dump({"run": self.run_id, "tests": ids}, fh)
            os.replace(tmp, os.path.join(self.dir, "quarantine.json"))
        except Exception:
            pass

    def quarantine(self) -> list:
        try:
            with open(os.path.join(self.dir, "quarantine.json")) as fh:
                return list(json.load(fh).get("tests") or ())
        except (OSError, ValueError, AttributeError):
            return []

    def _facts(self, rels, cache: dict) -> None:
        """Store index of the facts of the current version of every file in ``rels`` not in ``cache`` (new versions
        parsed together)."""
        jobs = []
        for rel in rels:
            if rel in cache:
                continue
            content = _core.file_digest(os.path.join(self.root, rel))
            ix = None if content is None else self.store.file_index(rel, content)
            cache[rel] = ix
            if content is not None and ix is None:
                jobs.append((rel, content))
        facts = _codefacts.read_many([(p, c, *_module_of(p)) for p, c in
                                      ((os.path.join(self.root, r), c) for r, c in jobs)],
                                     os.path.join(self.dir, "tmp")) if jobs else ()
        for (rel, content), f in zip(jobs, facts):
            cache[rel] = None if f is None else self.store.add_file(rel, content, *f)
            if self.iso_child and f is not None:
                self.iso_new_facts.append((rel, content, tuple(f)))

    def _record_all(self) -> None:
        if self.cap.rec is None:
            return
        t = _perf()
        self.cap.collect_children()
        self.sess.set_phase("children", _perf() - t)
        self._record_captured()

    def _record_captured(self) -> None:
        """Record every test that ran: the record plan is built and recorded in Rust (``CacheSession.record``,
        ``detpy_core::record``) from the session, the capture and the facts of the files it needs (CPython's
        parser, ``_codefacts``)."""
        cap, store, sess = self.cap, self.store, self.sess
        t = _perf()
        fcache: dict[str, int | None] = {}
        needed, whole = sess.files_needed(cap, self.items)
        self._facts(needed, fcache)
        self._facts(whole, fcache)
        sess.set_phase("facts", _perf() - t)
        t = _perf()
        per, imp = cap.rec.fold(len(cap.ctx_names), cap.segs, store.unit_ranges([fcache.get(r) for r in cap.fnames]))
        cfg = _state.STATE.config
        assemble = sess.record(store, cap, self.items, fcache, needed, per, imp, _module_of,
                               bool(cfg.control_urandom), "time" in cfg.controls, cfg.cassette_path)
        sess.set_phase("plan", _perf() - t - assemble)
        sess.set_phase("assemble", assemble)
        t = _perf()
        if self.role == "worker":
            self.shard_path = os.path.join(self.dir, "shards", f"{self.run_id}.{self.worker}.json")
            store.save_shard(self.shard_path, self.worker, "" if self.iso_child else None)
        else:
            store.save()
        sess.set_phase("save", _perf() - t)

    # -- reporting (Rust: CacheSession) --------------------------------------------------
    def summary_data(self) -> dict:
        return self._with_dists(self.sess.summary_data(self.cap))

    def _with_dists(self, d):
        tr = getattr(self.cap, "dists", None)
        if tr is not None and isinstance(d, dict):
            # --det-cache-dists (prototype): what the per-distribution identity cost and saw
            keys = [len(v) for v in tr.deps.values()]
            d["dists"] = {
                "identity_dir": tr.dir,
                "installed": len(tr.index.ident),
                "index_seconds": round(tr.index_seconds, 3),
                "contexts_with_keys": len(keys),
                "keys_per_context_mean": round(sum(keys) / len(keys), 1) if keys else None,
                "unmapped": dict(sorted(tr.unmapped.items(), key=lambda kv: -kv[1])[:20]),
            }
        return d

    def outcomes_data(self) -> dict:
        return self._with_dists(self.sess.outcomes_data(self.cap))

    def terminal_summary(self, tr) -> None:
        tr.section("detpy cache with proof")
        for text, markup in self.sess.summary_lines(self.cap, tr.config.option.verbose):
            tr.write_line(text, **({markup: True} if markup else {}))
        m = self.merge_result
        if m is not None:
            tr.write_line(f"parallel: decided once in the controller; {m['merged']} entries merged from the workers' "
                          f"shards, {len(m['dropped'])} dropped by the cross-worker write rule, {len(m['stale'])} "
                          f"reused results dropped (inputs written by this session), {m.get('edges', 0)} together "
                          f"edge(s) noted for the next plans"
                          + (f"; UNREADABLE shards: {len(m['unreadable'])}" if m["unreadable"] else ""))
            if "proven" in m:
                tr.write_line(f"parallel vs serial (P5): {m['proven']} entr(ies) proven equal to the serial result "
                              f"(reusable by serial sessions), {len(m['diverged'])} diverged (not stored: the serial "
                              f"entry stays), {m['unproven']} unproven (no stable serial fingerprint under their key)")
        st = self.shared_stats
        if self.shared and st is not None:
            if "error" in st:
                tr.write_line(f"shared store {self.shared}: not used ({st['error']})", yellow=True)
            else:
                rej = ", ".join(f"{k} {v}" for k, v in sorted(st.get("rejected", {}).items())) or "none"
                tr.write_line(f"shared store {self.shared}: {st.get('candidates', 0)} candidate(s) for "
                              f"{st.get('tests', 0)} test(s), {st.get('adopted', 0)} adopted after the check, "
                              f"rejected: {rej}" + (f", {st['torn']} torn log line(s)" if st.get("torn") else "")
                              + f"; pushed {st.get('pushed', 0)} entr(ies)"
                              + (f"; PUSH FAILED: {st['push_error']}" if st.get("push_error") else ""))


def _location_of(nodeid: str) -> tuple:
    """A report location for a test reported by the xdist controller (which has no items): the file, no line, the
    rest of the node id as the domain."""
    path, _, rest = nodeid.partition("::")
    return (path, None, rest.replace("::", ".") or path)


def _run_time(run: str) -> float:
    """Real time (seconds) of a run id ``YYYYmmddTHHMMSS-pid``; 0 when unreadable (then the entry has expired).
    (``time.strptime``'s rules, which depend on the Python version: called by ``ProofCache.check_all`` once per
    distinct run id.)"""
    import calendar

    try:
        return float(calendar.timegm(time.strptime(run.split("-", 1)[0], "%Y%m%dT%H%M%S")))
    except (ValueError, IndexError):
        return 0.0





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
    return _core.cache_epoch(cache_dir, head_ns, window_ns)  # Rust: identity.rs


CAPTURE: Capture | None = None
PLUGIN: ProofCachePlugin | None = None


def start(early_config, ns) -> None:
    """Start recording (from ``pytest_load_initial_conftests``, before conftests are imported)."""
    global CAPTURE
    if not AVAILABLE:
        raise pytest.UsageError("--det-cache needs Python 3.12+ (sys.monitoring)")
    if CAPTURE is not None and CAPTURE.active:
        return  # nested in-process session: the outer one records
    root = str(early_config.rootpath)
    # detpy's own variables (set by its re-exec, e.g. the precompile time) are configuration, not inputs
    # (undecodable bytes of environment strings escaped: valid UTF-8 text, Rust _safe)
    env0 = _core.safe_env(os.environ.items(), _DETPY_OWN_ENV)
    cap = Capture(root, env0)
    # known before the first lookup: a root conftest is imported between the start and pytest_configure, and its
    # module lookups must not key site-packages or the standard library as searched directories (each is covered by
    # the runtime identity, or by the per-distribution identity under --det-cache-dists)
    cap.stdlib_dirs = tuple(d + os.sep for d in _sites._stdlib_dirs)
    cap.site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
    CAPTURE = cap
    _core.cap_set_env_capture(cap)
    _patch_environ()
    _state.set_event_listener(cap.event)
    # probed before recording starts: the probe's own strace run is not a child of any test
    cap.follower = follow.Follower(cap, os.path.join(os.path.abspath(ns.det_cache), f"follow-{os.getpid()}"),
                                   not getattr(ns, "det_cache_no_follow", False))
    cap.follower.install()
    tr = None
    if getattr(ns, "det_cache_dists", False) or os.environ.get("DETPY_CACHE_DISTS") == "1":
        # prototype: per-distribution identity (distid, file index in Rust: distfiles.rs); built before recording
        # starts, so its reads are not inputs
        from . import distid

        t0 = _perf()
        index = distid.Index(root)
        ident_dir = os.path.join(os.path.abspath(ns.det_cache), "dist-identity")
        site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
        index.write(ident_dir, site_dirs)
        tr = distid.Tracker(cap, index, ident_dir)
        tr.site_dirs = site_dirs
        tr.index_seconds = _perf() - t0
        tr.install()
        cap.set_dist_read(lambda ctx, p, listing: tr.path(ctx, p))
    cap.dists = tr
    cap.start()
    if tr is not None:
        for k in tr.global_keys:  # .pth files of the site directories: inputs of every test
            tr.add(cap.import_ctx, k)


def install(config) -> None:
    """Register the plugin hooks (from ``pytest_configure``)."""
    global PLUGIN
    cap = CAPTURE
    if cap is None or PLUGIN is not None:
        return
    opt = config.option
    plugin = ProofCachePlugin(cap, opt.det_cache, opt.det_cache_verify, opt.det_cache_receipts)
    plugin.shared = getattr(opt, "det_cache_shared", None) or os.environ.get("DETPY_CACHE_SHARED") or None
    age = getattr(opt, "det_cache_max_age", 30.0)
    plugin.max_age_s = age * 86400 if age and age > 0 else None
    from . import xdist as _xdist

    if _xdist.worker_id(config) is not None:
        plugin.role, plugin.worker = "worker", _xdist.worker_id(config)
    elif _xdist.is_controller(config):
        plugin.role = "controller"
    plugin.configure(config)
    if getattr(opt, "det_plan_worker", None):
        plugin.store.set_parallel()  # one worker's list of a parallel plan: its results are parallel results
    PLUGIN = plugin
    config.pluginmanager.register(plugin, "detpy-cache")
    config.pluginmanager.register(_ProtocolWrapper(plugin), "detpy-cache-wrapper")
    cap.switch("s")


def uninstall() -> None:
    global CAPTURE, PLUGIN
    if CAPTURE is not None:
        CAPTURE.stop()
        if getattr(CAPTURE, "dists", None) is not None:
            CAPTURE.dists.uninstall()
            CAPTURE.set_dist_read(None)
        if CAPTURE.follower is not None:
            CAPTURE.follower.uninstall()
    _state.set_event_listener(None)
    CAPTURE = None
    PLUGIN = None
    _core.cap_set_env_capture(None)


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
