"""Review R-032b (claude/all-runners-2): wrong-reuse attacks on the Python runner drivers on the Rust engine.

Same protocol as tests/review_r032: run 1 records with --det-cache; ONE input changes; run 2 with the cache; run 3
fresh (no cache). A wrong reuse = the target is reused in run 2 although the fresh run fails it. Each scenario also
asserts that the change flips the target in a fresh run (else it proves nothing).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runners_util import run, write  # noqa: E402

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def scenario(tmp_path, files, mutate, runner="unittest", args=()):
    root = tmp_path / "p"
    write(root, files)
    first = run(runner, root, *args)
    mutate(root)
    second = run(runner, root, *args)
    fresh = run(runner, root, *args, cache=False)
    return first, second, fresh


def check(first, second, fresh, part):
    ids = [i for i in first.outcomes if part in i]
    assert ids, first
    t = ids[0]
    assert first.outcomes[t] == "passed", first
    assert fresh.outcomes.get(t) in ("failed", "error"), ("the change does not flip the test", fresh)
    assert t not in second.reused, ("WRONG REUSE: reused 'passed', fresh run fails", second, fresh)


# --- carried-set rule: state an earlier test left, reached without a static import -----------------------------------

# W1: a leaked unittest.mock patch by dotted name (patch(...).start() without stop: a classic order-dependent test).
#     test_a patches consts.V with a file's content; test_b imports consts (which imports nothing) and checks V.
#     test_a's executed repository file references unittest.mock (a library), not consts: no static path joins them.
W1 = {
    "consts.py": "V = None\n",
    "data.txt": "v1",
    "test_a.py": "import unittest\nfrom unittest import mock\n\nclass A(unittest.TestCase):\n"
                 "    def test_a(self):\n        mock.patch('consts.V', open('data.txt').read()).start()\n",
    "test_b.py": "import unittest\nimport consts\n\nclass Target(unittest.TestCase):\n"
                 "    def test_b(self):\n        self.assertEqual(consts.V, 'v1')\n",
}


@pytest.mark.parametrize("runner", ["unittest", "nose2"])
def test_w1_leaked_mock_patch_by_name(tmp_path, runner):
    if runner == "nose2":
        pytest.importorskip("nose2")
    f, s, fr = scenario(tmp_path, W1, lambda r: write(r, {"data.txt": "v2"}), runner=runner)
    check(f, s, fr, "Target")


def _pytest_run(root, cache):
    import json
    import subprocess
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--det"]
    if cache:
        args.append(f"--det-cache={root.parent / 'pc'}")
    p = subprocess.run(args + ["-rA"], cwd=root, capture_output=True, text=True)
    out = {}
    for line in p.stdout.splitlines():
        for k in ("PASSED", "FAILED", "ERROR"):
            if line.startswith(k + " "):
                out[line.split()[1]] = k.lower()
    reused = set()
    rc = root.parent / "pc" / "receipts.jsonl"
    if cache and rc.exists():
        for line in rc.read_text().splitlines():
            r = json.loads(line)
            if r.get("reused"):
                reused.add(r["nodeid"])
    return out, reused, p.stdout


@pytest.mark.parametrize("files", [W1], ids=["W1"])
def test_w1_pytest_plugin(tmp_path, files):
    root = tmp_path / "p"
    write(root, {k: v.replace("(unittest.TestCase)", "").replace("class Target", "class TestTarget")
                      .replace("class A:", "class TestA:").replace("self.assertEqual(consts.V, 'v1')", "assert consts.V == 'v1'")
                      .replace("import unittest\nimport consts", "import consts")
                  for k, v in files.items()})
    target = "test_b.py::TestTarget::test_b"
    o1, _, _ = _pytest_run(root, True)
    assert o1.get(target) == "passed", o1
    write(root, {"data.txt": "v2"})
    o2, r2, out2 = _pytest_run(root, True)
    o3, _, _ = _pytest_run(root, False)
    assert o3.get(target) == "failed", o3
    assert target not in r2, ("WRONG REUSE under the pytest plugin", out2)


# W2: sys.modules / importlib by name: test_a sets an attribute of a repository module it reaches by a string
W2 = {
    "consts.py": "V = None\n",
    "data.txt": "v1",
    "test_a.py": "import unittest, importlib\n\nclass A(unittest.TestCase):\n"
                 "    def test_a(self):\n        importlib.import_module('con' + 'sts').V = open('data.txt').read()\n",
    "test_b.py": "import unittest\nimport consts\n\nclass Target(unittest.TestCase):\n"
                 "    def test_b(self):\n        self.assertEqual(consts.V, 'v1')\n",
}


def test_w2_module_attribute_set_by_name(tmp_path):
    f, s, fr = scenario(tmp_path, W2, lambda r: write(r, {"data.txt": "v2"}))
    check(f, s, fr, "Target")


# W3: builtins as the channel: test_b imports nothing but unittest (infrastructure) and reads a builtin name that
#     test_a set from a file
W3 = {
    "data.txt": "v1",
    "test_a.py": "import unittest, builtins\n\nclass A(unittest.TestCase):\n"
                 "    def test_a(self):\n        builtins.MEMO = open('data.txt').read()\n",
    "test_b.py": "import unittest\n\nclass Target(unittest.TestCase):\n"
                 "    def test_b(self):\n        self.assertEqual(MEMO, 'v1')\n",
}


def test_w3_builtins_channel(tmp_path):
    f, s, fr = scenario(tmp_path, W3, lambda r: write(r, {"data.txt": "v2"}))
    check(f, s, fr, "Target")


# W4: os.environ as the channel: test_a exports a file's content; test_b reads the variable through __import__
W4 = {
    "data.txt": "v1",
    "test_a.py": "import unittest, os\n\nclass A(unittest.TestCase):\n"
                 "    def test_a(self):\n        os.environ['R032B_X'] = open('data.txt').read()\n",
    "test_b.py": "import unittest\n\nclass Target(unittest.TestCase):\n"
                 "    def test_b(self):\n        self.assertEqual(__import__('os').environ['R032B_X'], 'v1')\n",
}


def test_w4_environ_channel(tmp_path):
    f, s, fr = scenario(tmp_path, W4, lambda r: write(r, {"data.txt": "v2"}))
    check(f, s, fr, "Target")


# --- absent inputs / metadata the wrappers do not see ---------------------------------------------------------------

# W5: os.DirEntry.stat() (scandir): the size of a file, read without opening it and without os.stat
def test_w5_scandir_entry_stat_size(tmp_path):
    files = {
        "d/f.txt": "abc",
        "test_t.py": "import unittest, os\n\nclass Target(unittest.TestCase):\n"
                     "    def test_t(self):\n        e = [e for e in os.scandir('d')][0]\n"
                     "        self.assertEqual(e.stat().st_size, 3)\n",
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"d/f.txt": "abcd"}))
    check(f, s, fr, "Target")


# W6: os.fstat on an os.open'd descriptor: size without reading
def test_w6_fstat_size_without_read(tmp_path):
    files = {
        "f.txt": "abc",
        "test_t.py": "import unittest, os\n\nclass Target(unittest.TestCase):\n"
                     "    def test_t(self):\n        fd = os.open('f.txt', os.O_RDONLY)\n"
                     "        try:\n            self.assertEqual(os.fstat(fd).st_size, 3)\n"
                     "        finally:\n            os.close(fd)\n",
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"f.txt": "abcd"}))
    check(f, s, fr, "Target")


# W7: libc access() through ctypes (the C library, not a project .so): an absent file appears
def test_w7_libc_access_via_ctypes(tmp_path):
    files = {
        "test_t.py": "import unittest, ctypes, ctypes.util\n\nclass Target(unittest.TestCase):\n"
                     "    def test_t(self):\n        libc = ctypes.CDLL('libc.so.6')\n"
                     "        self.assertNotEqual(libc.access(b'flag.txt', 0), 0)\n",
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"flag.txt": "x"}))
    check(f, s, fr, "Target")


# W8: pathlib.Path.exists / is_file (Python 3.13: own implementation, through os.stat?)
@pytest.mark.parametrize("call", ["exists()", "is_file()", "stat().st_size == 0"])
def test_w8_pathlib_probe(tmp_path, call):
    neg = "assertFalse" if call != "stat().st_size == 0" else "assertTrue"
    files = {
        "f0.txt": "",
        "test_t.py": "import unittest, pathlib\n\nclass Target(unittest.TestCase):\n"
                     f"    def test_t(self):\n        self.{neg}(pathlib.Path('{'f0.txt' if 'stat' in call else 'flag.txt'}').{call})\n",
    }
    mut = (lambda r: write(r, {"f0.txt": "x"})) if "stat" in call else (lambda r: write(r, {"flag.txt": "x"}))
    f, s, fr = scenario(tmp_path, files, mut)
    check(f, s, fr, "Target")


# W9: a reference to os.path.exists bound before the session (stored in a default argument of a function in a
#     module the test imports: rebinding module dicts does not reach it). The helper is imported at test time.
def test_w9_exists_bound_in_default_arg(tmp_path):
    files = {
        "helper.py": "import os\n\ndef has(p, _exists=os.path.exists):\n    return _exists(p)\n",
        "test_t.py": "import unittest, helper\n\nclass Target(unittest.TestCase):\n"
                     "    def test_t(self):\n        self.assertFalse(helper.has('flag.txt'))\n",
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"flag.txt": "x"}))
    check(f, s, fr, "Target")


# W10: glob with a wildcard in a directory component that does not exist yet
def test_w10_glob_absent_dir(tmp_path):
    files = {
        "test_t.py": "import unittest, glob\n\nclass Target(unittest.TestCase):\n"
                     "    def test_t(self):\n        self.assertEqual(glob.glob('plugins/*/x.cfg'), [])\n",
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"plugins/a/x.cfg": "x"}))
    check(f, s, fr, "Target")


# W11: a module-level failed import in the TEST module satisfied by a new conftest-less sibling (doctest runner)
def test_w11_doctest_optional_import(tmp_path):
    files = {
        "mod.py": 'try:\n    import extra_r032b\nexcept ImportError:\n    extra_r032b = None\n\n'
                  'def f():\n    """\n    >>> f()\n    True\n    """\n    return extra_r032b is None\n',
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"extra_r032b.py": ""}), runner="doctest", args=("mod.py",))
    check(f, s, fr, "f")


# W12: zope.testrunner: the same leaked-patch channel as W1
def test_w12_zope_leaked_patch(tmp_path):
    pytest.importorskip("zope.testrunner")
    files = {
        "pkg/__init__.py": "",
        "pkg/consts.py": "V = None\n",
        "data.txt": "v1",
        "pkg/tests/__init__.py": "",
        "pkg/tests/test_a.py": "import unittest\nfrom unittest import mock\n\nclass A(unittest.TestCase):\n"
                               "    def test_a(self):\n        mock.patch('pkg.consts.V', open('data.txt').read()).start()\n",
        "pkg/tests/test_b.py": "import unittest\nfrom pkg import consts\n\nclass Target(unittest.TestCase):\n"
                               "    def test_b(self):\n        self.assertEqual(consts.V, 'v1')\n",
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"data.txt": "v2"}), runner="zope-testrunner", args=("--path=.",))
    check(f, s, fr, "Target")


# W13: Django (DiscoverRunner): the same leaked-patch channel as W1
def test_w13_django_leaked_patch(tmp_path):
    pytest.importorskip("django")
    settings = "SECRET_KEY='x'\nINSTALLED_APPS=['app']\nDATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}\n"
    files = {
        "settings.py": settings,
        "manage.py": "import os, sys\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')\n"
                     "from django.core.management import execute_from_command_line\nexecute_from_command_line(sys.argv)\n",
        "app/__init__.py": "",
        "app/consts.py": "V = None\n",
        "data.txt": "v1",
        "app/test_a.py": "from django.test import SimpleTestCase\nfrom unittest import mock\n\nclass A(SimpleTestCase):\n"
                         "    def test_a(self):\n        mock.patch('app.consts.V', open('data.txt').read()).start()\n",
        "app/test_b.py": "from django.test import SimpleTestCase\nfrom app import consts\n\nclass Target(SimpleTestCase):\n"
                         "    def test_b(self):\n        self.assertEqual(consts.V, 'v1')\n",
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"data.txt": "v2"}), runner="django", args=("manage.py", "test"))
    check(f, s, fr, "Target")


# W14: ward: the same leaked-patch channel as W1 (ward's tests import `ward`, infrastructure under this runner)
def test_w14_ward_leaked_patch(tmp_path):
    pytest.importorskip("ward")
    files = {
        "consts.py": "V = None\n",
        "data.txt": "v1",
        "pyproject.toml": "[tool.ward]\n",
        "test_a.py": "from ward import test\nfrom unittest import mock\n\n@test('a')\ndef _():\n"
                     "    mock.patch('consts.V', open('data.txt').read()).start()\n",
        "test_b.py": "from ward import test\nimport consts\n\n@test('Target')\ndef _():\n    assert consts.V == 'v1'\n",
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"data.txt": "v2"}), runner="ward", args=("test", "--path", "."))
    check(f, s, fr, "test_b")


# W15: W1 under pytest-xdist (-n 2, --dist loadfile keeps both files... on separate workers or together: the plan
#      decides); with sticky placement and the quarantine of parallel-proof-3
@pytest.mark.parametrize("dist", ["loadfile", "loadgroup"])
def test_w15_pytest_xdist(tmp_path, dist):
    pytest.importorskip("xdist")
    import json
    import subprocess
    root = tmp_path / "p"
    files = {
        "consts.py": "V = None\n",
        "data.txt": "v1",
        # both in one file: on one worker whatever the plan (atoms are files under loadfile; 'load' may split them,
        # the order inside a file is kept)
        # loadfile: both in one file (one worker); loadgroup: two files in one xdist_group (one worker)
        **({"test_ab.py": "import consts\nfrom unittest import mock\n\n"
                          "def test_a():\n    mock.patch('consts.V', open('data.txt').read()).start()\n\n"
                          "def test_b():\n    assert consts.V == 'v1'\n"} if dist == "loadfile" else
           {"test_a.py": "import pytest\nfrom unittest import mock\n\n@pytest.mark.xdist_group('g')\n"
                         "def test_a():\n    mock.patch('consts.V', open('data.txt').read()).start()\n",
            "test_b.py": "import pytest\nimport consts\n\n@pytest.mark.xdist_group('g')\n"
                         "def test_b():\n    assert consts.V == 'v1'\n",
            "test_c.py": "def test_c():\n    pass\n"}),
        "conftest.py": "",
    }
    write(root, files)
    target = "test_ab.py::test_b" if dist == "loadfile" else "test_b.py::test_b"

    def go(cache):
        args = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--det", "-n", "2",
                f"--dist={dist}", "-rA"]
        if cache:
            args.append(f"--det-cache={root.parent / 'pc'}")
        p = subprocess.run(args, cwd=root, capture_output=True, text=True)
        out = {line.split()[1]: line.split()[0].lower() for line in p.stdout.splitlines()
               if line.split()[:1] and line.split()[0] in ("PASSED", "FAILED", "ERROR")}
        reused = set()
        rc = root.parent / "pc" / "receipts.jsonl"
        if cache and rc.exists():
            reused = {json.loads(x)["nodeid"] for x in rc.read_text().splitlines() if json.loads(x).get("reused")}
        return out, reused, p.stdout

    o1, _, out1 = go(True)
    if o1.get(target) != "passed":
        pytest.skip(f"test_b did not run after test_a on one worker under this plan: {o1}")
    go(True)
    write(root, {"data.txt": "v2"})
    o3, _, _ = go(False)
    o2, r2, out2 = go(True)
    if o3.get(target) != "failed":
        pytest.skip(f"fresh plan did not put test_a before test_b: {o3}")
    assert not any(r.split("@")[0] == target for r in r2), ("WRONG REUSE under pytest-xdist", r2, out2)
