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


def _target_name(t) -> str:
    f = getattr(t, "_target", None) or getattr(t, "run", None)
    return getattr(f, "__qualname__", None) or type(t).__qualname__


def install(patcher) -> None:
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
