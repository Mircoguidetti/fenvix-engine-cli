"""Virtual clock.

All clocks derive from one virtual nanosecond counter that advances by a fixed
``tick`` on every read and by the requested amount on ``time.sleep``:

* wall clock (``time.time``, ``datetime.now``, ...) is reset to the configured
  epoch at the start of every test, so a test sees the same dates whatever its
  position in the run;
* monotonic clocks (``time.monotonic``, ``perf_counter``) never go backwards
  inside the process; events record them relative to the start of the test.

Blocking primitives that really time out (``threading.Condition.wait`` and
everything built on it: ``Event.wait``, ``queue.Queue.get``, ...) advance the
virtual clock by their timeout, so "wait up to N seconds" loops terminate.

The clock and the stand-ins are Rust (``crates/detpy-py/src/level0.rs``, ``clock.rs``). This module keeps the real
functions (module globals, which the stand-ins read at call time as the Python functions did), the patching, and the
thin shims that must bind as methods. The Python originals: ``tests/rust_hotpaths_ref/_ref_l0_clock.py`` (round 1:
the clock and the six ``time.*`` reads) and ``_ref_l0_clock_r2.py`` (round 2: everything else).
"""

from __future__ import annotations

import datetime as _dt
import os
import sys  # noqa: F401  (read by the Rust stand-ins)
import threading
import time as _time
import types
import warnings  # noqa: F401  (read by the Rust stand-ins)

from . import _core, _state
from ._patch import Patcher, binds_as_method, nonbinding, rebind_module_references

NS = 1_000_000_000

# Real functions, captured at import time (before any patching).
real_time = _time.time
real_time_ns = _time.time_ns
real_monotonic = _time.monotonic
real_monotonic_ns = _time.monotonic_ns
real_perf_counter = _time.perf_counter
real_perf_counter_ns = _time.perf_counter_ns
real_sleep = _time.sleep
_real_listdir = os.listdir
real_localtime = _time.localtime
real_gmtime = _time.gmtime
real_ctime = _time.ctime
real_asctime = _time.asctime
real_strftime = _time.strftime
real_clock_gettime = getattr(_time, "clock_gettime", None)
real_clock_gettime_ns = getattr(_time, "clock_gettime_ns", None)
real_datetime = _dt.datetime
real_date = _dt.date

_MONO_BASE_NS = 1_000 * NS  # arbitrary, positive, process-independent


# The adaptive tick never exceeds this per read. It only has to let
# calibration loops reach a few microseconds (pytest-benchmark needs ~10 us);
# a larger cap made virtual time run faster than real time and tripped the
# timeouts of algorithms that poll perf_counter in a hot loop (networkx).
MAX_TICK_NS = 16_000


class VirtualClock:
    """Deterministic clock.

    Adaptive tick: once ``adapt_after`` consecutive clock reads happened with no
    other event in between (no random draw, filesystem listing, network access,
    sleep...), every further read of that run doubles the tick, up to
    ``MAX_TICK_NS`` (16 us); any other event or the start of a test restores the base
    tick. Doubling on every read (rather than every N reads) is what makes
    calibration loops that double their own work per measurement terminate. Code that only watches the clock
    (time-calibrated loops such as pytest-benchmark's) therefore sees time
    move faster and terminates, while the sequence of values stays a pure
    function of the sequence of events.

    The state lives in Rust (``_core.clock_*``), where the ``time.*`` stand-ins below read it without a Python
    frame; this object is the Python view of it (one clock per process). The Python original is
    ``tests/rust_hotpaths_ref/_ref_l0_clock.py``.
    """

    def __init__(self, epoch_ns: int, tick_ns: int, adapt_after: int = 0) -> None:
        _core.clock_install(epoch_ns, tick_ns, adapt_after)

    read = staticmethod(_core.clock_read)  # advance by one tick and return the elapsed counter
    other_event = staticmethod(_core.clock_other_event)
    advance = staticmethod(_core.clock_advance)
    wall_ns = staticmethod(_core.clock_wall_ns)
    start_test = staticmethod(_core.clock_start_test)  # and: no process started by the test yet

    @staticmethod
    def mono_ns(e: int) -> int:
        return _MONO_BASE_NS + e

    def __getattr__(self, name):  # epoch_ns, base_tick_ns, tick_ns, adapt_after, streak, elapsed, ...
        st = _core.clock_state()
        if name in st:
            return st[name]
        raise AttributeError(name)


