"""Rows F-10 (install), F-09 (platforms), PY-01 (Python versions): the package `fenvix`, its interpreter guard, its
`fenvix` command, one version everywhere, and the per-OS observation layer (detpy_core::host) the shells use.

Audit gaps closed here (regression tests named after the family they close):
* G-0547, G-0548, G-0549, G-0550, G-0551, G-0556, G-0470, G-0471, G-2219: an interpreter below 3.12 never crashes;
  it gets one message and exit code 4 from pytest, `python -m detpy`, the `detpy` and `fenvix` commands.
* G-0553, G-0555, G-0557, G-1576 (free-threaded), G-0554 (PyPy): refused with the same message.
* G-0170, G-0248, G-0521, G-0737: the distribution is `fenvix`; a foreign distribution writing `detpy/` is reported.
* G-0732, G-2193, G-2212, G-2213: one version, licence file, metadata.
* G-0155, G-0156, G-0158: loaded images and child processes are observed through detpy_core::host on Linux and
  macOS (never read as "nothing" when /proc is absent).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Each fake changes what detpy._support sees, imports detpy (which decides once, at import, and swaps in the
# inactive plugin), then restores the interpreter's real values before pytest or a command runs: pytest itself never
# sees a fake version (it has version-dependent code paths of its own).
_FAKES = {
    "3.11": ("import sys; _real = sys.version_info; sys.version_info = (3, 11, 9, 'final', 0)",
             "sys.version_info = _real"),
    "3.9": ("import sys; _real = sys.version_info; sys.version_info = (3, 9, 25, 'final', 0)",
            "sys.version_info = _real"),
    "free-threaded": ("import sys, sysconfig; _g = sysconfig.get_config_var; "
                      "sysconfig.get_config_var = lambda n: 1 if n == 'Py_GIL_DISABLED' else _g(n)",
                      "sysconfig.get_config_var = _g"),
    "pypy": ("import sys, types; _real = sys.implementation; "
             "sys.implementation = types.SimpleNamespace(**{**vars(_real), 'name': 'pypy'})",
             "sys.implementation = _real"),
}
FAKE = {k: f"{a}\nimport detpy\n{b}\nassert detpy._support.PROBLEM" for k, (a, b) in _FAKES.items()}


def _run(code: str, cwd, env_extra=None):
    env = dict(os.environ, **(env_extra or {}))
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run([sys.executable, "-c", code], cwd=cwd, capture_output=True, text=True, env=env, timeout=300)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "test_a.py").write_text("def test_a():\n    assert 1\n")
    return tmp_path


@pytest.mark.parametrize("kind", ["3.11", "3.9", "free-threaded", "pypy"])
def test_unsupported_interpreter_pytest_det_refused_with_message_not_crash(kind, project):
    """G-0547/G-0548/G-0556 family: `pytest --det` on an unsupported interpreter: usage error 4 and one sentence."""
    code = FAKE[kind] + "\nimport pytest, sys\nsys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', '--det', 'test_a.py']))"
    r = _run(code, project)
    out = r.stdout + r.stderr
    assert r.returncode == 4, out
    assert "fenvix" in out and ("3.12" in out or "free-threaded" in out or "CPython only" in out), out
    assert "Traceback" not in out and "AttributeError" not in out and "INTERNALERROR" not in out, out


@pytest.mark.parametrize("opt", ["--det-isolate", "--det-cache=.c", "-n 2 --det"])
def test_unsupported_interpreter_other_det_options_refused(opt, project):
    """G-0550, G-0551, G-0552: --det-isolate, --det-cache and xdist under --det: the same message, no INTERNALERROR."""
    args = opt.split()
    code = FAKE["3.11"] + f"\nimport pytest, sys\nsys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', *{args!r}, 'test_a.py']))"
    r = _run(code, project)
    out = r.stdout + r.stderr
    if "-n" in args and "unrecognized arguments: -n" in out:
        pytest.fail("pytest-xdist must be installed in the gate (G-0010)")
    assert r.returncode == 4, out
    assert "needs CPython 3.12" in out and "INTERNALERROR" not in out, out


def test_unsupported_interpreter_plain_pytest_unchanged(project):
    """An installed but unsupported plugin never breaks a run that does not ask for the engine."""
    code = FAKE["3.11"] + "\nimport pytest, sys\nsys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', 'test_a.py']))"
    r = _run(code, project)
    assert r.returncode == 0 and "1 passed" in r.stdout, r.stdout + r.stderr


def test_unsupported_interpreter_det_from_addopts_refused(project):
    code = FAKE["3.11"] + "\nimport pytest, sys\nsys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', 'test_a.py']))"
    env = dict(os.environ, PYTEST_ADDOPTS="--det")
    r = subprocess.run([sys.executable, "-c", code], cwd=project, capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 4 and "needs CPython 3.12" in r.stdout + r.stderr, r.stdout + r.stderr


@pytest.mark.parametrize("entry", [
    "import runpy; runpy.run_module('detpy', run_name='__main__')",          # python -m detpy unittest --det
    "from detpy.cli import main; main()",                                     # the `detpy` console script
    "import sys; from detpy.fenvix_cli import main; sys.exit(main())",        # `fenvix python --det`
])
def test_unsupported_interpreter_commands_refused(entry, project):
    """G-0549, G-0471: `python -m detpy <runner> --det` and the console scripts: message and exit 4."""
    argv = "['x', 'python', '--det']" if "fenvix_cli" in entry else "['x', 'unittest', '--det']"
    code = FAKE["3.9"] + f"\nimport sys; sys.argv = {argv}\n" + entry
    r = _run(code, project)
    out = r.stdout + r.stderr
    assert r.returncode == 4, out
    assert "needs CPython 3.12" in out and "Traceback" not in out, out


def test_support_problem_none_here():
    from detpy import _support

    assert _support.PROBLEM is None


def test_install_metadata_refuses_old_python_and_names_fenvix():
    """G-0170/G-0248/G-0521, G-0547 (install side): the distribution is `fenvix`, Requires-Python >=3.12, the
    native module is built for the 3.12 stable ABI (pip on 3.11 cannot pick the wheel; PyPI tells it why)."""
    meta = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))
    p = meta["project"]
    assert p["name"] == "fenvix" and p["name"] != "detpy"
    assert p["requires-python"] == ">=3.12"
    assert "fenvix" in p["scripts"] and p["entry-points"]["pytest11"] == {"detpy": "detpy.plugin"}
    assert any("3.12" in c for c in p["classifiers"]) and any("3.14" in c for c in p["classifiers"])
    cargo = open(os.path.join(ROOT, "crates", "detpy-py", "Cargo.toml")).read()
    assert '"abi3-py312"' in cargo and "abi3-py39" not in cargo
    assert os.path.exists(os.path.join(ROOT, "LICENSE")) and p.get("license-files") == ["LICENSE"]


def test_one_version_everywhere():
    """G-0732, G-2193: Cargo.toml, the Python package and the npm package carry one version."""
    r = subprocess.run([sys.executable, os.path.join(ROOT, "release", "version.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    import detpy

    assert detpy.__version__ == r.stdout.strip()
    assert json.load(open(os.path.join(ROOT, "node", "package.json")))["version"] == detpy.__version__


def test_fenvix_command_version_and_doctor(capsys):
    from detpy import fenvix_cli
    import detpy

    assert fenvix_cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"fenvix {detpy.__version__}"
    assert fenvix_cli.main(["doctor"]) == 0, capsys.readouterr().out


def test_foreign_detpy_distribution_reported(tmp_path, monkeypatch):
    """G-0170, G-0737: another distribution that installs the import package `detpy/` is named by `fenvix doctor`."""
    di = tmp_path / "detpy-2.0.0.dist-info"
    di.mkdir()
    (di / "METADATA").write_text("Metadata-Version: 2.1\nName: detpy\nVersion: 2.0.0\n")
    (di / "top_level.txt").write_text("detpy\n")
    (di / "RECORD").write_text("detpy/DETAlgs/__init__.py,,\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    from detpy import fenvix_cli

    assert fenvix_cli.foreign_detpy_owners() == ["detpy 2.0.0"]
    rows = dict((n, (ok, d)) for n, ok, d in fenvix_cli.doctor())
    assert rows["import package detpy"][0] is False and "detpy 2.0.0" in rows["import package detpy"][1]


def test_host_loaded_images_and_children_observed():
    """G-0155/G-0156/G-0158 family: the process's loaded images come from the OS (maps or dyld), never empty."""
    from detpy import _core

    imgs = _core.loaded_images()
    assert imgs, "no loaded-image list on a supported OS"
    assert any(os.path.basename(p).startswith("_core") for p in imgs), imgs[:20]
    if sys.platform == "darwin":
        assert _core.cpu_features().startswith("brand=")


