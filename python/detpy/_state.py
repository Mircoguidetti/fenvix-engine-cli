"""Process-wide state shared by the controls and the pytest plugin."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from . import _core, _sites

_get_ident = threading.get_ident


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
    cassette_max_age: float = 0.0
    # Level 1 (--det-async, --det-threads), None when the option was not given. The scheduler's own settings live
    # here so that every runner (pytest, unittest, django, doctest, nose2) installs them the same way.
    det_async: dict | None = None  # seed, grace, wait, settle
    det_threads: dict | None = None  # seed, grace, deadlock, preempt, stuck


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


_event_listener = None  # set by the cache with proof: called with (source, value) for every user event


def set_event_listener(fn) -> None:
    global _event_listener
    _event_listener = fn


# _state.record(source, op, value, depth=1): record one event for the running test. ``depth`` is the number of
# frames between the caller of this function and the frame that called the patched API (1 = our wrapper called us
# directly). In Rust (``_core.l0_record``, wired to STATE, this module's ``_event_listener`` / ``_on_other_event``
# and ``_sites``' classification cache by ``l0_configure`` below); the Python original is
# ``tests/rust_hotpaths_ref/_ref_l0_state.py``.
record = _core.l0_record


# --det-threads / --det-async, both per thread and kept in Rust next to the quiet flag, so ``record`` reads them
# without entering the interpreter:
#
# * ``set_tkey(key)`` / ``get_tkey()``: the event key of a thread the scheduler manages (``threads.Thread.key``).
#   Without it ``record`` keys a thread's events by its OS ident, which the OS hands out again once the thread
#   ends: a later thread would take the finished one's column and the trace would differ between runs over
#   nothing the test did (``--det-threads`` round 2).
# * ``set_event_buffer(buf)``: while ``buf`` is a list, this thread's events are appended to it instead of
#   recorded, and ``detpy.aio`` records them with ``record_at`` at the virtual time the loop delivers the
#   executor job's result, instead of wherever the pool happened to run it.
#
# Both return the previous value, so a caller restores it in a ``finally``.
set_tkey = _core.l0_set_tkey
get_tkey = _core.l0_get_tkey
set_event_buffer = _core.l0_set_event_buffer


def record_at(source: str, op: str, site: str, value: str) -> None:
    """Record an event with an explicit site (used by detpy itself)."""
    rec = STATE.recorder
    if rec is not None and STATE.nodeid is not None:
        rec.record(source, op, site, value, 0)


class quiet:
    """Context manager: patched APIs called inside do not record events (a per-thread flag kept in Rust, which
    ``record`` reads)."""

    __slots__ = ("prev",)

    def __enter__(self) -> None:
        self.prev = _core.l0_set_busy(True)

    def __exit__(self, *exc: object) -> None:
        _core.l0_set_busy(self.prev)


is_quiet = _core.l0_is_busy


def digest(data: bytes) -> str:
    return _core.digest(data)


# digest_names(names): digest of the names (bytes as they are, others str(n) encoded "utf-8" / "surrogateescape")
# joined by NUL. In Rust; the Python original is ``tests/rust_hotpaths_ref/_ref_l0_state.py``.
digest_names = _core.l0_digest_names


_core.l0_configure(STATE, globals(), vars(_sites))
