"""R-008d FIX 7: what a finished start-up process gave back is an input of every test (the start-up digest).

The review's own tests are in ``test_review_r008d.py``. These cover the parts of the rule they do not: the daemon case
as the rule decides it (never cached, so never reused), a pipe read outside ``subprocess.run``, a program that cannot
be started, Python's own files under ``.pytest_cache``, and the pytest-benchmark digest (stable, so its projects keep
their reuse).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
_STARTUP_RULE_NOT_PORTED = pytest.mark.skip(
    reason="R-008c/R-008d start-up process rule (claude/shared-cache Python capture) not yet ported onto the Rust "
           "capture (claude/rust-hotpaths-2)")
pytestmark = [pytestmark, _STARTUP_RULE_NOT_PORTED]

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


def _write(root, files):
    (root / "tox.ini").write_text("[pytest]\n")
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def _tool(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _bin_dir(pytester, name):
    return pytester.path.parent / f"{pytester.path.name}-{name}"


def _startup_digests(cache_dir):
    store = json.loads((cache_dir / "proof-cache.json").read_text())
    return {e.get("startup", "") for e in store["tests"].values()}


DAEMON = """
import os, sys, time
fd = int(sys.argv[1]) if len(sys.argv) > 1 else None
if os.fork():
    sys.exit(0)  # the start-up process returns at once
os.setsid()
null = os.open(os.devnull, os.O_RDWR)
for std in (0, 1, 2):
    os.dup2(null, std)
time.sleep({sleep})
if fd is not None:
    os.write(fd, b"{v}\\n")
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the process tree is observed on Linux")
def test_daemon_with_a_passed_descriptor_keeps_every_test_uncached(pytester):
    """test_review_r008d's daemon case, decided as the rule says: a descriptor passed with pass_fds and a process
    left running each refuse the exemption, so the test is never recorded (and so never reused when the daemon's
    answer changes). The review test asserts run 1 is cacheable, which this rule must refuse."""
    daemon = _bin_dir(pytester, "bin") / "daemon.py"
    daemon.parent.mkdir(parents=True, exist_ok=True)
    daemon.write_text(textwrap.dedent(DAEMON).replace("{sleep}", "0.3").replace("{v}", "1.0"))
    _write(pytester.path, {"conftest.py": f"""
        import os, subprocess, sys

        def pytest_configure(config):
            r, w = os.pipe()
            subprocess.run([sys.executable, {str(daemon)!r}, str(w)], pass_fds=[w], check=True)
            os.close(w)
            config.daemon_fd = r
        """, "test_m.py": """
        import os

        def test_daemon_answer(pytestconfig):
            assert os.read(pytestconfig.daemon_fd, 100).decode().strip() == "1.0"
        """})
    r, c1 = _run(pytester, 1)
    r.assert_outcomes(passed=1)
    assert c1["not_cached_ids"] == {"test_m.py::test_daemon_answer": "subprocess"}
    assert "pass_fds" in c1["not_cached_where"]["test_m.py::test_daemon_answer"]
    daemon.write_text(textwrap.dedent(DAEMON).replace("{sleep}", "0.3").replace("{v}", "2.0"))
    r, c2 = _run(pytester, 2)
    assert c2["reused_ids"] == []
    r.assert_outcomes(failed=1)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the process tree is observed on Linux")
def test_process_left_running_by_a_finished_startup_process_keeps_every_test_uncached(pytester):
    """No channel at all, but a daemon outlives the start-up process that started it: the tests are uncached."""
    daemon = _bin_dir(pytester, "bin") / "daemon.py"
    daemon.parent.mkdir(parents=True, exist_ok=True)
    daemon.write_text(textwrap.dedent(DAEMON).replace("{sleep}", "3").replace("{v}", "1.0"))
    _write(pytester.path, {"conftest.py": f"""
        import subprocess, sys

        def pytest_configure(config):
            subprocess.run([sys.executable, {str(daemon)!r}], check=True)
        """, "test_m.py": TESTS})
    for n in (1, 2):
        r, c = _run(pytester, n)
        r.assert_outcomes(passed=2)
        assert c["reused_ids"] == []
        assert set(c["not_cached_ids"]) == {"test_m.py::test_one", "test_m.py::test_two"}
        assert "left running by a start-up process" in c["not_cached_where"]["test_m.py::test_one"]


