"""Rows F-05, PY-05, PY-08 (session 2026-11-20-py-cache): process-level state is part of every key unless it is on the
written allowlist (``_proof.ENV_ALLOWLIST``), code loaded from outside the project and every installed RECORD is an
input, a test that starts a process or calls C through ctypes runs and is never reused, and -n / --det-isolate never
change an outcome silently (a difference with the serial result is a PLACEMENT FINDING and fails the session).

Each scenario: record (two sessions), change one thing, then the truth (a run without the cache) and a cache run; the
cache run must not reuse the test and must give the truth's outcome."""

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

needs_cache = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
pytestmark = needs_cache


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS",
              "DETPY_CACHE_SHARED"):
        monkeypatch.delenv(k, raising=False)


def write(pytester, **files):
    for name, text in files.items():
        p = pytester.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def run(pytester, label, *args, prefix=(), cache=True, env=None):
    """pytest in a subprocess (optionally behind ``prefix``, e.g. taskset); returns (result, cache report)."""
    out = pytester.path / f"out-{label}.json"
    det = ["--det", "-p", "no:cacheprovider", "-p", "no:randomly", "-p", "no:benchmark"]
    if cache:
        det += [f"--det-cache={pytester.path / '.c'}", f"--det-outcomes={out}"]
    cmd = [*prefix, sys.executable, "-m", "pytest", *det, *args]
    e = dict(os.environ, **(env or {}))
    p = subprocess.run(cmd, cwd=pytester.path, env=e, capture_output=True, text=True, timeout=600)
    data = json.loads(out.read_text()) if cache and out.exists() else {}
    return p, data.get("cache", {}), (data.get("outcomes") or data.get("tests") or {})


def outcome_of(p, nid):
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")) and nid in line:
            return line.split()[0].lower()
    return None


def reused(c):
    return set(c.get("reused_ids", ()))


def recorded_then_changed(pytester, nid, change_prefix=(), change_env=None, before=None, args=("-rA", "tests")):
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, *args)
        assert p.returncode == 0, p.stdout + p.stderr
    p, c, _ = run(pytester, "r3", *args)
    assert nid in reused(c), ("not reused while nothing changed", p.stdout)
    if before:
        before()
    truth, _, _ = run(pytester, "truth", *args, prefix=change_prefix, cache=False, env=change_env)
    p, c, _ = run(pytester, "after", *args, prefix=change_prefix, env=change_env)
    assert nid not in reused(c), ("WRONG REUSE", p.stdout)
    assert outcome_of(p, nid) == outcome_of(truth, nid), (p.stdout, truth.stdout)
    return truth, p


# -- process-level state (audit G-0160..G-0163; F-05 "flip the default") ------------------------------------------
def _probe(pytester, body):
    write(pytester, **{"tests/test_p.py": body, "tests/conftest.py": ""})


@pytest.mark.skipif(not hasattr(os, "sched_getaffinity") or len(os.sched_getaffinity(0)) < 2 or not shutil.which(
    "taskset"), reason="needs 2+ CPUs and taskset")
def test_g0160_usable_cpus_are_an_input(pytester):
    n = len(os.sched_getaffinity(0))
    _probe(pytester, f"""
        import os
        def test_cpus():
            assert len(os.sched_getaffinity(0)) == {n}
        """)
    recorded_then_changed(pytester, "tests/test_p.py::test_cpus", change_prefix=("taskset", "-c", "0"))


def test_g0161_umask_is_an_input(pytester):
    _probe(pytester, """
        import os, tempfile
        def test_mode():
            fd, p = tempfile.mkstemp()
            os.close(fd)
            os.chmod(p, 0o666 & ~_umask())
            try:
                assert os.stat(p).st_mode & 0o777 == 0o644
            finally:
                os.remove(p)
        def _umask():
            u = os.umask(0); os.umask(u); return u
        """)
    old = os.umask(0o022)
    try:
        recorded_then_changed(pytester, "tests/test_p.py::test_mode", change_prefix=("sh", "-c", 'umask 077; exec "$@"', "sh"))
    finally:
        os.umask(old)


