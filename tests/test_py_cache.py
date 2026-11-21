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
    # --det pins TZ (UTC) since the release-1 time-zone control; with "keep" the machine's TZ is an input again
    recorded_then_changed(pytester, "tests/test_p.py::test_c_reads_env", change_env={"TZ": "Asia/Tokyo"},
                          before=None, args=("-rA", "--det-tz=keep", "tests"))


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


def test_shell_last_argument_read_inside_an_environment_copy_is_not_an_input(pytester):
    """`_` (the shell's last argument) is out of the whole-environment digest; a copy of os.environ reads it by name
    too, which made every library that copies the environment churn with the way pytest was started (moto: 176 of
    292 tests). Read by name alone, it stays an input."""
    _probe(pytester, """
        import os
        def test_reads_it():
            assert os.environ.get("_", "") != "x"
        def test_copies():
            assert len(os.environ.copy()) > 0
        """)
    for label in ("r1", "r2"):
        run(pytester, label, "tests", env={"_": "/usr/bin/first"})
    _, c, _ = run(pytester, "other", "tests", env={"_": "/usr/bin/second"})
    assert "tests/test_p.py::test_copies" in reused(c), c.get("miss_reasons")
    assert "tests/test_p.py::test_reads_it" not in reused(c)
    _, c, _ = run(pytester, "flag", "tests", env={"_": "/usr/bin/second", "PY_CACHE_SOME_FLAG": "1"})
    assert "tests/test_p.py::test_copies" not in reused(c), "a copy of the environment no longer sees other variables"


def test_the_virtual_clocks_own_probe_of_threads_is_not_the_tests_read(pytester):
    """detpy's clock lists /proc/self/task on a sleep (no other thread alive) to see whether a child process may need
    real time; that probe was recorded as the test reading its process's state, refusing every test that slept
    (moto: 128 of 292 with the tests after them)."""
    _probe(pytester, """
        import threading, time
        def test_sleeps():
            t = threading.Thread(target=lambda: None)
            t.start()
            t.join()
            time.sleep(0.05)
        """)
    nid = "tests/test_p.py::test_sleeps"
    run(pytester, "r1", "tests")
    _, c, _ = run(pytester, "r2", "tests")
    assert nid in reused(c), (c.get("not_cached_detail"), c.get("miss_reasons"))


def test_allowlist_has_a_reason_for_every_entry():
    from detpy import _proof

    assert _proof.ENV_ALLOWLIST and all(isinstance(v, str) and len(v) > 20 for v in _proof.ENV_ALLOWLIST.values())
    assert "PATH" not in _proof.ENV_ALLOWLIST and "LD_PRELOAD" not in _proof.ENV_ALLOWLIST


@pytest.mark.parametrize("mode", ["default", "default-n2", "fenvix-python"])
def test_g0164_module_outside_the_root_in_a_files_child_is_an_input(pytester, tmp_path_factory, mode):
    """Exam F-05.wrong-reuse.pythonpath (run 44851972153): under the per-file default (and `fenvix python`, which runs
    the xdist controller) a module from PYTHONPATH outside the root, imported at collection, was not an input of the
    children's results; changing it reused the test as passed."""
    if mode != "default":
        pytest.importorskip("xdist")
    ext = tmp_path_factory.mktemp("outside")
    _probe(pytester, """
        import exam_outside
        def test_outside():
            assert exam_outside.VALUE == 1
        """)
    env = {"PYTHONPATH": str(ext), "DETPY_CACHE_IN_PROCESS": "0"}
    args = ("-n", "2", "tests") if mode == "default-n2" else ("tests",)
    prefix = ()
    if mode == "fenvix-python":
        fx = shutil.which("fenvix", path=os.path.dirname(sys.executable))
        if fx is None:
            pytest.skip("no fenvix command next to this interpreter")
    for label, value in (("r1", 1), ("after", 22)):
        (ext / "exam_outside.py").write_text(f"VALUE = {value}\n")
        if mode == "fenvix-python":
            out = pytester.path / f"out-{label}.json"
            p = subprocess.run([fx, "python", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
                                f"--det-cache={pytester.path / '.c'}", f"--det-outcomes={out}", "-rA", "tests"],
                               cwd=pytester.path, env=dict(os.environ, **env), capture_output=True, text=True,
                               timeout=600)
            c = json.loads(out.read_text()).get("cache", {}) if out.exists() else {}
        else:
            p, c, _ = run(pytester, label, "-rA", *args, prefix=prefix, env=env)
        if label == "r1":
            assert p.returncode == 0, p.stdout + p.stderr
    assert "tests/test_p.py::test_outside" not in reused(c), ("WRONG REUSE", p.stdout)
    assert p.returncode == 1, p.stdout


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


