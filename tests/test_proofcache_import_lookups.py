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


# -- variants (review R-019c asked for them): other ways to look a module up -------------------------------------
def test_find_spec_of_a_module_that_appears(pytester, cycle):
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_fs="""
        import importlib.util

        def test_absent():
            assert importlib.util.find_spec("optmod") is None
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "optmod.py", "\n"))
    assert fresh.get("test_fs.py::test_absent") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_pkgutil_iter_modules_sees_a_new_module(pytester, cycle):
    pytester.makeini("[pytest]\n")
    _w(pytester.path / "plugins" / "__init__.py", "")
    _w(pytester.path / "plugins" / "a.py", "")
    pytester.makepyfile(test_pk="""
        import pkgutil

        import plugins

        def test_names():
            assert [m.name for m in pkgutil.iter_modules(plugins.__path__)] == ["a"]
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "plugins" / "b.py", "\n"))
    assert fresh.get("test_pk.py::test_names") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_package_path_extended_at_import(pytester, cycle):
    # pkg/__init__.py appends a directory to its __path__; a submodule that appears there is found
    pytester.makeini("[pytest]\n")
    _w(pytester.path / "pkg" / "__init__.py", """
        import os
        __path__.append(os.path.join(os.path.dirname(__file__), "..", "extra"))
        """)
    (pytester.path / "extra").mkdir()
    pytester.makepyfile(test_pe="""
        def test_no_plug():
            try:
                import pkg.plug  # noqa: F401
            except ImportError:
                return
            raise AssertionError("plug found")
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "extra" / "plug.py", "\n"))
    assert fresh.get("test_pe.py::test_no_plug") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_custom_meta_path_finder(pytester, cycle):
    # a conftest installs a finder that serves modules from *.src files; it checks for the file with os.path.exists
    pytester.makeini("[pytest]\n")
    pytester.makeconftest("""
        import importlib.abc, importlib.util, os, sys

        ROOT = os.path.dirname(__file__)

        class SrcFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
            def find_spec(self, name, path=None, target=None):
                f = os.path.join(ROOT, "virtual", name + ".src")
                if "." in name or not os.path.exists(f):
                    return None
                return importlib.util.spec_from_loader(name, self)

            def create_module(self, spec):
                return None

            def exec_module(self, module):
                with open(os.path.join(ROOT, "virtual", module.__name__ + ".src")) as fh:
                    exec(fh.read(), module.__dict__)

        sys.meta_path.append(SrcFinder())
        """)
    (pytester.path / "virtual").mkdir()
    pytester.makepyfile(test_mp="""
        def test_no_virtual():
            try:
                import vmod  # noqa: F401
            except ImportError:
                return
            raise AssertionError("vmod found")
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "virtual" / "vmod.src", "X = 1\n"))
    assert fresh.get("test_mp.py::test_no_virtual") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


@pytest.mark.skipif(__import__("shutil").which("gcc") is None, reason="needs gcc")
def test_library_a_root_conftest_loads_at_startup(pytester, cycle):
    # the root conftest is imported before the capture starts: the library it maps is an input of every test
    import subprocess

    def build(v):
        c = pytester.path / "n.c"
        c.write_text(f"int adj(void) {{ return {v}; }}\n")
        subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(pytester.path / "libadj.so"), str(c)], check=True)
        c.unlink()

    pytester.makeini("[pytest]\n")
    build(0)
    pytester.makeconftest("""
        import ctypes, os
        LIB = ctypes.CDLL(os.path.join(os.path.dirname(__file__), "libadj.so"))
        """)
    pytester.makepyfile(test_lib="""
        from conftest import LIB

        def test_adj():
            assert LIB.adj() == 0
        """)
    p, fresh, wrong, rs = cycle(lambda: build(1))
    assert fresh.get("test_lib.py::test_adj") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


# -- LIMITS S1 cases: native code and early-bound references must rerun, not be reused ----------------------------
def _build(pytester, name, src):
    import subprocess

    c = pytester.path / "src.c"
    c.write_text(src)
    subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(pytester.path / name), str(c)], check=True)
    c.unlink()


@pytest.mark.skipif(__import__("shutil").which("gcc") is None, reason="needs gcc")
def test_stat_from_c_code_of_the_repository(pytester, cycle):
    # a repository library stats a path in C: no Python event at all. Its context is not cached.
    pytester.makeini("[pytest]\n")
    _build(pytester, "libprobe.so", "#include <sys/stat.h>\nint has(const char *p) { struct stat s; "
                                    "return stat(p, &s) == 0; }\n")
    pytester.makepyfile(test_c="""
        import ctypes, os

        def test_no_flag():
            lib = ctypes.CDLL(os.path.join(os.path.dirname(__file__), "libprobe.so"))
            assert not lib.has(b"FLAG")
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "FLAG", ""))
    assert fresh.get("test_c.py::test_no_flag") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


@pytest.mark.skipif(__import__("shutil").which("gcc") is None, reason="needs gcc")
def test_library_loaded_and_unloaded_within_one_test(pytester, cycle):
    # dlopen + dlclose before the end of the test: no mapping is left for the scan to see
    pytester.makeini("[pytest]\n")
    _build(pytester, "libv.so", "int v(void) { return 1; }\n")
    pytester.makepyfile(test_d="""
        import _ctypes, ctypes, os

        def test_v():
            lib = ctypes.CDLL(os.path.join(os.path.dirname(__file__), "libv.so"))
            value = lib.v()
            _ctypes.dlclose(lib._handle)
            assert value == 1
        """)
    p, fresh, wrong, rs = cycle(lambda: _build(pytester, "libv.so", "int v(void) { return 2; }\n"))
    assert fresh.get("test_d.py::test_v") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()


def test_stat_bound_before_the_session(pytester, cycle):
    # a plugin loaded with -p at startup (before the capture starts) binds os.stat and checks for a file with it
    pytester.makeini("[pytest]\naddopts = -p earlyplug\n")
    _w(pytester.path / "earlyplug.py", """
        from os import stat as _stat

        def exists(p):
            try:
                _stat(p)
            except OSError:
                return False
            return True
        """)
    pytester.makepyfile(test_b="""
        import os
        from earlyplug import exists

        def test_no_legacy():
            assert not exists(os.path.join(os.path.dirname(__file__), "LEGACY"))
        """)
    p, fresh, wrong, rs = cycle(lambda: _w(pytester.path / "LEGACY", ""))
    assert p.get("test_b.py::test_no_legacy") == "passed", rs[0].stdout.str()
    assert fresh.get("test_b.py::test_no_legacy") == "failed", rs[2].stdout.str()
    assert wrong == {}, rs[1].stdout.str()
