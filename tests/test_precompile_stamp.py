"""--det's bytecode precompile skips library directories whose top-level state is unchanged."""

import os
import subprocess

from detpy import reexec


def test_library_dirs_are_precompiled_again_only_when_they_change(tmp_path, monkeypatch):
    site, proj = tmp_path / "site", tmp_path / "proj"
    (site / "lib1").mkdir(parents=True)
    (site / "lib1" / "__init__.py").write_text("X = {1, 2}\n")
    proj.mkdir()
    (proj / "m.py").write_text("Y = 1\n")
    monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / "pyc"))
    monkeypatch.setattr(reexec, "precompile_dirs", lambda rootdir: [str(site), str(proj)])
    calls = []
    real = subprocess.run

    def run(cmd, **kw):
        # the project's files compileall is given (round 2: only the stale ones) count as the project
        calls.append(sorted({str(proj) if c.startswith(str(proj) + os.sep) else c for c in cmd
                             if c in (str(site), str(proj)) or c.startswith(str(proj) + os.sep)}))
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", run)

    def precompile():
        calls.clear()
        reexec.precompile("0", str(proj))
        return [d for c in calls for d in c]

    assert precompile() == [str(site), str(proj)]
    prefix = reexec.pyc_cache_dir("0")
    os.utime(proj / "m.py", (1, 1))  # older than 2 s: kept, and from now on up to date (round 2: not recompiled)
    precompile()
    assert any(f.endswith(".pyc") for _, _, fs in os.walk(prefix + str(site)) for f in fs)
    # unchanged library and project: nothing to compile (the project is checked, in Rust, without compileall)
    assert precompile() == []
    # a project edit: only the project is compiled
    os.utime(proj / "m.py", (2, 2))
    assert precompile() == [str(proj)]
    # an installer adds a package (or rewrites a dist-info RECORD): the library is checked again
    (site / "lib2").mkdir()
    (site / "lib2" / "__init__.py").write_text("Z = 1\n")
    assert precompile() == [str(site)]
    di = site / "lib2-1.0.dist-info"
    di.mkdir()
    (di / "RECORD").write_text("a\n")
    precompile()
    assert precompile() == []
    os.utime(di / "RECORD", ns=(1, 1))
    assert precompile() == [str(site)]


def test_library_dirs_inside_a_virtual_environment_are_precompiled(tmp_path, monkeypatch):
    """The project's exclusions (``venv/``, ``.venv/``, ...) do not apply to the library directories, which live
    in a virtual environment themselves; inside the project they still apply."""
    site = tmp_path / ".venv" / "lib" / "python3" / "site-packages"
    (site / "lib1").mkdir(parents=True)
    (site / "lib1" / "__init__.py").write_text("X = {1, 2}\n")
    proj = tmp_path / "proj"
    (proj / "venv" / "inner").mkdir(parents=True)
    (proj / "venv" / "inner" / "v.py").write_text("V = 1\n")
    (proj / "m.py").write_text("Y = 1\n")
    os.utime(proj / "m.py", (1, 1))  # older than 2 s: its bytecode is kept (see the next test)
    monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / "pyc"))
    monkeypatch.setattr(reexec, "precompile_dirs", lambda rootdir: [str(site), str(proj)])
    reexec.precompile("0", str(proj))
    prefix = reexec.pyc_cache_dir("0")
    compiled = [os.path.join(r, f) for r, _, fs in os.walk(prefix) for f in fs if f.endswith(".pyc")]
    assert any(os.sep + "lib1" + os.sep in c for c in compiled)
    assert any(os.path.basename(c).startswith("m.") for c in compiled)
    assert not any(os.path.basename(c).startswith("v.") for c in compiled)


def test_project_bytecode_of_fresh_sources_is_dropped(tmp_path, monkeypatch):
    """A source modified within 2 s of the precompile keeps no cached bytecode: a same-size edit in the same second
    would not change the timestamp pyc's (mtime in seconds, size) and stale code would run."""
    import importlib.util
    import sys
    import time

    proj = tmp_path / "proj"
    proj.mkdir()
    old, fresh = proj / "old.py", proj / "fresh.py"
    old.write_text("X = 10\n")
    fresh.write_text("Y = 10\n")
    t = time.time() - 3600
    os.utime(old, (t, t))
    monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / "pyc"))
    monkeypatch.setattr(reexec, "precompile_dirs", lambda rootdir: [str(proj)])
    reexec.precompile("0", str(proj))
    prefix = reexec.pyc_cache_dir("0")
    monkeypatch.setattr(sys, "pycache_prefix", prefix)
    assert os.path.exists(importlib.util.cache_from_source(str(old)))
    assert not os.path.exists(importlib.util.cache_from_source(str(fresh)))
    os.utime(fresh, (t, t))
    reexec.precompile("0", str(proj))
    assert os.path.exists(importlib.util.cache_from_source(str(fresh)))
