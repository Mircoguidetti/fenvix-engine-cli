"""Round 2 of rust-hotpaths: --det's bytecode precompile checks its directories in Rust (``_core.pyc_stale_hashed``:
the walk and checked-hash test of ``_pycompile.py``, review R-015) and runs the driver only for the stale files;
``reexec.dir_stamp`` is ``_core.dir_stamp``.

Checked against the R-015 Python path kept verbatim in ``tests/rust_hotpaths_ref/_ref_reexec_r015.py`` (with its
driver ``_pycompile.py``): the stale list against the driver's own walk and test, the stamp against the Python
stamp, ``source_hash`` against ``importlib.util.source_hash``, and end to end the bytecode trees are byte-identical
across edits.
"""

from __future__ import annotations

import importlib.util
import os
import random
import re
import sys
import time
from pathlib import Path

import pytest

from detpy import _core, reexec

REF = Path(__file__).parent / "rust_hotpaths_ref"
KEY = int.from_bytes(importlib.util.MAGIC_NUMBER, "little")


def _tree(root: Path) -> None:
    files = {
        "a.py": "A = 1\n",
        "pkg/__init__.py": "",
        "pkg/b.py": "B = {1, 2}\n",
        "pkg/sub/deep/c.py": "C = 3\n",
        "pkg/bad.py": "def (:\n",  # never compiles: attempted at every run
        "pkg/notes.txt": "x\n",
        "pkg/__pycache__/ghost.py": "G = 1\n",  # compileall skips __pycache__ directories
        ".git/hooks/h.py": "H = 1\n",  # excluded (-x)
        "venv/lib/v.py": "V = 1\n",
        "node_modules/n.py": "N = 1\n",
        "docs/.py": "D = 1\n",  # a file named ".py"
        "x.PY": "X = 1\n",
        "tools/gen.pyi": "Y: int\n",
    }
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (root / "linkdir").symlink_to(root / "pkg", target_is_directory=True)  # not followed
    (root / "link.py").symlink_to(root / "a.py")  # a link to a file is compiled
    (root / "broken.py").symlink_to(root / "missing.py")
    weird = os.fsencode(str(root / "pkg")) + b"/caf\xe9.py"  # not valid UTF-8
    with open(weird, "wb") as fh:
        fh.write(b"W = 1\n")
    old = time.time() - 3600
    for dirpath, _dirs, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dirpath, f)
            if os.path.exists(p) and not os.path.islink(p):
                os.utime(p, (old, old))


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REF / file)
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    spec.loader.exec_module(m)
    return m


def _ref_reexec():
    return _load("detpy._ref_reexec_r015", "_ref_reexec_r015.py")


def _ref_driver():
    return _load("_ref_pycompile", "_pycompile.py")


def _driver_would_compile(dirs: list, prefix: str, exclude, monkeypatch) -> list:
    """The files the R-015 driver (``_pycompile.main``) hands to ``py_compile``, in its order."""
    drv = _ref_driver()
    seen = []
    monkeypatch.setattr(sys, "pycache_prefix", prefix)
    monkeypatch.setattr(drv.py_compile, "compile", lambda f, **k: seen.append(f))
    for f in drv.sources(dirs, re.compile(exclude) if exclude else None):
        drv.check(f)
    monkeypatch.undo()
    return seen


