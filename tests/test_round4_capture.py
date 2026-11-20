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


def test_a_spawn_hook_of_the_project_does_not_make_infrastructure_spawns_its_own(pytester):
    """pydantic-ai's cost_guards replaces subprocess.Popen._execute_child with a guard (a repository function). xdist's
    worker set-up spawns `uname` (platform.platform()) through it: that spawn is the infrastructure's, not the
    project's; before, every test of every worker was refused ('subprocess ... between tests')."""
    pytester.makeini("[pytest]\n")
    pytester.makeconftest("""
        import subprocess

        _orig = subprocess.Popen._execute_child

        def guarded(self, *a, **k):
            return _orig(self, *a, **k)

        subprocess.Popen._execute_child = guarded
        """)
    pytester.makepyfile(test_a="def test_a():\n    pass\n", test_b="def test_b():\n    pass\n",
                        test_spawn="import subprocess\n\ndef test_spawn():\n    subprocess.run(['true'])\n")
    import json

    out = pytester.path / "o.json"
    r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.c'}", f"--det-outcomes={out}",
                                      "-p", "no:cacheprovider", "-p", "xdist", "-n", "2")
    r.assert_outcomes(passed=3)
    nc = json.loads(out.read_text())["cache"]["not_cached_ids"]
    # the tests that spawn nothing are not refused for the worker set-up's spawn (the test's own spawn of `true` is
    # followed: no refusal either)
    assert not {"test_a.py::test_a", "test_b.py::test_b"} & set(nc), nc


def test_a_boot_id_read_at_import_is_a_content_input_not_a_refusal(pytester):
    """filelock reads /proc/sys/kernel/random/boot_id at import (pydantic-ai's conftest imports it): the session was
    uncacheable ('reads /proc, /sys or /dev', every test). It is keyed by content now: reused on the same boot."""
    import json

    pytester.makeini("[pytest]\n")
    pytester.makeconftest("BOOT = open('/proc/sys/kernel/random/boot_id').read()\n")
    pytester.makepyfile(test_a="def test_a():\n    pass\n")
    for i in range(2):
        out = pytester.path / f"o{i}.json"
        pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.c'}", f"--det-outcomes={out}",
                                      "-p", "no:cacheprovider").assert_outcomes(passed=1)
    assert json.loads(out.read_text())["cache"]["reused_ids"] == ["test_a.py::test_a"]