def test_children_alive_seen_by_virtual_clock():
    from detpy import _core

    assert _core.clock_children_alive() is False
    p = subprocess.Popen(["sleep", "5"])
    try:
        assert _core.clock_children_alive() is True
    finally:
        p.kill()
        p.wait()


def test_no_hard_coded_linux_x64_in_install_paths():
    """G-0478, G-0496, G-0497, G-0240 family: no installer or build script names one OS/arch's file."""
    bad = re.compile(r"detjs\.linux-x64\.node|libfenvix_jvm\.so\"\s+\"\$stage|linux_x86_64")
    for rel in ("release/install-image.sh", "jvm/build.sh", "node/src/native.js", "node/scripts/build.js",
                "release/npm/pack.py", ".github/workflows/packages.yml"):
        text = open(os.path.join(ROOT, rel)).read()
        assert not bad.search(text), (rel, bad.search(text).group(0))


def test_pytest_floor_excludes_versions_that_break_det():
    """G-0529 (pytest 7.0-7.2: INTERNALERROR on cache reuse), G-0171 (pytest 7.0-8.0: --det-isolate errors every
    unittest class): the package requires pytest 8.1+."""
    meta = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))
    assert meta["project"]["dependencies"] == ["pytest>=8.1"]
    assert meta["project"]["optional-dependencies"]["xdist"] == ["pytest-xdist>=3.7"]


