"""Review R-020b (last round of the dependency-update verdict, ``--det-cache-dists`` after the R-020 fixes).

New attempts at a wrong reuse in the spirit of R-020: a dependency update that changes what a test does without
changing anything the test's key records. Same protocol as the first review (record at P, bump, cached run and fresh
run at C; every reused result must equal the fresh one), same helpers.

Findings (fail on claude/dep-verdict-abjcfw 9019c6d, pass without ``--det-cache-dists``):
* ``test_file_installed_by_two_distributions``
* ``test_native_library_installed_outside_site_packages``
* ``test_console_script_added_by_a_bump``

Outside the target (fails without the flag too, pre-existing in the default cache):
``test_repository_file_existence_check``.

Checked and not findings (pass): ``test_same_version_reinstalled_from_a_different_wheel``,
``test_package_data_file_changed_by_a_bump``, ``test_entry_point_plugin_changed_by_a_bump``.
"""

import base64
import hashlib
import os
import shutil
import stat
import sys
import textwrap

import pytest

from test_review_r020_dep_verdict import _cc, _install, _uninstall, _wrong, env, walk  # noqa: F401

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def _add_record(site, dist_info, rel, data):
    h = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    with open(os.path.join(site, dist_info, "RECORD"), "a") as fh:
        fh.write(f"{rel},sha256={h},{len(data)}\n")


