"""Cache with proof, the runner-neutral part: the capture (``Capture``), the identities (runtime, time zone and
locale, the Level 0 configuration) and the session (``ProofSession``: decide, record, receipts, summary) that every
runner shell drives the same way. The pytest shell is ``proofcache.py`` (its hooks and its configuration digest); the
other runners' shell is the driver in ``runners/``. What counts as an input and what is never reused is described in
``proofcache.py``.
"""

from __future__ import annotations

import ast
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
                 "os.link", "ctypes.dlsym", "ctypes.dlsym/handle", "ctypes.call_function")
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


# existence and kind checks that ask os.stat (their answer is the kind, not the size): genericpath, posixpath, pathlib,
# glob, shutil. (Review R-023c E4: samefile is not one: its answer is the inode and device, keyed as status fields.)
_KIND_FUNCS = frozenset({"exists", "lexists", "isfile", "isdir", "islink", "ismount", "isjunction", "is_file", "is_dir",
                         "is_symlink", "is_mount", "is_junction", "is_socket", "is_fifo", "is_block_device",
                         "is_char_device", "_lexists", "_isdir", "which", "_access_check", "isdevdrive",
                         # review R-023c E4: realpath asks each component whether it is a symlink; shutil's _stat
                         # (copyfile) whether a file is a FIFO: kinds
                         "realpath", "_joinrealpath", "_stat"})
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


_REWRITE_FILE = os.sep + os.path.join("_pytest", "assertion", "rewrite.py")
# (module, function) of standard-library caches that stat a path only to know whether to read it again
_CACHE_VALIDATORS = frozenset({("importlib.metadata", "mtime"), ("linecache", "checkcache"),
                               ("linecache", "updatecache"), ("linecache", "lazycache")})


def _reaches_user(f) -> bool:
    """Review R-023c E2: whether a status result asked by frame ``f`` goes to code that can decide on it: walking
    out from ``f``, the first frame that is neither the standard library nor test infrastructure is repository or
    library code, whatever frames are between (tarfile's gettarinfo, pytest's LocalPath.mtime, Path.stat). Not:
    detpy's own status reads, pytest's assertion rewriting (its .pyc is a cache of the source, rewritten from the
    same source when stale) and shutil.copystat (it copies the times onto a file this session writes)."""
    while f is not None:
        fn = f.f_code.co_filename
        if fn.startswith(_DETPY_DIR) or fn.endswith(_REWRITE_FILE):
            return False
        if f.f_code.co_name == "copystat" and f.f_globals.get("__name__") == "shutil":
            return False
        if (f.f_globals.get("__name__"), f.f_code.co_name) in _CACHE_VALIDATORS:
            # the standard library's own caches, validated by a file's time or size: what they serve is read (and
            # keyed) again when the validator changes (py-cache: importlib.metadata's per-directory lookup keyed every
            # test by the project root's mtime, which changes between sessions)
            return False
        if fn == "<string>" or fn.startswith("<frozen"):
            # code compiled from a string (execnet's worker bootstrap, a user's exec): its caller decides
            f = f.f_back
            continue
        if _sites._classify(fn)[0] == _sites._USER:
            return True
        f = f.f_back
    return False


def _user_stat_caller() -> bool:
    """Whether the status asked of the os.stat wrapper (the caller's frame 1) reaches user code (``_reaches_user``)."""
    return _reaches_user(_getframe(2))


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
_REAL_STAT = os.stat
_REAL_READLINK = os.readlink


_UNLINKED = object()


