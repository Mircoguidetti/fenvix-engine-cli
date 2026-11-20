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


def test_g0159_cache_epoch_is_the_virtual_day_and_the_real_clock_check_reports(pytester):
    """Audit G-0159: under --det-cache (``--det-epoch=auto``) the epoch is today 00:00 UTC; the nightly
    ``--det-cache-real-clock`` check runs every test on the real clock, records nothing, and reports (and fails on)
    a test that passed on the virtual day and fails on the real clock."""
    import datetime

    _probe(pytester, """
        import datetime
        def test_today_is_the_virtual_day():
            now = datetime.datetime.now(datetime.timezone.utc)
            assert (now.hour, now.minute) == (0, 0)
            assert now.date() == datetime.datetime.fromtimestamp(OUTSIDE, datetime.timezone.utc).date()
        def test_plain():
            pass
        """.replace("OUTSIDE", str(int(__import__("time").time()))))
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, "-rA", "tests")
        assert p.returncode == 0, p.stdout
    assert "tests/test_p.py::test_today_is_the_virtual_day" in reused(c)
    now = datetime.datetime.now(datetime.timezone.utc)
    p, c, _ = run(pytester, "nightly", "-rA", "--det-cache-real-clock", "tests")
    assert reused(c) == set() and c.get("recorded") == 0, c
    if (now.hour, now.minute) != (0, 0):
        assert "REAL-CLOCK FINDINGS" in p.stdout and "test_today_is_the_virtual_day" in p.stdout, p.stdout
        assert p.returncode != 0


def test_g0510_numpy_random_imported_by_detpys_reseed_is_not_the_tests_entropy(pytester):
    """Audit G-0510: numpy loads numpy.random lazily and draws OS entropy at that import (its global RandomState);
    when detpy's own per-test reseed is what imports it, the draw reaches no test (it is reseeded at once). A stand-in
    package with the same shape (module __getattr__, os.urandom at import, seed()), so the gate needs no numpy."""
    write(pytester, **{
        "numpy/__init__.py": """
            import importlib
            def __getattr__(name):
                if name == "random":
                    return importlib.import_module("numpy.random")
                raise AttributeError(name)
            def add(a, b):
                return a + b
            """,
        "numpy/random.py": """
            import os
            _STATE = [int.from_bytes(os.urandom(8), "little")]
            def seed(s):
                _STATE[0] = s
            """,
        "tests/conftest.py": "",
        "tests/test_np.py": """
            import numpy as np
            def test_a():
                assert np.add(1, 1) == 2
            def test_b():
                pass
            def test_c():
                pass
            """})
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, "-rA", "tests", env={"PYTHONPATH": str(pytester.path)})
        assert p.returncode == 0, p.stdout
    assert reused(c) == {"tests/test_np.py::test_a", "tests/test_np.py::test_b", "tests/test_np.py::test_c"}, (
        c.get("not_cached_ids"))


def test_g0510_entropy_read_by_the_test_itself_still_refuses(pytester):
    _probe(pytester, """
        import os
        def test_entropy():
            assert len(os.urandom(4)) == 4
        """)
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, "-rA", "tests")
    assert reused(c) == set() and "os entropy" in c["not_cached_ids"]["tests/test_p.py::test_entropy"]


def test_g2211_isolate_sets_up_unittest_classes_without_the_teardown_deprecation(pytester):
    """Audit G-2211: --det-isolate's parent set up a unittest class fixture through a request of an inactive node
    (PytestRemovedIn10Warning); it must not warn."""
    _probe(pytester, """
        import unittest
        class T(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                cls.x = 1
            def test_a(self):
                self.assertEqual(self.x, 1)
        """)
    p, _, _ = run(pytester, "iso", "-rA", "-W", "error::pytest.PytestRemovedIn10Warning", "--det-isolate", "tests",
                  cache=False)
    assert p.returncode == 0 and "PytestRemovedIn10Warning" not in p.stdout, p.stdout


def test_g2197_a_configuration_miss_names_what_changed_and_g2196_receipts_are_kept_per_run(pytester):
    """Audit G-2197/G-1509: a receipt whose reason is the configuration names the parts that changed (here a
    variable of the process environment, TZ). Audit G-2196: every run's receipts are kept under DIR/receipts/."""
    _probe(pytester, """
        def test_pure():
            pass
        """)
    run(pytester, "r1", "tests")
    p, c, _ = run(pytester, "r2", "tests", env={"TZ": "Asia/Tokyo"})
    rows = [json.loads(x) for x in (pytester.path / ".c" / "receipts.jsonl").read_text().splitlines() if x.strip()]
    why = next(r["why"] for r in rows if r["nodeid"] == "tests/test_p.py::test_pure")
    assert why.startswith("config") and "environment.TZ" in why, why
    assert len(list((pytester.path / ".c" / "receipts").glob("*.jsonl"))) == 2


