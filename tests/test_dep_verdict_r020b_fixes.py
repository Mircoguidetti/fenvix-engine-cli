"""Fixes of review R-020b (dependency-update verdict, last round), beyond the review's own tests
(tests/test_review_r020b_dep_verdict.py, unchanged):

* N1, a distribution that starts claiming a file another one installed (it was not an owner when the test was
  recorded): the file's claim group changes, whether the new claimant is new in the group or already had files
  there;
* N3, an existence check of a path under a site directory that a second distribution adds (an optional plugin);
* an existence check never replaces the content digest of a file the same test reads (default cache).
"""

import os
import sys

import pytest

from test_review_r020_dep_verdict import _install, _uninstall, _wrong, env, run_cache_plain, walk  # noqa: F401

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

# the test reads the file by path, without importing the package (no m/ lookup of its top-level name)
_READ_BY_PATH = """
    import os, sys

    def _site():
        return next(p for p in sys.path if p.endswith("site-packages") and os.path.isdir(os.path.join(p, "cipher")))

    def test_v():
        with open(os.path.join(_site(), "cipher", "table.txt")) as fh:
            assert fh.read() == "1\\n"
    """


@pytest.mark.parametrize("already_in_group", [False, True])
def test_distribution_starts_claiming_a_file(pytester, env, walk, already_in_group):
    _install(env, "cipher-a", "1.0", {"cipher/__init__.py": "", "cipher/table.txt": "1\n"})
    if already_in_group:
        _install(env, "cipher-b", "1.0", {"cipher/extra.txt": "x\n"})
    pytester.makepyfile(test_cipher=_READ_BY_PATH)

    def bump():
        if already_in_group:
            _uninstall(env, "cipher-b")
        # cipher-b (2.0) now also installs cipher/table.txt and overwrites cipher-a's copy
        _install(env, "cipher-b", "2.0", {"cipher/extra.txt": "x\n", "cipher/table.txt": "2\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_cipher.py::test_v") == "passed", rs[0].stdout.str()
    assert fresh.get("test_cipher.py::test_v") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


def test_optional_plugin_module_added_by_a_second_distribution(pytester, env, walk):
    _install(env, "host", "1.0", {"host.py": "X = 1\n"})
    pytester.makepyfile(test_opt="""
        import os, sys

        import host

        def test_without_plugin():
            here = os.path.dirname(host.__file__)
            assert not os.path.exists(os.path.join(here, "host_plugin.py"))
        """)

    def bump():
        _install(env, "host-plugin", "1.0", {"host_plugin.py": "Y = 1\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_opt.py::test_without_plugin") == "passed", rs[0].stdout.str()
    assert fresh.get("test_opt.py::test_without_plugin") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


def test_existence_check_keeps_the_content_dependency(pytester, run_cache_plain):
    # an existence check after a read (here in a later test of the process, carried by the prefix rule, and in the
    # test itself) must not turn the file's content digest into "s:file"
    pytester.makeini("[pytest]\n")
    pytester.path.joinpath("data.txt").write_text("1\n")
    pytester.makepyfile(test_data="""
        import os

        def test_read_then_check():
            with open("data.txt") as fh:
                assert fh.read() == "1\\n"
            assert os.path.exists("data.txt")

        def test_check_only():
            assert os.path.isfile("data.txt")
        """)
    run_cache_plain()
    r, reused, _ = run_cache_plain()
    assert reused == {"test_data.py::test_read_then_check", "test_data.py::test_check_only"}, r.stdout.str()
    pytester.path.joinpath("data.txt").write_text("2\n")
    r, reused, _ = run_cache_plain()
    assert "test_data.py::test_read_then_check" not in reused, r.stdout.str()
    # the later test carries the earlier test's read (prefix rule)
    assert "test_data.py::test_check_only" not in reused, r.stdout.str()