CLOCK: VirtualClock | None = None

# _time_machine_ns(e): wall time of an active ``time_machine`` travel, or None. time-machine patches the C builtins
# (``time.time``, ``datetime.now``...), which detpy has replaced, so under --det its travel would be ignored. While a
# travel is active the virtual wall clock returns its destination; a ticking travel advances with the *virtual*
# counter (not real time) so the values stay deterministic. In Rust; the clock calls it directly.
_time_machine_ns = _core.clock_time_machine_ns

_rel = _core.clock_rel  # str(e - test start)


# Fake time functions ---------------------------------------------------------
# In Rust (no Python frame per call): read the counter and record the event ("time", "time.<name>", _rel(e)) at the
# caller's site, return the wall or monotonic value; with the clock not installed (a reference kept after
# uninstall), the real function.
time = _core.time
time_ns = _core.time_ns
monotonic = _core.monotonic
monotonic_ns = _core.monotonic_ns
perf_counter = _core.perf_counter
perf_counter_ns = _core.perf_counter_ns
_core.clock_set_hooks([real_time, real_time_ns, real_monotonic, real_monotonic_ns, real_perf_counter,
                       real_perf_counter_ns], None)  # None: the Rust _time_machine_ns

# sleep(secs): the real function's argument validation; records ("time", "time.sleep", ns), advances the virtual clock
# and also waits for real when someone observes real time: --det-sleep=real, another thread (_other_threads_alive) or
# a child process (_EXTERNAL, _children_alive) may need this time to make progress ("wait until the server is up"), or
# an asyncio loop (which keeps real time) is running here (_in_event_loop) and its deadlines must see the sleep;
# otherwise sleep(0) (still yield the GIL / scheduler).
sleep = _core.sleep
_other_threads_alive = _core.clock_other_threads_alive
_in_event_loop = _core.clock_in_event_loop
_children_alive = _core.clock_children_alive  # live child processes (Linux: /proc/self/task/*/children)

# _EXTERNAL: set when the running test starts another process (subprocess, fork, spawn): from then on, until the test
# ends, sleeps also wait for real, because the external work advances in real time even after it detached (daemons).
# A Rust flag (``_core.clock_external_started()``), cleared by ``start_test``.


def _mark_external(real, module=None, name=None):
    """Stand-in for ``real`` that sets the flag, then calls it (a Rust callable, no Python frame).

    A function (``subprocess.Popen.__init__``) gets a stand-in that binds like it; a builtin patched on module
    ``module`` as ``name`` (``os.fork``...) one that does not, disguised as ``module.name`` (pickled by reference).
    """
    binds = module is None or binds_as_method(real)
    stand_in = _core.clock_external_stand_in(real, binds)
    stand_in.__wrapped__ = real
    if binds:
        stand_in.__module__ = __name__
        for attr in ("__name__", "__qualname__", "__doc__"):
            try:
                setattr(stand_in, attr, getattr(real, attr))
            except (AttributeError, TypeError):
                pass
    else:
        stand_in.__name__ = stand_in.__qualname__ = name
        stand_in.__module__ = module
        stand_in.__doc__ = getattr(real, "__doc__", None)
    return stand_in


# localtime(secs=None), gmtime(secs=None), ctime(secs=None), asctime(t=None), strftime(fmt, t=None): the real function,
# of the virtual wall clock (read and recorded as "time.<name>") when no time is given. In Rust.
localtime = _core.localtime
gmtime = _core.gmtime
ctime = _core.ctime
asctime = _core.asctime
strftime = _core.strftime

_REALTIME = {getattr(_time, n) for n in ("CLOCK_REALTIME", "CLOCK_TAI") if hasattr(_time, n)}
_MONOTONIC = {
    getattr(_time, n)
    for n in ("CLOCK_MONOTONIC", "CLOCK_MONOTONIC_RAW", "CLOCK_BOOTTIME", "CLOCK_UPTIME", "CLOCK_HIGHRES")
    if hasattr(_time, n)
}

# clock_gettime(_ns)(clk_id): the virtual wall clock for the _REALTIME ids, the virtual monotonic clock for the
# _MONOTONIC ones (recorded as "time.clock_gettime"), the real function for the others. In Rust.
clock_gettime_ns = _core.clock_gettime_ns
clock_gettime = _core.clock_gettime


