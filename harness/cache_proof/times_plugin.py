"""pytest plugin for the cache-proof walk (``-p times_plugin``): per-test duration and outcome.

Writes ``$CP_TIMES_OUT`` at the end of the session: ``{"tests": {nodeid: [duration, outcome]}, "wall": s}``.
Duration = setup + call + teardown from pytest's reports (0 for results reused by ``--det-cache``).
"""

from __future__ import annotations

import json
import os
import time

_T0 = time.perf_counter()
_tests: dict[str, list] = {}


def pytest_runtest_logreport(report):
    rec = _tests.setdefault(report.nodeid, [0.0, None])
    rec[0] += report.duration
    o = report.outcome
    if hasattr(report, "wasxfail"):
        o = "xfailed" if report.skipped else "xpassed"
    if report.when == "call" or (report.when == "setup" and o != "passed") or rec[1] is None:
        rec[1] = o if not (report.when == "teardown" and o == "failed") else "error"
    elif report.when == "teardown" and o == "failed":
        rec[1] = "error"


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("CP_TIMES_OUT")
    if not out:
        return
    with open(out, "w") as fh:
        json.dump({"tests": _tests, "wall": time.perf_counter() - _T0, "exit": int(exitstatus)}, fh)
