"""Cache with proof, the runner-neutral part: the capture (``Capture``), the identities (runtime, time zone and
locale, the Level 0 configuration) and the session (``ProofSession``: decide, record, receipts, summary) that every
runner shell drives the same way. The pytest shell is ``proofcache.py`` (its hooks and its configuration digest); the
other runners' shell is the driver in ``runners/``. What counts as an input and what is never reused is described in
``proofcache.py``.
"""

from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
from types import FunctionType

from . import __version__, _codefacts, _core, _django, _sites, _state, follow

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


# ---------------------------------------------------------------------------
# standard-library modules whose own stat calls are helpers (review R-032b F2, claude/parallel-proof-3 6cfae24)
_STDLIB_PATH_MODULES = frozenset({"genericpath", "posixpath", "ntpath", "pathlib", "pathlib._local",
                                  "pathlib._abc", "glob", "shutil", "os"})


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
        return not (mod in _STDLIB_PATH_MODULES or fn.startswith(_STDLIB_DIR) or fn.startswith("<frozen"))
    return False


_STDLIB_DIR = os.path.dirname(os.__file__) + os.sep
# st_atime, st_mtime, st_ctime (indices 7, 8, 9) and their _ns, birthtime variants
_TIME_FIELDS = ("st_atime", "st_mtime", "st_ctime", "st_birthtime")


