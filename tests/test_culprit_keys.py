"""--det-cache-keys (prototype for the exact-culprit finder): every test's inputs are written, failures included,
and nothing about the cache changes. Plus the interpreter start-up gap the validation found (strict xfail)."""

import json
import sys

import pytest

from test_proofcache import ids, project, run_cache  # noqa: F401 (fixtures)

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

MOD = """
def f(x):
    return x + 1

def g(x):
    return x * 2
"""

TESTS = """
import os
from pkg import mod

def test_f():
    assert mod.f(1) == 2

def test_g_fails():
    os.environ.get("CULPRIT_VAR")
    assert mod.g(2) == 5
"""


def test_key_dump_lists_failures_and_inputs(pytester, run_cache):
    project(pytester, **{"pkg/mod.py": MOD, "test_m.py": TESTS})
    keys = pytester.path / "keys.json"
    r, _reused, _data = run_cache(f"--det-cache-keys={keys}")
    r.assert_outcomes(passed=1, failed=1)
    d = json.loads(keys.read_text())
    t = d["tests"]
    assert set(t) == ids("test_f", "test_g_fails")
    assert t["test_m.py::test_g_fails"]["outcome"] == "failed"
    assert "unit:pkg/mod.py::g" in t["test_m.py::test_g_fails"]["code"]
    assert "unit:pkg/mod.py::f" not in t["test_m.py::test_g_fails"]["code"]
    assert "CULPRIT_VAR" in t["test_m.py::test_g_fails"]["env"]
    assert d["runtime"] and d["distributions"] and "pytest" in d["loaded_distributions"]
    assert "warnoptions" in d["interpreter"] and "env" in d["interpreter"]


def test_key_dump_does_not_change_the_cache(pytester, run_cache):
    project(pytester, **{"pkg/mod.py": MOD, "test_m.py": TESTS})
    run_cache(f"--det-cache-keys={pytester.path / 'k1.json'}")
    # the dump path is not configuration: a run with another path (or none) reuses the passing test
    r, reused, _ = run_cache(f"--det-cache-keys={pytester.path / 'k2.json'}")
    assert reused == ids("test_f")
    r, reused, _ = run_cache()
    assert reused == ids("test_f")


def test_key_dump_records_startup_python_variables(pytester, run_cache, monkeypatch):
    project(pytester, **{"pkg/mod.py": MOD, "test_m.py": TESTS})
    monkeypatch.setenv("PYTHONWARNINGS", "error")
    keys = pytester.path / "keys.json"
    run_cache(f"--det-cache-keys={keys}")
    d = json.loads(keys.read_text())
    assert "PYTHONWARNINGS" in d["interpreter"]["env"]


@pytest.mark.xfail(strict=True, reason="validation finding (exact culprit, 2026-11-18): PYTHONWARNINGS and the other "
                   "interpreter start-up settings are read by C, not through os.environ, and are in neither the "
                   "configuration nor the runtime digest, so a pass recorded without them is reused with them")
def test_pythonwarnings_is_an_input(pytester, run_cache, monkeypatch):
    project(pytester, **{"test_w.py": """
        import warnings

        def old():
            warnings.warn("old", DeprecationWarning)
            return 1

        def test_w():
            assert old() == 1
        """})
    run_cache()
    monkeypatch.setenv("PYTHONWARNINGS", "error")
    r, reused, _ = run_cache()
    # a fresh run fails (the warning is an error): the cached pass must not be reused
    assert reused == set()