def test_g0162_resource_limits_are_an_input(pytester):
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft <= 512:
        pytest.skip("RLIMIT_NOFILE already low")
    _probe(pytester, f"""
        import resource
        def test_limit():
            assert resource.getrlimit(resource.RLIMIT_NOFILE)[0] == {soft}
        """)
    recorded_then_changed(pytester, "tests/test_p.py::test_limit", change_prefix=("sh", "-c", 'ulimit -n 512; exec "$@"', "sh"))


@pytest.mark.skipif(os.geteuid() != 0 or not shutil.which("unshare"), reason="needs root and unshare")
def test_g0163_host_name_is_an_input(pytester):
    import socket

    host = socket.gethostname()
    _probe(pytester, f"""
        import socket
        def test_host():
            assert socket.gethostname() == {host!r}
        """)
    recorded_then_changed(pytester, "tests/test_p.py::test_host",
                          change_prefix=("unshare", "--uts", "sh", "-c", 'hostname otherbox-py-cache; exec "$@"', "sh"))


def test_environment_variable_no_python_read_sees_is_an_input(pytester):
    """A variable the test never reads through os.environ (C reads it: here the time zone through time.localtime)."""
    _probe(pytester, """
        import time
        def test_c_reads_env():
            assert time.strftime("%Z", time.localtime(0)) in ("UTC", "GMT")
        """)
    recorded_then_changed(pytester, "tests/test_p.py::test_c_reads_env", change_env={"TZ": "Asia/Tokyo"},
                          before=None)


def test_new_unread_variable_invalidates_and_allowlisted_one_does_not(pytester):
    _probe(pytester, """
        def test_pure():
            assert 1 + 1 == 2
        """)
    nid = "tests/test_p.py::test_pure"
    for label in ("r1", "r2"):
        run(pytester, label, "tests")
    _, c, _ = run(pytester, "allow", "tests", env={"GITHUB_RUN_ID": "12345", "SHLVL": "7"})
    assert nid in reused(c), "an allowlisted variable invalidated the test"
    _, c, _ = run(pytester, "new", "tests", env={"PY_CACHE_SOME_FLAG": "1"})
    assert nid not in reused(c), "a new variable of the process environment did not invalidate the test"


def test_allowlist_has_a_reason_for_every_entry():
    from detpy import _proof

    assert _proof.ENV_ALLOWLIST and all(isinstance(v, str) and len(v) > 20 for v in _proof.ENV_ALLOWLIST.values())
    assert "PATH" not in _proof.ENV_ALLOWLIST and "LD_PRELOAD" not in _proof.ENV_ALLOWLIST


def test_g0164_module_from_pythonpath_outside_the_root_is_an_input(pytester, tmp_path_factory):
    ext = tmp_path_factory.mktemp("outside")
    (ext / "outmod_pycache.py").write_text("VALUE = 1\n")
    _probe(pytester, """
        import outmod_pycache
        def test_value():
            assert outmod_pycache.VALUE == 1
        """)
    env = {"PYTHONPATH": str(ext)}
    for label in ("r1", "r2"):
        p, _, _ = run(pytester, label, "-rA", "tests", env=env)
        assert p.returncode == 0, p.stdout
    _, c, _ = run(pytester, "r3", "-rA", "tests", env=env)
    assert "tests/test_p.py::test_value" in reused(c)
    (ext / "outmod_pycache.py").write_text("VALUE = 22\n")
    p, c, _ = run(pytester, "after", "-rA", "tests", env=env)
    assert "tests/test_p.py::test_value" not in reused(c), ("WRONG REUSE", p.stdout)
    assert p.returncode == 1


# -- PY-08: subprocesses and native code run and are never reused ---------------------------------------------------
def test_py08_a_test_that_starts_a_process_runs_every_time(pytester):
    _probe(pytester, """
        import subprocess, sys
        def test_pure():  # before the child: a refusal is carried into the later tests of the process
            pass
        def test_child():
            assert subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True, text=True).stdout == "1\\n"
        """)
    for label in ("r1", "r2", "r3"):
        p, c, _ = run(pytester, label, "-rA", "tests")
        assert p.returncode == 0, p.stdout
        assert "tests/test_p.py::test_child" not in reused(c)
    assert "tests/test_p.py::test_pure" in reused(c)