# -- N1: one file, two RECORDs (pycrypto / pycryptodome, opencv-python / -headless, jwt / PyJWT) ---------------------
def test_file_installed_by_two_distributions(pytester, env, walk):
    # Two distributions install the same file. Index.files maps a path to ONE owner (the last one iterated), so a
    # test that imports the module depends on that owner only. Upgrading the other one replaces the file (pip
    # uninstalls its old copy and writes the new one); the mapped owner's RECORD, version and identity file do not
    # change. Today's engine reruns: every distribution is an input of every test.
    # The shared file is a data file (a code change in a shared module is caught: the module's executed code is
    # recorded). opencv-python / -headless share cv2/data/*.xml and the cv2 extension; pycrypto / pycryptodome
    # share Crypto/.
    table = "cipher/table.txt"
    _install(env, "cipher-a", "1.0", {"cipher/__init__.py": "", table: "1\n"})
    _install(env, "cipher-b", "1.0", {"cipher/__init__.py": "", table: "1\n"})
    sys.path.insert(0, env)
    try:
        from detpy import distid

        owner = distid.Index(str(pytester.path)).dist_of(os.path.join(env, table))
    finally:
        sys.path.remove(env)
    assert owner in ("cipher-a", "cipher-b"), owner
    other = "cipher-b" if owner == "cipher-a" else "cipher-a"
    pytester.makepyfile(test_cipher="""
        from importlib.resources import files

        def test_v():
            assert files("cipher").joinpath("table.txt").read_text() == "1\\n"
        """)

    def bump():
        # pip install -U <other>: remove the files of its RECORD, write the new wheel's files
        _uninstall(env, other)
        _install(env, other, "2.0", {"cipher/__init__.py": "", table: "2\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_cipher.py::test_v") == "passed", rs[0].stdout.str()
    assert fresh.get("test_cipher.py::test_v") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


# -- N2: a shared library installed by a wheel's data scheme, outside site-packages (mkl, intel-openmp, tbb) --------
@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
def test_native_library_installed_outside_site_packages(pytester, env, walk):
    # natlib-b installs libb.so into <prefix>/lib (RECORD path ../lib/libb.so, as the mkl / intel-openmp / tbb wheels
    # do through <name>.data/data/lib). The extension "nat" is linked against it with an rpath, so the dynamic
    # loader maps it when nat is imported. Tracker.scan() reads /proc/self/maps but keeps only paths under a site
    # directory: the library is skipped although Index.files knows its owner. The test depends on d/nat only.
    import sysconfig

    build = pytester.path / "build"
    build.mkdir()
    prefix_lib = os.path.join(os.path.dirname(env), "lib")
    os.makedirs(prefix_lib)
    suffix = sysconfig.get_config_var("EXT_SUFFIX")

    def install_natlib(version, value):
        so = build / f"libb-{version}.so"
        _cc(str(build), str(so), "int bval(void) { return %d; }\n" % value)
        data = so.read_bytes()
        _install(env, "natlib-b", version, {})
        with open(os.path.join(prefix_lib, "libb.so"), "wb") as fh:
            fh.write(data)
        _add_record(env, f"natlib_b-{version}.dist-info", "../lib/libb.so", data)

    install_natlib("1.0", 1)
    nat_so = build / ("nat" + suffix)
    _cc(str(build), str(nat_so), """
        #define PY_SSIZE_T_CLEAN
        #include <Python.h>
        int bval(void);
        static PyObject *call(PyObject *self, PyObject *noarg) { return PyLong_FromLong(bval()); }
        static PyMethodDef M[] = {{"call", call, METH_NOARGS, NULL}, {NULL, NULL, 0, NULL}};
        static struct PyModuleDef D = {PyModuleDef_HEAD_INIT, "nat", NULL, -1, M};
        PyMODINIT_FUNC PyInit_nat(void) { return PyModule_Create(&D); }
        """, f"-L{prefix_lib}", "-lb", f"-Wl,-rpath,{prefix_lib}")
    _install(env, "nat", "1.0", {})
    shutil.copy(nat_so, os.path.join(env, "nat" + suffix))
    _add_record(env, "nat-1.0.dist-info", "nat" + suffix, nat_so.read_bytes())
    pytester.makepyfile(test_nat="""
        import nat

        def test_value():
            assert nat.call() == 1
        """)

    def bump():
        os.unlink(os.path.join(prefix_lib, "libb.so"))
        shutil.rmtree(os.path.join(env, "natlib_b-1.0.dist-info"))
        install_natlib("1.1", 2)

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_nat.py::test_value") == "passed", rs[0].stdout.str()
    assert fresh.get("test_nat.py::test_value") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


# -- N3: a console script a bump adds, found with shutil.which (an existence check: stat, no audit event) -----------
def test_console_script_added_by_a_bump(pytester, env, walk, monkeypatch):
    # Tests gate on tools being installed: skipif(shutil.which("ruff") is None), "black not installed", a CLI smoke
    # test. shutil.which() checks candidates with os.stat/os.access; neither raises an audit event, the bin directory
    # is not a site directory, and the test loads nothing of the distribution. tool 2.0 adds the script: a fresh run
    # runs (and here fails) the test, the cache reuses "skipped".
    bindir = os.path.join(os.path.dirname(env), "bin")
    os.makedirs(bindir)
    monkeypatch.setenv("PATH", bindir + os.pathsep + os.environ.get("PATH", ""))
    _install(env, "tool", "1.0", {"tool/__init__.py": "def main():\n    return 0\n"})
    pytester.makepyfile(test_tool="""
        import shutil

        import pytest

        def test_formatter_cli():
            exe = shutil.which("tool-fmt")
            if exe is None:
                pytest.skip("tool-fmt is not installed")
            with open(exe) as fh:
                assert "tool.main" in fh.read()
        """)

    def bump():
        _uninstall(env, "tool")
        _install(env, "tool", "2.0", {"tool/__init__.py": "def main():\n    return 0\n"})
        script = b"#!/bin/sh\nexec python -c 'import tool.cli' \"$@\"\n"
        p = os.path.join(bindir, "tool-fmt")
        with open(p, "wb") as fh:
            fh.write(script)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        _add_record(env, "tool-2.0.dist-info", "../bin/tool-fmt", script)

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_tool.py::test_formatter_cli") == "skipped", rs[0].stdout.str()
    assert fresh.get("test_tool.py::test_formatter_cli") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


# -- checked, not findings ---------------------------------------------------------------------------------------
def test_same_version_reinstalled_from_a_different_wheel(pytester, env, walk):
    # pip install --force-reinstall of a rebuilt wheel with the same version (a local build, a re-uploaded file):
    # the RECORD hashes change, and the identity is name==version plus the RECORD digest.
    _install(env, "lib", "1.0", {"lib.py": "X = 1\n"})
    pytester.makepyfile(test_lib="""
        import lib

        def test_x():
            assert lib.X == 1
        """)

    def bump():
        _uninstall(env, "lib")
        _install(env, "lib", "1.0", {"lib.py": "X = 2\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert fresh.get("test_lib.py::test_x") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


def test_package_data_file_changed_by_a_bump(pytester, env, walk):
    # a data file of a dependency read with importlib.resources (no module of it loaded by the test itself)
    _install(env, "tzdatax", "1.0", {"tzdatax/__init__.py": "", "tzdatax/zones.txt": "UTC\n"})
    pytester.makepyfile(test_data="""
        from importlib.resources import files

        def test_zones():
            assert files("tzdatax").joinpath("zones.txt").read_text() == "UTC\\n"
        """)

    def bump():
        _uninstall(env, "tzdatax")
        _install(env, "tzdatax", "1.1", {"tzdatax/__init__.py": "", "tzdatax/zones.txt": "UTC\nCET\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert fresh.get("test_data.py::test_zones") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


def test_entry_point_plugin_changed_by_a_bump(pytester, env, walk):
    # a plugin discovered by entry point group, loaded and memoised by a registry in a first test, used by a second
    _install(env, "host", "1.0", {"host.py": """
        import functools
        from importlib.metadata import entry_points

        @functools.lru_cache
        def plugins():
            return {ep.name: ep.load() for ep in entry_points(group="host.plugins")}
        """})
    _install(env, "plug", "1.0", {"plug.py": "def run():\n    return 1\n"},
             entry_points="[host.plugins]\nplug = plug:run\n")
    pytester.makepyfile(test_a="""
        import host

        def test_a():
            assert host.plugins()
        """, test_b="""
        import host

        def test_b():
            assert host.plugins()["plug"]() == 1
        """)

    def bump():
        _uninstall(env, "plug")
        _install(env, "plug", "1.1", {"plug.py": "def run():\n    return 20\n"},
                 entry_points="[host.plugins]\nplug = plug:run\n")

    reused, p, cached, fresh, rs = walk(bump)
    assert fresh.get("test_b.py::test_b") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


# -- outside the dependency target: the same existence check on a repository file (no --det-cache-dists) -----------
from test_review_r020_dep_verdict import run_cache_plain  # noqa: E402,F401


def test_repository_file_existence_check(pytester, run_cache_plain):
    # os.path.exists / Path.is_file / shutil.which use stat(); no audit event, so a file that appears is not seen
    # by a test that only checks for it (an optional config file, a generated fixture, a migration directory).
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_cfg="""
        import os

        def test_no_local_config():
            assert not os.path.exists("local.cfg")
        """)
    run_cache_plain()
    (pytester.path / "local.cfg").write_text("x = 1\n")
    r, reused, out = run_cache_plain()
    fresh = pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider")
    assert fresh.ret != 0  # a fresh run fails the test
    assert "test_cfg.py::test_no_local_config" not in reused, r.stdout.str()