class _TimedStat:
    """An ``os.stat_result`` given to user code: reading a time field flags the context "mtime" (not cached: a time
    is not an input the cache keys; review R-032b F2). Everything else is the result's own."""

    __slots__ = ("_r", "_cap", "_path")

    def __init__(self, r, cap, path):
        self._r = r
        self._cap = cap
        self._path = path

    def _timed(self):
        try:
            self._cap.flag(self._cap._cur(), "mtime", os.fsdecode(os.fspath(self._path)) if not isinstance(
                self._path, int) else str(self._path))
        except Exception:
            pass

    def __getattr__(self, name):
        if name.startswith(_TIME_FIELDS):
            self._timed()
        return getattr(self._r, name)

    def __getitem__(self, i):
        idx = range(len(self._r))[i]
        if (7 in idx or 8 in idx or 9 in idx) if isinstance(idx, range) else idx in (7, 8, 9):
            self._timed()
        return self._r[i]

    def __iter__(self):
        self._timed()  # unpacking gives every field
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
    """An ``os.DirEntry`` of user code's ``os.scandir`` whose ``stat()`` and kind checks are inputs (review R-032b F2;
    ``Capture._patch_scandir``)."""

    __slots__ = ("_e", "_cap")

    def __init__(self, e, cap):
        self._e = e
        self._cap = cap

    def _check(self, meta: bool, follow: bool = True) -> None:
        cap = self._cap
        if cap._in_stat:
            return
        cap._in_stat = True
        try:
            cap.stat_check(self._e.path, not follow, meta)
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
        self._patch_scandir()
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
        """``os.stat``, ``os.lstat``, ``os.access`` and ``os.readlink`` raise no audit event; neither do
        ``os.path.exists``, ``isfile``, ``isdir``, ``islink``, ``lexists`` (``Path.exists``, ``shutil.which`` and
        ``glob`` on a literal path go through them). What they answer is an input, recorded by the Rust capture
        (``CaptureCore.stat_check``):

        * ``os.stat``, ``os.lstat``, ``os.access``, ``os.readlink`` (and through them ``os.path.getsize``,
          ``getmtime``, ``realpath``, ``Path.stat``): the path's metadata (kind, permission bits, a file's size and
          modification time, a symlink's target: ``proof::probe_now``), so a file that grows, is touched, changes
          mode or is re-pointed invalidates the test;
        * the ``os.path.exists`` family: the path's kind only (they call the original ``os.stat`` / ``os.lstat``, not
          the wrapper), so a file that appears or disappears invalidates the test.

        ``os.lstat``, ``readlink`` and ``islink`` / ``lexists`` do not follow a final symlink (LIMITS K4). References
        bound before the session (``from os import stat`` in a plugin loaded at startup) are rebound to the wrapper
        too (LIMITS K3); the import system's own ``posix`` module is left alone (the module-lookup finder records its
        probes). This is interface only: what is recorded, and under which key, is Rust."""
        import posixpath

        cap = self
        self._stat_saved = []
        self._in_stat = False

        def rebind(owner, name, orig, new):
            self._stat_saved.append((owner, name, orig))
            setattr(owner, name, new)
            for mod in list(sys.modules.values()):
                d = getattr(mod, "__dict__", None)
                if not isinstance(d, dict) or mod is owner or getattr(mod, "__name__", "") in ("posix", "nt") \
                        or str(getattr(mod, "__file__", "") or "").startswith(_DETPY_DIR):
                    continue
                for k, v in list(d.items()):
                    if v is orig:
                        self._stat_saved.append((mod, k, orig))
                        try:
                            setattr(mod, k, new)
                        except Exception:
                            pass

        def note(path, link, meta):
            if cap._in_stat or isinstance(path, int):
                return
            cap._in_stat = True
            try:
                cap.stat_check(path, link, meta)
            except Exception:
                pass
            finally:
                cap._in_stat = False

        def wrap(name):
            orig = getattr(os, name, None)
            if orig is None:
                return

            own = name in ("lstat", "readlink")

            timed_ok = name in ("stat", "lstat")

            def checked(path, *args, **kwargs):
                if not kwargs.get("dir_fd"):
                    note(path, own or kwargs.get("follow_symlinks") is False, True)
                    # review R-032b F2 (coordinator's correction, claude/parallel-proof-3 6cfae24): a result given to
                    # repository or library code flags the test when a time field is read (atime and ctime are not
                    # keyed by the metadata probe; mtime is, the flag refuses all three alike)
                    if timed_ok and not isinstance(path, int) and not cap._in_stat and _user_stat_caller():
                        return _TimedStat(orig(path, *args, **kwargs), cap, path)
                return orig(path, *args, **kwargs)

            checked.__name__ = orig.__name__
            checked.__doc__ = orig.__doc__
            checked.__wrapped__ = orig
            rebind(os, name, orig, checked)

        real_stat, real_lstat = os.stat, os.lstat
        for name in ("stat", "lstat", "access", "readlink"):
            wrap(name)
        if os.path is not posixpath:
            return
        import stat as _st

        def kind_of(path, link):
            note(path, link, False)
            try:
                return (real_lstat if link else real_stat)(path)
            except (OSError, ValueError):
                return None

        def exists(path):
            """Test whether a path exists. Returns False for broken symbolic links"""
            return kind_of(path, False) is not None

        def lexists(path):
            """Test whether a path exists. Returns True for broken symbolic links"""
            return kind_of(path, True) is not None

        def isfile(path):
            """Test whether a path is a regular file"""
            st = kind_of(path, False)
            return st is not None and _st.S_ISREG(st.st_mode)

        def isdir(s):
            """Return true if the pathname refers to an existing directory."""
            st = kind_of(s, False)
            return st is not None and _st.S_ISDIR(st.st_mode)

        def islink(path):
            """Test whether a path is a symbolic link"""
            st = kind_of(path, True)
            return st is not None and _st.S_ISLNK(st.st_mode)

        for name, fn in (("exists", exists), ("lexists", lexists), ("isfile", isfile), ("isdir", isdir),
                         ("islink", islink)):
            orig = getattr(posixpath, name, None)
            if orig is not None:
                fn.__wrapped__ = orig
                rebind(posixpath, name, orig, fn)

    def _patch_scandir(self) -> None:
        """Review R-032b F2 (claude/parallel-proof-3 c5f0e70): ``os.scandir``'s entries answer ``stat()``,
        ``is_file()``, ``is_dir()`` and ``is_symlink()`` without ``os.stat``. User code iterating ``os.scandir`` gets
        entries whose ``stat()`` is an input like ``os.stat`` here (the path's metadata: ``q``, ``Q`` without
        following a symlink) and whose kind checks are kind checks. Library code's iterations (glob, shutil) keep the
        plain entries (their callers' own checks are recorded where they look)."""
        cap = self
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
        scandir.__doc__ = orig_scandir.__doc__
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