def test_source_hash_matches_importlib():
    variant = reexec._hash_variant()
    assert variant == ((1, 3) if sys.version_info >= (3, 11) else (2, 4))
    rnd = random.Random(7)
    for n in list(range(0, 40)) + [255, 256, 1000, 4096, 65537]:
        data = bytes(rnd.randrange(256) for _ in range(n))
        assert _core.source_hash(data, KEY, *variant) == importlib.util.source_hash(data), n


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("project", [True, False])
def test_stale_list_is_what_the_driver_compiles(tmp_path, monkeypatch, relative, project):
    root = tmp_path / "proj"
    _tree(root)
    prefix = str(tmp_path / "pyc")
    if relative:
        monkeypatch.chdir(tmp_path)
        rootarg = "proj"
    else:
        rootarg = str(root)
    exclude = reexec._EXCLUDE if project else None

    def check():
        want = _driver_would_compile([rootarg], prefix, exclude, monkeypatch)
        if relative:
            monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "pycache_prefix", prefix)
        got = reexec._stale_sources([rootarg], prefix, project)
        monkeypatch.undo()
        if relative:
            monkeypatch.chdir(tmp_path)
        assert got == want  # same files, same order
        return got

    first = check()
    assert any(f.endswith("c.py") for f in first) and not any("ghost" in f for f in first)
    assert any(f.endswith("link.py") for f in first) and not any("linkdir" in f for f in first)
    assert any(".git" in f for f in first) != project
    assert not any(f.endswith("broken.py") for f in first)  # unreadable: the driver skips it
    drv = _ref_driver()
    monkeypatch.setattr(sys, "pycache_prefix", prefix)
    for f in drv.sources([rootarg], re.compile(exclude) if exclude else None):
        drv.check(f)
    monkeypatch.undo()
    if relative:
        monkeypatch.chdir(tmp_path)
    assert [os.path.basename(f) for f in check()] == ["bad.py"]  # only the file that never compiles
    # a same-size edit that keeps the mtime, a new file, a deleted pyc, a truncated pyc, a timestamp pyc
    st = os.stat(root / "pkg" / "b.py")
    (root / "pkg" / "b.py").write_text("B = {1, 3}\n")
    os.utime(root / "pkg" / "b.py", ns=(st.st_atime_ns, st.st_mtime_ns))
    (root / "pkg" / "new.py").write_text("NEW = 1\n")
    os.unlink(_core.pyc_cache_path(os.path.join(rootarg, "a.py"), os.getcwd(), prefix, sys.implementation.cache_tag))
    tr = _core.pyc_cache_path(os.path.join(rootarg, "pkg", "sub", "deep", "c.py"), os.getcwd(), prefix,
                              sys.implementation.cache_tag)
    with open(tr, "r+b") as fh:
        fh.truncate(15)
    import py_compile

    monkeypatch.setattr(sys, "pycache_prefix", prefix)
    py_compile.compile(os.path.join(rootarg, "pkg", "__init__.py"), quiet=2,
                       invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
    monkeypatch.undo()
    if relative:
        monkeypatch.chdir(tmp_path)
    names = sorted(os.path.basename(f) for f in check())
    assert names == ["__init__.py", "a.py", "b.py", "bad.py", "c.py", "new.py"], names


def test_cache_path_matches_cache_from_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prefix = str(tmp_path / "pyc") + "/"
    monkeypatch.setattr(sys, "pycache_prefix", prefix)
    for p in ["/a/b/c.py", "/a/b/.py", "rel/x.py", "x.py", "/a//b/c.py", "/a/b.c/d.e.py", "/x.y/z"]:
        assert _core.pyc_cache_path(p, os.getcwd(), prefix, sys.implementation.cache_tag) == \
            importlib.util.cache_from_source(p), p


def test_exclusion_matches_the_regex():
    rx = re.compile(reexec._EXCLUDE)
    names = list(reexec._EXCLUDE_NAMES)
    for p in ["/a/.git/b", "/a/.git", "/a/x.git/b", "\\venv\\x", "/venv/", "venv/x", "/a/.venv/", "/a/.venvx/b",
              "/a/node_modules/b/", "/.detpy/", "/a/.eggs\\b", "/a/b/c.py", "//venv//"]:
        assert _core.path_excluded(p, names) == bool(rx.search(p)), p


def test_exclusion_matches_the_regex():
    rx = re.compile(reexec._EXCLUDE)
    names = list(reexec._EXCLUDE_NAMES)
    for p in ["/a/.git/b", "/a/.git", "/a/x.git/b", "\\venv\\x", "/venv/", "venv/x", "/a/.venv/", "/a/.venvx/b",
              "/a/node_modules/b/", "/.detpy/", "/a/.eggs\\b", "/a/b/c.py", "//venv//"]:
        assert _core.path_excluded(p, names) == bool(rx.search(p)), p


def test_dir_stamp_matches_the_python_stamp(tmp_path):
    ref = _ref_reexec()
    site = tmp_path / "site"
    (site / "pkg").mkdir(parents=True)
    (site / "pkg" / "__init__.py").write_text("")
    (site / "mod.py").write_text("M = 1\n")
    (site / "a-1.0.dist-info").mkdir()
    (site / "a-1.0.dist-info" / "RECORD").write_text("x\n")
    (site / "b-1.0.dist-info").mkdir()  # no RECORD
    (site / "c.dist-info").symlink_to(site / "a-1.0.dist-info", target_is_directory=True)
    (site / "dangling").symlink_to(site / "nowhere")
    with open(os.fsencode(str(site)) + b"/caf\xe9.pth", "wb") as fh:
        fh.write(b"\n")
    (site / "\u00e9t\u00e9.py").write_text("")  # valid UTF-8, sorts after the undecodable name in Python
    (site / "Zz").write_text("")
    for d in (site, tmp_path / "missing", site / "mod.py"):
        assert _core.dir_stamp(str(d)) == ref.dir_stamp(str(d)), d
        assert reexec.dir_stamp(str(d)) == ref.dir_stamp(str(d))
    before = reexec.dir_stamp(str(site))
    os.utime(site / "a-1.0.dist-info" / "RECORD", ns=(5, 5))
    assert reexec.dir_stamp(str(site)) != before
    assert reexec.dir_stamp(str(site)) == ref.dir_stamp(str(site))


def _snapshot(prefix: str) -> dict:
    out = {}
    for dirpath, _d, fs in os.walk(prefix):
        for f in fs:
            if f.endswith(".pyc"):
                p = os.path.join(dirpath, f)
                out[os.path.relpath(p, prefix)] = Path(p).read_bytes()
    return out


def test_precompile_writes_the_same_bytecode_as_the_python_driver(tmp_path, monkeypatch):
    ref = _ref_reexec()
    root = tmp_path / "proj"
    _tree(root)
    site = tmp_path / "site"
    (site / "lib1").mkdir(parents=True)
    (site / "lib1" / "__init__.py").write_text("X = {1, 2}\n")
    (site / "lib1" / "venv").mkdir()
    (site / "lib1" / "venv" / "v.py").write_text("V = 1\n")  # libraries: no exclusions
    snaps = {"ref": [], "new": []}

    def run_both():
        for name, mod in (("ref", ref), ("new", reexec)):
            monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / f"pyc-{name}"))
            monkeypatch.setattr(mod, "precompile_dirs", lambda rootdir: [str(site), str(root)])
            mod.precompile("0", str(root))
            snaps[name].append(_snapshot(mod.pyc_cache_dir("0")))

    run_both()
    run_both()  # nothing changed
    st = os.stat(root / "pkg" / "b.py")
    (root / "pkg" / "b.py").write_text("B = {1, 3}\n")  # same size, same mtime
    os.utime(root / "pkg" / "b.py", ns=(st.st_atime_ns, st.st_mtime_ns))
    (root / "pkg" / "new.py").write_text("NEW = 1\n")
    (site / "lib1" / "__init__.py").write_text("X = {1, 3}\n")  # a library module edited in place
    (site / "lib2").mkdir()
    (site / "lib2" / "__init__.py").write_text("Z = 1\n")  # an installer adds a package
    run_both()
    for i in range(3):
        a, b = snaps["ref"][i], snaps["new"][i]
        assert sorted(a) == sorted(b), (i, sorted(set(a) ^ set(b)))
        assert a == b, i
    last = snaps["new"][2]
    assert any(k.endswith("new." + sys.implementation.cache_tag + ".pyc") for k in last)
    assert any(os.sep + "lib2" + os.sep in k for k in last) and any(os.sep + "venv" + os.sep in k for k in last)
    b_pyc = next(v for k, v in last.items() if k.endswith(os.sep + "b." + sys.implementation.cache_tag + ".pyc"))
    assert b_pyc[8:16] == importlib.util.source_hash((root / "pkg" / "b.py").read_bytes())


def test_precompile_runs_the_driver_only_for_stale_files(tmp_path, monkeypatch):
    import subprocess

    root = tmp_path / "proj"
    _tree(root)
    monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / "pyc"))
    monkeypatch.setattr(reexec, "precompile_dirs", lambda rootdir: [str(root)])
    calls = []
    real = subprocess.run

    def run(cmd, **kw):
        calls.append((cmd[3:], kw.get("input")))
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    reexec.precompile("0", str(root))
    assert calls[0][0] == ["--stdin"] and b"c.py" in calls[0][1]
    calls.clear()
    reexec.precompile("0", str(root))
    assert [c[1].split(b"\0") for c in calls] == [[os.fsencode(str(root / "pkg" / "bad.py"))]]
    (root / "pkg" / "bad.py").unlink()
    calls.clear()
    reexec.precompile("0", str(root))
    assert calls == []  # nothing stale: no driver process
    monkeypatch.setattr(reexec, "_stale_sources", lambda *a: None)  # no Rust check: the driver walks
    reexec.precompile("0", str(root))
    assert calls[0] == (["-x", reexec._EXCLUDE, str(root)], None)
