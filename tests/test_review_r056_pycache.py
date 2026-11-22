"""Review R-056, full review of PR #5 (claude/py-cache @ 2b67ac0): channels through which a cached outcome differs
from the outcome of an uncached ``pytest --det`` run with the same arguments.

Every test asserts its precondition (uncached ``--det`` gives the outcome the test names) and passes once the cached
run reports that outcome. Shape of R-052 / R-053: no root conftest, ``import helper``, ``pythonpath = .``.

W1  a conftest.py in a directory without collected test files (outside every code prefix);
W2  under -n 2: collection-time effects of a later test file or its conftest/__init__ (decorator, annotation, class
    base, conftest import, conftest hook): every worker collects every file, the AST import-effect check misses them;
W3  file metadata read through ``posix`` (stat, lstat, access): not recorded (LIMITS 9 A3 rebinding skips ``posix``);
W4  PWD (allowlisted) read through ``posix.environ``;
W5  the kernel release (``platform.release()``, ``posix.uname().release``): not in the key;
W6  files read by C code in the test process (OpenSSL ``cafile``, ``pwd`` reading /etc/passwd);
W7  installed code edited in place without a version change (a distribution's module, a loose site-packages module,
    a module an unchanged .pth runs);
W8  ``_random.Random()`` seeded from OS entropy in C: fresh --det runs vary, the cache freezes one outcome;
W10 the cache's clock epoch (today 00:00 UTC) is not uncached --det's (HEAD commit time, else 2025-01-01);
W11 object addresses (set order of default-hash objects) differ between a cached run and uncached --det.
"""
import os
import re
import shutil
import subprocess
import sys
import sysconfig

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the cache gates run on Linux")

VICTIM = "tests/b/test_b.py::test_victim"
INI = {"pytest.ini": "[pytest]\npythonpath = .\n"}
HELPER = {"helper.py": "STATE = {'mode': 'good'}\n\ndef poison(f=None):\n    STATE['mode'] = 'bad'\n    return f\n\n"
                       "class Poison:\n    def __init_subclass__(cls, **kw):\n        STATE['mode'] = 'bad'\n",
          "tests/a/test_a.py": "def test_a():\n    pass\n",
          "tests/b/test_b.py": "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n",
          "tests/z/test_z.py": "def test_z():\n    pass\n"}