def test_py08_a_fixture_that_starts_a_process_refuses_its_tests(pytester):
    write(pytester, **{"tests/conftest.py": """
        import subprocess, sys, pytest
        @pytest.fixture
        def server():
            return subprocess.run([sys.executable, "-c", "print(7)"], capture_output=True, text=True).stdout
        """, "tests/test_p.py": """
        def test_uses(server):
            assert server == "7\\n"
        """})
    for label in ("r1", "r2", "r3"):
        p, c, _ = run(pytester, label, "-rA", "tests")
        assert p.returncode == 0, p.stdout
        assert "tests/test_p.py::test_uses" not in reused(c)


def test_py08_ctypes_libc_is_never_reused(pytester):
    _probe(pytester, """
        import ctypes
        def test_libc():
            assert ctypes.CDLL(None).abs(-3) == 3
        """)
    for label in ("r1", "r2", "r3"):
        p, c, _ = run(pytester, label, "-rA", "tests")
        assert p.returncode == 0, p.stdout
        assert "tests/test_p.py::test_libc" not in reused(c)


# -- PY-05 / G-0175 / G-0169: -n and --det-isolate never change an outcome silently ----------------------------------
STATE = {
    "tests/test_a.py": """
        import json
        def test_a_sets():
            json.py_cache_state = 1
        """,
    "tests/test_b.py": """
        import json, os
        def test_b_needs():
            with open(os.path.join(os.path.dirname(__file__), "b.txt")) as f:
                assert f.read().strip()
            assert getattr(json, "py_cache_state", 0) == 1
        """,
    "tests/b.txt": "1\n",
    "tests/conftest.py": "",
}


@pytest.mark.parametrize("mode", ["n2", "isolate"])
def test_placement_difference_is_a_finding(pytester, mode):
    pytest.importorskip("xdist")
    write(pytester, **STATE)
    for label in ("r1", "r2"):
        p, _, _ = run(pytester, label, "-rA", "tests")
        assert p.returncode == 0, p.stdout
    extra = ("-n", "2", "--dist", "loadfile") if mode == "n2" else ("--det-isolate",)
    # every test runs (verified against its entry): the store holds each one's serial outcome under unchanged inputs
    p, c, _ = run(pytester, "par", "-rA", "--det-cache-verify=1", *extra, "tests")
    got = outcome_of(p, "tests/test_b.py::test_b_needs")
    if got == "passed":
        return  # the same outcome as serial
    # a different outcome is never silent: the finding names the test and the session fails
    assert "PLACEMENT FINDINGS" in p.stdout and "tests/test_b.py::test_b_needs" in p.stdout, p.stdout
    assert p.returncode != 0


def test_g0174_serial_testrun_uid_is_derived_under_det(pytester):
    """Audit G-0174: with pytest-xdist installed, a serial --det session's ``testrun_uid`` fixture is the derived
    value (the same in two runs), not xdist's uuid4() draw."""
    pytest.importorskip("xdist")
    _probe(pytester, """
        def test_uid(testrun_uid):
            print("UID", testrun_uid)
        """)
    uids = []
    for label in ("u1", "u2"):
        p, _, _ = run(pytester, label, "-s", "tests", cache=False)
        uids.append(re.findall(r"UID ([0-9a-f]+)", p.stdout))
    assert uids[0] and uids[0] == uids[1], uids


def test_status_of_an_unlinked_temporary_file_is_not_a_refusal(pytester):
    """py-cache (moto walk): os.fstat of a descriptor whose file was unlinked (a temporary file) names no input; the
    test is recorded and reused. Its time fields stay real-clock reads (refused)."""
    _probe(pytester, """
        import os, tempfile
        def test_size():
            with tempfile.TemporaryFile() as f:
                f.write(b"abc"); f.flush()
                assert os.fstat(f.fileno()).st_size == 3
        def test_time():
            with tempfile.TemporaryFile() as f:
                assert os.fstat(f.fileno()).st_mtime > 0
        """)
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, "-rA", "tests")
        assert p.returncode == 0, p.stdout
    assert "tests/test_p.py::test_size" in reused(c), c.get("not_cached_ids")
    assert "tests/test_p.py::test_time" not in reused(c)
