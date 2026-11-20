import json
import os

import pytest


def load_trace(path):
    lines = [json.loads(line) for line in open(path) if line.strip()]
    header = lines[0]
    tests = {line["nodeid"]: line for line in lines if line["type"] == "test"}
    footer = lines[-1] if lines[-1]["type"] == "footer" else None
    return header, tests, footer


@pytest.fixture
def run_det(pytester):
    """Run pytest in a subprocess with --det and return (result, trace)."""

    counter = {"n": 0}

    def run(*args, trace=None):
        counter["n"] += 1
        trace = trace or str(pytester.path / f"trace{counter['n']}.jsonl")
        result = pytester.runpytest_subprocess("--det", f"--det-trace={trace}", "-p", "no:cacheprovider", *args)
        t = load_trace(trace) if os.path.exists(trace) else None
        return result, t

    return run


@pytest.fixture(scope="session")
def pyc_cache(tmp_path_factory):
    return str(tmp_path_factory.mktemp("detpy-pyc"))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, pyc_cache):
    # pytester points HOME at each test's directory: share the bytecode cache.
    monkeypatch.setenv("DETPY_PYC_CACHE", pyc_cache)
    # The subprocesses must decide about re-exec themselves.
    monkeypatch.delenv("DETPY_REEXEC", raising=False)
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    for var in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_benchmark_plugin_in_pytester(request, _clean_env):
    """pytest-benchmark (installed by the harness CI job) calls ``platform.architecture()`` in its pytest_configure:
    it iterates ``os.environ`` and spawns ``file``, so every test of an inner run carries the whole environment (sound:
    the child's environment reads are not observed) and any variable a test here changes invalidates every entry.
    The inner runs of these tests leave the plugin out; a test marked ``benchmark_plugin`` keeps it."""
    if "pytester" in request.fixturenames and request.node.get_closest_marker("benchmark_plugin") is None:
        pt = request.getfixturevalue("pytester")
        base = pt._getpytestargs
        pt._getpytestargs = lambda: (*base(), "-p", "no:benchmark")  # every runpytest_subprocess of the test


def pytest_configure(config):
    config.addinivalue_line("markers", "benchmark_plugin: the inner pytest runs load pytest-benchmark if installed")


# Review R-032b's file (tests/review_r032b/test_review_r032b_python.py, copied unchanged from claude/review-r032b
# 6f49632): its runner-driver cases run `python -m detpy <runner>` (unittest, nose2, zope, django, ward, doctest),
# which exists on claude/all-runners-2, not on this branch. They are skipped here and run where the drivers are (the
# all-runners-2 session merges this branch); its pytest-plugin cases (W1, W15) run here. The engine fixes are tested
# on the pytest plugin by tests/test_r032b_engine.py (W1-W7, serial and -n 2).
_R032B_RUNNERS = []


def _r032b_runners() -> bool:
    if not _R032B_RUNNERS:
        import subprocess
        import sys

        p = subprocess.run([sys.executable, "-m", "detpy", "unittest", "--help"], capture_output=True, text=True)
        _R032B_RUNNERS.append(p.returncode == 0)
    return _R032B_RUNNERS[0]


def pytest_collection_modifyitems(config, items):
    for item in items:
        if _uses_shared_cache(item):
            item.add_marker(pytest.mark.skip(reason=_OUT_OF_SCOPE))
            continue
        if "review_r032b" not in str(item.fspath) or "pytest_plugin" in item.name or "xdist" in item.name:
            continue
        if not _r032b_runners():
            item.add_marker(pytest.mark.skip(reason="needs claude/all-runners-2's `python -m detpy <runner>`"))


# Go-live scope (decided 2026-11-20): the shared cache across machines (--det-cache-shared, detpy_core::shared) is out.
# Its tests (reviewer files included, kept unchanged) are skipped, not deleted: a test whose body passes the option is
# marked here.
_OUT_OF_SCOPE = "out of go-live scope"


def _uses_shared_cache(item) -> bool:
    import inspect

    fn = getattr(item, "function", None)
    try:
        src = inspect.getsource(fn) if fn is not None else ""
    except (OSError, TypeError):
        return False
    return "--det-cache-shared" in src
