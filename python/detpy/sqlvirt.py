"""SQLite's clock and randomness under Level 0 (glue; the functions are Rust: ``crates/detpy-py/src/sqlvirt.rs``).

Every connection made through ``sqlite3.connect`` after Level 0 is installed gets per-connection overrides of
SQLite's date and time functions (``'now'`` is the virtual clock, read once per statement), ``CURRENT_TIMESTAMP`` /
``CURRENT_DATE`` / ``CURRENT_TIME`` (column defaults included) and ``random()`` / ``randomblob()`` (a stream seeded
per test). A connection made before (a plugin at import time) keeps SQLite's own functions.

The cache with proof sets its statement trace behind the connection's (``set_trace``): a virtualised connection's
``'now'`` is a virtual clock read (an input through the epoch), not a real clock read.
"""

from __future__ import annotations

import threading

from . import _core

# the virtualisation of the connection the innermost patched connect just made, for the wrapper around it (the
# cache's connect) to take right after the call returns (sqlite3.Connection has no weak references: no registry)
_LAST = threading.local()
_installed = False
_HELPER = None


def install(patcher) -> None:
    global _installed
    try:
        import sqlite3
        import sqlite3.dbapi2 as dbapi2
    except ImportError:  # pragma: no cover - Python built without sqlite
        return
    real = sqlite3.connect
    # the helper whose built-ins evaluate the calls: SQLite's own functions, no override. One per process, kept
    # until the interpreter exits (a connection virtualised earlier may still call it; dropping it would also raise a
    # ResourceWarning, an error under filterwarnings = error)
    global _HELPER
    if _HELPER is None:
        import atexit

        _HELPER = real(":memory:", check_same_thread=False)
        atexit.register(_HELPER.close)
    _core.sqlvirt_configure(_HELPER)

    def connect(*args, **kwargs):
        conn = real(*args, **kwargs)
        try:
            v = _core.SqlVirt()
            v.install(conn)
            _LAST.v = v
        except Exception:  # a connection type without create_function (a factory): SQLite's own functions
            pass
        return conn

    connect.__wrapped__ = real
    connect.__doc__ = real.__doc__
    patcher.set(sqlite3, "connect", connect)
    patcher.set(dbapi2, "connect", connect)
    _installed = True


def uninstall() -> None:
    global _installed
    _installed = False  # the helper stays: connections made under Level 0 keep their functions


def take_last():
    """The virtualisation of the connection the patched connect just returned in this thread (None: not
    virtualised); called once, right after the call."""
    v = getattr(_LAST, "v", None)
    _LAST.v = None
    return v


def set_trace(conn, virt, trace) -> None:
    """The cache's statement trace for ``conn``: behind the virtualisation's own (which starts each statement)."""
    if virt is not None:
        virt.set_inner(trace)
    else:
        conn.set_trace_callback(trace)


def start_test(seed: int) -> None:
    _core.sqlvirt_start_test(seed)
