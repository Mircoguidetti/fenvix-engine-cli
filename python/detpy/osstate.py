"""Process and operating-system state a test can observe (the ``os`` control; review P1 finding 4, F-01/F-03).

The rule this module enforces: under ``--det`` every source of nondeterminism a test can observe is either
controlled (pinned or virtualised, like the clock) or recorded as an event the verifier compares; none stays silently
real. What it covers:

* **Process identity (controlled).** ``os.getpid()``, ``os.getppid()`` and ``threading.get_native_id()`` (on the
  test's main thread) called by user code (the project and its libraries) return virtual values: ``10000`` in a
  serial session, ``10001 + N`` in xdist worker ``gwN`` (distinct per worker, so per-process file names stay unique
  across workers), parent ``9999`` (``10000`` for a worker). The standard library and test infrastructure keep the
  real values (fork detection in ``tempfile``, ``multiprocessing``, ``logging``), and so does every other process:
  a forked or spawned child is already an uncontrolled source (``uncontrolled.child``).
* **Temporary names (controlled).** The session gets its own empty temporary directory
  (``<tmp>/fenvix-det[-gwN]``, emptied when the session starts, guarded by a lock: a second concurrent session takes
  ``fenvix-det.1`` ...), set as ``tempfile.tempdir``; pytest's ``tmp_path`` lives under it too. Names drawn by
  ``tempfile`` are seeded per test (``seeds``), so with no leftovers of earlier runs a name no longer depends on what
  the machine's ``/tmp`` holds (MEASURED by the review: ``mkdtemp`` collided with the previous run's directory and
  took the next name).
* **Virtual files (controlled).** ``/dev/urandom`` and ``/dev/random`` opened for reading with ``open``/``io.open``
  (and so ``pathlib``) give a stream seeded from the test (a device read as a file is not the OS entropy API:
  ``os.urandom``/``secrets`` stay observed, or seeded with ``--det-urandom``). ``/proc/uptime`` reads the virtual
  monotonic clock (with the ``time`` control).
* **Everything else read from the OS as a file (recorded).** An audit hook on ``open`` (every opener: ``open``,
  ``os.open``, ``pathlib``, C code going through Python's I/O) records, for a file user code opens for reading
  (anywhere but the interpreter's installation and the session's temporary directories; Python sources and compiled
  modules, which the import system reads, excepted), one ``fs.read`` event with the file's path and a digest of its
  content (a file absent is recorded as absent). Files in the project are included: a state an earlier run left
  there (a counter, a cache file) is an input like a file outside it. ``/proc`` and ``/sys``
  files are files: their content is digested, so ``/proc/self/stat`` or ``/proc/loadavg`` make the verifier name the
  read. A device, FIFO or socket opened that way (other than ``/dev/null``, ``/dev/zero``, terminals and the
  standard streams) marks the test ``uncontrolled.device``: what it delivers cannot be digested.
* **OS measurements (recorded).** ``os.getloadavg``, ``os.statvfs`` / ``os.fstatvfs`` (``shutil.disk_usage``): one
  event with a digest of the value.

Not covered (DECLARED): reads done in C without Python's I/O (an extension calling ``fopen``), ``Thread.native_id``
attributes, ``multiprocessing.current_process().pid`` (standard library: real PID), the memory, page-fault, I/O and
context-switch counters of ``resource.getrusage`` (its CPU times are virtual; a call cannot be recorded only when
those fields are read, and recording every call made tests that read only the CPU times never identical: G-1515).
"""

from __future__ import annotations

import builtins
import hashlib
import io
import os
import stat as _stat
import sys
import tempfile
import threading

from . import _core, _sites, _state

VPID_BASE = 10000
_ACTIVE = False
_SESSION_PID: int | None = None
VPID: int | None = None
VPPID: int | None = None
TMPDIR: str | None = None
_LOCK_FD: int | None = None
_EXCLUDED: list = []  # directories whose files are not recorded (absolute, normalised)
_counter = [0]
_tls = threading.local()

