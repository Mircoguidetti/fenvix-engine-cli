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


MAX_TICK_NS = NS  # the adaptive tick never exceeds one second per read


class VirtualClock:
    """Deterministic clock.

    Adaptive tick: once ``adapt_after`` consecutive clock reads happened with no
    other event in between (no random draw, filesystem listing, network access,
    sleep...), every further read of that run doubles the tick, up to
    ``MAX_TICK_NS``; any other event or the start of a test restores the base
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
        with self._lock:
            self.streak = 0
            self.tick_ns = self.base_tick_ns
            self.test_start = self.elapsed
            self.wall_offset = self.epoch_ns - self.elapsed

    # Derived values ---------------------------------------------------
    def wall_ns(self, e: int) -> int:
        return self.wall_offset + e

    @staticmethod
    def mono_ns(e: int) -> int:
        return _MONO_BASE_NS + e


CLOCK: VirtualClock | None = None


def _rel(e: int) -> str:
    assert CLOCK is not None
    return str(e - CLOCK.test_start)


# Fake time functions ---------------------------------------------------------
def time() -> float:
    e = CLOCK.read()
    _state.record("time", "time.time", _rel(e))
    return CLOCK.wall_ns(e) / NS


def time_ns() -> int:
    e = CLOCK.read()
    _state.record("time", "time.time_ns", _rel(e))
    return CLOCK.wall_ns(e)


def monotonic() -> float:
    e = CLOCK.read()
    _state.record("time", "time.monotonic", _rel(e))
    return CLOCK.mono_ns(e) / NS


def monotonic_ns() -> int:
    e = CLOCK.read()
    _state.record("time", "time.monotonic_ns", _rel(e))
    return CLOCK.mono_ns(e)


def perf_counter() -> float:
    e = CLOCK.read()
    _state.record("time", "time.perf_counter", _rel(e))
    return CLOCK.mono_ns(e) / NS


def perf_counter_ns() -> int:
    e = CLOCK.read()
    _state.record("time", "time.perf_counter_ns", _rel(e))
    return CLOCK.mono_ns(e)


def sleep(secs: float) -> None:
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
    if _state.STATE.config.sleep == "real":
        real_sleep(secs)
    else:
        real_sleep(0)  # still yield the GIL / scheduler


def _wall_secs(op: str) -> float:
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
_real_date_today = real_date.__dict__["today"]


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


def _date_today(cls):
    # Also serves datetime.today(), which C inherits from date.
    return cls.fromtimestamp(_wall_secs("date.today"))


# Wait primitives -----------------------------------------------------------------
_real_condition_wait = threading.Condition.wait


def _condition_wait(self, timeout=None):
    got = _real_condition_wait(self, timeout)
    if not got and timeout is not None and timeout > 0 and CLOCK is not None:
        CLOCK.advance(int(timeout * NS))
    return got


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
    patcher.set_type_attr(real_date, "today", classmethod(_date_today))
    patcher.set(threading.Condition, "wait", _condition_wait)
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
