"""Process-wide state shared by the controls and the pytest plugin."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from . import _core, _sites

_get_ident = threading.get_ident
_tls = threading.local()


@dataclass
class Config:
    seed: int = 0
    shuffle: bool = False
    epoch_ns: int = 1_735_689_600 * 1_000_000_000  # 2025-01-01T00:00:00Z
    tick_ns: int = 1_000
    tick_adapt: int = 8
    sleep: str = "virtual"  # virtual | real
    controls: frozenset = frozenset({"order", "seeds", "time", "fs", "net"})
    record_net: bool = False
    cassette_path: str | None = None
    allow_hosts: tuple = ()
    control_urandom: bool = False
    max_events: int = 10_000


@dataclass
class State:
    config: Config = field(default_factory=Config)
    recorder: Any = None  # _core.Recorder
    nodeid: str | None = None
    test_index: int = -1
    test_thread: int | None = None
    threads: dict = field(default_factory=dict)
    installed: list = field(default_factory=list)


STATE = State()
_on_other_event = None  # set by the clock when the adaptive tick is on


def reset_threads() -> None:
    STATE.test_thread = _get_ident()
    STATE.threads = {STATE.test_thread: 0}


def record(source: str, op: str, value: str, depth: int = 1) -> None:
    """Record one event for the running test.

    ``depth`` is the number of frames between the caller of this function and
    the frame that called the patched API (1 = our wrapper called us directly).
    """
    if source != "time" and _on_other_event is not None:
        _on_other_event()  # breaks the clock's run of consecutive reads
    rec = STATE.recorder
    if rec is None or STATE.nodeid is None or getattr(_tls, "busy", False):
        return
    site = _sites.resolve(depth + 1)
    if site is None:  # infrastructure (pytest, detpy) touched the source
        return
    buf = getattr(_tls, "buffer", None)
    if buf is not None:  # --det-async executor job: recorded when its result is delivered
        buf.append((source, op, site, value))
        return
    tid = _get_ident()
    threads = STATE.threads
    t = threads.get(tid)
    if t is None:
        t = threads[tid] = len(threads)
    rec.record(source, op, site, value, t)


def set_event_buffer(buf):
    """Divert this thread's events into ``buf`` (None: record directly); returns the previous one."""
    prev = getattr(_tls, "buffer", None)
    _tls.buffer = buf
    return prev


def record_at(source: str, op: str, site: str, value: str) -> None:
    """Record an event with an explicit site (used by detpy itself)."""
    rec = STATE.recorder
    if rec is not None and STATE.nodeid is not None:
        rec.record(source, op, site, value, 0)


class quiet:
    """Context manager: patched APIs called inside do not record events."""

    __slots__ = ("prev",)

    def __enter__(self) -> None:
        self.prev = getattr(_tls, "busy", False)
        _tls.busy = True

    def __exit__(self, *exc: object) -> None:
        _tls.busy = self.prev


def is_quiet() -> bool:
    return getattr(_tls, "busy", False)


def digest(data: bytes) -> str:
    return _core.digest(data)


def digest_names(names: list) -> str:
    parts = [n if isinstance(n, bytes) else str(n).encode("utf-8", "surrogateescape") for n in names]
    return _core.digest(b"\0".join(parts))
