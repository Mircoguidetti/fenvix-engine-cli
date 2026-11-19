"""Review R-009b (cache with proof, step 1, fix round): wrong-reuse holes left by or introduced with the R-009 fixes.

Each test changes only what a fresh run would see (the real clock passing a deadline, or one file appearing), then
asserts the cache does not reuse the old result. Each fails on e5f4ca2 (the engine measured in s1g).
"""

import os
import shutil
import subprocess
import sys
import time

import pytest

from test_proofcache import project, run_cache  # noqa: F401 (fixtures)

pytestmark = [
    pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring"),
    pytest.mark.skipif(shutil.which("strace") is None, reason="following needs strace"),
]


# the first run must finish before the deadline: a cold run (re-exec, precompile of the project) takes seconds
MARGIN = 20


def _wait_past(t):
    while time.time() < t + 1:
        time.sleep(0.2)


def test_sqlite_clock_read_by_the_schema_is_refused(pytester, run_cache):
    # The sqlite statement trace only sees the statement text. A column default (CURRENT_TIMESTAMP, the usual
    # created_at), a trigger body or a view defined in a database the test opens reads the real clock in C while the
    # statement the test runs says nothing about time. REPORT-2 claims sqlite's real-clock reads are refused.
    import sqlite3

    t = int(time.time()) + MARGIN
    con = sqlite3.connect(pytester.path / "app.db")
    con.executescript("create table ev (id integer primary key, at text default current_timestamp);")
    con.commit()
    con.close()
    project(pytester, **{"test_m.py": f"""
        import shutil, sqlite3

        def test_before_deadline(tmp_path):
            shutil.copy("app.db", tmp_path / "work.db")
            con = sqlite3.connect(tmp_path / "work.db")
            con.execute("insert into ev (id) values (1)")
            at = con.execute("select strftime('%s', at) from ev").fetchone()[0]
            assert int(at) < {t}
        """})
    run_cache()
    _wait_past(t)
    r, reused, data = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=1)


@pytest.mark.parametrize("access", ["O_WRONLY", "O_RDWR"])
def test_exclusive_create_that_fails_is_an_input(pytester, run_cache, access):
    # 970daef records an exclusive create (O_CREAT|O_EXCL, mode "x") as an output only: "the file did not exist".
    # That holds only when the open succeeds. A lock file, a pid file or "write the defaults unless the project has
    # its own" branches on whether the path exists; the absence the test relied on is not an input. Write-only
    # exclusive creates were already output-only before (the O_WRONLY case fails on 646e28e and 2180148); 970daef
    # extends it to read-write ones (the O_RDWR case passes on 2180148 and fails from 970daef on).
    project(pytester, **{"test_m.py": f"""
        import os

        def acquire(path):
            try:
                return os.open(path, os.O_CREAT | os.O_EXCL | os.{access})
            except FileExistsError:
                return None

        def test_lock():
            fd = acquire("app.lock")
            assert fd is not None, "app.lock is held"
            os.close(fd)
            os.remove("app.lock")
        """})
    run_cache()
    (pytester.path / "app.lock").write_text("")  # a stale lock file (or one a commit adds)
    r, reused, data = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=1)


def test_python_child_clock_read_at_shutdown_is_refused(pytester, run_cache):
    # The clock library exempts reads made while Py_IsInitialized() is false, meant for the time module's zone
    # offsets at start-up. Py_FinalizeEx clears the flag before it tears the modules down, so every __del__ (or
    # generator finally) run at interpreter exit reads the real clock unseen.
    t = int(time.time()) + MARGIN
    project(pytester, **{"child.py": """
        import sys, time

        class Report:
            def __del__(self, now=time.time, out=sys.stdout):
                out.write(f"{int(now())}\\n")
                out.flush()

        _report = Report()
        """, "test_m.py": f"""
        import subprocess, sys

        def test_before_deadline():
            out = subprocess.run([sys.executable, "child.py"], capture_output=True, text=True, check=True).stdout
            assert int(out) < {t}
        """})
    run_cache()
    _wait_past(t)
    r, reused, data = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=1)


def test_child_reading_a_file_time_it_just_set_is_refused(pytester, run_cache):
    # A child that creates a file and reads its modification time reads the real clock through the kernel: no
    # clock_gettime, no gettimeofday, nothing the clock library sees (date -r, stat, find -newer, make, tar...).
    t = int(time.time()) + MARGIN
    project(pytester, **{"test_m.py": f"""
        import subprocess

        def test_before_deadline(tmp_path):
            out = subprocess.run(["sh", "-c", 'echo > "$1"/stamp && stat -c %Y "$1"/stamp', "sh", str(tmp_path)],
                                 capture_output=True, text=True, check=True).stdout
            assert int(out) < {t}
        """})
    run_cache()
    _wait_past(t)
    r, reused, data = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=1)
