"""pytest plugin (``-p harness.parallel_proof.phasetimes``): per-process phase times for item 4 of parallel-proof
round 3 (where ``--det -n 4`` spends its time against plain ``-n 4``).

Every process of the run (the controller, a re-executed controller, each xdist worker) appends one JSON line to
``$PHASETIMES_OUT``: its pid, role, whether it is the re-executed process, and the times (seconds since boot,
``/proc/uptime`` scale from ``/proc/self/stat``'s start time and ``time.clock_gettime(CLOCK_BOOTTIME)``, real clocks
bound at import, before Level 0) of: process start, this module's import (= the plugins' load), configure, collection
finish, first test start, last test end, session finish. MEASURED values; nothing here changes a test.
"""

from __future__ import annotations

import json
import os
import time

_boot = time.clock_gettime  # bound before Level 0 virtualises the time module
_BOOT = getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC)


def _now() -> float:
    return _boot(_BOOT)


def _start() -> float | None:
    try:
        with open("/proc/self/stat") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
        return int(fields[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None


T = {"start": _start(), "import": _now()}


def pytest_configure(config):
    T["configure"] = _now()
    T["role"] = "worker" if hasattr(config, "workerinput") else "controller"


def pytest_collection_finish(session):
    T["collected"] = _now()


def pytest_runtest_logstart(nodeid, location):
    T.setdefault("first_test", _now())


def pytest_runtest_logfinish(nodeid, location):
    T["last_test"] = _now()


def pytest_sessionfinish(session):
    T["finish"] = _now()
    out = os.environ.get("PHASETIMES_OUT")
    if not out:
        return
    T["pid"] = os.getpid()
    T["reexec"] = os.environ.get("DETPY_REEXEC") == "1"
    with open(out, "a") as fh:
        fh.write(json.dumps(T) + "\n")
