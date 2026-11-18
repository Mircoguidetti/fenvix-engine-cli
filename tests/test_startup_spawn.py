"""A process started while pytest starts (a plugin's ``pytest_configure`` or ``pytest_sessionstart``), outside every
test, is not an input of the tests.

pytest-benchmark calls ``platform.architecture()`` from ``pytest_configure``, which runs ``file -b <python>`` through
``subprocess.Popen`` (``pytest_benchmark/utils.py:68``). detpy flagged that start-up spawn on the start-up context,
an input of every test, so with the plugin installed no test was ever cacheable.

Rule: a process started at start-up that has finished, and whose pipes are closed, before the first collection or
test is ignored (nobody can talk to it any more). One still running, or with a pipe still open, when the tests start
keeps the tests uncached (a test may talk to it).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

TESTS = """
def test_one():
    assert 1 + 1 == 2

def test_two():
    assert "a" * 2 == "aa"
"""


def _run(pytester, n, *args):
    out = pytester.path / f"out{n}.json"
    r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.cachedir'}", f"--det-outcomes={out}",
                                      "-p", "no:cacheprovider", *args)
    return r, json.loads(out.read_text())["cache"]


def _write(pytester, files):
    pytester.makeini("[pytest]\n")
    for name, text in files.items():
        (pytester.path / name).write_text(textwrap.dedent(text))


@pytest.mark.parametrize("hook", ["pytest_configure(config)", "pytest_sessionstart(session)"])
def test_finished_startup_process_does_not_taint_the_tests(pytester, hook):
    """A tiny plugin that runs a program at start-up (as pytest-benchmark does): its tests are reused on the second
    run."""
    _write(pytester, {"conftest.py": f"""
        import subprocess, sys

        def {hook}:
            subprocess.check_output([sys.executable, "-c", "print('x86_64')"])
            p = subprocess.Popen([sys.executable, "-c", "pass"])
            p.wait()
        """, "test_m.py": TESTS})
    r, c1 = _run(pytester, 1)
    r.assert_outcomes(passed=2)
    assert c1["not_cached_ids"] == {}
    r, c2 = _run(pytester, 2)
    r.assert_outcomes(passed=2)
    assert set(c2["reused_ids"]) == {"test_m.py::test_one", "test_m.py::test_two"}


def test_startup_process_a_test_talks_to_keeps_that_test_uncached(pytester):
    """A start-up process still running when the tests start: a test that talks to it is never reused."""
    _write(pytester, {"conftest.py": """
        import subprocess, sys

        def pytest_configure(config):
            config.helper = subprocess.Popen(
                [sys.executable, "-c", "import sys\\nfor l in sys.stdin: print(l.strip() * 2, flush=True)"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

        def pytest_unconfigure(config):
            config.helper.stdin.close()
            config.helper.wait()
        """, "test_m.py": """
        def test_talks(pytestconfig):
            h = pytestconfig.helper
            h.stdin.write("ab\\n")
            h.stdin.flush()
            assert h.stdout.readline().strip() == "abab"
        """})
    for n in (1, 2):
        r, c = _run(pytester, n)
        r.assert_outcomes(passed=1)
        assert c["reused_ids"] == []
        assert c["not_cached_ids"] == {"test_m.py::test_talks": "subprocess"}
        assert "still running when the tests start" in c["not_cached_where"]["test_m.py::test_talks"]


def test_spawn_inside_a_test_still_keeps_that_test_uncached(pytester):
    """The start-up exemption does not reach a test's own window (nor collection, nor the other tests)."""
    _write(pytester, {"conftest.py": """
        import subprocess, sys

        def pytest_configure(config):
            subprocess.run([sys.executable, "-c", "pass"], check=True)
        """, "test_m.py": TESTS + """
import subprocess, sys

def test_spawns():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
"""})
    _run(pytester, 1)
    r, c = _run(pytester, 2)
    r.assert_outcomes(passed=3)
    assert set(c["reused_ids"]) == {"test_m.py::test_one", "test_m.py::test_two"}
    assert c["not_cached_ids"] == {"test_m.py::test_spawns": "subprocess"}


@pytest.mark.skipif(importlib.util.find_spec("pytest_benchmark") is None, reason="needs pytest-benchmark")
def test_pytest_benchmark_installed_does_not_taint_the_tests(pytester):
    """The real plugin, loaded through its entry point (the CI package set installs it)."""
    _write(pytester, {"test_m.py": TESTS})
    r, c1 = _run(pytester, 1)
    r.assert_outcomes(passed=2)
    assert c1["not_cached_ids"] == {}
    r, c2 = _run(pytester, 2)
    assert set(c2["reused_ids"]) == {"test_m.py::test_one", "test_m.py::test_two"}


def test_environment_handed_to_a_startup_process_is_not_an_input_of_the_tests(pytester, monkeypatch):
    """platform.architecture() (pytest-benchmark) builds the child's environment with ``dict(os.environ, ...)``: that
    enumeration is the start-up process's input, so a variable no test reads may change between runs."""
    _write(pytester, {"conftest.py": """
        import os, subprocess, sys

        def pytest_configure(config):
            env = dict(os.environ, LC_ALL="C")
            subprocess.check_output([sys.executable, "-c", "pass"], env=env)
        """, "test_m.py": TESTS})
    monkeypatch.delenv("DETPY_T_UNREAD", raising=False)
    _run(pytester, 1)
    monkeypatch.setenv("DETPY_T_UNREAD", "x")
    r, c = _run(pytester, 2)
    r.assert_outcomes(passed=2)
    assert set(c["reused_ids"]) == {"test_m.py::test_one", "test_m.py::test_two"}


def test_environment_kept_at_startup_is_still_an_input_of_every_test(pytester, monkeypatch):
    """An enumeration not handed to a start-up process (kept for the tests) stays an input of every test, even when
    the same hook also starts a process."""
    _write(pytester, {"conftest.py": """
        import os, subprocess, sys

        def pytest_configure(config):
            config.env_copy = dict(os.environ)
            subprocess.run([sys.executable, "-c", "pass"], check=True)
        """, "test_m.py": """
        def test_reads_the_copy(pytestconfig):
            assert pytestconfig.env_copy.get("DETPY_T_FLAG", "0") == "0"
        """})
    monkeypatch.delenv("DETPY_T_FLAG", raising=False)
    _run(pytester, 1)
    _, c = _run(pytester, 2)
    assert c["reused_ids"] == ["test_m.py::test_reads_the_copy"]
    monkeypatch.setenv("DETPY_T_FLAG", "1")
    r, c = _run(pytester, 3)
    r.assert_outcomes(failed=1)
    assert c["reused_ids"] == []
    assert c["miss_ids"]["test_m.py::test_reads_the_copy"].startswith("env")
