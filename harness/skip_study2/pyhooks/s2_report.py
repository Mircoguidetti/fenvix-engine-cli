"""pytest plugin (``-p s2_report``): per-test outcome and duration to the JSON file named by S2_REPORT."""

import json
import os
import time

_tests = {}
_t0 = time.perf_counter()
_marks = {}


def pytest_collection_finish(session):
    _marks["collected"] = time.perf_counter() - _t0
    _marks["n"] = len(session.items)


def pytest_collectreport(report):
    if report.failed:
        _tests["<collect>::" + report.nodeid] = ["error", 0.0]


def pytest_runtest_logreport(report):
    rec = _tests.setdefault(report.nodeid, [None, 0.0])
    rec[1] += report.duration
    o = report.outcome
    if report.when == "call":
        if rec[0] in (None, "passed"):
            rec[0] = "xfailed" if hasattr(report, "wasxfail") and o == "skipped" else o
    elif o == "failed":
        rec[0] = "error"
    elif o == "skipped" and report.when == "setup":
        rec[0] = "skipped"
    elif rec[0] is None and report.when == "teardown":
        rec[0] = "passed"


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("S2_REPORT")
    if out:
        _marks["finish"] = time.perf_counter() - _t0
        with open(out, "w") as fh:
            json.dump({"exit": int(exitstatus), "tests": _tests, "marks": _marks}, fh)
