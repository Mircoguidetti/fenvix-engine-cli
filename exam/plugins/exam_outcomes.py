"""pytest plugin of the exam (`-p exam_outcomes`): the reference outcome map of a plain run, written to
$EXAM_OUTCOMES as {"outcomes": {nodeid: passed|failed|skipped}}. It changes nothing in the run."""
import json
import os

_out = {}


def pytest_runtest_logreport(report):
    nid = report.nodeid
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        o = "skipped" if report.skipped else ("failed" if report.failed else "passed")
        if hasattr(report, "wasxfail"):
            o = "skipped" if report.skipped else "passed"
        _out[nid] = o
    elif report.when == "teardown" and report.failed:
        _out[nid] = "failed"


def pytest_sessionfinish(session):
    p = os.environ.get("EXAM_OUTCOMES")
    if p:
        with open(p, "w") as fh:
            json.dump({"outcomes": _out}, fh)
