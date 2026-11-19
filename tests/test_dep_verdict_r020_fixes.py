"""Fixes of review R-020 (dependency-update verdict), beyond the review's own tests
(tests/test_review_r020_dep_verdict.py, copied unchanged):

* the prefix rule (H1/O1) for every kind of input, not only a data file: code an earlier test executed, an
  environment variable it read, a refusal (an input the engine could not record);
* a directory under site-packages listed by a test, filled by a second distribution (H2's listing form);
* the identity files behind H2 and H3 (``l/`` listings, ``@pth``) are rewritten from the environment at every start.
"""

import json
import os
import sys
import textwrap

import pytest

from detpy import distid

needs_monitoring = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

# the review's helpers (installer, site directory, record -> bump -> cached and fresh runs)
from test_review_r020_dep_verdict import _install, _uninstall, _wrong, env, walk  # noqa: E402,F401


@pytest.fixture
def run_cache(pytester):
    n = {"i": 0}

    def run(*extra):
        n["i"] += 1
        out = pytester.path / f"o{n['i']}.json"
        r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.c'}", f"--det-outcomes={out}",
                                          "-p", "no:cacheprovider", *extra)
        data = json.loads(out.read_text()) if out.exists() else {}
        return r, set((data.get("cache") or {}).get("reused_ids", ())), data

    return run


def _memo_project(pytester, body):
    pytester.makeini("[pytest]\n")
    pytester.mkpydir("pkg")
    (pytester.path / "pkg" / "conf.py").write_text(textwrap.dedent(body))
    pytester.makepyfile(test_a="""
        from pkg import conf

        def test_a():
            assert conf.api()
        """, test_b="""
        from pkg import conf

        def test_b():
            assert conf.api() == "old"
        """)


@needs_monitoring
def test_code_memoised_by_an_earlier_test(pytester, run_cache):
    # O1 with the change in code instead of data: test_b never executes major(), test_a did and memoised it
    body = """
        import functools

        @functools.lru_cache
        def major():
            return {v}

        def api():
            return "new" if major() >= 2 else "old"
        """
    _memo_project(pytester, body.format(v=1))
    run_cache()
    (pytester.path / "pkg" / "conf.py").write_text(textwrap.dedent(body.format(v=2)))
    r, reused, _ = run_cache()
    pytester.runpytest_subprocess("-p", "no:cacheprovider").assert_outcomes(passed=1, failed=1)
    assert "test_b.py::test_b" not in reused, r.stdout.str()


@needs_monitoring
def test_environment_variable_memoised_by_an_earlier_test(pytester, run_cache, monkeypatch):
    _memo_project(pytester, """
        import functools
        import os

        @functools.lru_cache
        def major():
            return int(os.environ.get("R020_MAJOR", "1"))

        def api():
            return "new" if major() >= 2 else "old"
        """)
    monkeypatch.setenv("R020_MAJOR", "1")
    run_cache()
    monkeypatch.setenv("R020_MAJOR", "2")
    r, reused, _ = run_cache()
    pytester.runpytest_subprocess("-p", "no:cacheprovider").assert_outcomes(passed=1, failed=1)
    assert "test_b.py::test_b" not in reused, r.stdout.str()


@needs_monitoring
def test_refusal_of_an_earlier_test_is_carried(pytester, run_cache):
    # test_a reads a pseudo-file (an input the engine refuses to record) and memoises it: test_b uses the answer,
    # so test_b cannot be proven either
    _memo_project(pytester, """
        import functools

        @functools.lru_cache
        def major():
            with open("/proc/self/stat") as fh:
                return 1 if fh.read() else 1

        def api():
            return "new" if major() >= 2 else "old"
        """)
    r, _, data = run_cache()
    nc = (data.get("cache") or {}).get("not_cached") or {}
    assert sum(nc.values()) == 2, r.stdout.str()
    r, reused, _ = run_cache()
    assert reused == set(), r.stdout.str()


@needs_monitoring
def test_tests_that_ran_before_are_the_only_ones_carried(pytester, run_cache):
    # the prefix rule follows the order of the run: a test that ran after another does not make it rerun
    pytester.makeini("[pytest]\n")
    (pytester.path / "data.txt").write_text("1\n")
    pytester.makepyfile(test_a="""
        def test_a():
            pass
        """, test_b="""
        def test_b():
            assert open("data.txt").read()
        """)
    run_cache()
    (pytester.path / "data.txt").write_text("2\n")
    r, reused, _ = run_cache()
    assert reused == {"test_a.py::test_a"}, r.stdout.str()


@needs_monitoring
def test_listing_of_a_directory_another_distribution_fills(pytester, env, walk):
    # host-plugins/ (a data directory, no module name) is installed by host only; the test lists it (a plugin
    # directory scan). host-extra 2.0 installs a file into it: host's identity does not change, the listing does
    _install(env, "host", "1.0", {"host.py": "import os\nPLUGINS = os.path.join(os.path.dirname(__file__), "
                                  "'host-plugins')\n", "host-plugins/core.txt": "core\n"})
    _install(env, "host-extra", "1.0", {"host_extra.py": "X = 1\n"})
    pytester.makepyfile(test_l="""
        import os

        import host

        def test_plugins():
            assert sorted(os.listdir(host.PLUGINS)) == ["core.txt"]
        """)

    def bump():
        _uninstall(env, "host-extra")
        _install(env, "host-extra", "2.0", {"host_extra.py": "X = 1\n", "host-plugins/extra.txt": "extra\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_l.py::test_plugins") == "passed", rs[0].stdout.str()
    assert fresh.get("test_l.py::test_plugins") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


def test_identity_files_follow_the_environment(tmp_path):
    site = tmp_path / "site-packages"
    (site / "ns" / "a").mkdir(parents=True)
    (site / "x.pth").write_text("import sys\n")
    ix = distid.Index(str(tmp_path / "proj"))
    out = tmp_path / "ident"
    ix.write(str(out), (str(site) + os.sep,))
    pth = (out / distid.PTH).read_text()
    assert "x.pth" in pth
    # a listing file written by a session is rewritten from its directory at the next start
    key = distid.listing_key(str(site / "ns"))
    (out / key).write_text(distid.listing_content(str(site / "ns")))
    assert (out / key).read_text().splitlines()[1:] == ["a"]
    (site / "ns" / "b").mkdir()
    (site / "ns" / "__pycache__").mkdir()
    (site / "x.pth").write_text("import os\n")
    ix.write(str(out), (str(site) + os.sep,))
    assert (out / key).read_text().splitlines()[1:] == ["a", "b"]
    assert (out / distid.PTH).read_text() != pth
    # a directory that disappeared is a state of its own, not a stale file to delete
    import shutil

    shutil.rmtree(site / "ns")
    ix.write(str(out), (str(site) + os.sep,))
    assert (out / key).read_text().splitlines()[1:] == ["<missing>"]


@needs_monitoring
def test_a_file_an_earlier_test_wrote_and_read_back_does_not_refuse_later_tests(pytester, run_cache):
    # the prefix rule carries test_a's read of out.txt; test_a wrote it itself (its own code is carried), so test_b
    # stays cacheable (community.general: 90 tests after a test that writes and reads back a repository file)
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_a="""
        def test_a():
            with open("out.txt", "w") as fh:
                fh.write("x")
            with open("out.txt") as fh:
                assert fh.read() == "x"
        """, test_b="""
        def test_b():
            pass
        """)
    run_cache()
    r, reused, data = run_cache()
    assert "test_b.py::test_b" in reused, r.stdout.str()
