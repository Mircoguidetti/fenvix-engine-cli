"""Review R-032b F1-F3 on the pytest plugin (the reviewer's W1-W7 scenarios; tests/review_r032b/ has the reviewer's
file unchanged, whose runner-driver cases need claude/all-runners-2's `python -m detpy <runner>`).

Protocol: record with --det-cache; ONE input changes; run with the cache; run fresh. The target must not be reused
when the fresh run fails it; and the change must flip the target in a fresh run. Serial and -n 2 (both tests on one
worker: one xdist_group).
"""

import json
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

G = "import pytest\n\n@pytest.mark.xdist_group('g')\n"

CASES = {
    # F1: state an earlier test left, reached without a static import
    "w1_leaked_mock_patch": ({
        "consts.py": "V = None\n", "data.txt": "v1",
        "test_a.py": "from unittest import mock\n" + G + "def test_a():\n    mock.patch('consts.V', open('data.txt').read()).start()\n",
        "test_b.py": "import consts\n" + G + "def test_b():\n    assert consts.V == 'v1'\n",
    }, {"data.txt": "v2"}, "test_b.py::test_b"),
    "w2_importlib_setattr": ({
        "consts.py": "V = None\n", "data.txt": "v1",
        "test_a.py": "import importlib\n" + G + "def test_a():\n    importlib.import_module('con' + 'sts').V = open('data.txt').read()\n",
        "test_b.py": "import consts\n" + G + "def test_b():\n    assert consts.V == 'v1'\n",
    }, {"data.txt": "v2"}, "test_b.py::test_b"),
    "w2b_dunder_import": ({
        "consts.py": "V = None\n", "data.txt": "v1",
        "test_a.py": G + "def test_a():\n    __import__('con' + 'sts').V = open('data.txt').read()\n",
        "test_b.py": "import consts\n" + G + "def test_b():\n    assert consts.V == 'v1'\n",
    }, {"data.txt": "v2"}, "test_b.py::test_b"),
    "w3_builtins": ({
        "data.txt": "v1",
        "test_a.py": "import builtins\n" + G + "def test_a():\n    builtins.MEMO = open('data.txt').read()\n",
        "test_b.py": G + "def test_b():\n    assert MEMO == 'v1'\n",
    }, {"data.txt": "v2"}, "test_b.py::test_b"),
    "w4_environ": ({
        "data.txt": "v1",
        "test_a.py": "import os\n" + G + "def test_a():\n    os.environ['R032B_X'] = open('data.txt').read()\n",
        "test_b.py": G + "def test_b():\n    assert __import__('os').environ['R032B_X'] == 'v1'\n",
    }, {"data.txt": "v2"}, "test_b.py::test_b"),
    # F2: metadata read without opening the file
    "w5_scandir_entry_stat": ({
        "d/f.txt": "abc",
        "test_t.py": "import os\n\ndef test_t():\n    e = [e for e in os.scandir('d')][0]\n    assert e.stat().st_size == 3\n",
    }, {"d/f.txt": "abcd"}, "test_t.py::test_t"),
    "w6_fstat": ({
        "f.txt": "abc",
        "test_t.py": "import os\n\ndef test_t():\n    fd = os.open('f.txt', os.O_RDONLY)\n    try:\n"
                     "        assert os.fstat(fd).st_size == 3\n    finally:\n        os.close(fd)\n",
    }, {"f.txt": "abcd"}, "test_t.py::test_t"),
    "w6b_stat_size": ({
        "f.txt": "abc",
        "test_t.py": "import os\n\ndef test_t():\n    assert os.stat('f.txt').st_size == 3\n",
    }, {"f.txt": "abcd"}, "test_t.py::test_t"),
    # F3: the C library through ctypes
    "w7_libc_access": ({
        "test_t.py": "import ctypes\n\ndef test_t():\n    libc = ctypes.CDLL('libc.so.6')\n"
                     "    assert libc.access(b'flag.txt', 0) != 0\n",
    }, {"flag.txt": "x"}, "test_t.py::test_t"),
}


def _write(root, files):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def _run(pytester, n, *args):
    out = pytester.path / f"o{n}.json"
    r = pytester.runpytest_subprocess("--det", f"--det-outcomes={out}", "-p", "no:cacheprovider", *args)
    d = json.loads(out.read_text()) if out.exists() else {}
    o = {k: (v["outcome"] if isinstance(v, dict) else v) for k, v in (d.get("outcomes") or {}).items()}
    return r, o, set((d.get("cache") or {}).get("reused_ids", ()))


@pytest.mark.parametrize("mode", ["serial", "n2"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_r032b(pytester, monkeypatch, case, mode):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS",
              "R032B_X"):
        monkeypatch.delenv(k, raising=False)
    files, change, target = CASES[case]
    pytester.makeini("[pytest]\nmarkers =\n    xdist_group: group\n")
    _write(pytester.path, files)
    cache = f"--det-cache={pytester.path / '.c'}"
    par = ("-p", "xdist") + (() if mode == "serial" else ("-n", "2", "--dist", "loadgroup"))
    r0, o0, _ = _run(pytester, 0, cache, *par)
    assert o0.get(target) == "passed", r0.stdout.str()
    _write(pytester.path, change)
    r1, o1, reused = _run(pytester, 1, cache, *par)
    _, fresh, _ = _run(pytester, 2, "-p", "xdist")
    assert fresh.get(target) == "failed", fresh
    assert target not in reused, ("WRONG REUSE", r1.stdout.str())