@pytest.mark.parametrize("mode", ["n2", "isolate", "file", "default", "default-n2"])
def test_placement_difference_is_a_finding(pytester, mode):
    """The in-process session records (the user's plain run, --det-cache-in-process); then -n, one child per test,
    one child per file (explicit, and the default under the cache, serial and -n): a test whose outcome differs from
    the in-process one is a PLACEMENT FINDING and the session fails (coordinator condition 2: never silent)."""
    pytest.importorskip("xdist")
    write(pytester, **STATE)
    for label in ("r1", "r2"):
        p, _, _ = run(pytester, label, "-rA", "tests")
        assert p.returncode == 0, p.stdout
    extra = {"n2": ("-n", "2", "--dist", "loadfile"), "isolate": ("--det-isolate",),
             "file": ("--det-isolate", "--det-isolate-scope=file"), "default": (),
             "default-n2": ("-n", "2")}[mode]
    env = {"DETPY_CACHE_IN_PROCESS": "0"} if mode.startswith("default") else None
    # every test runs (verified against its entry): the store holds each one's serial outcome under unchanged inputs
    p, c, _ = run(pytester, "par", "-rA", "--det-cache-verify=1", *extra, "tests", env=env)
    got = outcome_of(p, "tests/test_b.py::test_b_needs")
    if got == "passed":
        return  # the same outcome as serial
    # a different outcome is never silent: the finding names the test and the session fails
    assert "PLACEMENT FINDINGS" in p.stdout and "tests/test_b.py::test_b_needs" in p.stdout, p.stdout
    assert p.returncode != 0
    # and it is never reused in this mode while the in-process session says otherwise: the next run runs it again
    # and reports the finding again
    p, c, _ = run(pytester, "par2", "-rA", *extra, "tests", env=env)
    assert "tests/test_b.py::test_b_needs" not in reused(c), p.stdout
    assert "PLACEMENT FINDINGS" in p.stdout and p.returncode != 0, p.stdout


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
    run(pytester, "r1", "--det-tz=keep", "tests")  # --det pins TZ unless "keep": then TZ is part of the config
    p, c, _ = run(pytester, "r2", "--det-tz=keep", "tests", env={"TZ": "Asia/Tokyo"})
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


def test_g2214_a_test_that_crashes_its_worker_is_a_record_of_the_merged_trace(pytester):
    """Audit G-2214: the crashed test is in the merged trace (outcome "crashed"), so verify compares it."""
    pytest.importorskip("xdist")
    write(pytester, **{"tests/conftest.py": "", "tests/test_c.py": """
        import os
        def test_crash():
            os._exit(17)
        def test_ok():
            pass
        """})
    for i in (1, 2):
        run(pytester, f"c{i}", "-n", "2", f"--det-trace={pytester.path / f't{i}.jsonl'}", "tests", cache=False)
    recs = [json.loads(x) for x in (pytester.path / "t1.jsonl").read_text().splitlines() if x.strip()]
    crash = [r for r in recs if r.get("type") == "test" and r["nodeid"] == "tests/test_c.py::test_crash"]
    assert crash and crash[0]["outcome"] == "crashed", recs
    p = subprocess.run([sys.executable, "-m", "detpy", "verify", "t1.jsonl", "t2.jsonl"], cwd=pytester.path,
                       capture_output=True, text=True)
    assert "covered by Level 0: 2" in p.stdout, p.stdout