def test_old_xdist_refused_with_usage_error(monkeypatch):
    """G-0530: pytest-xdist < 3.7 under --det -n: a usage error naming the version, not an INTERNALERROR."""
    import importlib.metadata as md

    from detpy import xdist as dx

    real = md.version
    monkeypatch.setattr(md, "version", lambda n: "3.5.0" if n == "pytest-xdist" else real(n))
    with pytest.raises(pytest.UsageError, match=r"pytest-xdist 3\.7 or newer \(installed: 3\.5\.0\)"):
        dx.require_version()
    monkeypatch.setattr(md, "version", lambda n: "3.8.0" if n == "pytest-xdist" else real(n))
    dx.require_version()


def test_release_workflow_uses_trusted_publishing_with_the_configured_names():
    """F-10: the PyPI trusted publisher the founder configured (project fenvix, workflow release.yml, environment
    pypi) must keep matching; publishing uses OIDC only: no stored token, no TestPyPI."""
    path = os.path.join(ROOT, ".github", "workflows", "release.yml")
    text = open(path).read()
    assert os.path.basename(path) == "release.yml"
    assert re.search(r"(?m)^  pypi:\n(?:    .*\n)*?    environment: pypi\n", text), "pypi job must use environment pypi"
    assert text.count("id-token: write") >= 2 and "pypa/gh-action-pypi-publish" in text
    assert "${{ secrets." not in text and "password" not in text.lower() and "NPM_TOKEN" not in text
    assert "test.pypi.org" not in text and "testpypi" not in text.lower()
    meta = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))
    assert meta["project"]["name"] == "fenvix"
