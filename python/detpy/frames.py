"""Keep detpy's own frames out of what the code under test sees of other threads.

``sys._current_frames()`` shows the innermost frame of every thread. A thread that
sleeps in plain Python shows the caller of ``time.sleep`` (a C function) on top;
under ``--det`` it showed detpy's sleep wrapper (``clock.py``), and under
``--det-threads`` the scheduler's wait (``threads.py``). Code that inspects other
threads' stacks (easypy's ``MultiObject`` logs where each worker is waiting) then
reported a detpy location: a false failure made by the engine (review R-007,
easypy ``test_multiobject_logging``).

Under ``--det`` every thread's frame is the innermost one outside detpy, as in a
plain run; threads that run only detpy code (the scheduler's watchdog, a managed
thread not yet released by the scheduler) are left out.
"""

from __future__ import annotations

import os
import sys

_DETPY_DIR = os.path.dirname(os.path.abspath(__file__))
_real_current_frames = sys._current_frames


def _outside_detpy(frame):
    f = frame
    while f is not None and f.f_code.co_filename.startswith(_DETPY_DIR):
        f = f.f_back
    return f


def current_frames():
    out = {}
    for ident, frame in _real_current_frames().items():
        f = _outside_detpy(frame)
        if f is not None:
            out[ident] = f
    return out


current_frames.__wrapped__ = _real_current_frames
current_frames.__doc__ = _real_current_frames.__doc__


def install(patcher) -> None:
    patcher.set(sys, "_current_frames", current_frames)