# datetime ---------------------------------------------------------------------
# The real C types are patched in place (see Patcher.set_type_attr): identity,
# isinstance, subclasses, pickling and libraries such as freezegun keep working.
_real_dt_now = real_datetime.__dict__["now"]
_real_dt_utcnow = real_datetime.__dict__["utcnow"]

# _dt_now(cls, tz=None), _dt_utcnow(cls) (with its DeprecationWarning from 3.12, attributed to the caller): the
# functions of the ``now`` / ``utcnow`` classmethods, in Rust: ``cls.fromtimestamp`` of the virtual wall clock
# (recorded as "datetime.now" / "datetime.utcnow"). A subclass whose ``fromtimestamp`` is Python code gets the
# functions below instead, so that this code runs under a detpy frame, as it did.
_dt_now = _core._dt_now
_dt_utcnow = _core._dt_utcnow


def _dt_now_py(cls, tz):
    return cls.fromtimestamp(_core.clock_wall_secs("datetime.now", 1), tz)


def _dt_utcnow_py(cls):  # the warning was given
    return cls.fromtimestamp(_core.clock_wall_secs("datetime.utcnow", 1), _dt.timezone.utc).replace(tzinfo=None)


# date.today() / datetime.today() are not replaced: CPython's implementation
# calls time.time() through the time module, i.e. the virtual time() below (or
# whatever a library such as freezegun patched in), with no extra Python frame.


# Wait primitives -----------------------------------------------------------------
# The timeout rules are Rust (``_core.clock_condition_wait``, ``clock_selector_select``, ``clock_lock_acquire``): a
# wait that times out advances the virtual clock by its timeout. The methods below are one-line shims because they
# must bind as methods; they keep a detpy frame above the real wait, which ends the call-site search of whatever
# records under it, as before.
_real_condition_wait = threading.Condition.wait
_wait = _core.clock_condition_wait
_select = _core.clock_selector_select
_lock_acquire = _core.clock_lock_acquire


def _condition_wait(self, timeout=None):
    return _wait(self, timeout)


def _wrap_selector_select(real):
    def select(self, timeout=None):
        # asyncio.sleep, loop deadlines; rounded up to the millisecond (asyncio asks for "deadline - now", a few
        # microseconds less than the delay the code requested)
        return _select(real, self, timeout)

    select.__wrapped__ = real
    return select


class _TimedLock:
    """Transparent wrapper of a Lock/RLock created under --det.

    ``acquire(timeout=t)`` that times out advances the virtual clock by ``t``
    (the C-level wait took real time): retry loops bounded by a time.time()
    deadline terminate. Everything else is delegated to the real lock.
    """

    __slots__ = ("_lock", "__weakref__")

    def __init__(self, lock):
        self._lock = lock

    def acquire(self, blocking=True, timeout=-1):
        return _lock_acquire(self._lock, blocking, timeout)

    def release(self):
        self._lock.release()

    def __enter__(self):
        # a with statement has no timeout: enter the real lock through its own __enter__, as a plain ``with lock:``
        # does (round 3, item 8: tools that watch ``lock.acquire``, such as blockbuster, see what they see without
        # --det; calling acquire here made pydantic-ai's uuid7 lock a "blocking call" under contention)
        return self._lock.__enter__()

    def __exit__(self, *exc):
        self._lock.release()

    def locked(self):
        return self._lock.locked()

    def __getattr__(self, name):  # _is_owned, _release_save, _acquire_restore, _at_fork_reinit...
        return getattr(self._lock, name)

    def __repr__(self):
        return repr(self._lock)


class _TimedLockMeta(type):
    """Metaclass of the stand-in for a lock *type* (threading.Lock from Python 3.13).

    ``isinstance(x, threading.Lock)`` stays true for real locks and for the
    wrappers created under --det; ``issubclass`` follows the real type.
    """

    def __instancecheck__(cls, obj):
        real = cls.__wrapped__
        return isinstance(obj, real) or (type(obj) is _TimedLock and isinstance(obj._lock, real))

    def __subclasscheck__(cls, sub):
        return sub is cls or issubclass(sub, cls.__wrapped__)

    def __repr__(cls):
        return repr(cls.__wrapped__)