def _write(root, files):
    for rel, text in files.items():
        p = root / rel
        if text is None:
            p.unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _pytest(root, *args, prefix=(), py=None, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    e.update(env or {})
    p = subprocess.run([*prefix, py or sys.executable, "-m", "pytest", "-q", "-rA", "-s", "-p", "no:cacheprovider",
                        "-p", "no:randomly", *args, "tests"], cwd=root, capture_output=True, text=True, env=e,
                       timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")):
            out[line.split()[1]] = line.split()[0].lower()
    return p, out


def _check(root, before, after=None, par=(), ctx1=None, ctx2=None, between=None):
    """Cold cached run (``ctx1``), change (``after`` files, ``between(root)``), warm cached run (``ctx2``); uncached
    --det under ``ctx2`` must fail the victim, and so must the cached run."""
    ctx1 = ctx1 or {}
    ctx2 = ctx2 if ctx2 is not None else ctx1
    cache = f"--det-cache={root / '.c'}"
    _write(root, {**INI, **before})
    p1, o1 = _pytest(root, "--det", cache, *par, **ctx1)
    assert o1.get(VICTIM) == "passed", p1.stdout[-1500:]
    if after:
        _write(root, after)
    if between:
        between(root)
    p, o = _pytest(root, "--det", cache, *par, **ctx2)
    det, do = _pytest(root, "--det", *par, **ctx2)
    assert det.returncode == 1 and do.get(VICTIM) == "failed", det.stdout[-1500:]
    assert p.returncode == 1 and o.get(VICTIM) == "failed", (
        f"--det-cache reports {o} (exit {p.returncode}); uncached --det fails {VICTIM}:\n{p.stdout[-2000:]}")


POISON_AT_IMPORT = "import helper\nhelper.STATE['mode'] = 'bad'\n"


# -- W1 ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("par", [(), ("-n", "2"), ("-n", "1")], ids=["serial", "n2", "n1"])
@pytest.mark.parametrize("where", ["tests/c", "tests/0", "tests/a/sub"])
def test_w1_a_conftest_in_a_directory_without_test_files(tmp_path, par, where):
    _check(tmp_path, {**HELPER, f"{where}/data.txt": "x"}, {f"{where}/conftest.py": POISON_AT_IMPORT}, par)


# -- W2 ------------------------------------------------------------------------------------------------------------
W2_CHANGES = {
    "later-conftest-import": {"tests/z/conftest.py": POISON_AT_IMPORT},
    "later-init-import": {"tests/z/__init__.py": POISON_AT_IMPORT},
    "later-bare-decorator": {"tests/z/test_z.py": "import helper\n\n@helper.poison\ndef test_z():\n    pass\n"},
    "later-class-base": {"tests/z/test_z.py": "import helper\n\nclass TestZ(helper.Poison):\n    def test_z(self):\n"
                                              "        pass\n"},
    "later-conftest-hook": {"tests/z/conftest.py": "import helper\n\ndef pytest_collection_modifyitems(items):\n"
                                                   "    helper.STATE['mode'] = 'bad'\n"},
}
if sys.version_info < (3, 14):  # annotations are evaluated at definition time before 3.14 (PEP 649)
    W2_CHANGES["later-return-annotation"] = {"tests/z/test_z.py": "import helper\n\ndef test_z() -> helper.poison():\n"
                                                                  "    pass\n"}


@pytest.mark.parametrize("change", sorted(W2_CHANGES))
def test_w2_n2_collection_time_effects_of_a_later_file(tmp_path, change):
    _check(tmp_path, HELPER, W2_CHANGES[change], ("-n", "2"))


# -- W3 / W4 / W5 / W6 ---------------------------------------------------------------------------------------------
def _single(body, imports="import os, posix"):
    return {"tests/a/test_a.py": "def test_a():\n    pass\n",
            "tests/b/test_b.py": imports + "\n\ndef test_victim():\n" + "".join(f"    {ln}\n" for ln in body.splitlines())}


@pytest.mark.parametrize("par", [(), ("-n", "2")], ids=["serial", "n2"])
@pytest.mark.parametrize("call", ["posix.stat('data.txt').st_size == 4", "posix.lstat('data.txt').st_size == 4"])
def test_w3_file_size_read_through_posix(tmp_path, par, call):
    _check(tmp_path, {"data.txt": "abcd", **_single(f"assert {call}")}, {"data.txt": "abcdefgh"}, par)


@pytest.mark.parametrize("par", [(), ("-n", "2")], ids=["serial", "n2"])
def test_w3_file_existence_read_through_posix_access(tmp_path, par):
    _check(tmp_path, {"marker": "x", **_single("assert posix.access('marker', posix.F_OK)")}, {"marker": None}, par)


def test_w3_file_mtime_read_through_posix_stat(tmp_path):
    _check(tmp_path, {"data.txt": "abcd", **_single("assert posix.stat('data.txt').st_mtime < 2000000000")},
           between=lambda root: os.utime(root / "data.txt", (2200000000, 2200000000)))


def test_w4_pwd_read_through_posix_environ(tmp_path):
    _check(tmp_path, _single("assert posix.environ.get(b'PWD', b'').endswith(b'/one')"),
           ctx1={"env": {"PWD": "/x/one"}}, ctx2={"env": {"PWD": "/x/two"}})


@pytest.mark.skipif(not shutil.which("setarch"), reason="needs setarch")
@pytest.mark.parametrize("call", ["platform.release()", "posix.uname().release"])
def test_w5_kernel_release(tmp_path, call):
    _check(tmp_path, _single(f"assert not {call}.startswith('2.6')", "import platform, posix"),
           ctx1={}, ctx2={"prefix": ("setarch", "x86_64", "--uname-2.6")})


_CA = "/etc/ssl/certs/ca-certificates.crt"


@pytest.mark.skipif(not os.path.exists(_CA), reason="needs a CA bundle")
def test_w6_a_file_openssl_reads(tmp_path):
    with open(_CA) as fh:
        pem = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\n", fh.read(), re.S).group(0)
    _check(tmp_path, {"ca.pem": pem, **_single("ssl.create_default_context(cafile='ca.pem')", "import ssl")},
           {"ca.pem": "-----BEGIN CERTIFICATE-----\ngarbage\n-----END CERTIFICATE-----\n"})


def _bind(src, dst):
    return ("unshare", "-m", "sh", "-c", f'mount --bind {src} {dst} && exec "$@"', "sh")


@pytest.mark.skipif(os.geteuid() != 0 or not shutil.which("unshare"), reason="needs root and unshare")
def test_w6_etc_passwd_read_by_pwd(tmp_path):
    with open("/etc/passwd") as fh:
        text = fh.read()
    home = next(ln.split(":")[5] for ln in text.splitlines() if ln.startswith("root:"))
    other = tmp_path / "passwd2"
    other.write_text(text.replace(f"root:x:0:0:root:{home}:", f"root:x:0:0:root:{home}OTHER:", 1))
    _check(tmp_path, _single(f"assert pwd.getpwuid(0).pw_dir == {home!r}", "import pwd"),
           ctx1={}, ctx2={"prefix": _bind(other, "/etc/passwd")})


# -- W7 ------------------------------------------------------------------------------------------------------------
def _venv(tmp_path):
    """A venv whose site-packages sees this interpreter's (pytest, xdist, detpy) through a .pth, plus a directory of
    its own for the installed code the test edits."""
    v = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(v)], check=True)
    py = str(v / "bin" / "python")
    sp = subprocess.run([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], capture_output=True,
                        text=True, check=True).stdout.strip()
    with open(os.path.join(sp, "zz_parent.pth"), "w") as fh:
        fh.write(sysconfig.get_paths()["purelib"] + "\n")
    return py, sp


