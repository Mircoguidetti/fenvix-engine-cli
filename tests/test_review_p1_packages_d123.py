"""Review R-050 (rows F-09, PY-01, JS-01, Passo 1 packages) of trunk f84dde7: defects as tests that fail there.

D1-D3, copied unchanged from claude/review-p1-packages @ 0119874 (tests/test_review_p1_packages.py); D4 is the
Python leaks session's.

D1 (PY-01): the supported set is CPython 3.12, 3.13, 3.14 (detpy._support.SUPPORTED, the installer's message,
    docs/INSTALL.md "otherwise: install.sh exits 4"), but both guards only refuse versions *below* 3.12: a newer
    CPython (3.15, available today as a pre-release) installs and runs `--det` with no word, untested.
D2 (F-09): `fenvix version` prints "fenvix 0.1.0" for every artifact. It does not name the artifact's build or the
    commit it came from, although the artifact carries both (VERSION, VERSION.json) and install.sh copies
    VERSION.json next to bin/fenvix; two different artifacts are indistinguishable from the command (exam check
    F-09.artifact-identity, gap G-0251, fails on f84dde7).
D3 (F-09): a job that creates its own venv does not get the engine from the runner image: the image's
    `$FENVIX_HOME/bin/fenvix` runs with the job's `python3` and stops with "the Python package fenvix is not
    installed" (exit 127) (exam check F-09.job-venv, gap G-0413, fails on f84dde7; docs/INSTALL.md asks every such job
    to pip-install the wheel itself instead).
D4 (PY-01, every version): two `pytest --det` runs of one unchanged checkout are reported divergent by
    `fenvix verify` (every test, reason "config": input `bytecode` "...rewritten from source in this run (cold rewrite
    cache: N)" vs "precompiled") whenever the tests import a library shipped by a pytest-plugin distribution
    (hypothesis): pytest rewrites that library's modules, the pre-warm (G-0168) covers only the project's own files,
    so the first run in a fresh environment is always "cold". Exam check PY-01.det2 on python-attrs/attrs fails on
    3.12, 3.13 and 3.14 (1330 of 1330 tests diverged; outcomes and fingerprints identical).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _installer_guard() -> str:
    """The interpreter check of release/engine/install.sh, exactly as the installer runs it (`"$py" - <<'PY'`)."""
    src = open(os.path.join(ROOT, "release", "engine", "install.sh")).read()
    m = re.search(r"<<'PY'(?: \|\| rc=\$\?)?\n(.*?)\nPY\n", src, re.S)
    assert m, "interpreter check not found in install.sh"
    return m.group(1)


# A CPython the engine does not list as supported, newer than the newest supported one.
_NEWER = "import sys; _real = sys.version_info; sys.version_info = (3, 15, 0, 'final', 0)"


def test_d1_newer_cpython_than_supported_is_refused_by_the_engine():
    """D1: `detpy._support` must not accept a CPython outside 3.12-3.14 (here 3.15): one sentence, exit 4."""
    sup = os.path.join(ROOT, "python", "detpy", "_support.py")  # pure stdlib: loaded on its own, as detpy does first
    code = (f"{_NEWER}\nimport importlib.util as u\nspec = u.spec_from_file_location('s', {sup!r})\n"
            "s = u.module_from_spec(spec); spec.loader.exec_module(s)\nsys.version_info = _real\n"
            "print(repr(s.PROBLEM))\nsys.exit(0 if s.PROBLEM else 1)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, ("CPython 3.15 is let through by detpy._support (PROBLEM is None), although the "
                               f"supported set is 3.12, 3.13, 3.14: {r.stdout}{r.stderr}")


def test_d1_newer_cpython_than_supported_is_refused_by_the_installer():
    """D1: install.sh's guard says 'needs CPython 3.12, 3.13 or 3.14' and must exit 4 on 3.15."""
    r = subprocess.run([sys.executable, "-c", f"{_NEWER}\n{_installer_guard()}"], capture_output=True, text=True)
    assert r.returncode == 4, f"install.sh's interpreter check accepts CPython 3.15 (exit {r.returncode}) {r.stderr}"


def test_d2_fenvix_version_names_the_installed_artifact(tmp_path):
    """D2: after install.sh (which copies the artifact's VERSION.json to PREFIX), `fenvix version` names the
    artifact: its build and the commit it was built from (the exam's check looks for the commit's first 8 chars)."""
    meta = {"version": "0.1.0", "build": "r4242.f84dde7", "commit": "f84dde74f3a415acc4678b2e0d6f71a03a2c9903",
            "platform": "linux-x86_64", "glibc_min": "2.28", "python": ["3.12", "3.13", "3.14"],
            "node": ["22", "24", "26"], "files": {}}
    (tmp_path / "VERSION.json").write_text(json.dumps(meta))
    (tmp_path / "bin").mkdir()
    env = dict(os.environ, FENVIX_HOME=str(tmp_path))
    env.pop("PYTEST_ADDOPTS", None)
    r = subprocess.run([sys.executable, "-m", "detpy.fenvix", "version"], capture_output=True, text=True, env=env,
                       cwd=str(tmp_path), timeout=120)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert meta["build"] in out and meta["commit"][:8] in out, (
        f"`fenvix version` does not name the installed artifact (build {meta['build']}, commit "
        f"{meta['commit'][:8]}):\n{out}")


def test_d3_a_job_venv_gets_the_engine_from_the_runner_image(tmp_path):
    """D3: the image's `fenvix` (release/fenvix -> $FENVIX_HOME/bin/fenvix) used from a job's own venv that has its
    test tools (pytest) but not the engine: `fenvix python --det` must run the job's tests under the engine."""
    import importlib.util

    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    vpy = str(venv / "bin" / "python")
    site = subprocess.check_output([vpy, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                                   text=True).strip()
    # the job's own test tools: pytest and its dependencies, and nothing of the engine
    tools = tmp_path / "tools"
    tools.mkdir()
    for mod in ("pytest", "_pytest", "pluggy", "iniconfig", "packaging", "pygments", "py"):
        spec = importlib.util.find_spec(mod)
        if spec is None or not spec.origin:
            continue
        src = os.path.dirname(spec.origin) if spec.submodule_search_locations else spec.origin
        os.symlink(src, tools / os.path.basename(src))
    with open(os.path.join(site, "job_tools.pth"), "w") as fh:
        fh.write(str(tools) + "\n")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTHONPATH", "PYTHONHOME")}
    env.update(PATH=f"{venv / 'bin'}:{env.get('PATH', '')}", VIRTUAL_ENV=str(venv))
    pre = subprocess.run([vpy, "-c", "import pytest; import detpy"], capture_output=True, text=True, env=env)
    assert "No module named 'detpy'" in pre.stderr, f"precondition: the job venv has pytest, not the engine: {pre}"
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "test_a.py").write_text("def test_a():\n    assert 1\n")
    image_fenvix = shutil.which("python3", path=env["PATH"]) and os.path.join(ROOT, "release", "fenvix")
    r = subprocess.run([image_fenvix, "python", "-q", "-p", "no:cacheprovider", "--det", "test_a.py"], cwd=proj,
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0 and "1 passed" in r.stdout and "detpy" in r.stdout, (
        f"`fenvix python --det` from a job venv (exit {r.returncode}):\n{r.stdout[-800:]}{r.stderr[-800:]}")
