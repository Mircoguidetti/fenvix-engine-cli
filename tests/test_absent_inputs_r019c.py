"""Copied from claude/dep-verdict-abjcfw (harness/culprit/review_r019c, 8d47dcd); serial and -n variants added.

R-019c, item 3: does the shipped proof cache (``--det-cache``) reuse a stale pass when a later commit changes an
input the key does not record? REPORT-4 §2.1 says the key omits failed imports and the import system's directory
reads, and leaves the cache impact UNKNOWN.

Each test: run 1 records a pass; the project changes only through an input listed in the test name; run 2 must not
reuse the pass, because a plain pytest run of the changed project fails. A test that fails here is a wrong reuse in
the shipped cache.
"""

import shutil
import sys
from pathlib import Path
import textwrap

import pytest

pytest_plugins = ["pytester"]

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


_MODE: list = []


@pytest.fixture(autouse=True, params=["serial", "n2"])
def _mode(request, monkeypatch):
    """parallel-proof round 3, item 9: each case serially and under ``-n 2`` (the truth stays plain serial pytest)."""
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS"):
        monkeypatch.delenv(k, raising=False)
    _MODE[:] = [] if request.param == "serial" else ["-n", "2", "-p", "xdist"]
    yield
    _MODE[:] = []


def _run_cache(pytester, n, *args):
    import json

    args = (*args, *_MODE)

    out = pytester.path / f"out{n}.json"
    r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.cachedir'}",
                                      f"--det-outcomes={out}", "-p", "no:cacheprovider", *args)
    data = json.loads(out.read_text()) if out.exists() else {}
    return r, set(data.get("cache", {}).get("reused_ids", ()))


def _write(pytester, files):
    for name, text in files.items():
        p = pytester.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def _check(pytester, before, change, test_id):
    """before: files of commit 1; change: files written for commit 2 (None deletes)."""
    _write(pytester, before)
    r1, _ = _run_cache(pytester, 1)
    r1.assert_outcomes(passed=1)
    for name, text in change.items():
        p = pytester.path / name
        if text is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(text))
    # truth: plain pytest on commit 2
    plain = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:detpy")
    po = plain.parseoutcomes()
    assert po.get("failed", 0) + po.get("errors", po.get("error", 0)) == 1, po
    r2, reused = _run_cache(pytester, 2)
    assert test_id not in reused, f"stale pass reused for {test_id}"
    o2 = r2.parseoutcomes()
    assert o2.get("failed", 0) + o2.get("errors", o2.get("error", 0)) == 1, o2


INI = {"pytest.ini": "[pytest]\n", "pkg/__init__.py": ""}


def test_e1_try_import_now_finds_a_new_module(pytester):
    """The finding of REPORT-4 §2.1: a module that a failed ``try: import`` now finds."""
    _check(pytester, {**INI, "test_m.py": """
        try:
            from pkg import optional
        except ImportError:
            optional = None

        def test_t():
            assert optional is None or optional.VALUE == 1
        """},
        {"pkg/optional.py": "VALUE = 2\n"}, "test_m.py::test_t")


def test_e1b_try_import_in_library_code(pytester):
    """Same, but the optional import sits in a library module the test calls (the usual shape)."""
    _check(pytester, {**INI, "pkg/core.py": """
        try:
            import pkg_speedups as _fast
        except ImportError:
            _fast = None

        def compute():
            return _fast.compute() if _fast else 1
        """, "test_m.py": """
        from pkg import core

        def test_t():
            assert core.compute() == 1
        """},
        {"pkg_speedups.py": "def compute():\n    return 2\n"}, "test_m.py::test_t")


def test_e2_pytest_ini_option_change(pytester):
    """The ini file: ``filterwarnings = error`` turns a warning into a failure."""
    _check(pytester, {**INI, "test_m.py": """
        import warnings

        def test_t():
            warnings.warn("old", UserWarning)
        """},
        {"pytest.ini": "[pytest]\nfilterwarnings = error\n"}, "test_m.py::test_t")


