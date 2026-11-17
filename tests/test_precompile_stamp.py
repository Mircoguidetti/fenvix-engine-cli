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
        calls.append([c for c in cmd if c in (str(site), str(proj))])
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    reexec.precompile("0", str(proj))
    assert calls[-1] == [str(site), str(proj)]
    prefix = reexec.pyc_cache_dir("0")
    assert any(f.endswith(".pyc") for _, _, fs in os.walk(prefix + str(site)) for f in fs)
    # unchanged library: only the project is checked
    reexec.precompile("0", str(proj))
    assert calls[-1] == [str(proj)]
    # an installer adds a package (or rewrites a dist-info RECORD): the library is checked again
    (site / "lib2").mkdir()
    (site / "lib2" / "__init__.py").write_text("Z = 1\n")
    reexec.precompile("0", str(proj))
    assert calls[-1] == [str(site), str(proj)]
    di = site / "lib2-1.0.dist-info"
    di.mkdir()
    (di / "RECORD").write_text("a\n")
    reexec.precompile("0", str(proj))
    reexec.precompile("0", str(proj))
    assert calls[-1] == [str(proj)]
    os.utime(di / "RECORD", ns=(1, 1))
    reexec.precompile("0", str(proj))
    assert calls[-1] == [str(site), str(proj)]