class _TimedStat:
    """An ``os.stat_result`` given to user code (review R-032b F2, round 4, review R-023c E2/E4), each field an input
    when it is read: ``st_mtime``/``st_ctime`` (their ``_ns`` variants, indices 8 and 9) the file's modification and
    change times ("y:", keyed); ``st_atime``/``st_birthtime`` (index 7; unpacking, equality, hashing, repr give
    every field) refuse the test ("mtime": the access time changes when the file is read); ``st_size`` (index 6) the
    size (keyed when the call was ``os.stat`` of a path; else with the other fields); ``st_mode``, ``st_ino``,
    ``st_dev``, ``st_nlink``, ``st_uid``, ``st_gid`` and the rest the status fields ("w:", keyed). ``path`` is a path
    or a descriptor (``os.fstat``, ``os.stat(fd)``): a descriptor's file is named through /proc/self/fd and must be
    the file the result describes (same device and inode); one of a pipe, socket or device is this process's own
    state (no input); one that cannot be named refuses the test ("pstate")."""

    __slots__ = ("_r", "_cap", "_path", "_link", "_sized")

    def __init__(self, r, cap, path, link=False, sized=False):
        self._r = r
        self._cap = cap
        self._path = path
        self._link = link
        self._sized = sized

    def _p(self):
        return os.fsdecode(os.fspath(self._path)) if not isinstance(self._path, int) else str(self._path)

    def _named(self):
        """The path to key, "" for no input, None when the descriptor's file cannot be named."""
        if not isinstance(self._path, int):
            return self._path
        try:
            p = _REAL_READLINK(f"/proc/self/fd/{self._path}")
        except OSError:
            return None
        if not p.startswith("/") or p.startswith(("/proc/", "/dev/", "/sys/")):
            return ""  # a pipe, a socket, an anonymous inode, a device: the process's own descriptor
        try:
            st = _REAL_STAT(p)
        except OSError:
            st = None
        if st is None or (st.st_dev, st.st_ino) != (self._r.st_dev, self._r.st_ino):
            # unlinked or replaced since it was opened (a temporary file, " (deleted)"): no path names it any more;
            # its status is what this process did to it (its content was an input when it was opened). Its times
            # are real-clock values: _input refuses those (py-cache: moto's spooled bodies refused every test)
            return _UNLINKED
        return p

    def _flag(self, flag, detail):
        try:
            self._cap.flag(self._cap._cur(), flag, detail)
        except Exception:
            pass

    def _timed(self):
        self._flag("mtime", self._p())

    def _input(self, check):
        p = self._named()
        if p is _UNLINKED:
            if check == "time_check":
                self._timed()
            return
        if p is None:
            return self._flag("pstate", f"the status of descriptor {self._path} (its file cannot be named)")
        if p == "":
            return
        try:
            getattr(self._cap, check)(p, self._link)
        except Exception:
            self._timed()

    def _keyed(self):
        self._input("time_check")

    def _fields(self):
        self._input("fields_check")

    def _size(self):
        if not self._sized:
            self._fields()

    def __getattr__(self, name):
        if name.startswith(("st_mtime", "st_ctime")):
            self._keyed()
        elif name.startswith(("st_atime", "st_birthtime")):
            self._timed()
        elif name == "st_size":
            self._size()
        elif name.startswith("st_"):
            self._fields()
        return getattr(self._r, name)

    def __getitem__(self, i):
        idx = range(len(self._r))[i]
        idx = list(idx) if isinstance(idx, range) else [idx]
        if 7 in idx:
            self._timed()
        elif 8 in idx or 9 in idx:
            self._keyed()
        if any(j < 6 for j in idx):
            self._fields()
        if 6 in idx:
            self._size()
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
        self._timed()
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
        return _TimedStat(self._e.stat(follow_symlinks=follow_symlinks), self._cap, self._e.path,
                          not follow_symlinks, follow_symlinks)

    def is_file(self, *, follow_symlinks=True):
        self._check(False, follow_symlinks)
        return self._e.is_file(follow_symlinks=follow_symlinks)

    def is_dir(self, *, follow_symlinks=True):
        self._check(False, follow_symlinks)
        return self._e.is_dir(follow_symlinks=follow_symlinks)

    def is_symlink(self):
        self._check(False, False)
        return self._e.is_symlink()

    def inode(self):
        try:
            self._cap.fields_check(self._e.path, True)
        except Exception:
            pass
        return self._e.inode()

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
        # the general rule: a gap the wide sensor finds makes this test uncacheable, so the cache never reuses a
        # result the rule refuses (detpy_core::record::uncacheable, flag "unacc")
        from . import provable as _provable

        _provable.ON_GAP = self._note_unaccounted
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

    def _note_unaccounted(self, key: str) -> None:
        """The general rule found something it cannot account for in the running test: never store it."""
        try:
            self.flag(self._cur(), "unacc", key)
        except Exception:
            pass   # between contexts (nothing to flag): the test is refused by the verifier regardless

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        try:
            from . import provable as _provable

            _provable.ON_GAP = None
        except Exception:
            pass
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

            def checked(path, *args, **kwargs):
                if cap._in_stat or kwargs.get("dir_fd") is not None:
                    return orig(path, *args, **kwargs)
                try:
                    # review R-023c E2: whatever frames are between (tarfile, pytest's LocalPath, Path.stat), the
                    # status goes to user code or it does not
                    user = _reaches_user(_getframe(1))
                except Exception:
                    user = True  # cannot tell: the default is an input
                if not user:
                    return orig(path, *args, **kwargs)
                fd = isinstance(path, int)
                nolink = own or kwargs.get("follow_symlinks") is False
                kind = sized = False
                if not fd:
                    cap._in_stat = True
                    try:
                        if name == "access":
                            # the path's metadata (kind, permission bits), and (review R-023c E4) the owner and the
                            # other status fields when a permission is asked
                            cap.stat_check(path, nolink, True, False, True)
                            mode = args[0] if args else kwargs.get("mode", os.F_OK)
                            if mode != os.F_OK:
                                cap.fields_check(path, nolink)
                        elif name == "readlink":
                            cap.stat_check(path, True, True, False, True)
                        else:
                            # an existence or kind check of the standard library (exists, isfile, is_dir, glob,
                            # realpath) sees the kind; os.stat asked for its own sake the path's metadata (kind, size,
                            # permission bits, modification time: proof::probe_now)
                            kind = _kind_check_caller()
                            sized = name in ("stat", "fstat") and not nolink and not kind
                            cap.stat_check(path, nolink, not kind, False, True)
                            helper = _time_helper_caller()
                            if helper == "getatime":
                                cap.flag(cap._cur(), "mtime", os.fsdecode(os.fspath(path)))
                            elif helper:
                                # os.path.getmtime & co.: the time is read inside the helper, for its caller
                                cap.time_check(path)
                                kind = True
                    except Exception:
                        pass
                    finally:
                        cap._in_stat = False
                r = orig(path, *args, **kwargs)
                if name in ("access", "readlink") or kind:
                    return r  # a boolean, a link's target, a kind check's / time helper's own use (recorded above)
                return _TimedStat(r, cap, path, nolink, sized)

            checked.__name__ = orig.__name__
            checked.__doc__ = orig.__doc__
            checked.__wrapped__ = orig
            rebind(os, name, orig, checked)

        real_stat, real_lstat = os.stat, os.lstat
        for name in ("stat", "lstat", "access", "readlink", "fstat"):
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
                if not _reaches_user(_getframe(1)):  # review R-023c E2
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

    libc = platform.libc_ver()
    if sys.platform == "darwin":
        # macOS has no glibc version: its system libraries (libSystem, libc++, libm in the dyld shared cache) change
        # with the OS release and build, which stand in the libc slot of the key, with the CPU's feature set
        # (audit G-0156, G-0157 family; Linux keys the glibc version as before)
        libc = ("macOS", f"{platform.mac_ver()[0]} {os.uname().version} {_core.cpu_features() or ''}")
    state = (sys.version, sys.implementation.cache_tag, sys.executable, sysconfig.get_config_var("LIBDIR"),
             sysconfig.get_config_var("LDLIBRARY"), platform.system(), platform.machine(), libc,
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


# ---------------------------------------------------------------------------
# Process-level state (F-05 "flip the default", review R-023c, audit G-0160..G-0163): what every test of the process
# can see without a read the capture attributes to one test (C code, libraries reading it at import, the pools and
# limits a test is sized by). It is part of every test's key, except what is on this allowlist, each with its reason.
# A variable on the allowlist is still an input of every test that reads it from Python (os.environ is recorded per
# test); it only stays out of the process-wide part.
ENV_ALLOWLIST: dict[str, str] = {
    **{k: "detpy's own bookkeeping (re-exec, bytecode cache, assertion-rewrite cache, worker hand-over): set by "
          "detpy itself for its own processes, never an input of the project's code"
       for k in ("DETPY_CACHE_IN_PROCESS", "DETPY_ISOLATE", "DETPY_REEXEC", "DETPY_PRECOMPILE_S", "DETPY_PYC_CACHE", "DETPY_BLOCKED_PLUGINS", "DETPY_XDIST_ENV",
                 "DETPY_REWRITE_CACHE", "DETPY_REWRITE_OWN")},
    "DETPY_L0_REF": "detpy's own equivalence tests: selects the Python reference of Level 0 (tests/rust_hotpaths_ref) "
                    "whose results must be identical to the engine's; never set in a project",
    "PYTEST_XDIST_*": "pytest-xdist's per-worker identity: differs between the controller and each worker of one "
                      "session; a test that reads it is keyed per test and pinned to its worker (placement)",
    "PYTEST_CURRENT_TEST": "set by pytest around each test (the running test's id)",
    "PWD": "the shell's copy of the working directory; the project root is part of every key",
    "OLDPWD": "the shell's previous directory: shell bookkeeping",
    "SHLVL": "shell nesting depth: shell bookkeeping",
    "_": "the shell's last command: shell bookkeeping",
    "GITHUB_RUN_ID": "a per-run identifier of GitHub Actions: different on every run by construction",
    "GITHUB_RUN_NUMBER": "a per-run counter of GitHub Actions: different on every run by construction",
    "GITHUB_RUN_ATTEMPT": "the attempt number of a GitHub Actions run",
    "GITHUB_JOB": "the job id of a GitHub Actions run",
    "GITHUB_ACTION": "the step id of a GitHub Actions run",
    "GITHUB_ENV": "a per-step file path of GitHub Actions (a test that reads the file reads it as a data input)",
    "GITHUB_OUTPUT": "a per-step file path of GitHub Actions",
    "GITHUB_PATH": "a per-step file path of GitHub Actions",
    "GITHUB_STATE": "a per-step file path of GitHub Actions",
    "GITHUB_STEP_SUMMARY": "a per-step file path of GitHub Actions",
    "INVOCATION_ID": "systemd's per-invocation identifier",
    "TERM_SESSION_ID": "a terminal's per-session identifier",
    "SSH_CLIENT": "the client address of an SSH login",
    "SSH_CONNECTION": "the addresses of an SSH login",
    "SSH_TTY": "the terminal of an SSH login",
}


def _env_allowed(name: str) -> bool:
    if name in ENV_ALLOWLIST:
        return True
    return any(k.endswith("*") and name.startswith(k[:-1]) for k in ENV_ALLOWLIST)


def _raw_environ() -> dict:
    """os.environ without its recording hooks (the process's environment as C and children see it)."""
    data = getattr(os.environ, "_data", None)
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            k = os.fsdecode(k) if isinstance(k, bytes) else k
            v = os.fsdecode(v) if isinstance(v, bytes) else v
            out[k] = v
        return out
    return dict(os.environ)


def process_identity() -> dict:
    """The process-level state of the session (see ENV_ALLOWLIST). Every part a test may depend on without a read
    the capture attributes to it: the environment (allowlist above), usable CPUs, umask, resource limits, host name,
    the preloaded shared objects, the warning filters, interpreter flags. Part of every test's key."""
    d: dict = {}
    env = _raw_environ()
    d["environment"] = {k: _core.env_value_digest(v) for k, v in sorted(env.items()) if not _env_allowed(k)}
    # review R-053 P: the machine's real values, not the ones --det pins for the tests (_level0.pin_cpu_count,
    # pin_hostname): a test can read the real ones through posix / _socket, so they stay in every key
    from . import _machine

    try:
        d["cpus"] = sorted(_machine._sched_getaffinity(0)) if _machine._sched_getaffinity is not None else None
    except OSError:
        d["cpus"] = None
    d["cpu_count"] = _machine._cpu_count()
    try:
        u = os.umask(0)
        os.umask(u)
        d["umask"] = u
    except OSError:
        d["umask"] = None
    try:
        import resource
        lim = {}
        for name in sorted(dir(resource)):
            if name.startswith("RLIMIT_"):
                try:
                    lim[name] = resource.getrlimit(getattr(resource, name))
                except (OSError, ValueError):
                    lim[name] = None
        d["rlimits"] = lim
    except ImportError:
        d["rlimits"] = None
    try:
        import posix

        d["host"] = posix.uname().nodename
    except (ImportError, AttributeError):
        d["host"] = platform.node()
    d["warnoptions"] = list(sys.warnoptions)
    d["xoptions"] = sorted((str(k), str(v)) for k, v in getattr(sys, "_xoptions", {}).items())
    d["flags"] = repr(sys.flags)
    try:
        d["uid"] = (os.getuid(), os.geteuid(), os.getgid(), os.getegid(), sorted(os.getgroups()))
    except (AttributeError, OSError):
        d["uid"] = None
    return d


def load_store(path: str) -> dict:
    """A store file (proof-cache.json) with every entry's data expanded to its (key, dependency) pairs: store
    version 2 writes each data chunk once (``chunks``) and entries list chunk addresses (py-cache item 4)."""
    with open(path) as fh:
        s = json.load(fh)
    chunks = s.pop("chunks", None) or {}
    groups = s.pop("groups", None) or {}  # groups of chunk addresses ("g...", py-cache)
    for e in (s.get("tests") or {}).values():
        for field in ("data", "env"):
            d = e.get(field) or []
            if d and isinstance(d[0], str):
                addrs = [c for a in d for c in (groups[a] if a.startswith("g") else (a,))]
                e[field] = [list(p) for a in addrs for p in chunks[a]]
    return s


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
        # F-05: process-level state no read attributes to one test is part of every key (ENV_ALLOWLIST)
        "process": process_identity(),
    }


