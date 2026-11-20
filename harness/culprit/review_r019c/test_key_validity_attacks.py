"""R-019c, item 2: attacks on the round-4 key-validity inference of the red-side check.

Shape of every case (as in ``round4/test_finder_round4.py``): green passes; C breaks ``f`` (the test fails);
L works around C through an input the key does not record (the test passes again); a harmless commit; B takes the
workaround away (the test fails again). The truth (newest transition, plain walk) is B. A finder that infers L
from a failing run's key, because every recorded input is unchanged at L, confirms C (parent passes, C fails) and
names it with confidence. A test that fails here is a confident wrong culprit.

    python -m pytest -p no:cacheprovider harness/culprit/review_r019c   # detpy installed in this interpreter
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "round4"))
sys.path.insert(0, str(HERE.parent / "review_r019"))
sys.path.insert(0, str(HERE.parent))
from test_wrong_culprits import commit, git, new_repo  # noqa: E402
from test_finder_round4 import _find, _truth  # noqa: E402

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
TEST = "from pkg import m\n\ndef test_api():\n    assert m.api(1) == 2\n"
BROKEN = "x + 2"
GOOD = "x + 1"


def _case(tmp_path, src, extra_green, workaround, undo, harmless=None):
    """green -> C (breaks f) -> L (workaround) -> x (harmless) -> B (undo). Returns repo, green, shas, truth."""
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(f=GOOD), "test_m.py": TEST, **extra_green})
    shas = [commit(repo, "C breaks f", {"pkg/m.py": src.format(f=BROKEN)})]
    shas.append(commit(repo, "L workaround", workaround))
    shas.append(commit(repo, "x tidy", harmless or {"README": "a\n"}))
    if callable(undo):
        undo(repo)
        shas.append(commit(repo, "B undoes the workaround"))
    else:
        shas.append(commit(repo, "B undoes the workaround", undo))
    truth = _truth(repo, shas)
    return repo, g0, shas, truth


@pytest.fixture(params=[True, False], ids=["key-validity", "control-no-inference"])
def infer(request):
    """``key-validity``: the round-4 finder as shipped (the finding). ``control-no-inference``: the same history with
    ``infer_keys = False``, so every later commit is replayed: shows the wrong answer comes from the inference."""
    return request.param


def _assert_not_wrong(res, truth, shas):
    named = res["named"]
    label = {s: n for s, n in zip(shas, "CLxB")}
    assert named in (truth, None), (
        f"confident wrong: named {label.get(named, named)} ({named[:10]}), truth {label.get(truth)} "
        f"({truth[:10]}); status {res['status']}, {res['why']}")


# ------------------------------------------------------------------ F1: try-import from a new sys.path entry
def test_f1_try_import_from_a_directory_without_inputs(tmp_path, infer):
    """``pkg/m.py`` adds ``extras/`` to ``sys.path`` and tries ``import fastpath``. ``extras/`` holds only a README
    at every commit, so it is not on the path of any recorded input and its names are not guarded; the failed
    import is not in the key. L adds ``extras/fastpath.py`` with a working ``f``; B removes it. REPORT-4 §6 names
    this shape as UNKNOWN."""
    src = ("import os, sys\n"
           "sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'extras'))\n"
           "try:\n    import fastpath\nexcept ImportError:\n    fastpath = None\n\n\n"
           "def f(x):\n    return {f}\n\n\n"
           "def api(x):\n    return fastpath.f(x) if fastpath else f(x)\n")
    repo, g0, shas, truth = _case(
        tmp_path, src, {"extras/README": "optional accelerators\n"},
        {"extras/fastpath.py": "def f(x):\n    return x + 1\n"},
        lambda repo: git(repo, "rm", "-q", "extras/fastpath.py"))
    assert truth == shas[-1]
    _assert_not_wrong(_find(repo, g0, shas[-1], tmp_path, infer_keys=infer), truth, shas)


# ------------------------------------------------------------------ F2: existence check of a flag file
def test_f2_flag_file_checked_with_exists(tmp_path, infer):
    """``api`` checks ``os.path.exists('flags/compat')`` (a stat, no read). ``flags/`` holds only a README.
    L adds ``flags/compat``; B removes it."""
    src = ("import os\n\nROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n\n\n"
           "def f(x):\n    return {f}\n\n\n"
           "def api(x):\n    if os.path.exists(os.path.join(ROOT, 'flags', 'compat')):\n        return x + 1\n"
           "    return f(x)\n")
    repo, g0, shas, truth = _case(
        tmp_path, src, {"flags/README": "feature flags\n"}, {"flags/compat": ""},
        lambda repo: git(repo, "rm", "-q", "flags/compat"))
    assert truth == shas[-1]
    _assert_not_wrong(_find(repo, g0, shas[-1], tmp_path, infer_keys=infer), truth, shas)


# ------------------------------------------------------------------ F3: a namespace package gets __init__.py
def test_f3_namespace_package_gains_init(tmp_path, infer):
    """``import compat`` resolves to a namespace package (``compat/`` holds only a README). L adds
    ``compat/__init__.py`` defining ``F``; B removes it."""
    src = ("import compat\n\n\ndef f(x):\n    return {f}\n\n\n"
           "def api(x):\n    g = getattr(compat, 'F', None)\n    return g(x) if g else f(x)\n")
    repo, g0, shas, truth = _case(
        tmp_path, src, {"compat/README": "shims\n"}, {"compat/__init__.py": "def F(x):\n    return x + 1\n"},
        lambda repo: git(repo, "rm", "-q", "compat/__init__.py"))
    assert truth == shas[-1]
    _assert_not_wrong(_find(repo, g0, shas[-1], tmp_path, infer_keys=infer), truth, shas)


# ------------------------------------------------------------------ F4: a vendored zip changes content
def _zip_bytes(tmp_path, name, body):
    import io
    import zipfile

    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        zi = zipfile.ZipInfo("vfast.py", date_time=(2020, 1, 1, 0, 0, 0))
        z.writestr(zi, body)
    p = tmp_path / name
    p.write_bytes(b.getvalue())
    return p


def test_f4_vendored_zip_changes(tmp_path, infer):
    """``pkg/m.py`` imports ``vfast`` from ``vendor/lib.zip`` (zipimport). The zip exists at every commit; L
    replaces it with one whose ``ADJ`` works around C; B restores it. Is the zip a recorded input?"""
    z0 = _zip_bytes(tmp_path, "z0.zip", "ADJ = 0\n")
    z1 = _zip_bytes(tmp_path, "z1.zip", "ADJ = -1\n")
    src = ("import os, sys\n"
           "sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "
           "'vendor', 'lib.zip'))\nimport vfast\n\n\n"
           "def f(x):\n    return {f}\n\n\ndef api(x):\n    return f(x) + vfast.ADJ\n")

    def put(z):
        def w(repo):
            (repo / "vendor").mkdir(exist_ok=True)
            shutil.copy(z, repo / "vendor" / "lib.zip")
        return w

    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(f=GOOD), "test_m.py": TEST})
    put(z0)(repo)
    g0 = commit(repo, "green + vendor")
    shas = [commit(repo, "C breaks f", {"pkg/m.py": src.format(f=BROKEN)})]
    put(z1)(repo)
    shas.append(commit(repo, "L vendored zip works around"))
    shas.append(commit(repo, "x tidy", {"README": "a\n"}))
    put(z0)(repo)
    shas.append(commit(repo, "B restores the zip"))
    truth = _truth(repo, shas)
    assert truth == shas[-1]
    _assert_not_wrong(_find(repo, g0, shas[-1], tmp_path, infer_keys=infer), truth, shas)


# ------------------------------------------------------------------ F5: a C library changes content
def _so(tmp_path, name, value):
    c = tmp_path / f"{name}.c"
    c.write_text(f"int adj(void) {{ return {value}; }}\n")
    out = tmp_path / f"{name}.so"
    subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(out), str(c)], check=True)
    return out


@pytest.mark.skipif(shutil.which("gcc") is None, reason="needs gcc")
def test_f5_native_library_changes(tmp_path, infer):
    """``pkg/m.py`` loads ``pkg/_native.so`` with ctypes (``dlopen``, not a Python read). The library exists at
    every commit, so ``pkg/`` names never change; L replaces it with one that works around C; B restores it."""
    s0, s1 = _so(tmp_path, "n0", 0), _so(tmp_path, "n1", -1)
    src = ("import ctypes, os\n_lib = ctypes.CDLL(os.path.join(os.path.dirname(os.path.abspath(__file__)), "
           "'_native.so'))\n\n\ndef f(x):\n    return {f}\n\n\ndef api(x):\n    return f(x) + _lib.adj()\n")

    def put(s):
        def w(repo):
            shutil.copy(s, repo / "pkg" / "_native.so")
        return w

    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(f=GOOD), "test_m.py": TEST})
    put(s0)(repo)
    g0 = commit(repo, "green + native")
    shas = [commit(repo, "C breaks f", {"pkg/m.py": src.format(f=BROKEN)})]
    put(s1)(repo)
    shas.append(commit(repo, "L native lib works around"))
    shas.append(commit(repo, "x tidy", {"README": "a\n"}))
    put(s0)(repo)
    shas.append(commit(repo, "B restores the lib"))
    truth = _truth(repo, shas)
    assert truth == shas[-1]
    _assert_not_wrong(_find(repo, g0, shas[-1], tmp_path, infer_keys=infer), truth, shas)


# ------------------------------------------------------------------ F6: pytest.ini next to the test (tried)
def test_f6_ini_in_the_test_directory(tmp_path, infer):
    """The test lives in ``tests/``; L adds ``tests/pytest.ini`` (it becomes the inifile, ``filterwarnings``
    ignores the warning the broken ``f`` raises as an error via the root ini); B removes it. Expected to be
    caught by the directory-names guard (``tests/`` is on the test's path)."""
    src = ("import warnings\n\n\ndef f(x):\n    if {f} != x + 1:\n        warnings.warn('drift', UserWarning)\n"
           "    return x + 1\n\n\ndef api(x):\n    return f(x)\n")
    repo, g0 = new_repo(tmp_path, {"pytest.ini": "[pytest]\nfilterwarnings = error\n",
                                   "pkg/m.py": src.format(f=GOOD), "tests/test_m.py": TEST})
    shas = [commit(repo, "C breaks f", {"pkg/m.py": src.format(f=BROKEN)}),
            commit(repo, "L tests/pytest.ini", {"tests/pytest.ini": "[pytest]\npythonpath = ..\n"}),
            commit(repo, "x tidy", {"README": "a\n"})]
    git(repo, "rm", "-q", "tests/pytest.ini")
    shas.append(commit(repo, "B removes it"))
    nid = "tests/test_m.py::test_api"
    truth = _truth(repo, shas, nid)
    if truth != shas[-1]:
        pytest.skip(f"construction: truth is not B ({truth[:10]})")
    _assert_not_wrong(_find(repo, g0, shas[-1], tmp_path, nid=nid, infer_keys=infer), truth, shas)
