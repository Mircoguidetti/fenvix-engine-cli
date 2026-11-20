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
import threading

from . import _state

_seen: set = set()


_OWN = os.path.dirname(os.path.abspath(__file__)) + os.sep


def start_test() -> None:
    _seen.clear()


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


def _mark_io() -> None:
    """I/O readiness on the test's own thread: an event loop the test runs, directly or through a plugin such as
    pytest-asyncio (whose frames are infrastructure), hence a fixed site."""
    st = _state.STATE
    if st.recorder is None or st.nodeid is None or "io" in _seen or _state.is_quiet():
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
        _mark("thread", _target_name(self), 1)
        return real_start(self)

    patcher.set(threading.Thread, "start", start)

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
