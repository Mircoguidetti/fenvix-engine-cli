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
    # The cache audit (default 5% of the reusable results run fresh) would make the reuse counts of the other suites
    # random: off unless a test asks for it (tests/test_cache_audit.py).
    monkeypatch.setenv("FENVIX_AUDIT_SHARE", "0")
    for var in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
