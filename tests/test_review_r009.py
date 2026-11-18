"""Review R-009 (cache with proof, step 1): holes in following child processes and the cache epoch.

Each test states what a fresh run does and asserts the cache does the same; each fails on 646e28e.
"""

import shutil
import sys

import pytest

from test_proofcache import ids, project, run_cache  # noqa: F401 (fixtures)

pytestmark = [
    pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring"),
    pytest.mark.skipif(shutil.which("strace") is None, reason="following needs strace"),
]


def test_child_started_by_one_test_and_used_by_another(pytester, run_cache):
    # A helper process started lazily by the first test that needs it and kept for the next ones (a language
    # server, a persistent shell, a ProcessPoolExecutor with spawn workers held in a module global). Its reads on
    # behalf of test_b are attributed to the context that started it (test_a); test_b itself raised no event.
    project(pytester, **{"data.txt": "hello\n", "test_m.py": """
        import subprocess

        _sh = None

        def sh():
            global _sh
            if _sh is None:
                _sh = subprocess.Popen(["sh"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            return _sh

        def ask(cmd):
            p = sh()
            p.stdin.write(cmd + "; echo __END__\\n")
            p.stdin.flush()
            out = []
            for line in p.stdout:
                if line == "__END__\\n":
                    return "".join(out)
                out.append(line)

        def test_a():
            assert ask("echo hi") == "hi\\n"

        def test_b():
            assert ask("cat data.txt") == "hello\\n"

        def test_c():
            _sh.stdin.close()
            _sh.wait()
        """})
    run_cache()
    (pytester.path / "data.txt").write_text("changed\n")
    r, reused, data = run_cache()
    # a fresh run of test_b reads "changed" and fails; reusing its pass is wrong
    assert "test_m.py::test_b" not in reused
    r.assert_outcomes(passed=2, failed=1)


def test_child_read_of_dev_shm_is_an_input_or_refused(pytester, run_cache, tmp_path):
    # In-process, a read under /dev is refused ("proc"); a followed child's read of /dev/shm is skipped as if it
    # were /dev/null. /dev/shm is a tmpfs of ordinary files (shared state between processes, test data).
    import os
    import uuid

    if not os.path.isdir("/dev/shm"):
        pytest.skip("no /dev/shm")
    shm = f"/dev/shm/detpy-r009-{uuid.uuid4().hex}"
    with open(shm, "w") as fh:
        fh.write("hello\n")
    try:
        project(pytester, **{"test_m.py": f"""
            import subprocess

            def test_cat():
                out = subprocess.run(["cat", "{shm}"], capture_output=True, text=True, check=True).stdout
                assert out == "hello\\n"
            """})
        run_cache()
        with open(shm, "w") as fh:
            fh.write("changed\n")
        r, reused, data = run_cache()
        assert reused == set()
        r.assert_outcomes(failed=1)
    finally:
        os.unlink(shm)


def test_timezone_read_by_c_is_an_input(pytester, run_cache, monkeypatch):
    # time.localtime / datetime.fromtimestamp read TZ through C getenv (and /etc/localtime through C open): neither
    # passes os.environ, so neither is recorded. A fresh run under another TZ gives another result.
    project(pytester, **{"test_m.py": """
        import time

        def test_local_hour():
            assert time.strftime("%H", time.localtime(0)) == "00"
        """})
    monkeypatch.setenv("TZ", "UTC")
    run_cache()
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    r, reused, data = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=1)


def test_real_clock_read_in_c_is_not_reused_after_it_moves(pytester, run_cache):
    # sqlite's date('now') reads the real clock in C (LIMITS S1): no "time" flag, so neither the epoch nor anything
    # else about time is in the key. The result is reused after the real clock passed the test's threshold.
    import time

    t = int(time.time()) + 3
    project(pytester, **{"test_m.py": f"""
        import sqlite3

        def test_before_deadline():
            now = sqlite3.connect(":memory:").execute("select strftime('%s', 'now')").fetchone()[0]
            assert int(now) < {t}
        """})
    run_cache()
    while time.time() < t + 1:
        time.sleep(0.2)
    r, reused, data = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=1)


def test_child_real_clock_is_not_reused_after_it_moves(pytester, run_cache):
    # a followed child reads the real clock (vDSO, invisible to strace): same as above through a subprocess
    import time

    t = int(time.time()) + 3
    project(pytester, **{"test_m.py": f"""
        import subprocess

        def test_before_deadline():
            now = int(subprocess.run(["date", "+%s"], capture_output=True, text=True, check=True).stdout)
            assert now < {t}
        """})
    run_cache()
    while time.time() < t + 1:
        time.sleep(0.2)
    r, reused, data = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=1)
