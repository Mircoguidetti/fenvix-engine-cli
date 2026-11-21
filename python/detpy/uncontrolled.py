"""Sources Level 0 observes but does not control on this release: threads, child processes and I/O readiness.

A test that starts a thread (``threading.Thread.start``: thread pools, ``run_in_executor``, servers), starts a
child process (``subprocess.Popen``, ``os.system``, ``os.posix_spawn*``, ``os.fork``) or whose event loop wakes up
on ready I/O (``selectors``: asyncio, socketserver) gets one ``uncontrolled.<kind>`` event per kind (source
``other``; value: the thread target, the program, ``ready``). The fingerprint records it, and the verifier never
reports such a test identical: thread interleavings, what a child does and the order of ready I/O leave no event,
so identical fingerprints would not be evidence of an identical execution (audit G-0180, G-0041, G-0054).

One event per kind and test (the number of threads or wake-ups may vary from run to run; the use of the source
does not), so a reproducible failure keeps one fingerprint in its replays.
"""

from __future__ import annotations

import os
import selectors
import subprocess
import sys
import threading

from . import _sites, _state

_seen: set = set()


_OWN = os.path.dirname(os.path.abspath(__file__)) + os.sep

# Threads alive when a test starts (review P1 finding 3, G-0180): a pool or server started at import or by a wider
# fixture runs the test's work without any ``Thread.start`` during the test. Each such thread (test infrastructure
# excepted) is remembered with its CPU time; when the test ends, one that consumed CPU time, or ended, ran during the
# test and marks it ``uncontrolled.thread``. A Python thread unknown to ``threading`` (started with ``_thread``) has
# no readable CPU clock: its top frame is compared instead.
_others: dict = {}
try:
    import time as _time

    _real_clock_gettime_ns = _time.clock_gettime_ns  # captured before the clock control replaces it
except (ImportError, AttributeError):  # pragma: no cover - not on POSIX
    _real_clock_gettime_ns = None
_LINUX = sys.platform.startswith("linux")


def _thread_cpu_ns(t):
    """CPU time of a ``threading`` thread (Linux thread CPU clock of its native id), -1 when it is gone, None when it
    cannot be read here."""
    nid = getattr(t, "native_id", None)
    if nid is None or _real_clock_gettime_ns is None or not _LINUX:
        return None
    try:
        return _real_clock_gettime_ns(((~nid) << 3) | 6)  # MAKE_THREAD_CPUCLOCK(tid, CPUCLOCK_SCHED)
    except (OSError, OverflowError, ValueError):
        return -1


def _infra_file(fn) -> bool:
    return bool(fn) and _sites._classify(fn)[0] == _sites._INFRA


def _infra_thread(t) -> bool:
    """A thread of the test infrastructure (pytest, its plugins, xdist/execnet, detpy), or the main thread while the
    test runs on another one (it runs the runner then)."""
    if t is threading.main_thread():
        return True
    run = type(t).run
    f = getattr(t, "_target", None) if run is threading.Thread.run else run
    f = getattr(f, "func", f)  # functools.partial
    code = getattr(f, "__code__", None)
    if code is not None:
        return _infra_file(code.co_filename)
    mod = sys.modules.get(getattr(f, "__module__", None) or "")
    return _infra_file(getattr(mod, "__file__", None))


def _infra_stack(frame) -> bool:
    while frame is not None:
        if _infra_file(frame.f_code.co_filename):
            return True
        frame = frame.f_back
    return False


def start_test() -> None:
    _seen.clear()
    _others.clear()
    try:
        me = threading.get_ident()
        known = dict(threading._active)
        for ident, t in known.items():
            if ident != me and not _infra_thread(t):
                _others[ident] = (t, _thread_cpu_ns(t), None, -1)
        for ident, frame in sys._current_frames().items():
            if ident != me and ident not in known and not _infra_stack(frame):
                _others[ident] = (None, None, frame, frame.f_lasti)
    except Exception:  # never break the code under test
        _others.clear()


def end_test() -> None:
    """Mark the test ``uncontrolled.thread`` when a thread that was alive when it started ran during it."""
    st = _state.STATE
    if not _others or "thread" in _seen or st.recorder is None or st.nodeid is None:
        _others.clear()
        return
    ran = None
    try:
        frames = sys._current_frames()
        for ident, (t, cpu, frame, lasti) in _others.items():
            if t is not None:
                now = _thread_cpu_ns(t) if t.is_alive() else -1
                if cpu is None or now is None or now == -1 or now != cpu:
                    ran = t.name
                    break
            else:
                cur = frames.get(ident)
                if cur is None or cur is not frame or cur.f_lasti != lasti:
                    ran = f"thread {ident:#x}"
                    break
    except Exception:
        ran = None
    _others.clear()
    if ran is not None:
        _seen.add("thread")
        _state.record_at("other", "uncontrolled.thread", "<thread alive before the test>", ran)