def test_output_read_outside_subprocess_run_keeps_the_old_flag(pytester):
    """A pipe read some other way (here a first line read before communicate()) is not seen whole: conservative."""
    tool = _tool(_bin_dir(pytester, "bin") / "fenvixtool", "echo 1.0; echo more")
    _write(pytester.path, {"conftest.py": f"""
        import subprocess

        def pytest_configure(config):
            p = subprocess.Popen([{str(tool)!r}], stdout=subprocess.PIPE, text=True)
            config.tool_version = p.stdout.readline().strip()
            p.communicate()
        """, "test_m.py": """
        def test_tool_version(pytestconfig):
            assert pytestconfig.tool_version == "1.0"
        """})
    r, c = _run(pytester, 1)
    r.assert_outcomes(passed=1)
    assert c["not_cached_ids"] == {"test_m.py::test_tool_version": "subprocess"}
    assert "outside subprocess.run" in c["not_cached_where"]["test_m.py::test_tool_version"]


def test_startup_program_that_cannot_be_started_is_an_input(pytester):
    """A plugin probes for a tool (pytest-benchmark's `file`, missing on slim images): the error is what the start-up
    process gave back. The tests stay cacheable; installing the tool reruns them."""
    tool = _bin_dir(pytester, "bin") / "fenvixtool"
    _write(pytester.path, {"conftest.py": f"""
        import subprocess

        def pytest_configure(config):
            try:
                config.tool_version = subprocess.check_output([{str(tool)!r}], text=True).strip()
            except OSError:
                config.tool_version = None
        """, "test_m.py": """
        def test_no_tool(pytestconfig):
            assert pytestconfig.tool_version is None
        """})
    r, c1 = _run(pytester, 1)
    r.assert_outcomes(passed=1)
    assert c1["not_cached_ids"] == {}
    r, c2 = _run(pytester, 2)
    assert c2["reused_ids"] == ["test_m.py::test_no_tool"]
    _tool(tool, "echo 1.0")
    r, c3 = _run(pytester, 3)
    assert c3["reused_ids"] == []
    r.assert_outcomes(failed=1)


def test_file_python_wrote_under_pytest_cache_is_not_an_input(pytester):
    """Condition 3 keys only what this session's Python did not write there: a fixture's own file keeps the reuse."""
    _write(pytester.path, {"conftest.py": """
        import os
        import pytest

        @pytest.fixture(scope="session")
        def stamp(pytestconfig):
            d = os.path.join(str(pytestconfig.rootpath), ".pytest_cache", "d", "own")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "stamp.txt")
            with open(p, "w") as f:
                f.write("ok")
            with open(p) as f:
                return f.read()
        """, "test_m.py": """
        def test_stamp(stamp):
            assert stamp == "ok"
        """})
    r, c1 = _run(pytester, 1)
    assert c1["not_cached_ids"] == {}
    r, c2 = _run(pytester, 2)
    assert c2["reused_ids"] == ["test_m.py::test_stamp"]


@pytest.mark.skipif(importlib.util.find_spec("pytest_benchmark") is None, reason="pytest-benchmark not installed")
@pytest.mark.skipif(shutil.which("file") is None, reason="needs the `file` program")
def test_pytest_benchmark_startup_digest_is_stable_and_portable(pytester):
    """pytest-benchmark's `file -b <python>` is keyed: the start-up digest is set, the same on every run on one
    machine, and the same for the same project in another directory (cwd and the interpreter path are portable), so
    the reuse stays."""
    _write(pytester.path, {"test_m.py": TESTS})
    both = {"test_m.py::test_one", "test_m.py::test_two"}
    r, c1 = _run(pytester, 1)
    assert c1["not_cached_ids"] == {}
    d1 = _startup_digests(pytester.path / ".cachedir")
    r, c2 = _run(pytester, 2)
    assert set(c2["reused_ids"]) == both
    d2 = _startup_digests(pytester.path / ".cachedir")
    assert len(d1) == 1 and "" not in d1 and d1 == d2
    other = pytester.path.parent / f"{pytester.path.name}-checkout2"
    other.mkdir()
    _write(other, {"test_m.py": TESTS})
    out = other / "out.json"
    subprocess.run([sys.executable, "-m", "pytest", "--det", f"--det-cache={other / '.cachedir'}",
                    f"--det-outcomes={out}", "-p", "no:cacheprovider", "-q"], cwd=other, check=True,
                   capture_output=True)
    assert json.loads(out.read_text())["cache"]["not_cached_ids"] == {}
    assert _startup_digests(other / ".cachedir") == d1
