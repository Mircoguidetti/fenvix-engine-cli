"""Round 2 of rust-hotpaths: the project half of --det's bytecode precompile walks the tree in Rust
(``_core.pyc_stale``, ``_core.fresh_sources``) and runs compileall only for the files it would compile.

Checked against compileall itself (the files ``compile_dir`` would hand to ``py_compile``), against the round-1
``os.walk`` of ``_drop_fresh_pycs``, and end to end against the round-1 precompile
(``tests/rust_hotpaths_ref/_ref_reexec.py``): the bytecode trees are byte-identical.
"""

from __future__ import annotations

import compileall
import importlib.util
import os
import re
import sys
import time
from pathlib import Path

import pytest

from detpy import _core, reexec

REF = Path(__file__).parent / "rust_hotpaths_ref"


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


def _compileall_would_compile(root: str, prefix: str, monkeypatch) -> list:
    """What ``compileall -qq -x _EXCLUDE root`` hands to py_compile with ``sys.pycache_prefix = prefix``."""
    seen = []
    monkeypatch.setattr(sys, "pycache_prefix", prefix)
    monkeypatch.setattr(compileall.py_compile, "compile", lambda f, *a, **k: seen.append(f) or True)
    compileall.compile_dir(root, quiet=2, rx=re.compile(reexec._EXCLUDE))
    monkeypatch.undo()
    return sorted(seen)


def _compile_for_real(root: str, prefix: str, files=None) -> None:
    saved = sys.pycache_prefix
    sys.pycache_prefix = prefix
    try:
        if files is None:
            compileall.compile_dir(root, quiet=2, rx=re.compile(reexec._EXCLUDE))
        else:
            for f in files:
                compileall.compile_file(f, quiet=2, rx=re.compile(reexec._EXCLUDE))
    finally:
        sys.pycache_prefix = saved


@pytest.mark.parametrize("relative", [False, True])
def test_stale_list_is_what_compileall_compiles(tmp_path, monkeypatch, relative):
    root = tmp_path / "proj"
    _tree(root)
    prefix = str(tmp_path / "pyc")
    if relative:
        monkeypatch.chdir(tmp_path)
        rootarg = "proj"
    else:
        rootarg = str(root)

    def check():
        want = _compileall_would_compile(rootarg, prefix, monkeypatch)
        if relative:
            monkeypatch.chdir(tmp_path)
        got = sorted(reexec._stale_project_sources([rootarg], prefix))
        assert got == want
        return got

    first = check()
    assert any(f.endswith("c.py") for f in first) and not any(".git" in f or "ghost" in f for f in first)
    assert any(f.endswith("link.py") for f in first) and not any("linkdir" in f for f in first)
    _compile_for_real(rootarg, prefix)
    assert [os.path.basename(f) for f in check()] == ["bad.py"]  # only the file that never compiles
    # an edit (new mtime), a new file, a deleted pyc, a truncated pyc
    os.utime(root / "pkg" / "b.py")
    (root / "pkg" / "new.py").write_text("NEW = 1\n")
    os.unlink(_core.pyc_cache_path(os.path.join(rootarg, "a.py"), os.getcwd(), prefix, sys.implementation.cache_tag))
    tr = _core.pyc_cache_path(os.path.join(rootarg, "pkg", "sub", "deep", "c.py"), os.getcwd(), prefix,
                              sys.implementation.cache_tag)
    with open(tr, "r+b") as fh:
        fh.truncate(7)
    names = sorted(os.path.basename(f) for f in check())
    assert names == ["a.py", "b.py", "bad.py", "c.py", "new.py"], names


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


def _old_fresh(d: str, limit: float) -> list:
    exclude = re.compile(reexec._EXCLUDE)
    out = []
    for root, subdirs, files in os.walk(d):
        subdirs[:] = [x for x in subdirs if not exclude.search(os.path.join(root, x) + os.sep)]
        for f in files:
            if f.endswith(".py"):
                src = os.path.join(root, f)
                try:
                    if os.stat(src).st_mtime >= limit:
                        out.append(src)
                except OSError:
                    pass
    return sorted(out)


def test_fresh_sources_match_the_os_walk(tmp_path):
    root = tmp_path / "proj"
    _tree(root)
    now = time.time()
    for name in ("a.py", "pkg/b.py", ".git/hooks/h.py", "pkg/__pycache__/ghost.py", "venv/lib/v.py"):
        os.utime(root / name, (now, now))
    for limit in (now - 2.0, now - 7200, now + 10):
        got = sorted(_core.fresh_sources(str(root), list(reexec._EXCLUDE_NAMES), limit))
        assert got == _old_fresh(str(root), limit)
    assert {os.path.basename(f) for f in _core.fresh_sources(str(root), list(reexec._EXCLUDE_NAMES), now - 2.0)} \
        == {"a.py", "b.py", "ghost.py", "link.py"}  # link.py: a link to a.py (stat follows it)


def _ref_reexec():
    spec = importlib.util.spec_from_file_location("detpy._ref_reexec", REF / "_ref_reexec.py")
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    spec.loader.exec_module(m)
    return m


def _snapshot(prefix: str) -> dict:
    out = {}
    for dirpath, _d, fs in os.walk(prefix):
        for f in fs:
            if f.endswith(".pyc"):
                p = os.path.join(dirpath, f)
                out[os.path.relpath(p, prefix)] = Path(p).read_bytes()
    return out


def test_precompile_writes_the_same_bytecode_as_round_1(tmp_path, monkeypatch):
    ref = _ref_reexec()
    root = tmp_path / "proj"
    _tree(root)
    site = tmp_path / "site"
    (site / "lib1").mkdir(parents=True)
    (site / "lib1" / "__init__.py").write_text("X = {1, 2}\n")
    snaps = {}
    for name, mod in (("ref", ref), ("new", reexec)):
        monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / f"pyc-{name}"))
        monkeypatch.setattr(mod, "precompile_dirs", lambda rootdir: [str(site), str(root)])
        steps = []
        mod.precompile("0", str(root))
        steps.append(_snapshot(mod.pyc_cache_dir("0")))
        mod.precompile("0", str(root))  # nothing changed
        steps.append(_snapshot(mod.pyc_cache_dir("0")))
        snaps[name] = steps
    # edits between runs, applied to both
    for name, mod in (("ref", ref), ("new", reexec)):
        monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / f"pyc-{name}"))
        monkeypatch.setattr(mod, "precompile_dirs", lambda rootdir: [str(site), str(root)])
        snaps[name].append(None)
    t = time.time() - 600
    (root / "pkg" / "b.py").write_text("B = {1, 2, 3}\n")
    (root / "pkg" / "new.py").write_text("NEW = 1\n")
    for f in ("pkg/b.py", "pkg/new.py"):
        os.utime(root / f, (t, t))
    os.utime(root / "a.py")  # fresh: its bytecode is dropped after the precompile
    for name, mod in (("ref", ref), ("new", reexec)):
        monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / f"pyc-{name}"))
        monkeypatch.setattr(mod, "precompile_dirs", lambda rootdir: [str(site), str(root)])
        mod.precompile("0", str(root))
        snaps[name][2] = _snapshot(mod.pyc_cache_dir("0"))
    for i in range(3):
        a, b = snaps["ref"][i], snaps["new"][i]
        assert sorted(a) == sorted(b), (i, sorted(set(a) ^ set(b)))
        assert a == b, i
    assert any(k.endswith("new.cpython-%d%d.pyc" % sys.version_info[:2]) for k in snaps["new"][2])
    assert not any(k.endswith(os.sep + "a." + sys.implementation.cache_tag + ".pyc") for k in snaps["new"][2])