_real_getpid = os.getpid
_real_getppid = os.getppid
_real_native_id = getattr(threading, "get_native_id", None)
_real_os_open = os.open
_real_os_read = os.read
_real_close = os.close
_real_fstat = os.fstat
_real_stat = os.stat
_real_lstat = os.lstat
_getframe = sys._getframe

# devices whose content is fixed or is the test's own stream: opening them observes nothing
_QUIET_DEVICES = frozenset({"/dev/null", "/dev/zero", "/dev/full", "/dev/tty", "/dev/stdin", "/dev/stdout",
                            "/dev/stderr", "/dev/console", "/dev/ptmx"})
_QUIET_PREFIXES = ("/dev/fd/", "/proc/self/fd/", "/dev/pts/", "/dev/shm/")
_DIGEST_FULL = 1 << 20  # files up to 1 MiB are digested whole; larger ones: size, mtime, first and last 64 KiB
_DIGEST_EDGE = 1 << 16


# ---------------------------------------------------------------------------------------------------------------
# process identity

def _user_caller() -> bool:
    """The code that called the patched function is user code (the project or a library), not the standard library
    or test infrastructure."""
    try:
        f = _getframe(2)
    except ValueError:  # pragma: no cover
        return False
    return _sites._classify(f.f_code.co_filename)[0] == _sites._USER


def getpid() -> int:
    """``os.getpid`` under ``--det`` (``detpy.osstate``): a virtual PID for user code in the session's process."""
    real = _real_getpid()
    if _ACTIVE and real == _SESSION_PID and _user_caller():
        return VPID
    return real


def getppid() -> int:
    """``os.getppid`` under ``--det`` (``detpy.osstate``): a virtual parent PID for user code."""
    if _ACTIVE and _real_getpid() == _SESSION_PID and _user_caller():
        return VPPID
    return _real_getppid()


def get_native_id() -> int:
    """``threading.get_native_id`` under ``--det``: on the session's main thread (whose native id is the PID), the
    virtual PID for user code. Other threads are uncontrolled sources (``uncontrolled.thread``)."""
    real = _real_native_id()
    if _ACTIVE and real == _SESSION_PID and _user_caller():
        return VPID
    return real


def _worker_index() -> int | None:
    w = os.environ.get("PYTEST_XDIST_WORKER", "")
    if w.startswith("gw") and w[2:].isdigit():
        return int(w[2:])
    return None


# ---------------------------------------------------------------------------------------------------------------
# the session's temporary directory