def test_g1550_worker_id_readers_keep_their_plan_and_are_reused(pytester):
    """Audit G-1550 (not reproducible on this engine): under --det-cache -n the plan stays the plan that recorded the
    tests (sticky), so tests that read the worker identity are reused with the rest."""
    pytest.importorskip("xdist")
    files = {"tests/conftest.py": ""}
    for f in "abc":
        body = ["import os"] + [f"def test_{f}{i}():\n    pass" for i in range(5)]
        if f == "b":
            body.append("def test_wid_env():\n    assert os.environ.get('PYTEST_XDIST_WORKER')")
        if f == "c":
            body.append("def test_wid_fixture(worker_id):\n    assert worker_id.startswith('gw')")
        files[f"tests/test_{f}.py"] = "\n".join(body) + "\n"
    write(pytester, **files)
    for label in ("r1", "r2", "r3"):
        p, c, _ = run(pytester, label, "-n", "2", "tests")
        assert p.returncode == 0, p.stdout
    assert len(reused(c)) == 17, c.get("miss_ids")


def test_g1549_a_failure_under_n_prints_its_worker_replay(pytester):
    """Audit G-1549/G-1557: the plan depends on the worker count; a failure under -n names the command that replays
    its worker's list from this run's plan, and that replay fails the same way."""
    pytest.importorskip("xdist")
    write(pytester, **STATE)
    p, _, _ = run(pytester, "par", "-n", "2", "--dist", "loadfile", "-rA", "tests", cache=False)
    line = next((x for x in p.stdout.splitlines() if x.startswith("replay tests/test_b.py::test_b_needs")), None)
    if line is None:
        assert "tests/test_b.py::test_b_needs" not in p.stdout.split("short test summary")[-1] or "PASSED" in p.stdout
        return  # the plan put both files on one worker: nothing failed
    args = line.split(": pytest ", 1)[1].split(" (")[0].split()
    r, _, _ = run(pytester, "replay", *args, "-rA", "tests", cache=False)
    assert outcome_of(r, "tests/test_b.py::test_b_needs") == "failed", r.stdout


def test_stdlib_cache_validators_are_not_time_inputs(pytester):
    """py-cache (moto walk): importlib.metadata stats every sys.path directory for its st_mtime to know whether to
    list it again; that time is not the test's input (the listing is, when it is read). A new file in the project root
    (its mtime moves) does not invalidate a test that looks up a distribution."""
    _probe(pytester, """
        import importlib.metadata, sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        def test_version():
            assert importlib.metadata.version("pytest")
        """)
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, "-rA", "tests")
        assert p.returncode == 0, p.stdout
    (pytester.path / "new-file.txt").write_text("x")
    p, c, _ = run(pytester, "r3", "-rA", "tests")
    assert "tests/test_p.py::test_version" in reused(c), c.get("miss_ids")


# -- --det-isolate-scope=file: one child per test file (py-cache, coordinator 2026-11-20 14:46) -------------------
_FILE_SCOPE = ("--det-isolate", "--det-isolate-scope=file", "-rA", "tests")


def _file_scope_project(pytester, a2_body="assert state.L == [1]"):
    write(pytester, **{
        "pkg/__init__.py": "",
        "pkg/state.py": "L = []\n",
        "tests/conftest.py": "",
        "tests/test_a.py": f"""
            from pkg import state

            def test_a1():
                state.L.append(1)

            def test_a2():
                {a2_body}
            """,
        "tests/test_b.py": """
            from pkg import state

            def test_b1():
                assert state.L == []
            """,
    })


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork per file: Linux")
@pytest.mark.parametrize("par", [(), ("-n", "2")], ids=["serial", "n2"])
def test_file_scope_tests_of_a_file_share_their_child_and_no_other_file_sees_it(pytester, par):
    if par and not shutil.which("true"):
        pytest.skip("needs a shell")
    pytest.importorskip("xdist") if par else None
    _file_scope_project(pytester)
    p, c, _ = run(pytester, "r1", *_FILE_SCOPE, *par)
    assert p.returncode == 0, p.stdout + p.stderr
    p, c, _ = run(pytester, "r2", *_FILE_SCOPE, *par)
    assert p.returncode == 0, p.stdout + p.stderr
    assert reused(c) == {"tests/test_a.py::test_a1", "tests/test_a.py::test_a2", "tests/test_b.py::test_b1"}, \
        (c.get("miss_reasons"), c.get("not_cached_detail"), p.stdout)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork per file: Linux")
