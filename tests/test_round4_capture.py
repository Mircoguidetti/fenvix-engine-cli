"""parallel-proof round 4: the capture under tools that patch os.path (found on pydantic-ai, MEASURED locally:
tests/models/test_openai.py, 81 of 335 tests failed under --det-cache only, 0 under --det).

blockbuster wraps os.path.abspath (and others) to raise BlockingError when called inside an event loop. detpy's audit
hook resolves the paths a test opens with os.path.abspath/realpath; it looked them up at each use (pyfakefs patches
them on purpose), so the test's open() inside the event loop raised blockbuster's error from detpy's own hook. The
capture now falls back to the real functions (bound at the session start) when a patched one raises something else
than OSError/ValueError.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def test_a_raising_os_path_patch_does_not_reach_the_test_through_detpy(pytester):
    pytester.makeini("[pytest]\n")
    (pytester.path / "data.txt").write_text("x")
    pytester.makepyfile(test_b="""
        import os, posixpath

        class Blocking(Exception):
            pass

        def test_open_while_abspath_raises(monkeypatch):
            real = posixpath.abspath

            def blocked(p):
                raise Blocking("Blocking call to os.path.abspath")

            monkeypatch.setattr(posixpath, "abspath", blocked)
            monkeypatch.setattr(posixpath, "realpath", blocked)
            monkeypatch.setattr(os, "getcwd", blocked)
            # the test itself never calls them: only detpy's audit hook would
            with open("data.txt") as fh:
                assert fh.read() == "x"
        """)
    for _ in range(2):
        r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.c'}", "-p", "no:cacheprovider")
        r.assert_outcomes(passed=1)