def _session_tmp() -> str | None:
    import fcntl
    import shutil

    base = os.path.realpath(tempfile.gettempdir())
    w = os.environ.get("PYTEST_XDIST_WORKER", "")
    name = "fenvix-det" + (f"-{w}" if w else "")
    for n in range(64):
        d = os.path.join(base, name + (f".{n}" if n else ""))
        try:
            fd = _real_os_open(d + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _real_close(fd)
            continue
        try:
            if os.path.islink(d) or (os.path.exists(d) and not os.path.isdir(d)):
                os.unlink(d)
            shutil.rmtree(d, ignore_errors=True)
            os.mkdir(d, 0o700)
        except OSError:
            _real_close(fd)
            continue
        global _LOCK_FD
        _LOCK_FD = fd
        return d
    return None


# ---------------------------------------------------------------------------------------------------------------
# virtual files

class _EntropyRaw(io.RawIOBase):
    """A seeded, endless byte stream standing for ``/dev/urandom`` (blake2b of the seed and a block counter)."""

    def __init__(self, path: str, seed: int) -> None:
        super().__init__()
        self.name = path
        self.mode = "rb"
        self._key = seed.to_bytes(16, "little", signed=False)
        self._block = 0
        self._buf = b""

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        n = len(b)
        while len(self._buf) < n:
            self._buf += hashlib.blake2b(self._block.to_bytes(8, "little"), key=self._key).digest()
            self._block += 1
        b[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n


def _args_of(args, kwargs, idx: int, name: str, default):
    if len(args) > idx:
        return args[idx]
    return kwargs.get(name, default)


def _virtual_entropy(path: str, mode: str, args, kwargs):
    st = _state.STATE
    _counter[0] += 1
    seed = _core.derive_seed(st.config.seed, f"{st.nodeid or '<session>'}\0{path}#{_counter[0]}")
    raw = _EntropyRaw(path, seed & ((1 << 128) - 1))
    _state.record("fs", "open.virtual", path, _user_depth(2))
    buffering = _args_of(args, kwargs, 0, "buffering", -1)
    if "b" in mode:
        return raw if buffering == 0 else io.BufferedReader(raw)
    return io.TextIOWrapper(io.BufferedReader(raw), encoding=_args_of(args, kwargs, 1, "encoding", None),
                            errors=_args_of(args, kwargs, 2, "errors", None),
                            newline=_args_of(args, kwargs, 3, "newline", None))


def _virtual_uptime(path: str, mode: str, args, kwargs):
    if "time" not in _state.STATE.config.controls:
        return None  # the real file: recorded by the audit hook
    from . import clock

    e = _core.clock_read()
    _state.record("time", "proc.uptime", str(e), _user_depth(2))
    secs = (clock._MONO_BASE_NS + e) / 1e9
    text = f"{secs:.2f} {secs:.2f}\n"
    f = io.BytesIO(text.encode()) if "b" in mode else io.StringIO(text)
    f.name = path
    return f


_VIRTUAL = {"/dev/urandom": _virtual_entropy, "/dev/random": _virtual_entropy, "/proc/uptime": _virtual_uptime}
_prev_open = io.open


def open_(file, mode="r", *args, **kwargs):
    if _ACTIVE and isinstance(file, (str, bytes, os.PathLike)) and isinstance(mode, str) \
            and not any(c in mode for c in "wax+"):
        try:
            p = os.fspath(file)
            if isinstance(p, bytes):
                p = os.fsdecode(p)
        except TypeError:
            p = None
        fn = _VIRTUAL.get(p) if p is not None else None
        if fn is not None and _real_getpid() == _SESSION_PID:
            v = fn(p, mode, args, kwargs)
            if v is not None:
                # the audit event the real open raises: other observers (the cache with proof's rule for /proc,
                # /sys and /dev reads) see the read as they did; this module's own hook skips it
                _tls.busy = True
                try:
                    sys.audit("open", p, mode, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
                finally:
                    _tls.busy = False
                return v
    return _prev_open(file, mode, *args, **kwargs)


# ---------------------------------------------------------------------------------------------------------------
# recorded reads: the audit hook

_OWN = os.path.dirname(os.path.abspath(__file__)) + os.sep


def _user_depth(depth: int) -> int:
    """``depth`` for ``_state.record`` from a function ``depth`` frames below the caller of the opener, past detpy's
    own wrappers (``fstime``'s ``open``, the cache's): the site is the user code whatever the wrapping order."""
    try:
        f = _getframe(depth + 1)
        while f is not None and f.f_code.co_filename.startswith(_OWN):
            f = f.f_back
            depth += 1
    except ValueError:  # pragma: no cover
        pass
    return depth


def _plugin_site(depth: int) -> bool:
    """The first frame past the standard library is a pytest plugin's (``_level0.INFRA_PACKAGES``, ``pytest_*``):
    the runner's machinery read the file, not the test."""
    from . import _level0

    try:
        f = _getframe(depth + 1)
    except ValueError:  # pragma: no cover
        return False
    while f is not None:
        kind = _sites._classify(f.f_code.co_filename)[0]
        if kind != _sites._STDLIB:
            top = str(f.f_globals.get("__name__") or "").split(".", 1)[0]
            return kind == _sites._INFRA or top in _level0.INFRA_PACKAGES or top.startswith("pytest_")
        f = f.f_back
    return False


def _under(p: str, d: str) -> bool:
    return p == d or p.startswith(d if d.endswith(os.sep) else d + os.sep)


def _excluded(p: str) -> bool:
    if "__pycache__" in p or p.endswith(_IMPORTED):
        return True  # the import system's reads: the code, not a state
    for d in _EXCLUDED:
        if _under(p, d):
            return True
    for d in _sites._site_dirs:
        if _under(p, d):
            return True
    for d in _sites._stdlib_dirs:
        if _under(p, d):
            return True
    prov = _sites._basetemp_provider
    if prov is not None:
        try:
            bt = prov()
        except Exception:
            bt = None
        if bt and _under(p, os.path.realpath(bt)):
            return True
    return False


def _digest_file(p: str):
    """(kind, value): ("file", digest) of a regular file's content, ("device", "") for one that cannot be digested,
    ("absent", "") or None (nothing to record)."""
    try:
        st = _real_stat(p)
    except FileNotFoundError:
        return ("absent", "")
    except OSError:
        return None
    mode = st.st_mode
    if _stat.S_ISDIR(mode):
        return None
    if not _stat.S_ISREG(mode):
        return ("device", "")
    try:
        fd = _real_os_open(p, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        h = hashlib.blake2b(digest_size=16)
        size = st.st_size
        if size <= _DIGEST_FULL:  # /proc and /sys files report size 0: read them to the end (at most 4 MiB)
            left = 4 * _DIGEST_FULL
            while left > 0:
                chunk = _real_os_read(fd, 1 << 16)
                if not chunk:
                    break
                h.update(chunk)
                left -= len(chunk)
        else:
            h.update(f"size={size} mtime={st.st_mtime_ns}\0".encode())
            h.update(_real_os_read(fd, _DIGEST_EDGE))
            os.lseek(fd, size - _DIGEST_EDGE, os.SEEK_SET)
            h.update(_real_os_read(fd, _DIGEST_EDGE))
        return ("file", h.hexdigest())
    except OSError:
        return ("file", "<unreadable>")
    finally:
        _real_close(fd)


_O_ACC = getattr(os, "O_ACCMODE", 3)


def _engine_probe(p: str) -> bool:
    """The virtual ``time.sleep`` (Rust, ``clock_children_alive``) reads ``/proc/self/task/<tid>/children`` from the
    sleeping test's frame, with the audit event of ``open``: the engine's own read, not the test's."""
    return p.startswith("/proc/self/task/") and p.endswith("/children")
_IMPORTED = (".py", ".pyc", ".pyo", ".pyi", ".pth", ".so", ".pyd")


# files read outside any test (module scope of a test file or conftest, a dependency at import, a hook): path ->
# content digest. No test's event: they are run inputs (`file:<path>`, _level0.run_inputs / the trace footer), so two
# runs where one differs are never identical (R-055 V3)
OUTSIDE_FILES: dict = {}
# files this process created outside any test (opened with O_CREAT while absent, a SQLite database connected to while
# absent): their content is this run's own output, so a later read of them (or of a file named after them: a SQLite
# journal, coverage's suffixed data files) outside any test is not an input. pytest-cov's ``.coverage.<host>.pid<N>.
# <random>`` files made every test of two runs diverge on a run input that only named the run's own output (MEASURED,
# exam PY-06.pytest-cov.det2, 297/297).
CREATED: set = set()


def _created_by_run(p: str) -> bool:
    if p in CREATED:
        return True
    for c in CREATED:
        if p.startswith(c) and p[len(c):len(c) + 1] in (".", "-"):
            return True
    return False


def _audit(event, args):
    if event == "sqlite3.connect":
        _audit_sqlite(args)
        return
    if event == "ctypes.dlopen":
        _audit_dlopen(args)
        return
    if event != "open" or not _ACTIVE:
        return
    st = _state.STATE
    if getattr(_tls, "busy", False) or _state.is_quiet():
        return
    if st.nodeid is None:
        _audit_outside(args)
        return
    if st.recorder is None:
        return
    try:
        path, _mode, flags = args
    except ValueError:
        return
    if path is None or isinstance(path, int):
        return
    if isinstance(flags, int) and ((flags & _O_ACC) == os.O_WRONLY or flags & os.O_TRUNC):
        return  # a write: an output, not an input
    if _real_getpid() != _SESSION_PID:
        return
    _tls.busy = True
    try:
        p = os.fsdecode(path) if isinstance(path, (bytes, os.PathLike)) else path
        if not isinstance(p, str):
            return
        if not os.path.isabs(p):
            p = os.path.join(_sites._real_getcwd(), p)
        p = os.path.normpath(p)
        if p in _QUIET_DEVICES or p.startswith(_QUIET_PREFIXES) or _excluded(p) or _engine_probe(p):
            return
        got = _digest_file(p)
        if got is None:
            return
        kind, value = got
        depth = _user_depth(1)
        if _plugin_site(depth):
            return
        if kind == "absent":
            if isinstance(flags, int) and flags & os.O_CREAT:
                return  # created by the opener
            _state.record("fs", "fs.read", f"{_sites.norm_path(p)} <absent>", depth)
        elif kind == "device":
            _state.record("other", "uncontrolled.device", _sites.norm_path(p), depth)
        else:
            _state.record("fs", "fs.read", f"{_sites.norm_path(p)} {value}", depth)
    except Exception:  # never break the code under test
        pass
    finally:
        _tls.busy = False


def _note_created(args) -> None:
    """An ``open`` outside any test that creates its file: the file is this run's output from now on."""
    try:
        path, _mode, flags = args
    except ValueError:
        return
    if path is None or isinstance(path, int) or not (isinstance(flags, int) and flags & os.O_CREAT):
        return
    p = os.fsdecode(path) if isinstance(path, (bytes, os.PathLike)) else path
    if not isinstance(p, str):
        return
    if not os.path.isabs(p):
        p = os.path.join(_sites._real_getcwd(), p)
    p = os.path.normpath(p)
    if not os.path.lexists(p):
        CREATED.add(p)


def _readable_path(args):
    try:
        path, _mode, flags = args
    except ValueError:
        return None, None
    if path is None or isinstance(path, int):
        return None, None
    if isinstance(flags, int) and ((flags & _O_ACC) == os.O_WRONLY or flags & os.O_TRUNC):
        return None, None
    p = os.fsdecode(path) if isinstance(path, (bytes, os.PathLike)) else path
    if not isinstance(p, str):
        return None, None
    if not os.path.isabs(p):
        p = os.path.join(_sites._real_getcwd(), p)
    p = os.path.normpath(p)
    if p in _QUIET_DEVICES or p.startswith(_QUIET_PREFIXES) or _excluded(p) or _engine_probe(p):
        return None, None
    return p, flags


def _audit_outside(args) -> None:
    if _real_getpid() != _SESSION_PID:
        return
    _tls.busy = True
    try:
        _note_created(args)
        p, flags = _readable_path(args)
        if p is None or _plugin_site(_user_depth(2)) or _created_by_run(p):
            return
        got = _digest_file(p)
        if got is None:
            return
        kind, value = got
        if kind == "absent" and isinstance(flags, int) and flags & os.O_CREAT:
            return
        OUTSIDE_FILES[_sites.norm_path(p)] = "<absent>" if kind == "absent" else ("<device>" if kind == "device" else value)
    except Exception:  # never break the code under test
        pass
    finally:
        _tls.busy = False


def _audit_sqlite(args) -> None:
    """``sqlite3.connect(path)``: the database file is read by C code, not through ``open`` (R-055 V7): its content
    is an input like a file the test reads (an event in a test, a run input outside one)."""
    if not _ACTIVE or getattr(_tls, "busy", False) or _state.is_quiet() or _real_getpid() != _SESSION_PID:
        return
    try:
        db = args[0]
        p = os.fsdecode(db) if isinstance(db, (bytes, os.PathLike)) else db
        if not isinstance(p, str) or p in ("", ":memory:") or p.startswith("file:"):
            if isinstance(p, str) and p.startswith("file:") and "mode=memory" not in p:
                p = p[5:].split("?", 1)[0]
            else:
                return
        if not os.path.isabs(p):
            p = os.path.join(_sites._real_getcwd(), p)
        p = os.path.normpath(p)
    except Exception:
        return
    _tls.busy = True
    try:
        got = _digest_file(p)
        if got is None:
            return
        kind, value = got
        value = "<absent>" if kind == "absent" else value
        if _state.STATE.nodeid is None:
            if kind == "absent":
                CREATED.add(p)  # SQLite creates it: this run's own database, not an input
                return
            if _created_by_run(p):
                return
            OUTSIDE_FILES[_sites.norm_path(p)] = value
        else:
            _state.record("fs", "sqlite.open", f"{_sites.norm_path(p)} {value}", _user_depth(2))
    except Exception:
        pass
    finally:
        _tls.busy = False


def _audit_dlopen(args) -> None:
    """``ctypes`` loads a native library: its C code reads files, the environment and the clock unobserved (R-055
    V7, V15). In a test: ``uncontrolled.native`` (never identical); outside one: every test is marked through the
    header (``not_proven_outside_tests``: ``native:<library>``)."""
    if not _ACTIVE or _state.is_quiet() or _real_getpid() != _SESSION_PID:
        return
    try:
        name = args[0]
    except Exception:
        return
    if name is None:  # CDLL(None): the process itself (libc): its getenv is recorded (envobs)
        return
    label = os.path.basename(os.fsdecode(name)) if isinstance(name, (bytes, str, os.PathLike)) else str(name)
    if _state.STATE.nodeid is None:
        NATIVE_OUTSIDE.add(label)
        return
    from . import uncontrolled

    uncontrolled._mark("native", f"ctypes loaded {label}", 3)


NATIVE_OUTSIDE: set = set()


def _stat_observed(real, op: str):
    """``os.stat`` / ``os.lstat`` (and through them ``os.path.exists``, ``getmtime``, ``getsize``, ``pathlib``): a
    file's existence, size and modification time read by the test are an input like its bytes (R-055 V6). The event
    carries what the test got (after the virtual file times of fstime); directories and the access time are left
    out (both change as the run itself reads and writes)."""
    def wrapper(path, *args, **kwargs):
        try:
            res = real(path, *args, **kwargs)
        except FileNotFoundError:
            _note_stat(op, path, None)
            raise
        _note_stat(op, path, res)
        return res

    wrapper.__name__ = getattr(real, "__name__", op)
    wrapper.__doc__ = getattr(real, "__doc__", None)
    wrapper.__wrapped__ = real
    return wrapper


def _rebind_stat(patcher, name, wrapper) -> None:
    """Install ``wrapper`` as ``os.<name>`` and wherever the function it replaces was bound before the session (``from
    os import stat`` in a plugin loaded at startup, rebound by fstime): one object for every binding, so the cache
    with proof, which rebinds by identity after this, finds every reference (LIMITS K3). The import system's
    ``posix`` module and detpy's own modules are left alone."""
    import sys

    from ._patch import nonbinding

    prev = getattr(os, name)
    wrapper = nonbinding(wrapper, "os", name)  # one object: patcher.set would make one per module from a function
    patcher.set(os, name, wrapper)
    own = os.path.dirname(os.path.abspath(__file__)) + os.sep
    for mod in list(sys.modules.values()):
        d = getattr(mod, "__dict__", None)
        if not isinstance(d, dict) or mod is os or getattr(mod, "__name__", "") in ("posix", "nt") \
                or str(getattr(mod, "__file__", "") or "").startswith(own):
            continue
        for k, v in list(d.items()):
            if v is prev:
                try:
                    patcher.set(mod, k, wrapper)
                except Exception:
                    pass


def _access_observed(real):
    """``os.access``: whether a path is there and usable is what the test learns (R-055, docs/VERIFY-CONTRACT.md
    section 2: an ``fs.stat`` event, ``<path>|missing`` when access fails, else its type)."""
    def access(path, mode, *args, **kwargs):
        r = real(path, mode, *args, **kwargs)
        if not kwargs.get("dir_fd") and not isinstance(path, int):
            res = None
            if r:
                try:
                    res = _real_stat(path)
                except OSError:
                    res = None
            _note_stat("fs.access", path, res, "exists")
        return r

    access.__name__ = getattr(real, "__name__", "access")
    access.__doc__ = getattr(real, "__doc__", None)
    access.__wrapped__ = real
    return access


OUTSIDE_STATS: dict = {}  # path -> stat value, for metadata calls made outside any test (files_read_outside_tests)


_EXISTS = frozenset(("exists", "lexists", "isfile", "isdir", "islink", "is_file", "is_dir", "is_symlink",
                     "is_fifo", "is_socket", "is_block_device", "is_char_device", "ismount", "samefile", "_is_dir"))


def _stat_question() -> str:
    """What the caller of os.stat asked (a few frames up, in genericpath / posixpath / pathlib, or the cache's own
    replacements of them): ``exists`` (the kind only), ``size``, ``mtime``, or everything (a direct stat: st_size,
    st_mtime... all reach the code). detpy's own frames (this wrapper, the cache's wrappers, which differ between
    its Python and Rust captures) are walked through, not counted: the answer depends on the caller only."""
    import sys

    try:
        f = sys._getframe(1)
    except ValueError:
        return ""
    stdlib = 0
    while f is not None and stdlib < 4:
        n = f.f_code.co_name
        if n in _EXISTS:
            return "exists"
        if n == "getsize":
            return "size"
        if n == "getmtime":
            return "mtime"
        fn = f.f_code.co_filename
        if fn.startswith(_OWN):
            pass
        elif fn.startswith(_STDLIB_PREFIX) or fn.startswith("<frozen"):
            stdlib += 1
        else:
            break
        f = f.f_back
    return ""


_STDLIB_PREFIX = tuple(d + os.sep for d in _sites._stdlib_dirs)


def _note_stat(op, path, res, asked=None) -> None:
    st = _state.STATE
    if not _ACTIVE or getattr(_tls, "busy", False) or _state.is_quiet():
        return
    outside = st.nodeid is None  # module scope, conftest, a hook: an entry of files_read_outside_tests (R-055)
    if not outside and st.recorder is None:
        return
    if isinstance(path, int) or _real_getpid() != _SESSION_PID:
        return
    _tls.busy = True
    try:
        p = os.fsdecode(path) if isinstance(path, (bytes, os.PathLike)) else path
        if not isinstance(p, str):
            return
        if not os.path.isabs(p):
            p = os.path.join(_sites._real_getcwd(), p)
        p = os.path.normpath(p)
        if p in _QUIET_DEVICES or p.startswith(_QUIET_PREFIXES) or _excluded(p):
            return
        depth = _user_depth(2)
        if _plugin_site(depth):
            return
        if asked is None:
            asked = _stat_question()
        # docs/VERIFY-CONTRACT.md section 2: `<path>|missing` or `<path>|<type>`, plus what the call returns of size
        # and modification time (an exists-style call: the type only)
        if res is None:
            value = "missing"
        else:
            fmt = _stat.S_IFMT(res.st_mode)
            value = {_stat.S_IFREG: "file", _stat.S_IFDIR: "dir", _stat.S_IFLNK: "link"}.get(fmt, "other")
            if value != "dir" and asked != "exists":
                if asked in ("", "size"):
                    value += f" size={res.st_size}"
                if asked in ("", "mtime"):
                    value += f" mtime_ns={res.st_mtime_ns}"
        if outside:
            OUTSIDE_STATS[_sites.norm_path(p)] = value
        else:
            _state.record("fs", "fs.stat", f"{_sites.norm_path(p)}|{value}", depth)
    except Exception:  # never break the code under test
        pass
    finally:
        _tls.busy = False

_HOOKED = [False]


# ---------------------------------------------------------------------------------------------------------------
# recorded OS measurements

def _observed(real, op: str, pick=None):
    def wrapper(*args, **kwargs):
        res = real(*args, **kwargs)
        if _ACTIVE and _state.STATE.nodeid is not None:
            try:
                v = pick(res) if pick is not None else res
                _state.record("other", op, _core.digest(repr(tuple(v) if not isinstance(v, (str, bytes)) else v)
                                                        .encode())[:16], 1)
            except Exception:
                pass
        return res

    wrapper.__name__ = getattr(real, "__name__", op)
    wrapper.__doc__ = getattr(real, "__doc__", None)
    wrapper.__wrapped__ = real
    return wrapper


# ---------------------------------------------------------------------------------------------------------------

def install(patcher, cfg) -> None:
    """Install the ``os`` control (after ``fstime``: its ``open`` is wrapped, not replaced)."""
    global _ACTIVE, _SESSION_PID, VPID, VPPID, TMPDIR, _prev_open
    _SESSION_PID = _real_getpid()
    idx = _worker_index()
    VPID = VPID_BASE if idx is None else VPID_BASE + 1 + idx
    VPPID = VPID_BASE - 1 if idx is None else VPID_BASE
    _counter[0] = 0
    patcher.set(os, "getpid", getpid)
    patcher.set(os, "getppid", getppid)
    if _real_native_id is not None:
        patcher.set(threading, "get_native_id", get_native_id)
        import _thread

        patcher.set(_thread, "get_native_id", get_native_id)
    _prev_open = io.open
    for name in ("stat", "lstat"):
        _rebind_stat(patcher, name, _stat_observed(getattr(os, name), f"fs.{name}"))
    _rebind_stat(patcher, "access", _access_observed(os.access))
    patcher.set(io, "open", open_)
    patcher.set(builtins, "open", open_)
    if TMPDIR is None:
        TMPDIR = _session_tmp()
    if TMPDIR is not None:
        patcher.set(tempfile, "tempdir", TMPDIR)
        patcher.set(tempfile, "_name_sequence", None)
    _EXCLUDED[:] = [d for d in {os.path.realpath(TMPDIR) if TMPDIR else None,
                                os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix),
                                os.path.realpath(sys.exec_prefix), os.environ.get("PYTHONPYCACHEPREFIX")} if d]
    if hasattr(os, "getloadavg"):
        patcher.set(os, "getloadavg", _observed(os.getloadavg, "os.getloadavg"))
    for name in ("statvfs", "fstatvfs"):
        if hasattr(os, name):
            patcher.set(os, name, _observed(getattr(os, name), f"os.{name}"))
    if not _HOOKED[0]:
        sys.addaudithook(_audit)  # cannot be removed: inert while the control is off (_ACTIVE)
        _HOOKED[0] = True
    _ACTIVE = True


def input_text() -> str:
    """The ``os`` run input: what the control does in this session, never which directory it took (the same text
    in a serial run, an xdist controller and a session that runs beside another one, which takes ``fenvix-det.1``:
    the directory's name is not an input, the control is)."""
    tmp = "fresh per run" if TMPDIR else "real"
    return (f"virtual pid; temporary directory: {tmp}; entropy devices and /proc/uptime virtual; "
            "other files read, devices and OS measurements recorded")


def start_test() -> None:
    _counter[0] = 0


def uninstall() -> None:
    global _ACTIVE
    _ACTIVE = False
