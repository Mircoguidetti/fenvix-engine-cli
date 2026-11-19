"""Negative import lookups and the import system's directory reads as inputs of ``--det-cache`` (exact-culprit
REPORT-4 §2.1, asked to be checked here): a module the test failed to import, a namespace package that gains a
regular ``__init__.py``, a conftest.py that appears, a change of the pytest ini file. Each case records a run, makes
the change, and requires that every reused result equals a fresh run's."""

import json
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


@pytest.fixture
def cycle(pytester):
    n = {"i": 0}

    def run(*args):
        n["i"] += 1
        out = pytester.path / f"o{n['i']}.json"
        r = pytester.runpytest_subprocess("--det", f"--det-outcomes={out}", "-p", "no:cacheprovider", *args)
        d = json.loads(out.read_text()) if out.exists() else {}
        o = d.get("outcomes") or d.get("tests") or {}
        if isinstance(o, list):
            o = {t["nodeid"]: t["outcome"] for t in o}
        o = {k: (v["outcome"] if isinstance(v, dict) else v) for k, v in o.items()}
        return r, o, set((d.get("cache") or {}).get("reused_ids", ()))

    def go(change):
        cache = f"--det-cache={pytester.path / '.c'}"
        r0, p, _ = run(cache)
        change()
        r1, cached, reused = run(cache)
        r2, fresh, _ = run()
        wrong = {k: (cached.get(k), fresh.get(k)) for k in reused if cached.get(k) != fresh.get(k)}
        return p, fresh, wrong, (r0, r1, r2)

    return go


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


def test_failed_import_of_a_module_that_appears(pytester, cycle):
    pytester.makeini("[pytest]\n")
    _w(pytester.path / "pkg" / "__init__.py", "")
    pytester.makepyfile(test_opt="""
        try:
            from pkg import optional
        except ImportError:
            optional = None

        def test_without_optional():
            assert optional is None
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "pkg" / "optional.py", "X = 1\n"))
    assert p.get("test_opt.py::test_without_optional") == "passed", rs[0].stdout.str()
    assert fresh.get("test_opt.py::test_without_optional") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_failed_top_level_import_inside_the_test(pytester, cycle):
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_top="""
        import importlib

        def test_no_plugin():
            try:
                importlib.import_module("localplugin")
            except ImportError:
                return
            raise AssertionError("plugin present")
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "localplugin.py", "\n"))
    assert fresh.get("test_top.py::test_no_plugin") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_namespace_package_gains_an_init(pytester, cycle):
    # ns/ has no __init__.py (a namespace package); a later __init__.py makes it a regular package whose code runs
    pytester.makeini("[pytest]\n")
    _w(pytester.path / "ns" / "mod.py", "X = 1\n")
    pytester.makepyfile(test_ns="""
        import ns.mod

        def test_ns():
            assert getattr(ns, "FLAG", None) is None
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "ns" / "__init__.py", "FLAG = 1\n"))
    assert p.get("test_ns.py::test_ns") == "passed", rs[0].stdout.str()
    assert fresh.get("test_ns.py::test_ns") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_conftest_that_appears(pytester, cycle):
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_c="""
        def test_value(request):
            assert getattr(request.config, "_flag", 0) == 0
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "conftest.py", """
        def pytest_configure(config):
            config._flag = 1
        """))
    assert fresh.get("test_c.py::test_value") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_conftest_in_a_subdirectory_that_appears(pytester, cycle):
    pytester.makeini("[pytest]\n")
    _w(pytester.path / "sub" / "test_s.py", """
        import pytest

        @pytest.fixture
        def value():
            return 1

        def test_value(value):
            assert value == 1
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "sub" / "conftest.py", """
        import pytest

        @pytest.fixture(autouse=True)
        def boom():
            raise RuntimeError("new conftest")
        """))
    assert fresh.get("sub/test_s.py::test_value") == "error", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_pytest_ini_change(pytester, cycle):
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_w="""
        import warnings

        def test_warns():
            warnings.warn("old", DeprecationWarning)
        """)
    p, fresh, wrong, rs = cycle(lambda: pytester.makeini("[pytest]\nfilterwarnings = error\n"))
    assert fresh.get("test_w.py::test_warns") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_module_shadowed_by_a_new_file_earlier_on_the_path(pytester, cycle):
    # helpers/util.py is imported as "util" through sys.path; a util.py at the root (earlier on sys.path in rootdir
    # mode) shadows it
    pytester.makeini("[pytest]\npythonpath = . helpers\n")
    _w(pytester.path / "helpers" / "util.py", "V = 1\n")
    pytester.makepyfile(test_u="""
        import util

        def test_v():
            assert util.V == 1
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "util.py", "V = 2\n"))
    assert p.get("test_u.py::test_v") == "passed", rs[0].stdout.str()
    assert fresh.get("test_u.py::test_v") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()