def _mark(kind: str, value: str, depth: int) -> None:
    """One ``uncontrolled.<kind>`` event per test, at the site of the user code that used the source (``_state.record``:
    nothing when only test infrastructure (pytest, its plugins, detpy) did)."""
    st = _state.STATE
    rec = st.recorder
    if rec is None or st.nodeid is None or kind in _seen or _state.is_quiet():
        return
    try:
        # other controls may wrap the same entry point (the closed network's Popen proxy variables): skip detpy's
        # own frames, so the site is the user code whatever the wrapping order
        import sys

        f = sys._getframe(depth + 1)
        while f is not None and f.f_code.co_filename.startswith(_OWN):
            f = f.f_back
            depth += 1
        before = rec.current_events
        _state.record("other", f"uncontrolled.{kind}", value, depth + 1)
        if rec.current_events > before:
            _seen.add(kind)
    except Exception:  # never break the code under test
        pass


def _scheduled_thread() -> bool:
    """``--det-threads``: a thread started now is scheduled, so it is not an uncontrolled source.

    The scheduler hands the baton to one managed thread at a time and records every choice among runnable threads
    as a ``sched.thread`` event, so the interleaving is a run input like any other and the test can be proven
    identical. It is not a promise: if the scheduler loses control of a thread (it blocks in C code, spins without
    reaching a scheduling point, or runs outside the scheduler) it calls ``mark_thread_escaped`` below and the test
    is NOT PROVEN again. Anything that goes wrong here answers False, which marks the test, as before.
    """
    try:
        from . import threads

        return threads.will_manage()
    except Exception:
        return False


def mark_thread_escaped(why: str) -> None:
    """``--det-threads`` lost control of a thread: mark the test ``uncontrolled.thread`` after all.

    A fixed site, as in ``_mark_io``: an escape happens inside the scheduler, so there is no user frame that asked
    for it. ``why`` names what escaped (the thread and what it was doing).
    """
    st = _state.STATE
    if st.recorder is None or st.nodeid is None or "thread" in _seen or _state.is_quiet():
        return
    try:
        _seen.add("thread")
        _state.record_at("other", "uncontrolled.thread", "<scheduler escape>", why)
    except Exception:  # never break the code under test
        pass


def _scheduled_io() -> bool:
    """``--det-async``: the loop whose ready I/O this is belongs to the scheduler, so the order is a run input.

    As with ``_scheduled_thread``, this is not a promise: a wake-up the scheduler had to take from the real world
    is recorded as ``asyncio.uncontrolled`` and marks the test through ``mark_io_escaped``. Anything that goes
    wrong here answers False, which marks the test, as before.
    """
    try:
        from . import aio

        return aio.controls_io()
    except Exception:
        return False


def mark_io_escaped(why: str) -> None:
    """``--det-async`` took a wake-up from the real world: mark the test ``uncontrolled.io`` after all."""
    st = _state.STATE
    if st.recorder is None or st.nodeid is None or "io" in _seen or _state.is_quiet():
        return
    try:
        _seen.add("io")
        _state.record_at("other", "uncontrolled.io", "<scheduler escape>", why)
    except Exception:  # never break the code under test
        pass


def _mark_io() -> None:
    """I/O readiness on the test's own thread: an event loop the test runs, directly or through a plugin such as
    pytest-asyncio (whose frames are infrastructure), hence a fixed site."""
    st = _state.STATE
    if st.recorder is None or st.nodeid is None or "io" in _seen or _state.is_quiet():
        return
    if _scheduled_io():  # --det-async: the scheduler chooses the delivery order and records every choice
        return
    try:
        _seen.add("io")
        _state.record_at("other", "uncontrolled.io", "<event loop>", "ready")
    except Exception:
        pass


# Native network clients: their sockets are opened in C, outside the closed network and the cassette (audit G-1521).
# Creating a channel, a handle or a connection marks the test (``uncontrolled.native``); blocking or recording them
# needs the syscall backend.
NATIVE_FACTORIES = {
    "grpc": ("insecure_channel", "secure_channel", "aio.insecure_channel", "aio.secure_channel"),
    "pycurl": ("Curl", "CurlMulti"),
    "psycopg": ("connect", "AsyncConnection.connect", "Connection.connect"),
    "psycopg2": ("connect",),
    "MySQLdb": ("connect", "Connect"),
    "confluent_kafka": ("Producer", "Consumer", "admin.AdminClient"),
    "asyncpg": ("connect", "create_pool"),
    "pymssql": ("connect",),
}


def _resolve(mod, dotted: str):
    obj, parent, name = mod, None, None
    for part in dotted.split("."):
        parent, name = obj, part
        obj = getattr(obj, part, None)
        if obj is None:
            return None, None, None
    return parent, name, obj


