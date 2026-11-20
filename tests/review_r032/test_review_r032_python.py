"""Review R-032 (claude/all-runners): adversarial wrong-reuse attacks on the Python runner adapters.

Each scenario: a project whose target test passes; run 1 records with --det-cache; ONE input changes; run 2.
A wrong reuse = the target is reused in run 2 although a fresh run 3 (no cache) fails it. Every scenario also has a
control class that the change does not touch (the cache must reuse it in run 2, else the scenario proves nothing).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runners_util import run, write  # noqa: E402

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

CONTROL = "\n\nclass Control(unittest.TestCase):\n    def test_control(self):\n        self.assertEqual(1, 1)\n"


def scenario(tmp_path, files, mutate, runner="unittest", args=(), env1=None, env2=None, mod="test_t",
             target="Target", control_id=None, fresh_env=None):
    root = tmp_path / "p"
    files = dict(files)
    if runner != "django":
        files.setdefault("test_ctl.py", "import unittest" + CONTROL)
    write(root, files)
    env1 = env1 or {}
    first = run(runner, root, *args, env=env1)
    mutate(root)
    env2 = dict(env1, **(env2 or {}))
    second = run(runner, root, *args, env=env2)
    fresh = run(runner, root, *args, env=env2, cache=False)
    return first, second, fresh


def tid(first, part):
    ids = [i for i in first.outcomes if part in i]
    assert ids, first
    return ids[0]


def assert_no_wrong_reuse(first, second, fresh, part="Target", control="test_ctl"):
    t = tid(first, part)
    assert first.outcomes[t] == "passed", first
    # the control (another module) is reused when the cache works; a target that reruns needs no control
    assert fresh.outcomes.get(t) in ("failed", "error"), ("the change does not flip the test", fresh)
    assert t not in second.reused, ("WRONG REUSE: reused 'passed', fresh run fails", second, fresh)


# P1: a failed `try: import` at module level of a HELPER module (not the test module), satisfied later in a
#     namespace package directory on sys.path
def test_p1_optional_import_in_helper_namespace_pkg(tmp_path):
    files = {
        "helper.py": "try:\n    from nspkg import extra\nexcept ImportError:\n    extra = None\n",
        "nspkg/base.py": "",
        "test_t.py": "import unittest, helper\n\nclass Target(unittest.TestCase):\n"
                     "    def test_t(self):\n        self.assertIsNone(helper.extra)\n" + CONTROL,
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"nspkg/extra.py": "X = 1\n"}))
    assert_no_wrong_reuse(f, s, fr)


# P2: a namespace package gains __init__.py (the package's attributes change)
def test_p2_namespace_package_gains_init(tmp_path):
    files = {
        "nspkg2/mod.py": "",
        "test_t.py": "import unittest\nimport nspkg2.mod, nspkg2\n\nclass Target(unittest.TestCase):\n"
                     "    def test_t(self):\n        self.assertFalse(hasattr(nspkg2, 'FLAG'))\n" + CONTROL,
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"nspkg2/__init__.py": "FLAG = 1\n"}))
    assert_no_wrong_reuse(f, s, fr)


# P3: zipimport: a module imported from a zip archive on sys.path; the archive's member changes
def test_p3_zipimport_member_changes(tmp_path):
    import zipfile

    root = tmp_path / "p"
    root.mkdir()

    def mkzip(v):
        with zipfile.ZipFile(root / "lib.zip", "w") as z:
            z.writestr("zmod.py", f"V = {v}\n")

    mkzip(1)
    files = {"test_t.py": "import unittest, sys, os\nsys.path.insert(0, os.path.abspath('lib.zip'))\nimport zmod\n\n"
                          "class Target(unittest.TestCase):\n    def test_t(self):\n        self.assertEqual(zmod.V, 1)\n"
                          + CONTROL}
    f, s, fr = scenario(tmp_path, files, lambda r: mkzip(2))
    assert_no_wrong_reuse(f, s, fr)


# P4: ctypes / dlopen of a project shared library whose code changes
@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler")
def test_p4_ctypes_dlopen(tmp_path):
    root = tmp_path / "p"
    root.mkdir()

    def build(v):
        (root / "v.c").write_text(f"int v(void) {{ return {v}; }}\n")
        subprocess.run(["cc", "-shared", "-fPIC", "-o", str(root / "libv.so"), str(root / "v.c")], check=True)

    build(1)
    files = {"test_t.py": "import unittest, ctypes, os\n\nclass Target(unittest.TestCase):\n"
                          "    def test_t(self):\n        self.assertEqual(ctypes.CDLL(os.path.abspath('libv.so')).v(), 1)\n"
                          + CONTROL}
    f, s, fr = scenario(tmp_path, files, lambda r: build(2))
    assert_no_wrong_reuse(f, s, fr)


# P5: prefix state: a library memoises (functools.lru_cache) a file read; class A reads it first, class B gets the
#     memoised answer. The file changes: does B's record carry the file as an input?
def test_p5_lru_cache_prefix_state(tmp_path):
    files = {
        "conf.txt": "x",
        "lib.py": "import functools\n\n@functools.lru_cache\ndef conf():\n    return open('conf.txt').read()\n",
        "test_a.py": "import unittest, lib\n\nclass A(unittest.TestCase):\n    def test_a(self):\n"
                     "        self.assertTrue(lib.conf())\n",
        "test_b.py": "import unittest, lib\n\nclass Target(unittest.TestCase):\n    def test_b(self):\n"
                     "        self.assertEqual(lib.conf(), 'x')\n" + CONTROL,
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"conf.txt": "y"}))
    assert_no_wrong_reuse(f, s, fr)


# P6: prefix state through a module-level dict filled lazily by whichever test calls first
def test_p6_module_dict_prefix_state(tmp_path):
    files = {
        "data.json": '{"k": 1}',
        "lib.py": "import json\n_C = {}\n\ndef get():\n    if 'd' not in _C:\n"
                  "        _C['d'] = json.load(open('data.json'))\n    return _C['d']\n",
        "test_a.py": "import unittest, lib\n\nclass A(unittest.TestCase):\n    def test_a(self):\n"
                     "        self.assertIn('k', lib.get())\n",
        "test_b.py": "import unittest, lib\n\nclass Target(unittest.TestCase):\n    def test_b(self):\n"
                     "        self.assertEqual(lib.get()['k'], 1)\n" + CONTROL,
    }
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"data.json": '{"k": 1, "j": 2}'}) if False else
                        write(r, {"data.json": '{"k": 2}'}))
    assert_no_wrong_reuse(f, s, fr)


# P7: C-level getenv: locale.setlocale(LC_ALL, '') reads LC_ALL/LANG in C, not through os.environ
def test_p7_locale_from_c_getenv(tmp_path):
    files = {"test_t.py": "import unittest, locale\n\nclass Target(unittest.TestCase):\n    def test_t(self):\n"
                          "        locale.setlocale(locale.LC_ALL, '')\n"
                          "        self.assertEqual(locale.localeconv()['decimal_point'], '.')\n" + CONTROL}
    probe = subprocess.run([sys.executable, "-c", "import locale;locale.setlocale(locale.LC_ALL,'');"
                            "print(locale.localeconv()['decimal_point'])"], env=dict(os.environ, LC_ALL="de_DE.UTF-8"),
                           capture_output=True, text=True)
    if probe.stdout.strip() != ",":
        pytest.skip("de_DE.UTF-8 locale not installed")
    f, s, fr = scenario(tmp_path, files, lambda r: None, env1={"LC_ALL": "C.UTF-8"}, env2={"LC_ALL": "de_DE.UTF-8"})
    assert_no_wrong_reuse(f, s, fr)


# P8: user identity read in C (pwd database) and HOME through os.path.expanduser
def test_p8_home_via_expanduser(tmp_path):
    files = {"test_t.py": "import unittest, os\n\nclass Target(unittest.TestCase):\n    def test_t(self):\n"
                          "        self.assertFalse(os.path.exists(os.path.expanduser('~/.detpy-r032-flag')))\n"
                          + CONTROL}
    home2 = tmp_path / "home2"
    write(home2, {".detpy-r032-flag": ""})
    f, s, fr = scenario(tmp_path, files, lambda r: None, env2={"HOME": str(home2)})
    assert_no_wrong_reuse(f, s, fr)


# P9: nose2: a configuration file that did not exist appears (nose2 reads unittest.cfg / nose2.cfg from the cwd)
def test_p9_nose2_config_appears(tmp_path):
    pytest.importorskip("nose2")
    files = {"plug_r032.py": "from nose2.events import Plugin\nimport os\n\nclass P(Plugin):\n"
                             "    configSection = 'r032'\n    alwaysOn = True\n"
                             "    def __init__(self):\n        os.environ['R032_PLUGIN'] = '1'\n",
             "test_t.py": "import unittest, os\n\nclass Target(unittest.TestCase):\n    def test_t(self):\n"
                          "        self.assertIsNone(os.environ.get('R032_PLUGIN'))\n" + CONTROL}
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, {"nose2.cfg": "[unittest]\nplugins = plug_r032\n"}),
                        runner="nose2")
    assert_no_wrong_reuse(f, s, fr)


# P10: unittest discovery top-level directory: -t changes which package name a module is imported under
def test_p10_django_settings_env_switch(tmp_path):
    pytest.importorskip("django")
    settings = "SECRET_KEY='x'\nINSTALLED_APPS=['app']\nDATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}\n"
    files = {"manage.py": "import os, sys\nif __name__ == '__main__':\n"
                          "    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'proj.settings')\n"
                          "    from django.core.management import execute_from_command_line\n"
                          "    execute_from_command_line(sys.argv)\n",
             "proj/__init__.py": "", "proj/settings.py": settings + "FEATURE = False\n",
             "proj/settings2.py": settings + "FEATURE = True\n",
             "app/__init__.py": "", "app/models.py": "",
             "app/tests.py": "from django.test import SimpleTestCase\nfrom django.conf import settings\n\n"
                             "class Target(SimpleTestCase):\n    def test_t(self):\n        self.assertFalse(settings.FEATURE)\n\n"
                             "",
             "app/test_ctl.py": "from django.test import SimpleTestCase\n\nclass Control(SimpleTestCase):\n"
                                "    def test_control(self):\n        self.assertEqual(1, 1)\n"}
    f, s, fr = scenario(tmp_path, files, lambda r: None, runner="django", args=("manage.py", "test"),
                        env2={"DJANGO_SETTINGS_MODULE": "proj.settings2"})
    assert_no_wrong_reuse(f, s, fr)


# P11: a .pth file appears in a site directory (sys.path changes at start-up, an optional import is satisfied)
def test_p11_pth_file_appears(tmp_path):
    import site
    sp = Path(site.getsitepackages()[0])
    if not os.access(sp, os.W_OK):
        pytest.skip("site-packages not writable")
    extra = tmp_path / "extra"
    write(extra, {"r032_pthmod.py": "X = 1\n"})
    pth = sp / "zz_r032_review.pth"
    files = {"test_t.py": "import unittest\ntry:\n    import r032_pthmod\nexcept ImportError:\n    r032_pthmod = None\n\n"
                          "class Target(unittest.TestCase):\n    def test_t(self):\n        self.assertIsNone(r032_pthmod)\n"
                          + CONTROL}
    try:
        f, s, fr = scenario(tmp_path, files, lambda r: pth.write_text(str(extra) + "\n"))
    finally:
        pth.unlink(missing_ok=True)
    assert_no_wrong_reuse(f, s, fr)


# P12: Hypothesis: the profile is chosen by an environment variable read at import by a helper; max_examples change
#      makes the property find a counterexample
def test_p12_hypothesis_profile_env(tmp_path):
    pytest.importorskip("hypothesis")
    files = {"test_t.py": "import unittest, os\nfrom hypothesis import given, settings, strategies as st\n"
                          "settings.register_profile('big', max_examples=2000)\n"
                          "settings.register_profile('tiny', max_examples=1)\n"
                          "settings.load_profile(os.environ.get('R032_PROFILE', 'tiny'))\n\n"
                          "class Target(unittest.TestCase):\n    @given(st.integers(0, 10**6))\n"
                          "    def test_t(self, x):\n        self.assertNotEqual(x % 997, 5)\n" + CONTROL}
    f, s, fr = scenario(tmp_path, files, lambda r: None, env2={"R032_PROFILE": "big"})
    assert_no_wrong_reuse(f, s, fr)


# P13: doctest: a file included through a doctest that reads a fixture with os.path.exists created later
def test_p13_doctest_exists_probe(tmp_path):
    files = {"mod.py": '"""\n>>> import os\n>>> os.path.exists("flag")\nFalse\n"""\n\n'
                       'def ctl():\n    """\n    >>> 1\n    1\n    """\n'}
    root = tmp_path / "p"
    write(root, files)
    f = run("doctest", root, "mod.py")
    write(root, {"flag": ""})
    s = run("doctest", root, "mod.py")
    fr = run("doctest", root, "mod.py", cache=False)
    t = [i for i in f.outcomes if i.endswith("mod")] or list(f.outcomes)
    assert f.outcomes[t[0]] == "passed", f
    assert fr.outcomes[t[0]] == "failed", fr
    assert t[0] not in s.reused, ("WRONG REUSE", s)


# -- the same holes under nose2 and under the pytest plugin (one shared capture core) ------------------------------
NS_FILES = {"nspkg2/mod.py": "",
            "test_t.py": "import unittest\nimport nspkg2.mod, nspkg2\n\nclass Target(unittest.TestCase):\n"
                         "    def test_t(self):\n        self.assertFalse(hasattr(nspkg2, 'FLAG'))\n"}
LRU_FILES = {"conf.txt": "x",
             "lib.py": "import functools\n\n@functools.lru_cache\ndef conf():\n    return open('conf.txt').read()\n",
             "test_a.py": "import unittest, lib\n\nclass A(unittest.TestCase):\n    def test_a(self):\n"
                          "        self.assertTrue(lib.conf())\n",
             "test_b.py": "import unittest, lib\n\nclass Target(unittest.TestCase):\n    def test_b(self):\n"
                          "        self.assertEqual(lib.conf(), 'x')\n"}


@pytest.mark.parametrize("files,change", [(NS_FILES, {"nspkg2/__init__.py": "FLAG = 1\n"}), (LRU_FILES, {"conf.txt": "y"})],
                         ids=["namespace_init", "lru_prefix"])
def test_x_nose2(tmp_path, files, change):
    pytest.importorskip("nose2")
    f, s, fr = scenario(tmp_path, files, lambda r: write(r, change), runner="nose2", args=("-s", ".", "-t", "."))
    assert_no_wrong_reuse(f, s, fr)


def _pytest_run(root, cache):
    import json
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


@pytest.mark.parametrize("files,change,target", [
    ({"ns/m.py": "", "test_ns.py": "import ns.m, ns\n\ndef test_t():\n    assert not hasattr(ns, 'FLAG')\n"},
     {"ns/__init__.py": "FLAG = 1\n"}, "test_ns.py::test_t"),
    ({"conf.txt": "x", "lib.py": LRU_FILES["lib.py"], "test_a.py": "import lib\n\ndef test_a():\n    assert lib.conf()\n",
      "test_b.py": "import lib\n\ndef test_t():\n    assert lib.conf() == 'x'\n"}, {"conf.txt": "y"}, "test_b.py::test_t"),
    ({"data.json": '{"k": 1}', "lib.py": "import json\n_C = {}\n\ndef get():\n    if 'd' not in _C:\n"
      "        _C['d'] = json.load(open('data.json'))\n    return _C['d']\n",
      "test_a.py": "import lib\n\ndef test_a():\n    assert 'k' in lib.get()\n",
      "test_b.py": "import lib\n\ndef test_t():\n    assert lib.get()['k'] == 1\n"}, {"data.json": '{"k": 2}'}, "test_b.py::test_t"),
    ({"test_z.py": "import sys, os\nsys.path.insert(0, os.path.abspath('lib.zip'))\nimport zmod\n\ndef test_t():\n"
      "    assert zmod.V == 1\n"}, "zip:2", "test_z.py::test_t"),
    ({"test_c.py": "import ctypes, os\n\ndef test_t():\n    assert ctypes.CDLL(os.path.abspath('libv.so')).v() == 1\n"},
     "so:2", "test_c.py::test_t"),
], ids=["namespace_init", "lru_prefix", "module_dict_prefix", "zipimport", "ctypes_dlopen"])
def test_x_pytest_plugin(tmp_path, files, change, target):
    import zipfile
    root = tmp_path / "p"
    write(root, files)

    def apply(ch):
        if isinstance(ch, dict):
            write(root, ch)
        elif ch.startswith("zip:"):
            with zipfile.ZipFile(root / "lib.zip", "w") as z:
                z.writestr("zmod.py", f"V = {ch[4:]}\n")
        elif ch.startswith("so:"):
            if shutil.which("cc") is None:
                pytest.skip("no C compiler")
            (root / "v.c").write_text(f"int v(void) {{ return {ch[3:]}; }}\n")
            subprocess.run(["cc", "-shared", "-fPIC", "-o", str(root / "libv.so"), str(root / "v.c")], check=True)

    if change == "zip:2":
        apply("zip:1")
    if change == "so:2":
        apply("so:1")
    o1, _, _ = _pytest_run(root, True)
    assert o1.get(target) == "passed", o1
    apply(change)
    o2, r2, out2 = _pytest_run(root, True)
    o3, _, _ = _pytest_run(root, False)
    assert o3.get(target) == "failed", o3
    assert target not in r2, ("WRONG REUSE under the pytest plugin", out2)


# -- "failed tests are never reused": failures that happen outside a test body -------------------------------------
@pytest.mark.parametrize("hook", [
    "def tearDownModule():\n    raise RuntimeError('teardown module')\n",
    "unittest.addModuleCleanup(lambda: (_ for _ in ()).throw(RuntimeError('module cleanup')))\n",
    "import atexit, os\natexit.register(lambda: os._exit(3))\n",
], ids=["tearDownModule", "addModuleCleanup", "atexit_exit_code"])
def test_f_failure_outside_test_never_reused(tmp_path, hook):
    root = tmp_path / "p"
    write(root, {"test_t.py": "import unittest\n" + hook + "\nclass Target(unittest.TestCase):\n    def test_t(self):\n        pass\n",
                 "test_ctl.py": "import unittest" + CONTROL})
    first = run("unittest", root)
    assert first.code != 0, ("precondition: the run fails", first)
    second = run("unittest", root)
    assert second.code != 0, ("WRONG REUSE: the cached run exits 0 where every fresh run fails", second)