def test_file_scope_a_test_that_runs_runs_after_the_earlier_tests_of_its_file(pytester):
    """test_a2 changes and runs; it consumed test_a1's state when recorded (the file's child): test_a1 runs before it
    again, not reused (E7 within the file), so test_a2 sees what a fresh run gives it."""
    _file_scope_project(pytester)
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, *_FILE_SCOPE)
        assert p.returncode == 0, p.stdout + p.stderr
    _file_scope_project(pytester, a2_body="assert state.L == [1], 'changed'")
    truth, _, _ = run(pytester, "truth", *_FILE_SCOPE, cache=False)
    p, c, _ = run(pytester, "after", *_FILE_SCOPE)
    assert "tests/test_a.py::test_a1" not in reused(c), p.stdout
    assert "tests/test_b.py::test_b1" in reused(c), (c.get("miss_reasons"), p.stdout)
    assert outcome_of(p, "tests/test_a.py::test_a2") == outcome_of(truth, "tests/test_a.py::test_a2") == "passed"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork per file: Linux")
def test_file_scope_a_test_deselected_when_recorded_is_not_a_wrong_reuse_when_it_runs(pytester):
    """Recorded with -k deselecting test_new (before test_y in the file); then a run that selects it: in a fresh run
    of the file test_new runs before test_y and fills the list. test_y's entry does not hold test_new (it did not run):
    the file's earlier tests are part of the check (file-prefix.json), so test_y is not reused."""
    write(pytester, **{"pkg/__init__.py": "", "pkg/state.py": "L = []\n", "tests/conftest.py": "",
                       "tests/test_a.py": """
        from pkg import state

        def test_x():
            pass

        def test_new():
            state.L.append(1)

        def test_y():
            assert state.L == []
        """})
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, *_FILE_SCOPE, "-k", "not test_new")
        assert p.returncode == 0, p.stdout + p.stderr
    assert "tests/test_a.py::test_y" in reused(c)
    truth, _, _ = run(pytester, "truth", *_FILE_SCOPE, cache=False)
    p, c, _ = run(pytester, "after", *_FILE_SCOPE)
    assert "tests/test_a.py::test_y" not in reused(c), ("WRONG REUSE", p.stdout)
    assert outcome_of(p, "tests/test_a.py::test_y") == outcome_of(truth, "tests/test_a.py::test_y") == "failed"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork per file: Linux")
@pytest.mark.parametrize("par", [(), ("-n", "2")], ids=["serial", "n2"])
def test_file_scope_a_test_added_before_a_reused_one_in_its_file_is_not_a_wrong_reuse(pytester, par):
    """test_y read an empty list after test_x; a new test_new before it in the file appends to the list: a fresh run
    of the file fails test_y. Its entry does not hold test_new (it did not exist): the file's earlier tests are part
    of the check (file-prefix.json), so test_y is not reused."""
    if par:
        pytest.importorskip("xdist")
    body = """
        from pkg import state

        def test_x():
            pass
        {new}
        def test_y():
            assert state.L == []
        """
    write(pytester, **{"pkg/__init__.py": "", "pkg/state.py": "L = []\n", "tests/conftest.py": "",
                       "tests/test_a.py": body.format(new="")})
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, *_FILE_SCOPE, *par)
        assert p.returncode == 0, p.stdout + p.stderr
    assert "tests/test_a.py::test_y" in reused(c)
    write(pytester, **{"tests/test_a.py": body.format(new="\n        def test_new():\n            state.L.append(1)\n")})
    truth, _, _ = run(pytester, "truth", *_FILE_SCOPE, *par, cache=False)
    p, c, _ = run(pytester, "after", *_FILE_SCOPE, *par)
    assert "tests/test_a.py::test_y" not in reused(c), ("WRONG REUSE", p.stdout)
    assert outcome_of(p, "tests/test_a.py::test_y") == outcome_of(truth, "tests/test_a.py::test_y") == "failed"