def test_g1510_cache_command_stats_explain_gc_clear(pytester):
    """Audit G-1510/G-1509: ``detpy cache`` shows, explains, bounds and clears a cache directory."""
    _probe(pytester, """
        def test_pure():
            pass
        def test_other():
            pass
        """)
    run(pytester, "r1", "tests")
    run(pytester, "r2", "tests")
    d = str(pytester.path / ".c")

    def cache(*a):
        p = subprocess.run([sys.executable, "-m", "detpy", "cache", *a], capture_output=True, text=True,
                           cwd=pytester.path)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)

    st = cache("stats", d)
    assert st["entries"] == 2 and st["latest_run"]["reused"] == 2 and st["history_runs"] == 2, st
    ex = cache("explain", d, "tests/test_p.py::test_pure")
    assert ex["entry"]["outcome"] == "passed" and ex["latest"]["reused"] is True and len(ex["history"]) == 2, ex
    assert "tests/conftest.py" in ex["entry"]["project_files"], ex
    g = cache("gc", d, "--max-age", "0.000001")
    assert g["dropped"] == 2, g
    assert cache("stats", d)["entries"] == 0
    assert cache("clear", d)["removed"] is True and not os.path.exists(d)


# -- pytest-xdist modes (audit G-1548, G-1552, G-2215, G-1553, G-1551, G-0708) ---------------------------------------
def test_g1548_dist_each_with_the_cache_is_refused_with_a_reason(pytester):
    pytest.importorskip("xdist")
    _probe(pytester, "def test_a():\n    pass\n")
    p, _, _ = run(pytester, "each", "-n", "2", "--dist", "each", "tests")
    assert p.returncode != 0 and "--dist=each is not supported" in (p.stdout + p.stderr), p.stdout + p.stderr


def test_g1552_remote_workers_are_refused_with_a_reason(pytester):
    pytest.importorskip("xdist")
    _probe(pytester, "def test_a():\n    pass\n")
    p, _, _ = run(pytester, "tx", "--dist", "load", "--tx", "socket=127.0.0.1:1", "tests", cache=False)
    assert p.returncode != 0 and "remote pytest-xdist worker" in (p.stdout + p.stderr), p.stdout + p.stderr


def test_g2215_g1553_header_says_what_happened_to_the_asked_dist(pytester):
    pytest.importorskip("xdist")
    _probe(pytester, "def test_a():\n    pass\n")
    p, _, _ = run(pytester, "no", "-n", "2", "--dist", "no", "tests", cache=False)
    assert "--dist=no asked; pytest-xdist runs load under -n" in p.stdout, p.stdout
    p, _, _ = run(pytester, "ws", "-n", "2", "--dist", "worksteal", "tests", cache=False)
    assert "work stealing is replaced by the fixed plan" in p.stdout, p.stdout


def test_g1551_tests_a_dead_worker_never_ran_fail_the_session(pytester):
    pytest.importorskip("xdist")
    write(pytester, **{"tests/conftest.py": "", "tests/test_a.py": """
        import os
        def test_crash():
            os._exit(17)
        def test_after_1():
            pass
        def test_after_2():
            pass
        """})
    p, _, _ = run(pytester, "dead", "-n", "1", "--max-worker-restart=0", "tests", cache=False)
    assert p.returncode != 0 and "NOT RUN: " in p.stdout and "test_after_2" in p.stdout, p.stdout


def test_g0708_work_stealing_callback_keeps_the_plan():
    from detpy.xdist import DetScheduling

    assert DetScheduling.remove_pending_tests_from_node(object.__new__(DetScheduling), None, [1]) is None


def test_g1539_runner_shells_refuse_pytest_only_options(tmp_path):
    """Audit G-1539: ``python -m detpy unittest --det --det-isolate`` ran no test at all; it is refused with why."""
    (tmp_path / "test_u.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n    def test_a(self):\n"
                                        "        pass\n")
    p = subprocess.run([sys.executable, "-m", "detpy", "unittest", "--det", "--det-isolate", "test_u"], cwd=tmp_path,
                       capture_output=True, text=True)
    assert p.returncode != 0 and "--det-isolate is a pytest option" in p.stderr, (p.stdout, p.stderr)


def test_g1544_missing_strace_is_said(pytester, tmp_path):
    """Audit G-1544: without strace, the summary says that processes started outside a test are not followed."""
    _probe(pytester, "def test_a():\n    pass\n")
    p, _, _ = run(pytester, "nostrace", "tests", env={"PATH": str(tmp_path)})
    assert "install strace" in p.stdout, p.stdout