def level0_identity() -> dict:
    """The Level 0 part of every runner's configuration digest: detpy's version and encoding, the controls, and the
    time zone and locale as C sees them."""
    cfg = _state.STATE.config
    return {
        "detpy": __version__,
        "encoding": _core.ENCODING_VERSION,
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


def digest_identity(d: dict) -> str:
    return _core.digest(json.dumps(d, sort_keys=True, default=str).encode())


# ---------------------------------------------------------------------------
class ProofSession:
    """One session of the cache with proof, for any runner. The session's bookkeeping (decisions, reports, the record
    plan, the reasons and the summary) is Rust (``_core.CacheSession``, ``crates/detpy-py/src/session.rs``); this
    class hands it the runner's objects. The pytest shell (``proofcache.ProofCachePlugin``) adds pytest's hooks and
    pytest-xdist's controller and worker roles; the runners driver (``runners.driver.DetRun``) calls the same methods
    from the other runners' hooks.

    ``items`` maps every test id to an object the record reads: a test whose own file's whole content is its input
    (a doctest) is an object of a class named ``DoctestItem`` or without an ``obj`` attribute."""

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
        self.root = cap.root
        self.config_digest = ""
        self.config_info: dict = {}
        self.runtime_digest = ""
        self.runtime_info: dict = {}
        self.epoch = 0
        self.items: dict[str, object] = {}
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime(_now()))}-{os.getpid()}"
        self.sess = _core.CacheSession(self.run_id, self.receipts_path)
        self.keys_path: str | None = None  # --det-cache-keys (the culprit finder's input)
        # pytest-xdist under --det (pytest shell only): "controller" (decides, reports hits, merges the shards),
        # "worker" (runs what the plan sends, records a shard), "serial" (every other runner)
        self.role = "serial"
        self.worker = None
        self.shard_path = None
        self.merge_result: dict | None = None
        # --det-isolate (claude/parallel-proof-3 isolate.py; the pytest shell today): tests run in forked children,
        # each records a one-test shard; this process merges them (serial) or hands them to the controller (worker)
        self.isolate = False
        self.iso_child = False
        self.iso_shards: list[str] = []
        self.iso_forked: set[str] = set()
        self.iso_summaries: list = []
        self.iso_new_facts: list = []
        self.iso_warm = False

    # -- setup ----------------------------------------------------------------
    def open(self, root: str, config_digest: str, config_info: dict, basetemp: str | None = None) -> None:
        """The session's configuration and runtime identities, and the store."""
        self.root = os.path.realpath(root)
        self.config_digest, self.config_info = config_digest, config_info
        os.makedirs(self.dir, exist_ok=True)
        cap = self.cap
        self.runtime_digest, self.runtime_info, editable = runtime_identity(
            self.root, os.path.join(self.dir, "distributions.json"), per_dist=getattr(cap, "dists", None) is not None)
        # sys.path and the .pth files of the site directories (Rust; review R-019c E-1/E-9)
        self.runtime_digest, pth, spath = _core.runtime_with_paths(
            self.runtime_digest, self.root, list(_sites._site_dirs), [e for e in sys.path if isinstance(e, str)])
        self.runtime_info = {**self.runtime_info, "pth": pth, "sys_path": spath}
        cap.dist_info_ok = tuple(editable)
        cap.stdlib_dirs = tuple(d + os.sep for d in _sites._stdlib_dirs)
        cap.site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
        if getattr(cap, "dists", None) is not None:
            cap.dists.site_dirs = tuple(sorted(set(cap.site_dirs) | set(cap.dists.site_dirs)))
        if basetemp is not None:
            cap.basetemp = basetemp
        self.epoch = _state.STATE.config.epoch_ns
        self.store = _core.ProofCache(self.dir, self.root)
        self.store.begin(self.config_digest, self.runtime_digest, self.epoch, dict(cap.env0))
        self.sess.configure(self.config_digest, self.runtime_digest, self.epoch)

    # -- decisions ----------------------------------------------------------------
    def collected(self) -> None:
        """Collection is over (every shell, before ``check``): the modules loaded so far are scanned."""
        self.cap.switch("s")
        self.cap.scan_modules(-1, self._conftests())
        if getattr(self.cap, "dists", None) is not None:
            self.cap.dists.scan(-1)
        _django.ensure(self.cap)  # Django's caches of file contents (every runner)

    def check(self, nids: list, items: dict, units: list | None = None) -> None:
        """Decide every test (``units``: groups of ids reused together or not at all)."""
        t0 = _perf()
        try:
            self._decide(nids, items)
            if units:
                self.sess.regroup(units)
        finally:
            self.sess.t_check = _perf() - t0

    def _decide(self, nids, items) -> None:
        store, cap = self.store, self.cap
        nids = list(nids)
        self._shared_fetch(nids)
        changed = list(store.changed_code_files())
        for (path, content), f in zip(changed, self._read_facts([os.path.join(self.root, p) for p, _ in changed],
                                                                 [c for _, c in changed])):
            if f is not None:
                store.set_fresh(path, content, *f)
        self._shared_adopt()
        self.sess.seed_exclusive(store, cap)  # review R-009b R2
        self.items = dict(items)
        # the checks, the expiry (review R-009 F4: an entry older than --det-cache-max-age is not reused), the
        # receipts and the verification draw (Python's Mersenne Twister, seeded per run) are Rust
        rng = random.Random(f"detpy-cache-verify:{self.run_id}")
        self.sess.decide(store, nids, self.max_age_s, _now(), _run_time, self.verify, rng.random)
        self._demote_writers_of_running_readers(nids)

    def _demote_writers_of_running_readers(self, nids) -> None:
        """review R-023b N8: a test whose output another test read (a data edge (writer, reader) of an earlier session:
        a spool file the reader consumes, a lock file) is not reused while that reader runs in this session: reused,
        the writer would not write, and the reader would not find what a serial session gives it."""
        present = set(nids)
        for w, r in self.store.edges():
            if r in present and w in present and self.sess.is_hit(w) and not self.sess.is_hit(r):
                self.sess.demote(w, f"reader: its output is read by {r}, which runs in this session")

    def recheck(self, nid: str) -> None:
        """At the test's turn (serial session): a reuse decided before a writer of this session wrote the test's input
        is withdrawn (review R-023 F2); the test then runs."""
        if self.role == "serial" and self.sess.is_hit(nid):
            self.sess.recheck_hit(self.store, self.cap, nid)

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

    # -- tests ---------------------------------------------------------------------
    def start(self, nid: str, fixtures: list) -> None:
        """A test that runs (not reused) starts, with the contexts of the wider-scoped fixtures it uses."""
        self.sess.start_test(nid, fixtures)
        _django.ensure(self.cap)
        self.cap.switch("t|" + nid)

    def stop(self, nid: str, duration: float) -> None:
        self.cap.switch("s")
        index = self.sess.end_test(nid, duration)
        self.cap.scan_modules(index, self._conftests())
        if getattr(self.cap, "dists", None) is not None:
            self.cap.dists.scan(index, self.cap.ctx_index("t|" + nid))

    def _conftests(self):
        return ()

    # -- end of session ------------------------------------------------------------
    def finish(self, fingerprints: dict) -> None:
        """Record every test that ran, compare the verified ones, write the receipts. ``fingerprints``: the Level 0
        fingerprints of the tests that ran."""
        sess, cap = self.sess, self.cap
        sess.add_fingerprints(fingerprints)
        cap.switch("s")
        cap.stop()
        if self.isolate and not self.iso_child:
            # --det-isolate: nothing ran in this process; the children's shards are merged here (serial) or by the
            # controller (worker)
            if self.role == "worker":
                return
            self.iso_merge_summaries()
            self.merge_shards(list(self.iso_shards))
        if self.role == "controller" or (self.isolate and not self.iso_child):
            # no test ran here: the workers (or children) recorded, the merge happened in merge_workers
            sess.t_record = self.sess.phase("merge")
            sess.compare_verified()
            sess.write_receipts(self.store)
            self._shared_push()
            self._after_session()
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
        self._after_session()

    def _after_session(self) -> None:
        """A shell's own bookkeeping once the receipts are written (pytest: the quarantine of the next -n plan)."""

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
                               bool(cfg.control_urandom), "time" in cfg.controls, cfg.cassette_path,
                               bool(self.keys_path))
        sess.set_phase("plan", _perf() - t - assemble)
        sess.set_phase("assemble", assemble)
        if self.keys_path:
            self._dump_keys()
        t = _perf()
        if self.role == "worker":
            self.shard_path = os.path.join(self.dir, "shards", f"{self.run_id}.{self.worker}.json")
            store.save_shard(self.shard_path, self.worker, "" if self.iso_child else None)
        else:
            store.save()
        sess.set_phase("save", _perf() - t)

    def _dump_keys(self) -> None:
        """``--det-cache-keys``: every test's inputs (any outcome), resolved to paths, names and digests.

        Prototype for the culprit finder: the per-test inputs are built in Rust next to the record plan
        (``detpy_core::record::record_session_keys``), for every test that ran, failures and uncacheable tests
        included, without the cacheability checks. Writes JSON only.
        """
        raw = self.sess.keys_json()
        tests = json.loads(raw) if raw else {}
        try:
            dists, _editable = _dist_infos(self.root, os.path.join(self.dir, "distributions.json"))
        except Exception:
            dists = []
        # top-level import names loaded in this process, mapped to their distributions (prunes package changes)
        loaded_dists: set[str] = set()
        try:
            from importlib import metadata

            pkg = metadata.packages_distributions()
            for m in list(sys.modules):
                for dname in pkg.get(m.split(".", 1)[0], ()):
                    loaded_dists.add(dname.lower().replace("_", "-"))
        except Exception:
            pass
        # interpreter start-up settings (PYTHON* variables, -W/-X options, flags): read by C at start-up, so no
        # os.environ event records them and they are not in the config or runtime digest
        env0 = dict(self.cap.env0)
        interp = {
            "warnoptions": list(sys.warnoptions),
            "xoptions": {str(k): str(v) for k, v in getattr(sys, "_xoptions", {}).items()},
            "flags": repr(sys.flags),
            "env": {k: _core.env_value_digest(v) for k, v in sorted(env0.items())
                    if k.startswith("PYTHON") and k not in ("PYTHONHASHSEED",)},
        }
        out = {
            "root": self.root,
            "interpreter": interp,
            "config": self.config_digest,
            "config_info": self.config_info,
            "runtime": self.runtime_digest,
            "runtime_info": self.runtime_info,
            "distributions": dists,
            "loaded_distributions": sorted(loaded_dists),
            "epoch": self.epoch,
            "tests": tests,
        }
        # one file per recording process: an xdist worker or a --det-isolate child records its own tests only
        path = self.keys_path
        if self.role == "worker":
            path = f"{path}.{self.worker}"
        elif self.iso_child:
            path = f"{path}.{os.getpid()}"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w") as fh:
                json.dump(out, fh, sort_keys=True, default=str)
        except OSError:
            pass

    # -- --det-isolate (a shell that forks a child per test calls these) ------------------------------------------
    def merge_shards(self, paths: list, edges=(), lists: dict | None = None, t0: float | None = None) -> None:
        """One merge of recorded shards into the store (``ProofCache.merge_shards``: the cross-worker write rule);
        the shard files are removed. The pytest shell's xdist controller and --det-isolate's parent call it."""
        t0 = _perf() if t0 is None else t0
        try:
            res = json.loads(self.store.merge_shards(list(paths), list(self.sess.hit_ids), [tuple(e) for e in edges],
                                                     {w: list(v) for w, v in (lists or {}).items()}))
        except Exception as e:  # never break the session: nothing is recorded this time
            self.sess.error = f"merge of the shards: {type(e).__name__}: {e}"
            res = {"merged": 0, "dropped": [], "stale": [], "unreadable": list(paths)}
        self.sess.apply_merge([tuple(x) for x in res["dropped"]], [tuple(x) for x in res["stale"]])
        self.merge_result = res
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass
        self.sess.set_phase("merge", _perf() - t0)

    def iso_record(self, fingerprints: dict) -> tuple:
        """In a --det-isolate child, after its test: record it as a one-test shard (no placement: the test ran
        alone from the session's snapshot); returns (shard path or None, the child's summary)."""
        self.role = "worker"
        self.worker = f"iso{os.getpid()}"
        self.sess.add_fingerprints(fingerprints)
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

    def summary_lines(self, verbose: int) -> list:
        lines = list(self.sess.summary_lines(self.cap, verbose))
        st = self.shared_stats
        if self.shared and st is not None:
            if "error" in st:
                lines.append((f"shared store {self.shared}: not used ({st['error']})", "yellow"))
            else:
                rej = ", ".join(f"{k} {v}" for k, v in sorted(st.get("rejected", {}).items())) or "none"
                lines.append((f"shared store {self.shared}: {st.get('candidates', 0)} candidate(s) for "
                              f"{st.get('tests', 0)} test(s), {st.get('adopted', 0)} adopted after the check, "
                              f"rejected: {rej}" + (f", {st['torn']} torn log line(s)" if st.get("torn") else "")
                              + f"; pushed {st.get('pushed', 0)} entr(ies)"
                              + (f"; PUSH FAILED: {st['push_error']}" if st.get("push_error") else ""), None))
        return lines