@pytest.mark.parametrize("par", [(), ("-n", "2")], ids=["serial", "n2"])
def test_a_test_that_did_not_run_when_a_result_was_recorded_is_not_a_wrong_reuse_when_it_runs(pytester, par):
    """In-process (no isolation): recorded with -k deselecting test_new, which runs before test_y and fills the list;
    then a run that selects it. test_y's entry does not hold test_new (it did not run, so the carried set cannot hold
    it): the tests before it in its session (prefix-session.json; under -n the planned predecessors, preds_check) are
    part of the check, so test_y is not reused (it was, as passed, while a fresh run fails it)."""
    if par:
        pytest.importorskip("xdist")
    write(pytester, **{"pkg/__init__.py": "", "pkg/state.py": "L = []\n", "tests/conftest.py": "",
                       "tests/test_a.py": """
        from pkg import state

        def test_x():
            pass

        def test_new():
            state.L.append(1)

        def test_y():
            assert state.L == []
        """})
    for label in ("r1", "r2"):
        run(pytester, label, "-rA", "tests", *par, "-k", "not test_new")
    truth, _, _ = run(pytester, "truth", "-rA", "tests", *par, cache=False)
    p, c, _ = run(pytester, "after", "-rA", "tests", *par)
    nid = "tests/test_a.py::test_y"
    assert nid not in reused(c) or outcome_of(truth, nid) == "passed", ("WRONG REUSE", p.stdout)
    assert outcome_of(p, nid) == outcome_of(truth, nid)


def test_a_directory_on_sys_path_twice_is_not_another_runtime_under_n(pytester):
    """esphome: tests/unit_tests/conftest.py puts the project root on sys.path; workers import it at collection (the
    controller does not collect), and pytest-xdist puts the root on a worker's path once more than the controller's.
    A second copy of a directory resolves no import differently: every result a worker recorded missed on the runtime
    (0 of 14,446 reused on esphome, CI run py-cache-2026-11-20f)."""
    pytest.importorskip("xdist")
    pytester.makeini("[pytest]\npythonpath = .\n")
    write(pytester, **{"tests/unit/conftest.py": """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        """, "tests/unit/test_u.py": """
        def test_u():
            assert True
        """})
    run(pytester, "r1", "-n", "2", "tests")
    _, c, _ = run(pytester, "r2", "-n", "2", "tests")
    assert "tests/unit/test_u.py::test_u" in reused(c), c.get("miss_reasons")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork per file: Linux")
