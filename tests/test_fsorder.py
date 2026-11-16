"""Point 4: normalised filesystem order."""

import os

from detpy import fsorder

FS_TESTS = """
import glob, os, pathlib
NAMES = ["zeta", "Alpha", "mid", "beta", "_x", "0num", "omega", "kappa"]

def make(tmp_path):
    for n in NAMES:
        (tmp_path / n).mkdir()
        (tmp_path / n / "f.txt").write_text(n)
    return sorted(NAMES)

def test_listdir(tmp_path):
    exp = make(tmp_path)
    assert os.listdir(tmp_path) == exp

def test_scandir(tmp_path):
    exp = make(tmp_path)
    with os.scandir(tmp_path) as it:
        assert [e.name for e in it] == exp
    assert [e.name for e in os.scandir(tmp_path)] == exp

def test_walk(tmp_path):
    exp = make(tmp_path)
    top, dirs, files = next(os.walk(tmp_path))
    assert dirs == exp

def test_glob(tmp_path):
    exp = make(tmp_path)
    assert [os.path.basename(os.path.dirname(p)) for p in glob.glob(str(tmp_path / "*" / "f.txt"))] == exp
    assert list(glob.iglob(str(tmp_path / "*"))) == [str(tmp_path / n) for n in exp]

def test_pathlib(tmp_path):
    exp = make(tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == exp
    assert [p.parent.name for p in tmp_path.glob("*/f.txt")] == exp
    assert [p.parent.name for p in tmp_path.rglob("f.txt")] == exp
"""


def test_fs_apis_are_sorted(pytester, run_det):
    pytester.makepyfile(test_fs=FS_TESTS)
    result, (_, tests, _) = run_det()
    result.assert_outcomes(passed=5)
    events = tests["test_fs.py::test_listdir"]["events"]
    fs = [e for e in events if e["s"] == "fs"]
    assert len(fs) == 1  # pytest's own tmp_path bookkeeping is not recorded
    assert fs[0]["o"] == "os.listdir" and fs[0]["at"] == "test_fs.py:12"
    # Paths are normalised: no run-specific temporary directory in the value.
    assert fs[0]["v"].startswith("<basetemp>/test_listdir0|8|")


def test_fs_fingerprints_stable_across_runs(pytester, run_det):
    pytester.makepyfile(test_fs=FS_TESTS)
    _, (_, a, _) = run_det()
    _, (_, b, _) = run_det()
    assert {k: v["fingerprint"] for k, v in a.items()} == {k: v["fingerprint"] for k, v in b.items()}


def test_sorting_does_not_rely_on_the_filesystem(monkeypatch, tmp_path):
    """Unit test: even if the OS returns entries in reverse order they come back sorted."""
    for n in "cab":
        (tmp_path / n).write_text(n)
    real_listdir, real_scandir = os.listdir, os.scandir

    class Rev:
        def __init__(self, path):
            self.entries = sorted(real_scandir(path), key=lambda e: e.name, reverse=True)

        def __iter__(self):
            return iter(self.entries)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(fsorder, "_real_listdir", lambda p=".": sorted(real_listdir(p), reverse=True))
    monkeypatch.setattr(fsorder, "_real_scandir", Rev)
    assert fsorder.listdir(tmp_path) == ["a", "b", "c"]
    with fsorder.scandir(tmp_path) as it:
        assert [e.name for e in it] == ["a", "b", "c"]
