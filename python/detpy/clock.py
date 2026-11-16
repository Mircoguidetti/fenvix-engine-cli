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
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import threading
import time as _time
import warnings

from . import _state
from ._patch import Patcher, disguise, rebind_module_references

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
    """

    def __init__(self, epoch_ns: int, tick_ns: int, adapt_after: int = 0) -> None:
        self._lock = threading.Lock()
        self.epoch_ns = epoch_ns
        self.base_tick_ns = tick_ns
        self.tick_ns = tick_ns
        self.adapt_after = adapt_after
        self.streak = 0
        self.elapsed = 0  # ns since installation
        self.wall_offset = epoch_ns
        self.test_start = 0

    def read(self) -> int:
        """Advance by one tick and return the elapsed counter."""
        with self._lock:
            self.elapsed += self.tick_ns
            if self.adapt_after:
                self.streak += 1
                if self.streak >= self.adapt_after:
                    self.tick_ns = min(max(1, self.tick_ns) * 2, MAX_TICK_NS)
            return self.elapsed

    def other_event(self) -> None:
        if self.streak or self.tick_ns != self.base_tick_ns:
            self.streak = 0
            self.tick_ns = self.base_tick_ns

    def advance(self, ns: int) -> None:
        if ns > 0:
            with self._lock:
                self.elapsed += ns

    def start_test(self) -> None:
        _EXTERNAL["started"] = False
        with self._lock:
            self.streak = 0
            self.tick_ns = self.base_tick_ns
            self.test_start = self.elapsed
            self.wall_offset = self.epoch_ns - self.elapsed

    # Derived values ---------------------------------------------------
    def wall_ns(self, e: int) -> int:
        travel = _time_machine_ns(e)
        return self.wall_offset + e if travel is None else travel

    @staticmethod
    def mono_ns(e: int) -> int:
        return _MONO_BASE_NS + e


CLOCK: VirtualClock | None = None


def _time_machine_ns(e: int) -> int | None:
    """Wall time of an active ``time_machine`` travel, or None.

    time-machine patches the C builtins (``time.time``, ``datetime.now``...),
    which detpy has replaced, so under --det its travel would be ignored. While
    a travel is active the virtual wall clock returns its destination; a ticking
    travel advances with the *virtual* counter (not real time) so the values
    stay deterministic.
    """
    tm = sys.modules.get("time_machine")
    stack = getattr(tm, "traveller_stack", None) if tm is not None else None
    if not stack:
        return None
    t = stack[-1]
    dest = getattr(t, "_destination_timestamp_ns", None)
    if dest is None:
        return None
    if not getattr(t, "_tick", True):
        return dest
    start = t.__dict__.setdefault("_detpy_start_elapsed", e)
    return getattr(tm, "SYSTEM_EPOCH_TIMESTAMP_NS", 0) + dest + (e - start)


def _rel(e: int) -> str:
    assert CLOCK is not None
    return str(e - CLOCK.test_start)


# Fake time functions ---------------------------------------------------------
def time() -> float:
    if CLOCK is None:  # called through a reference kept after uninstall
        return real_time()
    e = CLOCK.read()
    _state.record("time", "time.time", _rel(e))
    return CLOCK.wall_ns(e) / NS


def time_ns() -> int:
    if CLOCK is None:  # called through a reference kept after uninstall
        return real_time_ns()
    e = CLOCK.read()
    _state.record("time", "time.time_ns", _rel(e))
    return CLOCK.wall_ns(e)


def monotonic() -> float:
    if CLOCK is None:  # called through a reference kept after uninstall
        return real_monotonic()
    e = CLOCK.read()
    _state.record("time", "time.monotonic", _rel(e))
    return CLOCK.mono_ns(e) / NS


def monotonic_ns() -> int:
    if CLOCK is None:  # called through a reference kept after uninstall
        return real_monotonic_ns()
    e = CLOCK.read()
    _state.record("time", "time.monotonic_ns", _rel(e))
    return CLOCK.mono_ns(e)


def perf_counter() -> float:
    if CLOCK is None:  # called through a reference kept after uninstall
        return real_perf_counter()
    e = CLOCK.read()
    _state.record("time", "time.perf_counter", _rel(e))
    return CLOCK.mono_ns(e) / NS


def perf_counter_ns() -> int:
    if CLOCK is None:  # called through a reference kept after uninstall
        return real_perf_counter_ns()
    e = CLOCK.read()
    _state.record("time", "time.perf_counter_ns", _rel(e))
    return CLOCK.mono_ns(e)


def sleep(secs: float) -> None:
    if CLOCK is None:
        return real_sleep(secs)
    # Same argument validation as the real function.
    if not isinstance(secs, (int, float)):
        try:
            secs = float(secs)  # Decimal, Fraction, numpy scalars
        except (TypeError, ValueError):
            raise TypeError(f"'{type(secs).__name__}' object cannot be interpreted as an integer or float")
    if secs != secs:
        raise ValueError("Invalid value NaN (not a number)")
    if secs < 0:
        raise ValueError("sleep length must be non-negative")
    ns = int(secs * NS)
    CLOCK.other_event()  # a sleep is not a read: it ends a run of reads
    _state.record("time", "time.sleep", str(ns))
    CLOCK.advance(ns)
    if (_state.STATE.config.sleep == "real" or _other_threads_alive() or _in_event_loop()
            or _EXTERNAL["started"] or _children_alive()):
        # Someone observes real time: another thread or a child process may need
        # this time to make progress ("wait until the server is up"), or an
        # asyncio loop (which keeps real time) is running here and its
        # deadlines must see the sleep.
        # Wait for real as well; the virtual clock still advances.
        real_sleep(secs)
    else:
        real_sleep(0)  # still yield the GIL / scheduler


# Set when the running test starts another process (subprocess, fork, spawn):
# from then on, until the test ends, sleeps also wait for real, because the
# external work advances in real time even after it detached (daemons).
_EXTERNAL = {"started": False}


def _mark_external(real):
    def wrapper(*args, **kwargs):
        _EXTERNAL["started"] = True
        return real(*args, **kwargs)

    wrapper.__wrapped__ = real
    for attr in ("__name__", "__qualname__", "__doc__"):
        try:
            setattr(wrapper, attr, getattr(real, attr))
        except (AttributeError, TypeError):
            pass
    return wrapper


def _children_alive() -> bool:
    """True if this process has live child processes (Linux: /proc children lists)."""
    try:
        for tid in _real_listdir("/proc/self/task"):
            with open(f"/proc/self/task/{tid}/children") as f:
                if f.read().strip():
                    return True
    except OSError:
        return False
    return False


def _in_event_loop() -> bool:
    aio = sys.modules.get("asyncio")
    if aio is None:
        return False
    try:
        return aio._get_running_loop() is not None
    except Exception:  # pragma: no cover
        return False


def _other_threads_alive() -> bool:
    for t in threading.enumerate():
        if t is not threading.current_thread() and not t.name.startswith("detpy-"):
            return True
    return False


def _wall_secs(op: str) -> float:
    if CLOCK is None:
        return real_time()
    e = CLOCK.read()
    _state.record("time", op, _rel(e), depth=2)
    return CLOCK.wall_ns(e) / NS


def localtime(secs=None):
    return real_localtime(_wall_secs("time.localtime") if secs is None else secs)


def gmtime(secs=None):
    return real_gmtime(_wall_secs("time.gmtime") if secs is None else secs)


def ctime(secs=None):
    return real_ctime(_wall_secs("time.ctime") if secs is None else secs)


def asctime(t=None):
    return real_asctime(real_localtime(_wall_secs("time.asctime")) if t is None else t)


def strftime(fmt, t=None):
    return real_strftime(fmt, real_localtime(_wall_secs("time.strftime")) if t is None else t)


_REALTIME = {getattr(_time, n) for n in ("CLOCK_REALTIME", "CLOCK_TAI") if hasattr(_time, n)}
_MONOTONIC = {
    getattr(_time, n)
    for n in ("CLOCK_MONOTONIC", "CLOCK_MONOTONIC_RAW", "CLOCK_BOOTTIME", "CLOCK_UPTIME", "CLOCK_HIGHRES")
    if hasattr(_time, n)
}


def clock_gettime_ns(clk_id):
    if CLOCK is None:
        return real_clock_gettime_ns(clk_id)
    if clk_id in _REALTIME:
        e = CLOCK.read()
        _state.record("time", "time.clock_gettime", _rel(e))
        return CLOCK.wall_ns(e)
    if clk_id in _MONOTONIC:
        e = CLOCK.read()
        _state.record("time", "time.clock_gettime", _rel(e))
        return CLOCK.mono_ns(e)
    return real_clock_gettime_ns(clk_id)


def clock_gettime(clk_id):
    if CLOCK is None:
        return real_clock_gettime(clk_id)
    if clk_id in _REALTIME or clk_id in _MONOTONIC:
        e = CLOCK.read()
        _state.record("time", "time.clock_gettime", _rel(e))
        return (CLOCK.wall_ns(e) if clk_id in _REALTIME else CLOCK.mono_ns(e)) / NS
    return real_clock_gettime(clk_id)


# datetime ---------------------------------------------------------------------
# The real C types are patched in place (see Patcher.set_type_attr): identity,
# isinstance, subclasses, pickling and libraries such as freezegun keep working.
_real_dt_now = real_datetime.__dict__["now"]
_real_dt_utcnow = real_datetime.__dict__["utcnow"]


def _dt_now(cls, tz=None):
    return cls.fromtimestamp(_wall_secs("datetime.now"), tz)


def _dt_utcnow(cls):
    if sys.version_info >= (3, 12):
        warnings.warn(
            "datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. "
            "Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).",
            DeprecationWarning,
            stacklevel=2,
        )
    return cls.fromtimestamp(_wall_secs("datetime.utcnow"), _dt.timezone.utc).replace(tzinfo=None)


# date.today() / datetime.today() are not replaced: CPython's implementation
# calls time.time() through the time module, i.e. the virtual time() below (or
# whatever a library such as freezegun patched in), with no extra Python frame.


# Wait primitives -----------------------------------------------------------------
_real_condition_wait = threading.Condition.wait


def _condition_wait(self, timeout=None):
    got = _real_condition_wait(self, timeout)
    if not got and timeout is not None and timeout > 0 and CLOCK is not None:
        CLOCK.advance(int(timeout * NS))
    return got


def _wrap_selector_select(real):
    def select(self, timeout=None):
        ready = real(self, timeout)
        if not ready and timeout is not None and timeout > 0 and CLOCK is not None:
            # Same rule as Condition.wait: a wait that times out advances the
            # virtual clock by its timeout (asyncio.sleep, loop deadlines).
            # asyncio asks for "deadline - now" (a few microseconds less than the
            # delay the code requested): round up to the millisecond so the
            # virtual clock never shows less than the requested delay.
            CLOCK.advance(-(-int(timeout * NS) // 1_000_000) * 1_000_000)
        return ready

    select.__wrapped__ = real
    return select


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
        real = patcher.set(_time, name, disguise(fake, "time", name))
        replacements[id(real)] = (real, fake)
    patcher.set_type_attr(real_datetime, "now", classmethod(_dt_now))
    patcher.set_type_attr(real_datetime, "utcnow", classmethod(_dt_utcnow))
    patcher.set(threading.Condition, "wait", _condition_wait)
    import subprocess

    patcher.set(subprocess.Popen, "__init__", _mark_external(subprocess.Popen.__init__))
    for name in ("fork", "forkpty", "posix_spawn", "posix_spawnp", "spawnv", "spawnve", "system"):
        if hasattr(os, name):
            patcher.set(os, name, _mark_external(getattr(os, name)))
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
    _state._on_other_event = None


def start_test() -> None:
    if CLOCK is not None:
        CLOCK.start_test()