def test_e2b_ini_getini_custom_option(pytester):
    """A conftest reads a custom ini option with ``getini``; only the ini value changes."""
    _check(pytester, {**INI, "conftest.py": """
        import pytest

        def pytest_addoption(parser):
            parser.addini("app_mode", "mode", default="lenient")

        @pytest.fixture
        def mode(request):
            return request.config.getini("app_mode")
        """, "test_m.py": """
        def test_t(mode):
            assert mode == "lenient"
        """},
        {"pytest.ini": "[pytest]\napp_mode = strict\n"}, "test_m.py::test_t")


def test_e3_new_conftest_in_subdir(pytester):
    """A new conftest.py next to the test adds an autouse fixture that fails."""
    _check(pytester, {**INI, "tests/__init__.py": "", "tests/test_m.py": """
        def test_t():
            assert True
        """},
        {"tests/conftest.py": """
        import pytest

        @pytest.fixture(autouse=True)
        def boom():
            raise RuntimeError("new conftest")
        """}, "tests/test_m.py::test_t")


def test_e4_init_turns_namespace_into_package(pytester):
    """``ns/`` is a namespace package; a later commit adds ``ns/__init__.py``, which defines the attribute."""
    _check(pytester, {**INI, "ns/mod.py": "X = 1\n", "test_m.py": """
        import ns
        import ns.mod

        def test_t():
            assert getattr(ns, "FLAG", None) is None
        """},
        {"ns/__init__.py": "FLAG = 1\n"}, "test_m.py::test_t")


def test_e5_data_file_found_by_glob(pytester):
    """A data file found by glob (a directory listing, no read of the new file)."""
    _check(pytester, {**INI, "data/a.txt": "a\n", "test_m.py": """
        import glob, os

        HERE = os.path.dirname(__file__)

        def test_t():
            assert len(glob.glob(os.path.join(HERE, "data", "*.txt"))) == 1
        """},
        {"data/b.txt": "b\n"}, "test_m.py::test_t")


def test_e5b_data_file_existence_check(pytester):
    """``os.path.exists`` on a file that does not exist yet (a stat, no read)."""
    _check(pytester, {**INI, "test_m.py": """
        import os

        HERE = os.path.dirname(__file__)

        def test_t():
            assert not os.path.exists(os.path.join(HERE, "LEGACY_MODE"))
        """},
        {"LEGACY_MODE": ""}, "test_m.py::test_t")


def test_e6_stdlib_shadowed_by_new_module(pytester):
    """A new top-level ``colorsys.py`` in the rootdir (on ``sys.path`` under prepend import mode) shadows the stdlib
    module the test imports."""
    _check(pytester, {**INI, "test_m.py": """
        import colorsys

        def test_t():
            assert colorsys.rgb_to_hsv(1, 0, 0)[0] == 0
        """},
        {"colorsys.py": "def rgb_to_hsv(r, g, b):\n    return (0.5, 1, 1)\n"}, "test_m.py::test_t")


def _zip(path, body):
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("vfast.py", date_time=(2020, 1, 1, 0, 0, 0)), body)


def test_e7_vendored_zip_changes(pytester):
    """A module imported from a vendored zip on ``sys.path`` (zipimport) changes."""
    _write(pytester, INI)
    _zip(pytester.path / "vendor" / "lib.zip", "ADJ = 0\n")
    _write(pytester, {"test_m.py": """
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor", "lib.zip"))
        import vfast

        def test_t():
            assert vfast.ADJ == 0
        """})
    r1, _ = _run_cache(pytester, 1)
    r1.assert_outcomes(passed=1)
    _zip(pytester.path / "vendor" / "lib.zip", "ADJ = 1\n")
    pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:detpy").assert_outcomes(failed=1)
    r2, reused = _run_cache(pytester, 2)
    assert "test_m.py::test_t" not in reused, "stale pass reused"


