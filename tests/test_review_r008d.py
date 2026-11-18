"""R-008d review: the start-up subprocess rule (63a7efb, fc5b70b).

Rule under review: a ``subprocess.Popen`` started at pytest start-up (``pytest_configure``, ``pytest_sessionstart``)
that has finished, with its pipes closed, before the first collection is ignored; environment reads of the frame
that copies the environment into its ``env=`` are dropped.

Every test below is a case where the cache reuses a test's 'passed' result although a fresh run of the same suite
FAILS: run 1 records, something outside the recorded inputs changes, run 2 must not reuse. Before the rule each of
these suites was uncached (the start-up spawn tainted every test), so each is a hole the rule opened.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def _run(pytester, n, *args):
    out = pytester.path / f"out{n}.json"
    r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.cachedir'}", f"--det-outcomes={out}",
                                      "-p", "no:cacheprovider", *args)
    return r, json.loads(out.read_text())["cache"]


def _write(pytester, files):
    pytester.makeini("[pytest]\n")
    for name, text in files.items():
        p = pytester.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def _tool(path, version):
    """An executable outside the repository root that prints a version (like `node --version`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho {version}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _bin_dir(pytester, name):
    """A directory next to (not inside) the repository root."""
    return pytester.path.parent / f"{pytester.path.name}-{name}"


def _assert_recorded_then_not_reused(pytester, nid):
    """Run 1 passes and records ``nid`` (cacheable); the caller then changes something outside the recorded inputs;
    run 2 must run it fresh (and fail)."""
    r, c1 = _run(pytester, 1)
    r.assert_outcomes(passed=1)
    assert c1["not_cached_ids"] == {}, c1["not_cached_ids"]  # the rule made it cacheable


def _assert_fresh_failure(pytester, nid):
    r, c2 = _run(pytester, 2)
    assert c2["reused_ids"] == [], f"{nid} reused although a fresh run differs: {c2['reused_ids']}"
    r.assert_outcomes(failed=1)


def test_startup_tool_output_kept_in_config_is_an_input(pytester):
    """A plugin reads a tool's version at pytest_configure and exposes it on config (the main suspicion).
    The tool is upgraded between runs: the test that checks the version must not be reused."""
    tool = _tool(_bin_dir(pytester, "bin") / "fenvixtool", "1.0")
    _write(pytester, {"conftest.py": f"""
        import subprocess

        def pytest_configure(config):
            config.tool_version = subprocess.check_output([{str(tool)!r}, "--version"], text=True).strip()
        """, "test_m.py": """
        def test_tool_version(pytestconfig):
            assert pytestconfig.tool_version == "1.0"
        """})
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_tool_version")
    _tool(tool, "2.0")  # the tool's binary (and so its output) changes
    _assert_fresh_failure(pytester, "test_m.py::test_tool_version")


def test_startup_tool_found_through_path_is_an_input(pytester, monkeypatch):
    """The same command on another machine: `fenvixtool --version` resolves through PATH to a different binary.
    The value reaches the test through a session fixture."""
    b1 = _bin_dir(pytester, "m1")
    b2 = _bin_dir(pytester, "m2")
    _tool(b1 / "fenvixtool", "1.0")
    _tool(b2 / "fenvixtool", "2.0")
    _write(pytester, {"conftest.py": """
        import subprocess
        import pytest

        def pytest_configure(config):
            config.tool_version = subprocess.check_output(["fenvixtool", "--version"], text=True).strip()

        @pytest.fixture(scope="session")
        def tool_version(pytestconfig):
            return pytestconfig.tool_version
        """, "test_m.py": """
        def test_tool_version(tool_version):
            assert tool_version == "1.0"
        """})
    path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{b1}{os.pathsep}{path}")
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_tool_version")
    monkeypatch.setenv("PATH", f"{b2}{os.pathsep}{path}")
    _assert_fresh_failure(pytester, "test_m.py::test_tool_version")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_startup_git_describe_is_an_input(pytester):
    """A version plugin (setuptools_scm style) runs `git describe` at configure. A new tag on a new commit (a change
    to a file no test reads) changes the value a test checks."""
    _write(pytester, {"conftest.py": """
        import subprocess

        def pytest_configure(config):
            config.version = subprocess.check_output(["git", "describe", "--tags"], cwd=config.rootpath,
                                                     text=True).strip()
        """, "test_m.py": """
        def test_version_is_a_1x(pytestconfig):
            assert pytestconfig.version.startswith("v1.")
        """, "NOTES.txt": "one\n"})
    g = ["git", "-c", "user.name=review", "-c", "user.email=review@example.invalid", "-c", "commit.gpgsign=false"]

    def git(*a):
        subprocess.run(g + list(a), cwd=pytester.path, check=True, capture_output=True)

    git("init", "-q")
    git("add", "conftest.py", "test_m.py", "NOTES.txt", "tox.ini")
    git("commit", "-q", "-m", "one")
    git("tag", "v1.0")
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_version_is_a_1x")
    (pytester.path / "NOTES.txt").write_text("two\n")
    git("commit", "-q", "-am", "two")
    git("tag", "v2.0")
    _assert_fresh_failure(pytester, "test_m.py::test_version_is_a_1x")


def test_startup_output_put_in_os_environ_is_an_input(pytester):
    """A plugin puts a tool's output into os.environ at start-up; the test reads the variable. The environment
    digests come from the environment as it was before start-up (env0), which does not hold the variable."""
    tool = _tool(_bin_dir(pytester, "bin") / "fenvixtool", "1.0")
    _write(pytester, {"conftest.py": f"""
        import os, subprocess

        def pytest_configure(config):
            os.environ["FENVIX_TOOL_VERSION"] = subprocess.check_output([{str(tool)!r}], text=True).strip()
        """, "test_m.py": """
        import os

        def test_tool_version_env():
            assert os.environ["FENVIX_TOOL_VERSION"] == "1.0"
        """})
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_tool_version_env")
    _tool(tool, "2.0")
    _assert_fresh_failure(pytester, "test_m.py::test_tool_version_env")


def test_startup_process_writing_a_file_under_pytest_cache_is_an_input(pytester):
    """A start-up process writes generated data where detpy skips reads (.pytest_cache, as a plugin using
    config.cache.makedir would); a session fixture reads it."""
    gen = _bin_dir(pytester, "bin") / "gen"
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text('#!/bin/sh\nmkdir -p "$1"\necho 1.0 > "$1/version.txt"\n')
    gen.chmod(0o755)
    _write(pytester, {"conftest.py": f"""
        import os, subprocess
        import pytest

        def pytest_configure(config):
            config.gen_dir = os.path.join(str(config.rootpath), ".pytest_cache", "d", "gen")
            subprocess.run([{str(gen)!r}, config.gen_dir], check=True)

        @pytest.fixture(scope="session")
        def generated(pytestconfig):
            with open(os.path.join(pytestconfig.gen_dir, "version.txt")) as f:
                return f.read().strip()
        """, "test_m.py": """
        def test_generated(generated):
            assert generated == "1.0"
        """})
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_generated")
    gen.write_text('#!/bin/sh\nmkdir -p "$1"\necho 2.0 > "$1/version.txt"\n')
    _assert_fresh_failure(pytester, "test_m.py::test_generated")


def test_finished_startup_process_that_left_a_daemon_is_not_ignored(pytester):
    """The start-up process exits at once but leaves a daemon (a forked child) running, connected to the test
    process by a descriptor passed with pass_fds (not one of the Popen's pipes). The test reads the daemon's answer.
    The daemon's program changes between runs."""
    daemon = _bin_dir(pytester, "bin") / "daemon.py"
    daemon.parent.mkdir(parents=True, exist_ok=True)
    src = textwrap.dedent("""
        import os, sys, time
        fd = int(sys.argv[1])
        if os.fork():
            sys.exit(0)  # the start-up process returns at once
        os.setsid()
        null = os.open(os.devnull, os.O_RDWR)
        for std in (0, 1, 2):
            os.dup2(null, std)
        time.sleep(0.3)  # still running when the tests start
        os.write(fd, b"{v}\\n")
        """)
    daemon.write_text(src.format(v="1.0"))
    _write(pytester, {"conftest.py": f"""
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
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_daemon_answer")
    daemon.write_text(src.format(v="2.0"))
    _assert_fresh_failure(pytester, "test_m.py::test_daemon_answer")


def test_variable_read_by_the_hook_that_also_copies_the_environment_for_a_child_is_an_input(pytester, monkeypatch):
    """fc5b70b drops EVERY start-up environment read of the frame that copies the environment into a child's env=,
    not only the copy: a variable the hook reads for itself is lost as an input of the tests."""
    _write(pytester, {"conftest.py": """
        import os, subprocess, sys

        def pytest_configure(config):
            config.mode = os.environ.get("FENVIX_APP_MODE", "dev")
            env = dict(os.environ, LC_ALL="C")
            subprocess.run([sys.executable, "-c", "pass"], env=env, check=True)
        """, "test_m.py": """
        def test_mode(pytestconfig):
            assert pytestconfig.mode == "dev"
        """})
    monkeypatch.delenv("FENVIX_APP_MODE", raising=False)
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_mode")
    monkeypatch.setenv("FENVIX_APP_MODE", "prod")
    _assert_fresh_failure(pytester, "test_m.py::test_mode")


def test_environment_copy_kept_and_handed_to_a_child_is_an_input(pytester, monkeypatch):
    """The copy handed to the child is also kept for the tests (REPORT-4 names this case as a limit)."""
    _write(pytester, {"conftest.py": """
        import os, subprocess, sys

        def pytest_configure(config):
            env = dict(os.environ)
            config.env = env
            subprocess.run([sys.executable, "-c", "pass"], env=env, check=True)
        """, "test_m.py": """
        def test_flag(pytestconfig):
            assert pytestconfig.env.get("FENVIX_FLAG", "0") == "0"
        """})
    monkeypatch.delenv("FENVIX_FLAG", raising=False)
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_flag")
    monkeypatch.setenv("FENVIX_FLAG", "1")
    _assert_fresh_failure(pytester, "test_m.py::test_flag")


# --- checks that hold on the delivered commit (kept as guards; not defects) ---------------------------------------

def test_startup_process_writing_a_file_in_the_root_is_checked(pytester):
    """A start-up process regenerates a file inside the root that a test reads: the file's digest is checked
    after start-up, so a changed output is a miss (holds)."""
    gen = _bin_dir(pytester, "bin") / "gen"
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text('#!/bin/sh\necho 1.0 > "$1"\n')
    gen.chmod(0o755)
    _write(pytester, {"conftest.py": f"""
        import os, subprocess

        def pytest_configure(config):
            subprocess.run([{str(gen)!r}, os.path.join(str(config.rootpath), "version.txt")], check=True)
        """, "test_m.py": """
        def test_generated():
            with open("version.txt") as f:
                assert f.read().strip() == "1.0"
        """})
    _assert_recorded_then_not_reused(pytester, "test_m.py::test_generated")
    gen.write_text('#!/bin/sh\necho 2.0 > "$1"\n')
    _assert_fresh_failure(pytester, "test_m.py::test_generated")


def test_finished_startup_process_that_left_a_socket_daemon_keeps_its_client_uncached(pytester):
    """A daemon left by a finished start-up process, reached over a Unix socket from Python: the connect flags the
    test (holds)."""
    import pathlib
    import tempfile

    sock = pathlib.Path(tempfile.mkdtemp(prefix="r8d")) / "d.sock"  # AF_UNIX paths are limited to 108 bytes
    daemon = _bin_dir(pytester, "bin") / "sdaemon.py"
    daemon.parent.mkdir(parents=True, exist_ok=True)
    daemon.write_text(textwrap.dedent(f"""
        import os, socket, sys
        if os.fork():
            sys.exit(0)
        os.setsid()
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        s = socket.socket(socket.AF_UNIX)
        s.bind({str(sock)!r})
        s.listen(1)
        s.settimeout(60)
        c, _a = s.accept()  # one client per run, then exit
        c.sendall(b"1.0\\n")
        c.close()
        """))
    _write(pytester, {"conftest.py": f"""
        import os, subprocess, sys, time

        def pytest_configure(config):
            if os.path.exists({str(sock)!r}):
                os.unlink({str(sock)!r})
            subprocess.run([sys.executable, {str(daemon)!r}], check=True, stdout=subprocess.DEVNULL)
            for _ in range(1000):
                if os.path.exists({str(sock)!r}):
                    break
                time.sleep(0.01)
        """, "test_m.py": f"""
        import socket

        def test_ask():
            s = socket.socket(socket.AF_UNIX)
            s.connect({str(sock)!r})
            assert s.recv(10).strip() == b"1.0"
        """})
    for n in (1, 2):
        r, c = _run(pytester, n)
        r.assert_outcomes(passed=1)
        assert c["reused_ids"] == []
        assert "test_m.py::test_ask" in c["not_cached_ids"]