def digest_identity(d: dict) -> str:
    return _core.digest(json.dumps(d, sort_keys=True, default=str).encode())


# ---------------------------------------------------------------------------
def _pure_expr(e) -> bool:
    """An expression whose evaluation at import time defines a value only: constants, names, attribute reads,
    containers and operators of those, lambdas, and pytest's marks and fixtures (``pytest.mark.x(...)``)."""
    if e is None or isinstance(e, (ast.Constant, ast.Name, ast.Lambda)):
        return True
    if isinstance(e, ast.Attribute):
        return _pure_expr(e.value)
    if isinstance(e, (ast.Tuple, ast.List, ast.Set)):
        return all(_pure_expr(x) for x in e.elts)
    if isinstance(e, ast.Dict):
        return all(_pure_expr(k) for k in e.keys if k is not None) and all(_pure_expr(v) for v in e.values)
    if isinstance(e, ast.Starred):
        return _pure_expr(e.value)
    if isinstance(e, ast.UnaryOp):
        return _pure_expr(e.operand)
    if isinstance(e, ast.BinOp):
        return _pure_expr(e.left) and _pure_expr(e.right)
    if isinstance(e, ast.BoolOp):
        return all(_pure_expr(x) for x in e.values)
    if isinstance(e, ast.Compare):
        return _pure_expr(e.left) and all(_pure_expr(x) for x in e.comparators)
    if isinstance(e, ast.IfExp):
        return _pure_expr(e.test) and _pure_expr(e.body) and _pure_expr(e.orelse)
    if isinstance(e, ast.JoinedStr):
        return all(_pure_expr(v.value) if isinstance(v, ast.FormattedValue) else True for v in e.values)
    if isinstance(e, ast.Subscript):
        return _pure_expr(e.value) and _pure_expr(e.slice)
    if isinstance(e, ast.Slice):
        return _pure_expr(e.lower) and _pure_expr(e.upper) and _pure_expr(e.step)
    if isinstance(e, ast.Call):
        f = e.func
        while isinstance(f, (ast.Attribute, ast.Call)):
            f = f.value if isinstance(f, ast.Attribute) else f.func
        return (isinstance(f, ast.Name) and f.id == "pytest" and all(_pure_expr(a) for a in e.args)
                and all(_pure_expr(k.value) for k in e.keywords))
    return False