def _timed_factory(real):
    """Stand-in for ``threading.Lock`` / ``threading.RLock`` that returns a _TimedLock.

    Where the real object is a function (Lock before 3.13, RLock) the stand-in is a
    function; where it is a type (Lock from 3.13) the stand-in is a type too, so
    ``isinstance(x, threading.Lock)`` keeps working (review R-001).
    """
    if isinstance(real, type):

        def __new__(cls, *args, **kwargs):
            return _TimedLock(real(*args, **kwargs))

        ns = {"__new__": __new__, "__wrapped__": real, "__module__": real.__module__,
              "__qualname__": real.__qualname__, "__doc__": real.__doc__, "__slots__": ()}
        return _TimedLockMeta(real.__name__, (), ns)

    def factory(*args, **kwargs):
        return _TimedLock(real(*args, **kwargs))

    factory.__wrapped__ = real
    # threading.Lock before 3.13 is a builtin (does not bind as a method);
    # threading.RLock is a Python function (binds): keep each one's behaviour.
    if isinstance(real, types.FunctionType):
        return factory
    return nonbinding(factory, "threading", "Lock")


# Installation ---------------------------------------------------------------------

# Stdlib modules that bind clock functions at import time and use them for real
# blocking waits: import them now so they keep the *real* functions.
_PRELOAD = ("threading", "queue", "subprocess", "sched", "socketserver", "selectors", "asyncio",
            "concurrent.futures", "multiprocessing", "multiprocessing.connection", "logging", "tempfile")


def install(patcher: Patcher, epoch_ns: int, tick_ns: int, skip_module, adapt_after: int = 0) -> list[str]:
    global CLOCK
    import importlib

    for name in _PRELOAD:
        try:
            importlib.import_module(name)
        except Exception:  # pragma: no cover - optional modules
            pass
    CLOCK = VirtualClock(epoch_ns, tick_ns, adapt_after)
    _core.clock_activate(True)
    if adapt_after:
        _state._on_other_event = CLOCK.other_event
    fakes = {
        "time": time, "time_ns": time_ns, "monotonic": monotonic, "monotonic_ns": monotonic_ns,
        "perf_counter": perf_counter, "perf_counter_ns": perf_counter_ns, "sleep": sleep,
        "localtime": localtime, "gmtime": gmtime, "ctime": ctime, "asctime": asctime, "strftime": strftime,
    }
    if real_clock_gettime is not None:
        fakes["clock_gettime"] = clock_gettime
    if real_clock_gettime_ns is not None:
        fakes["clock_gettime_ns"] = clock_gettime_ns
    replacements = {}
    for name, fake in fakes.items():
        # the stand-ins are Rust builtins (whose __module__ disguise would rewrite in place): wrap them directly
        stand_in = nonbinding(fake, "time", name)
        real = patcher.set(_time, name, stand_in)
        replacements[id(real)] = (real, stand_in)
    patcher.set_type_attr(real_datetime, "now", classmethod(_dt_now))
    patcher.set_type_attr(real_datetime, "utcnow", classmethod(_dt_utcnow))
    patcher.set(threading.Condition, "wait", _condition_wait)
    patcher.set(threading, "Lock", _timed_factory(threading.Lock))
    patcher.set(threading, "RLock", _timed_factory(threading.RLock))
    import subprocess

    patcher.set(subprocess.Popen, "__init__", _mark_external(subprocess.Popen.__init__))
    for name in ("fork", "forkpty", "posix_spawn", "posix_spawnp", "spawnv", "spawnve", "system"):
        if hasattr(os, name):
            patcher.set(os, name, _mark_external(getattr(os, name), os.__name__, name))
    import selectors

    for name in ("SelectSelector", "PollSelector", "EpollSelector", "DevpollSelector", "KqueueSelector"):
        cls = getattr(selectors, name, None)
        if cls is not None and "select" in vars(cls):
            patcher.set(cls, "select", _wrap_selector_select(vars(cls)["select"]))
    # asyncio's event loop must keep real time: its selector waits for real.
    import asyncio.base_events

    patcher.set(asyncio.base_events.BaseEventLoop, "time", lambda self: real_monotonic())
    return rebind_module_references(patcher, replacements, skip_module)


def uninstall() -> None:
    global CLOCK
    CLOCK = None
    _core.clock_activate(False)
    _state._on_other_event = None


def start_test() -> None:
    if CLOCK is not None:
        CLOCK.start_test()


_core.clock_configure(globals())
