"""Review R-032b's file is copied unchanged (claude/review-r032b 6f49632). Its runner-driver cases run
``python -m detpy <runner>`` (unittest, nose2, zope, django, ward, doctest), which exists on claude/all-runners-2,
not on this branch: those cases are skipped here and run where the drivers are (the all-runners-2 session merges
this branch). The pytest-plugin cases (W1 under the pytest plugin, W15 under pytest-xdist) run here; the engine
fixes are tested on the pytest plugin by tests/test_r032b_engine.py (W1-W7, serial and -n 2)."""

import subprocess
import sys

import pytest

_HAS_RUNNERS = None


def _runners() -> bool:
    global _HAS_RUNNERS
    if _HAS_RUNNERS is None:
        p = subprocess.run([sys.executable, "-m", "detpy", "unittest", "--help"], capture_output=True, text=True)
        _HAS_RUNNERS = p.returncode == 0
    return _HAS_RUNNERS


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "pytest_plugin" in item.name or "xdist" in item.name:
            continue
        if not _runners():
            item.add_marker(pytest.mark.skip(reason="needs claude/all-runners-2's `python -m detpy <runner>`"))