#: Directories a collection walk never enters, so the conftest walk does not either.
_WALK_SKIP = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".nox", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", "site-packages", ".eggs", "build", "dist", ".detpy"}


def _conftests_in_tree(root: str, rels) -> set:
    """Every ``conftest.py`` under the directory that holds the collected files, relative to ``root``.

    Review R-056 W1, the `-n` half: pytest imports the ``conftest.py`` of every directory it walks, and under
    ``-n`` the controller decides what to reuse BEFORE any worker has collected, so the runner's own list of
    imported conftests (``loaded_conftest_files``) is still empty there. The directories of the collected files
    never reach a directory that holds no test file, which is exactly what the finding changes. A walk of the
    collected files' common directory does, and it needs no cooperation from the runner.

    It is a superset of what pytest imports when the session was given narrower arguments: a conftest in the key
    that pytest did not import can only cost reuse when it changes, never a wrong reuse.
    """
    dirs = {os.path.dirname(r) for r in rels if r}
    if not dirs:
        return set()
    try:
        base = os.path.commonpath(list(dirs)) if len(dirs) > 1 else next(iter(dirs))
    except ValueError:
        base = ""
    out = set()
    start = os.path.join(root, base) if base else root
    for dirpath, dirnames, filenames in os.walk(start):
        dirnames[:] = [d for d in dirnames if d not in _WALK_SKIP and not d.startswith(".")]
        if "conftest.py" in filenames:
            out.add(os.path.relpath(os.path.join(dirpath, "conftest.py"), root))
    # the root conftest, above the common directory
    d = base
    while True:
        out.add(os.path.join(d, "conftest.py") if d else "conftest.py")
        if not d:
            break
        d = os.path.dirname(d)
    return {f for f in out if os.path.exists(os.path.join(root, f))}