@pytest.mark.skipif(__import__("shutil").which("gcc") is None, reason="needs gcc")
def test_e8_native_library_changes(pytester):
    """A C library loaded with ctypes (``dlopen``) changes."""
    import subprocess

    def build(v):
        c = pytester.path / "n.c"
        c.write_text(f"int adj(void) {{ return {v}; }}\n")
        subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(pytester.path / "pkg" / "_native.so"), str(c)],
                       check=True)
        c.unlink()

    _write(pytester, INI)
    build(0)
    _write(pytester, {"test_m.py": """
        import ctypes, os
        lib = ctypes.CDLL(os.path.join(os.path.dirname(__file__), "pkg", "_native.so"))

        def test_t():
            assert lib.adj() == 0
        """})
    r1, _ = _run_cache(pytester, 1)
    r1.assert_outcomes(passed=1)
    build(1)
    pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:detpy").assert_outcomes(failed=1)
    r2, reused = _run_cache(pytester, 2)
    assert "test_m.py::test_t" not in reused, "stale pass reused"


def test_e9_pth_file_added_to_site_packages(pytester, tmp_path):
    """The environment changes between runs: a ``.pth`` file in site-packages adds a directory to ``sys.path``
    that holds a module an optional import of the test now finds. Same distributions, same repository."""
    import sysconfig

    pth = Path(sysconfig.get_paths()["purelib"]) / "zz_review_r019c.pth"
    shadow = tmp_path / "shadowdir"
    shadow.mkdir()
    (shadow / "r019c_helper.py").write_text("VALUE = 2\n")
    _write(pytester, {**INI, "test_m.py": """
        try:
            import r019c_helper
        except ImportError:
            r019c_helper = None

        def test_t():
            assert r019c_helper is None
        """})
    try:
        r1, _ = _run_cache(pytester, 1)
        r1.assert_outcomes(passed=1)
        pth.write_text(str(shadow) + "\n")
        pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:detpy").assert_outcomes(failed=1)
        r2, reused = _run_cache(pytester, 2)
        assert "test_m.py::test_t" not in reused, "stale pass reused"
    finally:
        pth.unlink(missing_ok=True)


def test_e10_pytest_plugin_entry_point_installed(pytester, tmp_path):
    """The environment gains a pytest plugin through an entry point (a ``.dist-info`` with ``pytest11``) whose
    autouse fixture fails the test. The distributions digest should notice."""
    import sysconfig

    sp = Path(sysconfig.get_paths()["purelib"])
    di = sp / "r019c_plug-1.0.dist-info"
    mod = sp / "r019c_plug.py"
    _write(pytester, {**INI, "test_m.py": "def test_t():\n    assert True\n"})
    try:
        r1, _ = _run_cache(pytester, 1)
        r1.assert_outcomes(passed=1)
        di.mkdir()
        (di / "METADATA").write_text("Metadata-Version: 2.1\nName: r019c-plug\nVersion: 1.0\n")
        (di / "entry_points.txt").write_text("[pytest11]\nr019c = r019c_plug\n")
        (di / "RECORD").write_text("")
        mod.write_text("import pytest\n\n@pytest.fixture(autouse=True)\ndef _boom():\n    raise RuntimeError('plugin')\n")
        plain = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:detpy")
        assert plain.ret != 0
        r2, reused = _run_cache(pytester, 2)
        assert "test_m.py::test_t" not in reused, "stale pass reused"
    finally:
        shutil.rmtree(di, ignore_errors=True)
        mod.unlink(missing_ok=True)


def test_e3b_new_root_conftest(pytester):
    """A new conftest.py at the rootdir (none before) adds an autouse fixture that fails."""
    _check(pytester, {**INI, "test_m.py": """
        def test_t():
            assert True
        """},
        {"conftest.py": """
        import pytest

        @pytest.fixture(autouse=True)
        def boom():
            raise RuntimeError("new conftest")
        """}, "test_m.py::test_t")


def test_e3c_existing_conftest_gains_autouse_fixture(pytester):
    """Control for E3: an existing conftest.py changes (adds the failing autouse fixture)."""
    _check(pytester, {**INI, "conftest.py": "X = 1\n", "test_m.py": """
        def test_t():
            assert True
        """},
        {"conftest.py": """
        import pytest

        @pytest.fixture(autouse=True)
        def boom():
            raise RuntimeError("changed conftest")
        """}, "test_m.py::test_t")
