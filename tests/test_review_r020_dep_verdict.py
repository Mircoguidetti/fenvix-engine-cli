"""Review R-020 (dependency-update verdict, prototype ``--det-cache-dists``): wrong reuses after a version bump.

Each test installs small distributions into a site directory, records a run with ``--det-cache-dists``, bumps one
distribution, then runs with the cache and once fresh. The assertion is the cache's own promise: a reused result is
the result a fresh run gives. Each test fails on the prototype commit (claude/dep-verdict-abjcfw, 81354c25 + 7f353b0f)
and passes without the flag (today's engine reruns everything after any bump).
"""

import base64
import hashlib
import json
import os
import shutil
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


# -- a tiny installer: what pip writes (files, dist-info with METADATA and RECORD) -----------------------------------
def _install(site, name, version, files, entry_points=None):
    dist = f"{name.replace('-', '_')}-{version}.dist-info"
    rec = []
    allf = dict(files)
    allf[f"{dist}/METADATA"] = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    allf[f"{dist}/WHEEL"] = "Wheel-Version: 1.0\nGenerator: review\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    allf[f"{dist}/INSTALLER"] = "pip\n"
    if entry_points:
        allf[f"{dist}/entry_points.txt"] = entry_points
    for rel, text in allf.items():
        p = os.path.join(site, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = textwrap.dedent(text).encode()
        with open(p, "wb") as fh:
            fh.write(data)
        h = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rec.append(f"{rel},sha256={h},{len(data)}")
    rec.append(f"{dist}/RECORD,,")
    with open(os.path.join(site, dist, "RECORD"), "w") as fh:
        fh.write("\n".join(rec) + "\n")


def _uninstall(site, name):
    prefix = name.replace("-", "_") + "-"
    for d in os.listdir(site):
        if d.startswith(prefix) and d.endswith(".dist-info"):
            for line in open(os.path.join(site, d, "RECORD")).read().splitlines():
                rel = line.split(",", 1)[0]
                p = os.path.join(site, rel)
                if os.path.isfile(p):
                    os.unlink(p)
            shutil.rmtree(os.path.join(site, d))
    # empty package directories left behind (pip removes them too)
    for root, dirs, files in os.walk(site, topdown=False):
        if root != site and not os.listdir(root):
            os.rmdir(root)


@pytest.fixture
def env(pytester, monkeypatch):
    """A site directory (``.../site-packages``, processed by ``site.addsitedir`` at startup, so .pth files run)."""
    site = pytester.path / "env" / "site-packages"
    boot = pytester.path / "env" / "boot"
    site.mkdir(parents=True)
    boot.mkdir()
    (boot / "sitecustomize.py").write_text(f"import site\nsite.addsitedir({str(site)!r})\n")
    monkeypatch.setenv("PYTHONPATH", str(boot))
    pytester.makeini("[pytest]\n")
    return str(site)


@pytest.fixture
def walk(pytester):
    """record at P -> bump -> cached run and fresh run at C; returns (reused ids, cached outcomes, fresh outcomes)."""
    n = {"i": 0}

    def run(*args):
        n["i"] += 1
        out = pytester.path / f"out{n['i']}.json"
        r = pytester.runpytest_subprocess("--det", f"--det-outcomes={out}", "-p", "no:cacheprovider", *args)
        data = json.loads(out.read_text()) if out.exists() else {}
        return r, data

    def outcomes(data):
        o = data.get("outcomes") or data.get("tests") or {}
        if isinstance(o, list):
            o = {t["nodeid"]: t["outcome"] for t in o}
        return {k: (v["outcome"] if isinstance(v, dict) else v) for k, v in o.items()}

    def go(bump):
        cache = f"--det-cache={pytester.path / '.cachedir'}"
        r0, d0 = run(cache, "--det-cache-dists")
        assert (d0.get("cache") or {}).get("recorded", 1), r0.stdout.str()
        bump()
        r1, d1 = run(cache, "--det-cache-dists")
        r2, d2 = run()  # fresh: no cache
        reused = set((d1.get("cache") or {}).get("reused_ids", ()))
        return reused, outcomes(d0), outcomes(d1), outcomes(d2), (r0, r1, r2)

    return go


def _wrong(reused, cached, fresh):
    return {n: (cached.get(n), fresh.get(n)) for n in reused if cached.get(n) != fresh.get(n)}


# -- F1: a distribution's metadata answer memoised by one test and used by the next ------------------------------
def test_version_answer_memoised_by_an_earlier_test(pytester, env, walk):
    # helper (never changed) asks importlib.metadata for lib's version the first time it is needed and keeps the
    # answer (functools.lru_cache, a module global: packaging/feature gates in transformers, huggingface_hub,
    # sqlalchemy dialects, pydantic plugins). test_a pays for the query and depends on d/lib; test_b gets the
    # memoised answer, raises no event and depends on d/helper alone. Today's engine is safe here only because every
    # test depends on every distribution; with per-distribution identity, test_b is reused after lib 2.0 although a
    # fresh run fails it. (The same memoisation hole exists for repository data files without the flag: see
    # test_repository_file_memoised_by_an_earlier_test, outside the dependency target.)
    _install(env, "lib", "1.0", {"lib.py": "X = 1\n"})
    _install(env, "helper", "1.0", {"helper.py": """
        import functools
        from importlib.metadata import version

        @functools.lru_cache
        def lib_major():
            return int(version("lib").split(".")[0])

        def api():
            return "new" if lib_major() >= 2 else "old"
        """})
    pytester.makepyfile(test_a="""
        import helper

        def test_a():
            assert helper.api()
        """, test_b="""
        import helper

        def test_b():
            assert helper.api() == "old"
        """)

    def bump():
        _uninstall(env, "lib")
        _install(env, "lib", "2.0", {"lib.py": "X = 1\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_b.py::test_b") == "passed", rs[0].stdout.str()
    assert fresh.get("test_b.py::test_b") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


# -- F2: a submodule of a namespace package added by a distribution the test never loaded --------------------------
def test_namespace_subpackage_added_by_a_bump(pytester, env, walk):
    # ns is a namespace package shared by ns-core and ns-tools (google.*, azure.*, opentelemetry.*, sphinxcontrib.*,
    # jaraco.*). The test probes an optional ns.extra (try/except ImportError, importlib.util.find_spec). The name
    # finder records top-level names only ("m/ns": who provides "ns", unchanged); the import system's listing of
    # site-packages/ns/ is not an input; ns-tools was never loaded. ns-tools 2.0 adds ns/extra: a fresh run takes
    # the other branch, the cache reuses the old outcome.
    _install(env, "ns-core", "1.0", {"ns/core/__init__.py": "CORE = 1\n"})
    _install(env, "ns-tools", "1.0", {"ns/tools/__init__.py": "TOOLS = 1\n"})
    pytester.makepyfile(test_ns="""
        import ns.core

        def test_extra_absent():
            try:
                import ns.extra  # noqa: F401
            except ImportError:
                return
            raise AssertionError("ns.extra is installed")
        """)

    def bump():
        _uninstall(env, "ns-tools")
        _install(env, "ns-tools", "2.0", {"ns/tools/__init__.py": "TOOLS = 1\n", "ns/extra/__init__.py": "E = 1\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_ns.py::test_extra_absent") == "passed", rs[0].stdout.str()
    assert fresh.get("test_ns.py::test_extra_absent") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


# -- F3: a .pth file runs code at interpreter startup, before anything is recorded ----------------------------------
def test_pth_startup_code_of_a_distribution_no_test_imports(pytester, env, walk):
    # site.py executes the `import` lines of every .pth file at startup. A distribution whose .pth configures the
    # process inline (warnings filters, sys.setrecursionlimit, os.umask, a builtins hook) changes what tests do
    # without any of its modules being loaded and without any read during the session: no test depends on it.
    _install(env, "tuner", "1.0", {"tuner.pth": "import sys; sys.setrecursionlimit(5000)\n"})
    pytester.makepyfile(test_pth="""
        import sys

        def test_limit():
            assert sys.getrecursionlimit() == 5000
        """)

    def bump():
        _uninstall(env, "tuner")
        _install(env, "tuner", "1.1", {"tuner.pth": "import sys; sys.setrecursionlimit(3000)\n"})

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_pth.py::test_limit") == "passed", rs[0].stdout.str()
    assert fresh.get("test_pth.py::test_limit") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


# -- F4: a native library loaded lazily by C code, during a test, after every Python import ------------------------
def _cc(src_dir, out, src, *flags):
    import subprocess
    import sysconfig

    c = os.path.join(src_dir, os.path.basename(out) + ".c")
    with open(c, "w") as fh:
        fh.write(textwrap.dedent(src))
    subprocess.run(["cc", "-shared", "-fPIC", "-O0", "-o", out, c, *flags,
                    f"-I{sysconfig.get_paths()['include']}"], check=True)


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
def test_native_library_dlopened_lazily_by_an_extension(pytester, env, walk):
    # An extension module (dist "nat") opens a shared library of another distribution ("natlib-b") with dlopen()
    # the first time a function is called, not at import (torch's lazily loaded CUDA/cuDNN libraries, onnxruntime
    # execution providers, GDAL/PROJ drivers, OpenSSL providers). No Python event marks it: sys.modules does not
    # change and ctypes is not involved, so Tracker.scan() does not re-read /proc/self/maps after the test and the
    # test does not depend on natlib-b. (As the first test of a session it is caught by luck: pytest's own lazy
    # imports change sys.modules after it; the warm-up tests take that away, as any earlier test in a real suite
    # does.) natlib-b 1.1 changes the library's answer; the cache reuses the old outcome.
    import sysconfig

    build = pytester.path / "build"
    build.mkdir()
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    lib_src = "int bval(void) { return %d; }\n"

    def natlib(version, value):
        so = build / f"libb-{version}.so"
        _cc(str(build), str(so), lib_src % value)
        return so

    nat_so = build / ("nat" + suffix)
    _cc(str(build), str(nat_so), """
        #define PY_SSIZE_T_CLEAN
        #include <Python.h>
        #include <dlfcn.h>
        static PyObject *call(PyObject *self, PyObject *arg) {
            const char *path = PyUnicode_AsUTF8(arg);
            if (!path) return NULL;
            void *h = dlopen(path, RTLD_NOW);
            if (!h) { PyErr_SetString(PyExc_OSError, dlerror()); return NULL; }
            int (*f)(void) = (int (*)(void))dlsym(h, "bval");
            return PyLong_FromLong(f ? f() : -1);
        }
        static PyMethodDef M[] = {{"call", call, METH_O, NULL}, {NULL, NULL, 0, NULL}};
        static struct PyModuleDef D = {PyModuleDef_HEAD_INIT, "nat", NULL, -1, M};
        PyMODINIT_FUNC PyInit_nat(void) { return PyModule_Create(&D); }
        """, "-ldl")

    def install_natlib(version, value):
        data = natlib(version, value).read_bytes()
        _install(env, "natlib-b", version, {})
        os.makedirs(os.path.join(env, "natlib_b"), exist_ok=True)
        with open(os.path.join(env, "natlib_b", "libb.so"), "wb") as fh:
            fh.write(data)
        # RECORD lists the library, as a wheel's would
        d = os.path.join(env, f"natlib_b-{version}.dist-info", "RECORD")
        h = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        with open(d, "a") as fh:
            fh.write(f"natlib_b/libb.so,sha256={h},{len(data)}\n")

    _install(env, "nat", "1.0", {})
    shutil.copy(nat_so, os.path.join(env, "nat" + suffix))
    with open(os.path.join(env, "nat-1.0.dist-info", "RECORD"), "a") as fh:
        fh.write(f"nat{suffix},,\n")
    install_natlib("1.0", 1)
    pytester.makepyfile(test_nat="""
        import os

        import nat

        LIB = os.path.join(os.path.dirname(nat.__file__), "natlib_b", "libb.so")

        def test_0_warm_up():  # pytest's own lazy imports happen around the first test of a session
            pass

        def test_1_warm_up():
            pass

        def test_value():
            assert nat.call(LIB) == 1
        """)

    def bump():
        os.unlink(os.path.join(env, "natlib_b", "libb.so"))
        shutil.rmtree(os.path.join(env, "natlib_b-1.0.dist-info"))
        install_natlib("1.1", 2)

    reused, p, cached, fresh, rs = walk(bump)
    assert p.get("test_nat.py::test_value") == "passed", rs[0].stdout.str()
    assert fresh.get("test_nat.py::test_value") == "failed", rs[2].stdout.str()
    assert _wrong(reused, cached, fresh) == {}, rs[1].stdout.str()


# -- outside the dependency target: the same memoisation hole for a repository file (no --det-cache-dists) ---------
def test_repository_file_memoised_by_an_earlier_test(pytester, run_cache_plain):
    pytester.makeini("[pytest]\n")
    pytester.mkpydir("pkg")
    (pytester.path / "data.txt").write_text("1\n")
    (pytester.path / "pkg" / "conf.py").write_text(textwrap.dedent("""
        import functools

        @functools.lru_cache
        def major():
            with open("data.txt") as fh:
                return int(fh.read())

        def api():
            return "new" if major() >= 2 else "old"
        """))
    pytester.makepyfile(test_a="""
        from pkg import conf

        def test_a():
            assert conf.api()
        """, test_b="""
        from pkg import conf

        def test_b():
            assert conf.api() == "old"
        """)
    run_cache_plain()
    (pytester.path / "data.txt").write_text("2\n")
    r, reused, out = run_cache_plain()
    fresh = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    fresh.assert_outcomes(passed=1, failed=1)  # test_b fails on a fresh run
    assert "test_b.py::test_b" not in reused, r.stdout.str()


@pytest.fixture
def run_cache_plain(pytester):
    n = {"i": 0}

    def run():
        n["i"] += 1
        out = pytester.path / f"plain{n['i']}.json"
        r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.plaincache'}",
                                          f"--det-outcomes={out}", "-p", "no:cacheprovider")
        data = json.loads(out.read_text()) if out.exists() else {}
        return r, set((data.get("cache") or {}).get("reused_ids", ())), data

    return run
