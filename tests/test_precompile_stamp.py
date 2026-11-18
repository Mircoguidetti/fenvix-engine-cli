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
        # the directories the driver is run for: given as directories, or as their stale files on stdin
        files = [os.fsdecode(f) for f in (kw.get("input") or b"").split(b"\0") if f] + list(cmd[3:])
        calls.append(sorted({d for d in (str(site), str(proj)) for f in files
                             if f == d or f.startswith(d + os.sep)}))
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", run)

    def precompile():
        calls.clear()
        reexec.precompile("0", str(proj))
        return [d for c in calls for d in c]

    assert precompile() == [str(site), str(proj)]
    prefix = reexec.pyc_cache_dir("0")
    assert any(f.endswith(".pyc") for _, _, fs in os.walk(prefix + str(site)) for f in fs)
    # unchanged library and project: nothing to compile (the project is checked, in Rust, without a driver process)
    assert precompile() == []
    # a project edit: only the project is compiled
    (proj / "m.py").write_text("Y = 2\n")
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
    assert precompile() == []  # checked again, but every module's pyc holds its source's hash: nothing to compile
    (site / "lib2" / "__init__.py").write_text("Z = 3\n")
    assert precompile() == []  # an in-place edit without an installer: the stamp is unchanged (import checks it)
    os.utime(di / "RECORD", ns=(2, 2))
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


def test_project_bytecode_is_checked_against_the_source_content(tmp_path, monkeypatch):
    """Every cached .pyc is a checked-hash pyc of its source (review R-015 F2/F3): a same-size edit that keeps the
    mtime (restored, foreign or same-second) is compiled again at the next precompile, and the import system, which
    hashes the source before it uses a pyc, never runs the old bytecode in between."""
    import importlib.util
    import sys

    proj = tmp_path / "proj"
    proj.mkdir()
    src = proj / "m.py"
    src.write_text("X = 1\n")
    os.utime(src, (1, 1))
    monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / "pyc"))
    monkeypatch.setattr(reexec, "precompile_dirs", lambda rootdir: [str(proj)])
    reexec.precompile("0", str(proj))
    monkeypatch.setattr(sys, "pycache_prefix", reexec.pyc_cache_dir("0"))
    pyc = importlib.util.cache_from_source(str(src))

    def header():
        with open(pyc, "rb") as fh:
            return fh.read(16)

    h1 = header()
    assert h1[4:8] == (3).to_bytes(4, "little")  # hash-based, checked
    assert h1[8:] == importlib.util.source_hash(src.read_bytes())
    mtime_before = os.stat(pyc).st_mtime_ns
    reexec.precompile("0", str(proj))  # unchanged source: not compiled again
    assert os.stat(pyc).st_mtime_ns == mtime_before
    src.write_text("X = 2\n")
    os.utime(src, (1, 1))
    # before the next precompile: the import system rejects the pyc (source hash) and compiles from source
    probe = subprocess.run([sys.executable, "-c", "import m; print(m.X)"], cwd=proj, capture_output=True, text=True,
                           env={**os.environ, "PYTHONPYCACHEPREFIX": reexec.pyc_cache_dir("0"),
                                "PYTHONDONTWRITEBYTECODE": "1"})
    assert probe.stdout.strip() == "2", probe.stderr
    reexec.precompile("0", str(proj))
    assert header()[8:] == importlib.util.source_hash(src.read_bytes())