def test_per_file_is_the_default_under_the_cache_and_in_process_is_a_choice(pytester, monkeypatch):
    """Coordinator decision 2026-11-20: --det-cache alone runs one child per test file (state left by file A never
    reaches file B); --det-cache-in-process keeps the session's process."""
    monkeypatch.delenv("DETPY_CACHE_IN_PROCESS", raising=False)
    write(pytester, **{"pkg/__init__.py": "", "pkg/state.py": "L = []\n", "tests/conftest.py": "",
                       "tests/test_a.py": """
        from pkg import state

        def test_a():
            state.L.append(1)
        """, "tests/test_b.py": """
        from pkg import state

        def test_b():
            assert state.L == []
        """})
    p, c, _ = run(pytester, "default", "-rA", "tests")
    assert outcome_of(p, "tests/test_b.py::test_b") == "passed", p.stdout  # file A's state does not reach file B
    assert "forked children" in p.stdout or "--det-isolate" in p.stdout
    p, c, _ = run(pytester, "inproc", "-rA", "tests", "--det-cache-in-process")
    assert outcome_of(p, "tests/test_b.py::test_b") == "failed", p.stdout  # one process: it does


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork per file: Linux")
def test_file_scope_a_subprocess_in_a_files_child_runs_and_is_never_reused(pytester):
    """esphome (tests/script/test_setup.py): following a process started in a file's child under strace hung (the
    detached tracer kept the test's pipe open); in a file's child it is not followed, and the test is never reused."""
    write(pytester, **{"tests/conftest.py": "", "tests/test_s.py": """
        import subprocess, sys

        def test_runs_python():
            out = subprocess.run([sys.executable, "-c", "print('hi')"], capture_output=True, text=True, timeout=60)
            assert out.stdout.strip() == "hi"
        """})
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, *_FILE_SCOPE)
        assert p.returncode == 0, p.stdout + p.stderr
    assert "tests/test_s.py::test_runs_python" not in reused(c)
    assert "not followed" in json.dumps(c.get("not_cached_detail")) or "process" in json.dumps(c.get("not_cached_detail"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork per file: Linux")
@pytest.mark.parametrize("par", [(), ("-n", "2", "--dist", "loadfile")], ids=["serial", "n2"])
def test_file_scope_a_file_another_files_test_writes_this_session_is_not_a_wrong_reuse(pytester, tmp_path_factory,
                                                                                      monkeypatch, par):
    """Review R-023b F2 (absent input) under the per-file default: after value.txt changes, test_a_flag (an earlier
    file) creates the flag test_b_no_flag checks is absent. The in-process session withdraws B as A writes; with one
    child per file A's writes are its child's: serial, a file is gated against the children's writes before it
    starts (its whole file runs); under -n the controller checks the workers' children's shards (it read only the
    workers' own shard). Both were wrong reuses (B reused as passed, a fresh run fails it)."""
    if par:
        pytest.importorskip("xdist")
    monkeypatch.delenv("DETPY_CACHE_IN_PROCESS", raising=False)
    d = tmp_path_factory.mktemp("outside")
    write(pytester, **{"tests/conftest.py": "", "tests/value.txt": "x\n", "tests/test_a_writer.py": """
        import os, pathlib
        def test_a_flag():
            p = pathlib.Path(os.environ["SHARED_DIR"]) / "flag"
            if (pathlib.Path(__file__).parent / "value.txt").read_text().strip() == "y":
                p.write_text("1")
            elif p.exists():
                p.unlink()
        """, "tests/test_b_reader.py": """
        import os
        def test_b_no_flag():
            assert not os.path.exists(os.path.join(os.environ["SHARED_DIR"], "flag"))
        """})
    env = {"SHARED_DIR": str(d)}
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, "-rA", *par, "tests", env=env)
        assert p.returncode == 0, p.stdout
    assert "tests/test_b_reader.py::test_b_no_flag" in reused(c)
    (pytester.path / "tests" / "value.txt").write_text("y\n")
    (d / "flag").unlink(missing_ok=True)
    p, c, _ = run(pytester, "after", "-rA", *par, "tests", env=env)
    assert "tests/test_b_reader.py::test_b_no_flag" not in reused(c), ("WRONG REUSE", p.stdout)
    assert outcome_of(p, "tests/test_b_reader.py::test_b_no_flag") == "failed", p.stdout


@pytest.mark.parametrize("n", ["serial", "n2"])
def test_carried_lines_of_test_files_children_stay_whole(pytester, n):
    """Walk run py-cache-2026-11-20g (esphome): test files' children appended to DIR/carried.jsonl at the same time
    and one line was cut by another; each line is now one write. Every line parses, one per recording child."""
    if n == "n2":
        pytest.importorskip("xdist")
    files = {"tests/conftest.py": ""}
    for i in range(12):
        files[f"tests/test_f{i}.py"] = "".join(f"def test_{j}():\n    assert {j} >= 0\n" for j in range(30))
    write(pytester, **files)
    args = ("-n", "2", "tests") if n == "n2" else ("tests",)
    p, c, _ = run(pytester, "r1", *args, env={"DETPY_CACHE_IN_PROCESS": "0"})
    assert p.returncode == 0, p.stdout + p.stderr
    lines = (pytester.path / ".c" / "carried.jsonl").read_text().splitlines()
    rows = [json.loads(x) for x in lines if x.strip()]  # a cut line fails here
    assert sum(r["tests"] for r in rows) == 12 * 30, rows


@pytest.mark.parametrize("mode", ["in-process", "default", "default-n2"])
def test_import_time_code_of_another_test_module_is_an_input(pytester, mode):
    """Exam F-05.probe.import-side-effect (run 44851972153): test_a's module patches json.dumps at import (collection,
    before every test of the process); test_b was reused as passed after that line was added, while a plain run fails
    it. A body-only edit of test_a keeps test_b reused (definitions are not import-time effects)."""
    if mode == "default-n2":
        pytest.importorskip("xdist")
    env = {"DETPY_CACHE_IN_PROCESS": "1" if mode == "in-process" else "0"}
    args = ("-n", "2", "tests") if mode == "default-n2" else ("tests",)
    b = "tests/test_b.py::test_dump"
    write(pytester, **{"tests/conftest.py": "", "tests/test_a.py": "def test_nothing():\n    pass\n",
                       "tests/test_b.py": "import json\n\ndef test_dump():\n    assert json.dumps([1, 2]) == '[1, 2]'\n"})
    for label in ("r1", "r2"):
        p, c, _ = run(pytester, label, "-rA", *args, env=env)
        assert p.returncode == 0, p.stdout + p.stderr
    assert b in reused(c), c.get("miss_reasons")
    write(pytester, **{"tests/test_a.py": "def test_nothing():\n    assert 1\n"})
    p, c, _ = run(pytester, "body", "-rA", *args, env=env)
    if mode != "in-process":  # in one process test_a's code is in test_b's carried set: it reruns there anyway
        assert b in reused(c), ("a body-only edit invalidated another module's test", c.get("miss_reasons"))
    write(pytester, **{"tests/test_a.py": "import json, functools\njson.dumps = functools.partial(json.dumps, "
                                          "separators=(',', ':'))\n\ndef test_nothing():\n    pass\n"})
    p, c, _ = run(pytester, "after", "-rA", *args, env=env)
    assert b not in reused(c), ("WRONG REUSE", p.stdout)
    assert outcome_of(p, b) == "failed", p.stdout


ODPAIR = """
STATE = {}

def test_a_setter():
    STATE["x"] = 1

def test_b_victim():
    assert STATE.get("x") == 1
"""


@pytest.mark.parametrize("args", [("-n", "2"), ("-n", "4"), ("--det-isolate",), ("--det-cache=.c", "-n", "2")],
                         ids=["n2", "n4", "isolate", "cache-n2"])
def test_order_dependent_pair_has_the_serial_verdict(pytester, args):
    """Exam PY-05.odpair and PY-05.probe.isolate (run 44851972153): test_b relies on test_a, earlier in its file. With
    no --dist asked, -n keeps a file's tests on one worker in order; --det-isolate forks one child per file (per test
    only with --det-isolate-scope=test): the verdict is the serial one."""
    if "-n" in args:
        pytest.importorskip("xdist")
    write(pytester, **{"tests/conftest.py": "", "tests/test_od.py": ODPAIR})
    p, _, _ = run(pytester, "plain", "-rA", "tests", cache=False)
    assert outcome_of(p, "tests/test_od.py::test_b_victim") == "passed", p.stdout
    p, _, _ = run(pytester, "mode", "-rA", *args, "tests", cache=False)
    assert outcome_of(p, "tests/test_od.py::test_b_victim") == "passed", p.stdout
    assert p.returncode == 0, p.stdout + p.stderr


RUNTEST_PROTOCOL_PLUGIN = """
import pytest

STATS = {}

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item):
    STATS[item.nodeid] = []
    yield

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    STATS[item.nodeid].append(call.when)  # KeyError when the wrapper above did not run (pytest-retry's pattern)
    yield
"""


@pytest.mark.parametrize("mode", [(), ("-n", "2"), ("--det-isolate", "--det-isolate-scope=test")],
                         ids=["file", "n2", "test-scope"])
def test_other_plugins_runtest_protocol_wrappers_run_in_the_childs(pytester, mode):
    """litellm (parallel-proof run g): pytest-retry creates a test's entry in its pytest_runtest_protocol wrapper and
    reads it in pytest_runtest_makereport; a per-file child ran runtestprotocol without the other plugins' protocol
    wrappers, so every test there errored with a KeyError (2,073 failed against 1 in the uncached run). The child
    runs the test inside those wrappers, as a serial run does."""
    if mode[:1] == ("-n",):
        pytest.importorskip("xdist")
    write(pytester, **{"tests/test_p.py": "def test_a():\n    pass\n\ndef test_b():\n    assert 1\n",
                       "tests/conftest.py": RUNTEST_PROTOCOL_PLUGIN})
    # the default per-file children (detpy's own suites run in-process: DETPY_CACHE_IN_PROCESS=1)
    p, _, outcomes = run(pytester, "w" + "-".join(mode), "-rA", *mode, "tests", env={"DETPY_CACHE_IN_PROCESS": "0"})
    assert mode[:1] == ("-n",) or "in forked children" in p.stdout, p.stdout[-3000:]  # (the workers print it under -n)
    assert p.returncode == 0 and "KeyError" not in p.stdout, p.stdout[-3000:]
    assert set(outcomes.values()) == {"passed"} and len(outcomes) == 2, outcomes


EARLIER_FILE_STATE = {
    "tests/helper.py": "STATE = {}\n",
    "tests/test_a_setup.py": "from helper import STATE\n\ndef test_sets_credentials():\n    STATE['creds'] = 'x'\n",
    # moto 96f50b1a test_s3_file_handles.py::TestS3FileHandleClosuresUsingMocks (parallel-proof run g/h): setUp builds
    # a client outside the mock and works only after an earlier test file of the same process left state behind
    "tests/test_b_client.py": (
        "import unittest\nfrom helper import STATE\n\n"
        "class UsingMocks(unittest.TestCase):\n"
        "    def setUp(self):\n        self.client = STATE['creds']  # KeyError when no earlier file set it\n\n"
        "    def test_use(self):\n        self.assertEqual(self.client, 'x')\n\n"
        "    def test_use_again(self):\n        self.assertEqual(self.client, 'x')\n"),
}


def test_a_failure_only_the_per_file_isolation_causes_is_reported_not_the_result(pytester):
    """Coordinator decision 2026-11-21 (b): a test that fails in its file's child and has no in-process result to
    compare with is replayed in one process after the earlier tests; when it passes there the run reports the pass
    (the user's normal run) and a PLACEMENT FINDING naming the earlier-file dependency, never the isolated failure."""
    write(pytester, **{**EARLIER_FILE_STATE, "tests/conftest.py": "import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n"})
    env = {"DETPY_CACHE_IN_PROCESS": "0"}
    plain = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "tests"],
                           cwd=pytester.path, capture_output=True, text=True, timeout=300)
    assert plain.returncode == 0, plain.stdout[-2000:]
    p, _, outcomes = run(pytester, "pf", "-rA", "tests", env=env)
    assert "in forked children" in p.stdout, p.stdout[-3000:]
    assert p.returncode == 0, p.stdout[-3000:]
    assert set(outcomes.values()) == {"passed"} and len(outcomes) == 3, outcomes
    assert "PLACEMENT FINDINGS: tests that fail only when their file runs in its own process" in p.stdout, p.stdout
    assert ("placement: tests/test_b_client.py::UsingMocks::test_use: failed when its file runs in its own process"
            in p.stdout), p.stdout
    assert "after the 1 earlier tests of this process (1 earlier file(s), tests/test_a_setup.py" in p.stdout, p.stdout
    # the file alone fails in one process too: its failure stands, no finding
    alone, _, out2 = run(pytester, "alone", "-rA", "tests/test_b_client.py", env=env)
    assert set(out2.values()) == {"failed"} and "PLACEMENT FINDINGS" not in alone.stdout, alone.stdout[-3000:]
    # serial without the isolation (in-process) gives the pass with no finding
    inproc, _, out3 = run(pytester, "inproc", "-rA", "tests", env={"DETPY_CACHE_IN_PROCESS": "1"})
    assert set(out3.values()) == {"passed"} and "PLACEMENT FINDINGS" not in inproc.stdout, inproc.stdout[-3000:]