def _patch_native(patcher, mod_name: str, mod) -> None:
    for dotted in NATIVE_FACTORIES.get(mod_name, ()):
        parent, name, real = _resolve(mod, dotted)
        if real is None or getattr(real, "_detpy_native", False):
            continue
        label = f"{mod_name}.{dotted}"
        if isinstance(real, type):
            def make(real=real, label=label):
                def factory(*a, **kw):
                    _mark("native", label, 1)
                    return real(*a, **kw)
                return factory
            wrapper = make()
        else:
            def make(real=real, label=label):
                def factory(*a, **kw):
                    _mark("native", label, 1)
                    return real(*a, **kw)
                return factory
            wrapper = make()
        wrapper._detpy_native = True
        wrapper.__doc__ = getattr(real, "__doc__", None)
        try:
            patcher.set(parent, name, wrapper)
        except (AttributeError, TypeError):  # a read-only attribute (C type): left alone
            pass


class _NativeImports:
    """``sys.meta_path`` finder: patches a native client's factories when it is imported (now or later)."""

    def __init__(self, patcher) -> None:
        self.patcher, self.busy = patcher, False

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in NATIVE_FACTORIES or self.busy:
            return None
        import importlib.util

        self.busy = True
        try:
            spec = importlib.util.find_spec(fullname)
        finally:
            self.busy = False
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return None
        loader, hook = spec.loader, self

        class _Loader:
            def create_module(self, spec):
                return loader.create_module(spec)

            def exec_module(self, module):
                loader.exec_module(module)
                _patch_native(hook.patcher, fullname, module)

            def __getattr__(self, name):
                return getattr(loader, name)

        spec.loader = _Loader()
        return spec


def _install_native(patcher) -> None:
    import sys

    for name in NATIVE_FACTORIES:
        if name in sys.modules:
            _patch_native(patcher, name, sys.modules[name])
    hook = _NativeImports(patcher)
    sys.meta_path.insert(0, hook)

    def undo() -> None:
        if hook in sys.meta_path:
            sys.meta_path.remove(hook)

    patcher._undo.append((undo, None, None))


def _target_name(t) -> str:
    f = getattr(t, "_target", None) or getattr(t, "run", None)
    return getattr(f, "__qualname__", None) or type(t).__qualname__


def install(patcher) -> None:
    _install_native(patcher)
    real_start = threading.Thread.start

    def start(self):
        if not _scheduled_thread():  # --det-threads: the scheduler controls the interleaving, so it is a run input
            _mark("thread", _target_name(self), 1)
        return real_start(self)

    patcher.set(threading.Thread, "start", start)

    # threads started below ``threading`` (review P1 finding 3): ``threading`` keeps its own references to these, so
    # only direct callers go through the wrappers
    import _thread

    for name in ("start_new_thread", "start_new", "start_joinable_thread"):
        real_raw = getattr(_thread, name, None)
        if real_raw is None:
            continue

        def raw_start(function, *a, _real=real_raw, **kw):
            if not _scheduled_thread():
                _mark("thread", getattr(function, "__qualname__", None) or repr(function), 1)
            return _real(function, *a, **kw)

        raw_start.__name__ = name
        raw_start.__doc__ = real_raw.__doc__
        patcher.set(_thread, name, raw_start)

    real_popen_init = subprocess.Popen.__init__

    def popen_init(self, args, *a, **kw):
        prog = args if isinstance(args, (str, bytes)) else (args[0] if args else "")
        prog = os.fsdecode(prog) if isinstance(prog, (bytes, os.PathLike)) else str(prog)
        _mark("child", os.path.basename(prog.split()[0]) if prog.strip() else "?", 1)
        return real_popen_init(self, args, *a, **kw)

    patcher.set(subprocess.Popen, "__init__", popen_init)

    for name in ("system", "posix_spawn", "posix_spawnp", "fork", "forkpty"):
        real = getattr(os, name, None)
        if real is None:
            continue

        def wrap(*a, _real=real, _name=name, **kw):
            _mark("child", f"os.{_name}", 1)
            return _real(*a, **kw)

        wrap.__name__ = name
        patcher.set(os, name, wrap)

    for cname in ("SelectSelector", "PollSelector", "EpollSelector", "DevpollSelector", "KqueueSelector"):
        cls = getattr(selectors, cname, None)
        if cls is None:
            continue
        real_select = cls.select

        def select(self, timeout=None, _real=real_select):
            ready = _real(self, timeout)
            # only the test's own thread: an event loop the test runs (directly, or through pytest-asyncio and
            # the like, hence the fallback site); infrastructure threads (xdist's I/O) are not the test's
            if ready and _state.STATE.test_thread == threading.get_ident():
                _mark_io()
            return ready

        patcher.set(cls, "select", select)
