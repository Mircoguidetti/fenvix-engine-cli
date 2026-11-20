"""Review R-008, second round: holes in the code the R-008 fixes added.

FIX 1 and FIX 2 key the site directories (``site_tree``) and the other import-path entries (``extra_paths``) by
walking them with ``os.walk``, which does not descend into symlinked directories. The import system does follow
them, so a package that is a symlinked directory is imported but not keyed. Each test first proves that behaviour
really differs between the two "machines", then asserts that the identity differs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from test_review_r008 import _two_machines, run  # noqa: F401
from test_runtime_id import identity, site_packages, venv
from test_shared_cache import service  # noqa: F401

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux identity")
_CLIENT_NOT_PORTED = pytest.mark.skip(
    reason='shared-cache Python client not yet ported onto the Rust proof cache (claude/rust-hotpaths-2)')


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "project"
    r.mkdir()
    return r


def _versions(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """Two releases of a package, side by side (a deploy tree, a monorepo, a vendored checkout)."""
    out = []
    for v in (1, 2):
        d = tmp_path / "releases" / f"{name}-{v}" / name
        d.mkdir(parents=True)
        (d / "__init__.py").write_text(f"VALUE = {v}\n")
        out.append(d)
    return out[0], out[1]


def test_hole_symlinked_package_directory_on_an_import_path(tmp_path, root):
    """PYTHONPATH names a directory outside project, stdlib and site (FIX 2); in it, the package is a symlink to
    the release directory (``helper -> releases/helper-1/helper``). The machines differ in the release."""
    py = venv(tmp_path / "m")
    ext = tmp_path / "shared-libs"
    ext.mkdir()
    v1, v2 = _versions(tmp_path, "helper")
    env = {"PYTHONPATH": f"{Path(__file__).resolve().parents[1] / 'python'}:{ext}"}
    (ext / "helper").symlink_to(v1)
    out1, a = run(py, "import helper; print(helper.VALUE)", env), identity(py, root, env)
    (ext / "helper").unlink()
    (ext / "helper").symlink_to(v2)
    out2, b = run(py, "import helper; print(helper.VALUE)", env), identity(py, root, env)
    assert (out1, out2) == ("1", "2")
    assert a["digest"] != b["digest"], "same identity although `import helper` gives 1 on one machine and 2 on the other"


def test_hole_symlinked_package_directory_in_site_packages(tmp_path, root):
    """FIX 1's site tree: a package in site-packages that is a symlinked directory (no dist-info, as in the first
    round's unowned-package test)."""
    py1, py2 = venv(tmp_path / "m1"), venv(tmp_path / "m2")
    v1, v2 = _versions(tmp_path, "vendored")
    (site_packages(py1) / "vendored").symlink_to(v1)
    (site_packages(py2) / "vendored").symlink_to(v2)
    assert run(py1, "import vendored; print(vendored.VALUE)") == "1"
    assert run(py2, "import vendored; print(vendored.VALUE)") == "2"
    a, b = identity(py1, root), identity(py2, root)
    assert a["digest"] != b["digest"], "same identity although `import vendored` gives different values"


@_CLIENT_NOT_PORTED
@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_e2e_wrong_reuse_symlinked_package_on_an_import_path(service, pytester, tmp_path, monkeypatch):
    """End to end through the service: machine 1 and machine 2 have the same PYTHONPATH directory; its ``helper``
    symlink points at release 1 on machine 1 and at release 2 on machine 2."""
    svc, t = service
    ext = tmp_path / "shared-libs"
    ext.mkdir()
    v1, v2 = _versions(tmp_path, "helper")
    (ext / "helper").symlink_to(v1)
    pp = os.pathsep.join(x for x in [str(ext), os.environ.get("PYTHONPATH", "")] if x)
    files = {"test_h.py": "import helper\n\ndef test_value():\n    assert helper.VALUE == 1\n"}

    def deploy_release_2():
        (ext / "helper").unlink()
        (ext / "helper").symlink_to(v2)

    reused, real, _ = _two_machines(pytester, tmp_path, monkeypatch, (svc, t["a"]), files, {"PYTHONPATH": pp},
                                    {"PYTHONPATH": pp}, before_2=deploy_release_2)
    assert real["test_h.py::test_value"] == "failed"
    assert reused["test_h.py::test_value"] == "failed", "machine 2 reused 'passed' from the service"



def _sourceless(directory: Path, name: str, value: int) -> None:
    """``name.pyc`` with no ``name.py`` next to it: imported by the sourceless loader (vendor SDKs shipped as
    bytecode only, compiled deploy trees)."""
    import py_compile

    src = directory / f"{name}.py"
    src.write_text(f"VALUE = {value}\n")
    py_compile.compile(str(src), cfile=str(directory / f"{name}.pyc"), doraise=True)
    src.unlink()


def test_hole_sourceless_module_on_an_import_path(tmp_path, root):
    """The FIX 2 walker drops every ``.pyc``; outside ``__pycache__`` a ``.pyc`` is the module itself."""
    py = venv(tmp_path / "m")
    ext = tmp_path / "shared-libs"
    ext.mkdir()
    env = {"PYTHONPATH": f"{Path(__file__).resolve().parents[1] / 'python'}:{ext}"}
    _sourceless(ext, "helper", 1)
    out1, a = run(py, "import helper; print(helper.VALUE)", env), identity(py, root, env)
    _sourceless(ext, "helper", 2)
    out2, b = run(py, "import helper; print(helper.VALUE)", env), identity(py, root, env)
    assert (out1, out2) == ("1", "2")
    assert a["digest"] != b["digest"], "same identity although `import helper` gives 1 on one machine and 2 on the other"


def test_hole_sourceless_module_in_site_packages(tmp_path, root):
    """The FIX 1 site tree drops every ``.pyc`` too (no dist-info, as in the first round's unowned-package test)."""
    py1, py2 = venv(tmp_path / "m1"), venv(tmp_path / "m2")
    _sourceless(site_packages(py1), "vendored", 1)
    _sourceless(site_packages(py2), "vendored", 2)
    assert run(py1, "import vendored; print(vendored.VALUE)") == "1"
    assert run(py2, "import vendored; print(vendored.VALUE)") == "2"
    a, b = identity(py1, root), identity(py2, root)
    assert a["digest"] != b["digest"], "same identity although `import vendored` gives different values"