VB = "import builtins\n\ndef test_victim():\n    assert not hasattr(builtins, 'R056')\n"


@pytest.mark.parametrize("kind", ["dist-module", "loose-module", "pth-module"])
def test_w7_installed_code_edited_in_place(tmp_path, kind):
    py, sp = _venv(tmp_path)
    root = tmp_path / "proj"
    root.mkdir()

    def put(rel, text):
        with open(os.path.join(sp, rel), "w") as fh:
            fh.write(text)

    if kind == "dist-module":
        os.makedirs(os.path.join(sp, "r056lib-1.0.dist-info"))
        put("r056lib-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: r056lib\nVersion: 1.0\n")
        put("r056lib-1.0.dist-info/RECORD", "r056lib.py,,\nr056lib-1.0.dist-info/METADATA,,\n")
        put("r056lib.py", "MODE = 'good'\n")
        victim, edit = "import r056lib\n\ndef test_victim():\n    assert r056lib.MODE == 'good'\n", ("r056lib.py", "MODE = 'bad'\n")
    elif kind == "loose-module":
        put("r056loose.py", "MODE = 'good'\n")
        victim, edit = "import r056loose\n\ndef test_victim():\n    assert r056loose.MODE == 'good'\n", ("r056loose.py", "MODE = 'bad'\n")
    else:
        put("r056pth.py", "X = 1\n")
        put("r056.pth", "import r056pth\n")
        victim, edit = VB, ("r056pth.py", "import builtins\nbuiltins.R056 = 1\n")
    _check(root, {"tests/a/test_a.py": "def test_a():\n    pass\n", "tests/b/test_b.py": victim},
           ctx1={"py": py}, between=lambda _: put(*edit))


# -- W8 ------------------------------------------------------------------------------------------------------------
def test_w8_c_seeded_random_is_controlled_or_refused(tmp_path):
    """Reused only if the value fresh --det runs see is the same every run (R-053 E1 shape)."""
    _write(tmp_path, {**INI, "tests/test_e.py": "import _random\n\ndef test_e():\n    print('VALUE', _random.Random().random())\n"})
    cache = f"--det-cache={tmp_path / '.c'}"
    _pytest(tmp_path, "--det", cache)
    p, _ = _pytest(tmp_path, "--det", cache)
    reused = any(line.startswith("reused 1 ") for line in p.stdout.splitlines())
    vals = [next(line for line in _pytest(tmp_path, "--det")[0].stdout.splitlines() if line.startswith("VALUE"))
            for _ in range(2)]
    assert not (reused and vals[0] != vals[1]), f"reused while fresh --det runs read {vals}:\n{p.stdout[-1500:]}"


# -- W10 / W11: a test the cache runs (not reused) gets another outcome than under uncached --det ---------------------
def _same_outcome(root, body):
    _write(root, {**INI, "tests/test_w.py": body})
    det, do = _pytest(root, "--det")
    p, o = _pytest(root, "--det", f"--det-cache={root / '.c'}")
    assert o == do, f"uncached --det: {do}; --det-cache: {o}\n{p.stdout[-1500:]}"


def test_w10_the_cache_runs_tests_at_the_epoch_uncached_det_uses(tmp_path):
    # tmp_path is not a git checkout: uncached --det's epoch is 2025-01-01 (LIMITS C6b)
    _same_outcome(tmp_path, "import datetime\n\ndef test_w():\n    assert datetime.date.today() == datetime.date(2025, 1, 1)\n")


def test_w11_object_addresses_match_uncached_det(tmp_path):
    probe = ("class K:\n    def __init__(self, n):\n        self.n = n\n\ndef order():\n"
             "    return [k.n for k in {K(i) for i in range(6)}]\n\n")
    _write(tmp_path, {**INI, "tests/test_w.py": probe + "def test_w():\n    print('ORDER', order())\n"})
    det, _ = _pytest(tmp_path, "--det")
    order = next(line for line in det.stdout.splitlines() if line.startswith("ORDER"))[6:]
    _same_outcome(tmp_path, probe + f"def test_w():\n    assert order() == {order}\n")