def _import_effect_nodes(body) -> list:
    """The top-level statements of a module (and of its class bodies, which run at import too) that may do more
    than define names: anything but imports, ``def``/``class`` with pure decorators and defaults, docstrings,
    assignments of pure expressions to names, and ``if``/``try`` around those."""
    out: list = []
    for st in body:
        if isinstance(st, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
            continue
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = st.args
            if all(_pure_expr(d) for d in st.decorator_list) and all(_pure_expr(d) for d in a.defaults) \
                    and all(_pure_expr(d) for d in a.kw_defaults):
                continue
            out.append(st)
            continue
        if isinstance(st, ast.ClassDef):
            if not (all(_pure_expr(d) for d in st.decorator_list) and all(_pure_expr(b) for b in st.bases)
                    and all(_pure_expr(k.value) for k in st.keywords)):
                out.append(st)
                continue
            out.extend(_import_effect_nodes(st.body))
            continue
        if isinstance(st, (ast.Assign, ast.AnnAssign)):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            if all(isinstance(t, (ast.Name, ast.Tuple)) and all(isinstance(x, ast.Name) for x in (
                    t.elts if isinstance(t, ast.Tuple) else [t])) for t in targets) and _pure_expr(st.value):
                continue
            out.append(st)
            continue
        if isinstance(st, ast.If) and _pure_expr(st.test):
            out.extend(_import_effect_nodes(st.body))
            out.extend(_import_effect_nodes(st.orelse))
            continue
        if isinstance(st, ast.Try):
            out.extend(_import_effect_nodes(st.body))
            for hd in st.handlers:
                out.extend(_import_effect_nodes(hd.body))
            out.extend(_import_effect_nodes(st.orelse))
            out.extend(_import_effect_nodes(st.finalbody))
            continue
        out.append(st)
    return out


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
        self.iso_scope = "test"
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
        self.prefix_check(nids)
        self.demote_for_running([nids])

    # -- the tests a reused result was recorded after (in-process) ---------------------------------------------------
    PREFIX_FILES = {"file": "prefix-file.json", "session": "prefix-session.json"}

    @staticmethod
    def engine_json_load(path):
        """The engine's own state file, read as detpy's probe: the capture never takes it for a test's input (the
        runner shells decide while the capture runs; prefix-session.json was a data input of every unittest test)."""

        def load():
            try:
                with open(path) as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                return None

        return _core.detpy_probe_call(load)

    @staticmethod
    def engine_json_save(path, data, **kw) -> None:
        """Written as detpy's probe, atomically (see ``engine_json_load``)."""

        def save():
            try:
                tmp = path + f".tmp{os.getpid()}"
                with open(tmp, "w") as fh:
                    json.dump(data, fh, **kw)
                os.replace(tmp, path)
            except OSError:
                pass

        _core.detpy_probe_call(save)

    def _prefix_scope(self):
        """'file' (--det-isolate-scope=file: a file's tests share one child), 'session' (a serial session without
        isolation: every earlier test of the process), None (one child per test: no earlier test; the xdist
        controller: Checker's planned predecessors, preds_check)."""
        if getattr(self, "iso_scope", "test") == "file":
            return "file"
        if getattr(self, "isolate", False) or self.role in ("controller", "worker"):
            return None
        return "session"

    @staticmethod
    def _prefixes(nids, scope) -> dict:
        """Per test, the digest of the tests collected before it in its file (scope 'file') or in the session."""
        import hashlib

        seen: dict = {}
        out = {}
        for n in nids:
            lst = seen.setdefault(n.split("::", 1)[0] if scope == "file" else "", [])
            out[n] = hashlib.blake2b("\0".join(lst).encode(), digest_size=12).hexdigest()
            lst.append(n)
        return out

    IMPORT_EFFECTS_FILE = "import-effects.json"

    def _import_effects(self, nids) -> str:
        """Exam F-05.probe.import-side-effect: every collected test module's import-time code runs before any test of
        the process (collection), and what it does to other modules' state (``json.dumps = ...``) is not followed by
        the capture. The digest of the collected modules' top-level statements that may act beyond defining names
        (``_import_effect_nodes``); a module of definitions and imports only adds nothing."""
        import hashlib

        h = hashlib.blake2b(digest_size=12)
        root = self.root
        for rel in sorted({n.split("::", 1)[0] for n in nids}):
            path = os.path.join(root, rel)
            if not rel.endswith(".py"):
                continue
            try:
                with open(path, "rb") as fh:
                    tree = ast.parse(fh.read(), filename=path)
            except (OSError, SyntaxError, ValueError):
                h.update(f"{rel}\0?\0".encode())
                continue
            eff = _import_effect_nodes(tree.body)
            if eff:
                h.update(f"{rel}\0".encode())
                for node in eff:
                    h.update(ast.dump(node).encode())
                    h.update(b"\0")
        return h.hexdigest()

    def import_effects_check(self, nids) -> None:
        """A reused result was recorded after the same import-time effects of the collected test modules (see
        ``_import_effects``); unknown: not reused."""
        try:
            now = _core.detpy_probe_call(lambda: self._import_effects(nids))
        except Exception:
            now = None
        self.effects_now = now
        stored = self.engine_json_load(os.path.join(self.dir, self.IMPORT_EFFECTS_FILE))
        self.effects_stored = stored if isinstance(stored, dict) else {}
        for n in nids:
            if self._is_hit(n) and (now is None or self.effects_stored.get(n) != now):
                self._demote(n, "code: import-time code of the collected test modules changed (it runs before every test)")

    OUTSIDE_IMPORTS_GLOB = "outside-imports"

    def _outside_import_files(self) -> dict:
        """Every module file the process has imported from OUTSIDE the project, with the digest of its content.

        Review R-056 W7: the runtime key holds each installed distribution as a name and a version, so a file
        edited in place under an unchanged version is invisible -- which is what happens with a dependency
        installed from a git branch, with patched site-packages and with a CI cache of a venv. The capture tracks
        code only inside the project root (`want` in `crates/detpy-py/src/capture.rs`), so none of these files is
        a dependency of anything today.

        The content of what the run actually imported is the answer that needs no version to be honest.
        """
        import hashlib

        root_sep = os.path.join(os.path.abspath(self.root), "")
        out = {}
        for mod in list(sys.modules.values()):
            f = getattr(mod, "__file__", None)
            if not f or not isinstance(f, str) or f.startswith("<"):
                continue
            try:
                p = os.path.realpath(f)
            except OSError:
                continue
            if p.startswith(root_sep) or not p.endswith((".py", ".so", ".pyd", ".dylib")):
                continue
            try:
                with open(p, "rb") as fh:
                    out[p] = hashlib.blake2b(fh.read(), digest_size=12).hexdigest()
            except OSError:
                out[p] = "?"
        return out

    def outside_imports_save(self) -> None:
        """One file per recording process (no two writers, so no merge race under ``-n``)."""
        if self.role == "controller":
            return
        try:
            files = _core.detpy_probe_call(self._outside_import_files)
        except Exception:
            return
        who = getattr(self, "worker", None) or self.role
        self.engine_json_save(os.path.join(self.dir, f"{self.OUTSIDE_IMPORTS_GLOB}.{who}.json"), files)

    def outside_imports_check(self, nids) -> None:
        """A reused result was recorded against the installed code that is on disk now; otherwise it is not reused.

        The stored list is what the recording process imported from outside the project. Re-reading exactly those
        paths works in the controller too, which never imports the project's modules under ``-n`` and so could
        never answer this from its own ``sys.modules``. A test cannot import a NEW outside module without its own
        code changing, which the code prefix already holds.
        """
        import glob
        import hashlib

        stored: dict = {}
        for path in sorted(glob.glob(os.path.join(self.dir, f"{self.OUTSIDE_IMPORTS_GLOB}.*.json"))):
            part = self.engine_json_load(path)
            if isinstance(part, dict):
                stored.update(part)
        if not stored:
            return

        def changed():
            for p, d in stored.items():
                try:
                    with open(p, "rb") as fh:
                        now = hashlib.blake2b(fh.read(), digest_size=12).hexdigest()
                except OSError:
                    now = "?"
                if now != d:
                    return p
            return None

        try:
            bad = _core.detpy_probe_call(changed)
        except Exception:
            bad = "unknown"
        if bad is None:
            return
        where = bad if bad != "unknown" else "an installed file the engine could not read"
        for n in nids:
            if self._is_hit(n):
                self._demote(n, f"code: installed code the run imports changed in place ({where})")

    def import_effects_save(self) -> None:
        now = getattr(self, "effects_now", None)
        if now is None:
            return
        stored = dict(getattr(self, "effects_stored", {}))
        nids = getattr(self, "prefix_nids", None) or []
        stored.update({n: now for n in nids if not self._is_hit(n)})
        self.engine_json_save(os.path.join(self.dir, self.IMPORT_EFFECTS_FILE), stored)

    def prefix_check(self, nids) -> None:
        """A result recorded in-process is reused only when the tests before it in its process (its file's child, or
        the serial session) are those it was recorded after: a test that did not run then (added, or deselected by
        -k) runs before it in a fresh run and may leave state it reads, and the carried set cannot hold it.
        Unknown: not reused."""
        self.prefix_nids = list(nids)
        self.import_effects_check(nids)
        self.outside_imports_check(nids)
        scope = self._prefix_scope()
        self.prefix_scope = scope
        if scope is None:
            return
        now = self._prefixes(nids, scope)
        self.prefix_now = now
        stored = self.engine_json_load(os.path.join(self.dir, self.PREFIX_FILES[scope]))
        self.prefix_stored = stored if isinstance(stored, dict) else {}
        where = "file" if scope == "file" else "session"
        for n in nids:
            if self._is_hit(n) and self.prefix_stored.get(n) != now[n]:
                self._demote(n, f"placement: the tests before it in its {where} are not those it was recorded after")

    CODE_PREFIX_FILE = "code-prefix.json"

    def code_prefix_stale(self, lists) -> set:
        """Review R-052: per test, the digest of the contents of the distinct test files at or before it in its process
        (``lists``: the tests of each process, in order); the tests whose digest differs from the one stored when they
        last ran (unknown: stale)."""
        import hashlib

        content: dict = {}

        def digest_of(rel):
            if rel not in content:
                try:
                    with open(os.path.join(self.root, rel), "rb") as fh:
                        content[rel] = hashlib.blake2b(fh.read(), digest_size=12).hexdigest()
                except OSError:
                    content[rel] = "?"
            return content[rel]

        # The whole collected set, not the files at or before the test in collection order.
        #
        # Review R-056 W2 (6 wrong results under `-n 2`, MEASURED): pytest imports EVERY collected test module
        # before it runs any test, in the serial session and in EVERY xdist worker -- each worker collects the
        # whole session. So the import-time code of a file that comes LATER in the collection order has already
        # run in this test's process. This code used to digest the files at or before the test and called them
        # "a superset: conservative"; under `-n` they are a SUBSET, so a new `conftest.py` or `__init__.py`, a new
        # decorator, class base or annotation in a later file changed what ran before the victim and the cache
        # reused it all the same. Serially the same gap was covered only by the blunt rule that reruns every
        # earlier test of an edited file, not by this digest.
        #
        # One digest over the whole collected set, the same for every test of the session, is exact for both, and
        # it does not depend on reading the later file's intent: whatever that code does, the file's bytes are in
        # the key. It costs reuse -- any change to any collected file invalidates the session -- which is what
        # precise per-test tracking (P-061) exists to give back.
        #
        # Per-file children (--det-isolate-scope=file): the process really is the file, so the old per-process
        # lists stay.
        whole_session = getattr(self, "iso_scope", "test") != "file"
        if whole_session:
            order = list(getattr(self, "prefix_nids", None) or [n for lst in lists for n in lst])
            present = {n for lst in lists for n in lst}
            lists = [[n for n in order if n in present]]

        def loaded_with(rel):
            """review R-053 K1: the conftest.py and __init__.py files pytest loads with a test file (its directory and
            every parent up to the root): their import-time code and fixtures act on the state as the test file's do"""
            out = []
            d = os.path.dirname(rel)
            while True:
                for name in ("conftest.py", "__init__.py"):
                    out.append(os.path.join(d, name) if d else name)
                if not d:
                    return out
                d = os.path.dirname(d)

        def files_of(nids):
            """Every distinct file the process imports for these tests, with the conftest and ``__init__`` files
            pytest loads with each one, and every conftest the runner says it imported (W1: a directory with no
            test file in it), in a fixed order."""
            out = []
            done = set()
            for rel in sorted({n.split("::", 1)[0] for n in nids}):
                for f in [rel, *loaded_with(rel)]:
                    if f not in done:
                        done.add(f)
                        out.append(f)
            try:
                extra = set(self.loaded_conftest_files())
            except Exception:
                extra = set()
            extra |= _conftests_in_tree(self.root, [n.split("::", 1)[0] for n in nids])
            for f in sorted(extra):
                if f not in done:
                    done.add(f)
                    out.append(f)
            return out

        def compute():
            now = {}
            for lst in lists:
                if whole_session:
                    # one digest over the whole collected set, shared by every test of this session
                    h = hashlib.blake2b(digest_size=12)
                    for f in files_of(lst):
                        # an absent file reads "?": one that appears changes the digest
                        h.update(f"{f}\0{digest_of(f)}\0".encode())
                    d = h.hexdigest()
                    for n in lst:
                        now[n] = d
                    continue
                h = hashlib.blake2b(digest_size=12)
                done = set()
                for n in lst:
                    rel = n.split("::", 1)[0]
                    for f in [rel, *loaded_with(rel)]:
                        if f not in done:
                            done.add(f)
                            h.update(f"{f}\0{digest_of(f)}\0".encode())
                    now[n] = h.copy().hexdigest()
            return now

        now = _core.detpy_probe_call(compute)
        if getattr(self, "code_prefix_stored", None) is None:
            stored = self.engine_json_load(os.path.join(self.dir, self.CODE_PREFIX_FILE))
            self.code_prefix_stored = stored if isinstance(stored, dict) else {}
        self.code_prefix_now = {**getattr(self, "code_prefix_now", {}), **now}
        return {n for n, d in now.items() if self.code_prefix_stored.get(n) != d}

    def code_prefix_save(self) -> None:
        now = getattr(self, "code_prefix_now", None)
        if not now:
            return
        stored = dict(getattr(self, "code_prefix_stored", None) or {})
        stored.update({n: d for n, d in now.items() if not self._is_hit(n)})
        self.engine_json_save(os.path.join(self.dir, self.CODE_PREFIX_FILE), stored)

    def prefix_save(self) -> None:
        self.code_prefix_save()
        self.import_effects_save()
        self.outside_imports_save()
        now = getattr(self, "prefix_now", None)
        scope = getattr(self, "prefix_scope", None)
        if now is None or scope is None:
            return
        stored = dict(getattr(self, "prefix_stored", {}))
        stored.update({n: d for n, d in now.items() if not self._is_hit(n)})
        self.engine_json_save(os.path.join(self.dir, self.PREFIX_FILES[scope]), stored)

    def demote_for_running(self, lists) -> list:
        """Review R-023c E7: a test that runs in this session runs after the earlier tests of its process whose
        in-process state it may consume (the tests of its carried set when it was recorded, ``Entry::needs``; every
        earlier test when it reached the library node, or when it has no entry), as in a fresh run of the suite: those
        are not reused. A demoted test runs too: its own predecessors follow, and so do the reused writers whose output
        it reads (review R-023b N8). ``lists``: the tests of each process, in order. Not under --det-isolate (each test
        in its own child: no in-process state reaches it). Returns the demoted tests."""
        out: list = []
        file_scope = getattr(self, "iso_scope", "test") == "file"
        if getattr(self, "isolate", False) and not file_scope:
            self.code_prefix_stale(lists)  # recorded in every mode: a later session in another mode compares with it
            return out
        if file_scope:
            # --det-isolate-scope=file: a file's tests share one child, in order; the process is the file
            files: dict = {}
            for lst in lists:
                for n in lst:
                    files.setdefault(n.split("::", 1)[0], []).append(n)
            lists = list(files.values())
        ids = [n for lst in lists for n in lst]
        needs = dict(zip(ids, self.store.needs(ids)))
        # review R-052 (S1, S3, S5, C3, C5): stored needs were computed from the code as it was; when the test file of
        # the test or of an earlier test of its process changed since, they may be stale (an earlier test now writes
        # the state this one reads). Such a test is not reused, and its needs are unknown: every earlier test runs.
        stale = self.code_prefix_stale(lists)
        for n in ids:
            if n in stale:
                needs[n] = None
                if self._is_hit(n) and self._demote(n, "code: a test file at or before it in its process changed (its "
                                                       "stored needs may be stale)"):
                    out.append(n)
        # review R-050 P2: a test with no entry has the needs it had when it last ran (a failure, a refusal), or every
        # earlier test when it never ran (``Store::needs_of``): the polluter of an earlier file was reused, not run,
        # and the victim passed
        present = set(ids)
        changed = True
        while changed:
            changed = False
            for lst in lists:
                for i in range(len(lst) - 1, -1, -1):
                    n = lst[i]
                    if self._is_hit(n):
                        continue
                    need = needs.get(n)
                    want = None if need is None else set(need)
                    for m in lst[:i]:
                        if (want is None or m in want) and self._demote(
                                m, f"placement: a predecessor of {n}, which runs in this session"):
                            out.append(m)
                            changed = True
                    if want is None:
                        break
            for w, r in self.store.edges():
                if r in present and w in present and self._is_hit(w) and not self._is_hit(r):
                    if self._demote(w, f"reader: its output is read by {r}, which runs in this session"):
                        out.append(w)
                        changed = True
        return out

    def _is_hit(self, nid) -> bool:
        return self.sess.is_hit(nid)

    def _demote(self, nid, why) -> bool:
        return self.sess.demote(nid, why)

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

    def loaded_conftest_files(self) -> list:
        """The ``conftest.py`` files the runner has actually imported, relative to the root.

        Review R-056 W1: pytest imports the ``conftest.py`` of EVERY directory it walks during collection, including
        a directory that holds no test file at all (``tests/c/conftest.py`` next to a data file). Its import-time
        code runs before every test of the process, and walking the directories of the COLLECTED files never finds
        it. The runner's own list of imported conftest modules is the exact answer, so the shell overrides this.
        """
        return []

    # -- end of session ------------------------------------------------------------
    def finish(self, fingerprints: dict) -> None:
        """Record every test that ran, compare the verified ones, write the receipts. ``fingerprints``: the Level 0
        fingerprints of the tests that ran."""
        sess, cap = self.sess, self.cap
        sess.add_fingerprints(fingerprints)
        cap.switch("s")
        try:
            self._outside_modules()
        except Exception:
            pass
        cap.stop()
        if self.isolate and not self.iso_child:
            # --det-isolate: nothing ran in this process; the children's shards are merged here (serial) or by the
            # controller (worker)
            if self.role == "worker":
                return
            self.iso_merge_summaries()
            self.iso_flush()
            self.merge_shards(list(self.iso_shards))
        if self.role == "controller" or (self.isolate and not self.iso_child):
            # no test ran here: the workers (or children) recorded, the merge happened in merge_workers
            sess.t_record = self.sess.phase("merge")
            sess.compare_verified()
            sess.write_receipts(self.store)
            self._receipts_extras()
            self._shared_push()
            self._after_session()
            return
        t0 = _perf()
        try:
            if not getattr(self, "real_clock", False):  # the real-clock check reads the cache, never writes it
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
        self._receipts_extras()
        self._shared_push()
        self._after_session()

    # -- receipts: what changed in a configuration miss, and a history of runs ---------------------------------------
    _HISTORY = 30

    def _config_file(self, digest: str) -> str:
        return os.path.join(self.dir, "configs", f"{digest}.json")

    def _save_config(self) -> None:
        """The parts of this session's configuration digest (process identity included), once per digest: a later
        miss with reason "config" names the parts that changed (audit G-2197, G-1509)."""
        p = self._config_file(self.config_digest)
        if os.path.exists(p):
            return
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = f"{p}.{os.getpid()}"
            with open(tmp, "w") as fh:
                json.dump(self.config_info, fh, sort_keys=True, default=str)
            os.replace(tmp, p)
        except OSError:
            pass

    @staticmethod
    def _changed_parts(old: dict, new: dict, prefix: str = "") -> list:
        out = []
        for k in sorted(set(old) | set(new)):
            a, b = old.get(k), new.get(k)
            if a == b:
                continue
            name = f"{prefix}{k}"
            if isinstance(a, dict) and isinstance(b, dict) and len(out) < 20:
                out.extend(ProofSession._changed_parts(a, b, name + "."))
            elif k == "options" and isinstance(a, list) and isinstance(b, list):
                da, db = dict(map(tuple, a)), dict(map(tuple, b))
                out.extend(f"option {o}" for o in sorted(set(da) | set(db)) if da.get(o) != db.get(o))
            else:
                out.append(name)
        return out

    def _previous_config(self):
        d = os.path.join(self.dir, "configs")
        try:
            files = [(os.path.getmtime(os.path.join(d, f)), f[:-5]) for f in os.listdir(d)
                     if f.endswith(".json") and f[:-5] != self.config_digest]
        except OSError:
            return None
        return max(files)[1] if files else None

    def _receipts_extras(self) -> None:
        cap, was = self.cap, getattr(self.cap, "active", False)
        cap.active = False
        try:
            self._save_config()
            path = self.receipts_path
            if not os.path.exists(path):
                return
            with open(path) as fh:
                lines = [json.loads(x) for x in fh if x.strip()]
            changed = False
            memo: dict = {}
            for r in lines:
                why = r.get("why") or ""
                if not why.startswith("config") or "(changed:" in why:
                    continue
                try:
                    old_digest = json.loads(self.store.entry(r["nodeid"])).get("config")
                except Exception:
                    old_digest = None
                if old_digest in (None, self.config_digest):
                    # recorded again in this session: the configuration of the previous session (the newest other)
                    old_digest = self._previous_config()
                if old_digest not in memo:
                    try:
                        with open(self._config_file(old_digest)) as fh:
                            memo[old_digest] = self._changed_parts(json.load(fh), json.loads(
                                json.dumps(self.config_info, default=str)))
                    except (OSError, ValueError):
                        memo[old_digest] = None
                parts = memo[old_digest]
                if parts:
                    r["why"] = f"{why} (changed: {', '.join(parts[:12])})"
                    changed = True
            if changed:
                with open(path, "w") as fh:
                    fh.writelines(json.dumps(r) + "\n" for r in lines)
            # audit G-2196: every run's receipts are kept (the last _HISTORY runs) beside the latest
            hist = os.path.join(self.dir, "receipts")
            os.makedirs(hist, exist_ok=True)
            import shutil

            shutil.copyfile(path, os.path.join(hist, f"{self.run_id}.jsonl"))
            old = sorted(os.listdir(hist))
            for name in old[:-self._HISTORY]:
                try:
                    os.remove(os.path.join(hist, name))
                except OSError:
                    pass
        except Exception:
            pass
        finally:
            cap.active = was

    def _outside_modules(self) -> None:
        """Audit G-0164 (F-05): a module loaded from outside the project root, the standard library and every
        installed distribution's RECORD (PYTHONPATH, a directory a .pth file adds, a file dropped into site-packages)
        is code the capture does not follow. Its content is an input of every test of the process (the start-up
        context: a module may have been imported by any test, or at import time of any other)."""
        cap = self.cap
        root = os.path.realpath(self.root) + os.sep
        stdlib = tuple(d + os.sep for d in _sites._stdlib_dirs)
        ctx = cap.ctx_index("")
        seen = set()
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if not isinstance(f, str) or not f:
                continue
            try:
                p = os.path.realpath(f)
            except (OSError, ValueError):
                continue
            if p in seen or p.startswith(root) or p.startswith(stdlib) or p.startswith(_DETPY_DIR):
                continue
            seen.add(p)
            if not os.path.isfile(p) or cap._installed(p):
                continue
            cap.read(ctx, p, "f")

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
            self.prefix_save()
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
        self.prefix_save()
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
        try:
            # audit G-0164 in a child too (exam F-05.wrong-reuse.pythonpath: a module from PYTHONPATH outside the
            # root, imported at collection in the parent, was not an input of the children's results)
            self._outside_modules()
        except Exception:
            pass
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
            # folded into this process's one shard now (py-cache: one shard per child repeated every carried file's
            # facts: 648 shards, 1.4 GB on esphome); a shard that cannot be read is merged as it is
            try:
                ok = self.store.shard_absorb(shard)
            except Exception:
                ok = False
            if not ok:
                self.iso_shards.append(shard)

    def iso_flush(self) -> None:
        """The children's shards folded by ``iso_child_done``, written as one shard (before the merge or the
        controller's)."""
        path = os.path.join(self.dir, "shards", f"{self.run_id}.{getattr(self, 'worker', None) or 'iso'}.isolate.json")
        try:
            if self.store.shard_absorbed_save(path, str(getattr(self, "worker", None) or "iso")):
                self.iso_shards.append(path)
        except Exception as e:  # nothing recorded this time
            self.sess.error = f"isolate shard: {type(e).__name__}: {e}"

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
    # known before the first lookup (claude/parallel-proof-3 9b20f6a): a root conftest is imported between the start
    # and pytest_configure, and its module lookups must not key site-packages or the standard library as searched
    # directories (each is covered by the runtime identity, or by the per-distribution identity under
    # --det-cache-dists)
    cap.stdlib_dirs = tuple(d + os.sep for d in _sites._stdlib_dirs)
    cap.site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
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