PROJECT_REPORTER = """
import pytest
from _pytest.terminal import TerminalReporter


class ProjectReporter(TerminalReporter):
    def write_line(self, line, **markup):
        pass

    def section(self, title, sep="=", **kw):
        pass


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    std = config.pluginmanager.getplugin("terminalreporter")
    if std is not None and not isinstance(std, ProjectReporter):
        config.pluginmanager.unregister(std)
        config.pluginmanager.register(ProjectReporter(config), "terminalreporter")
"""


@pytest.mark.parametrize("reporter", ["project", "none"])
def test_g0412_cache_summary_is_written_when_a_project_reporter_swallows_it(pytester, reporter):
    """Audit G-0412, exam probe F-05.probe.custom-reporter (claude/exam d92e259): a conftest that replaces pytest's
    terminal reporter swallowed the cache summary; it is also written to <cache>/summary.txt, with or without a
    reporter (-p no:terminal)."""
    write(pytester, **{"tests/conftest.py": PROJECT_REPORTER if reporter == "project" else "",
                       "tests/test_cr.py": "def test_cr_one():\n    assert sum([1, 2]) == 3\n\n"
                                           "def test_cr_two():\n    assert 'ab'.upper() == 'AB'\n"})
    extra = ("-p", "no:terminal") if reporter == "none" else ()
    run(pytester, "cr1", *extra, "tests")
    p, cache, _ = run(pytester, "cr2", *extra, "tests")
    assert p.returncode == 0, p.stdout[-2000:]
    assert "cache with proof" not in p.stdout  # swallowed, as in the project
    text = (pytester.path / ".c" / "summary.txt").read_text()
    assert "detpy cache with proof" in text and "reused 2 result(s) with proof" in text, text