# ---------------------------------------------------------------------------
def start_capture(root: str, cache_dir: str, follow_children: bool, dists: bool = False) -> Capture:
    """Create and start the capture (before the project's modules are imported). ``dists``: ``--det-cache-dists``
    (per-distribution identity)."""
    # detpy's own variables (set by its re-exec, e.g. the precompile time) are configuration, not inputs
    # (undecodable bytes of environment strings escaped: valid UTF-8 text, Rust _safe)
    env0 = _core.safe_env(os.environ.items(), _DETPY_OWN_ENV)
    cap = Capture(root, env0)
    _core.cap_set_env_capture(cap)
    _patch_environ()
    _state.set_event_listener(cap.event)
    # probed before recording starts: the probe's own strace run is not a child of any test
    cap.follower = follow.Follower(cap, os.path.join(os.path.abspath(cache_dir), f"follow-{os.getpid()}"),
                                   follow_children)
    cap.follower.install()
    tr = None
    if dists or os.environ.get("DETPY_CACHE_DISTS") == "1":
        # prototype: per-distribution identity (distid, file index in Rust: distfiles.rs); built before recording
        # starts, so its reads are not inputs
        from . import distid

        t0 = _perf()
        index = distid.Index(root)
        ident_dir = os.path.join(os.path.abspath(cache_dir), "dist-identity")
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
    return cap


def stop_capture(cap: Capture | None) -> None:
    _django.uninstall()
    if cap is not None:
        cap.stop()
        if getattr(cap, "dists", None) is not None:
            cap.dists.uninstall()
            cap.set_dist_read(None)
        if cap.follower is not None:
            cap.follower.uninstall()
    _state.set_event_listener(None)
    _core.cap_set_env_capture(None)


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


