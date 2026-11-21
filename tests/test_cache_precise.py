"""P-061 (cache precise tracking): attack tests for per-test state tracking (docs/CACHE-PRECISE.md).

The cache today keeps a reused result sound by running every earlier test of a process before a test that runs
(failing, new, or in an edited file), once that test can reach a library. P-061 narrows that set to the earlier tests
that MODIFIED state the running test may READ. Every test here makes that narrowing dangerous: an earlier test (the
polluter) changes process state through one channel, and a later test (the victim) is made to run in the warm session
by one trigger:

* ``fail``: the victim fails because of the polluted state (cold and warm): it is never stored and runs every time;
* ``new``: the victim is added between the runs and passes only after the polluter;
* ``edit``: the victim's test file is edited (a comment) between the runs; it passes only after the polluter.

The polluter itself is unchanged and reusable. A cache that runs the victim without the polluter (or with only part of
the earlier tests that wrote the state) reports another outcome than uncached ``--det``. Each test asserts:

1. its precondition: uncached ``pytest --det`` gives the victim the outcome the trigger expects (so the attack bites);
2. the warm cached run reports, for every test, the outcome of uncached ``--det`` with the same arguments.

Serial and ``-n 2 --dist loadgroup`` (polluter and victim pinned to one worker with ``xdist_group``). The serial
variant imports only ``helper`` (no library reach through the test files: the static reference closure would
otherwise carry every earlier test and hide a defect in the dynamic tracking); the ``-n 2`` variant imports pytest
for the group marks.

The ``test_reuse_*`` tests are the reuse targets of P-061 phase 2 (they fail on the current rule, which reruns every
earlier test): marked ``xfail(strict=True)`` until phase 2 lands; phase 2 removes the marks.

No conftest at the root, ``import helper`` (as in R-052/R-053).
"""
import os
import re
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the cache gates run on Linux")

VICTIM = "tests/b/test_b.py::test_victim"
INI = "[pytest]\npythonpath = .\n"
SCRATCH = ("p061.txt", "p061c.txt", "p061f.txt")  # files a polluter leaves in the project: removed before every run

# channel -> dict(helper=..., imports=..., polluters=[body, ...], pre=..., after=...)
#   helper:    extra text of helper.py (STATE = {'mode': 'good'} is always there)
#   polluters: the bodies of the polluter tests, in order (tests/a/test_a.py::test_a0, test_a1, ...)
#   pre:       statements the victim runs before its assertion
#   after:     an expression, True in the state the full prefix leaves and False when the polluters (or some of them)
#              did not run
CH = {
    # -- module state --------------------------------------------------------------------------------------------
    "global-rebind": dict(helper="MODE = 'good'\n", polluters=["helper.MODE = 'bad'"], after="helper.MODE == 'bad'"),
    "dict-item": dict(polluters=["helper.STATE['mode'] = 'bad'"], after="helper.STATE['mode'] == 'bad'"),
    "nested-list": dict(helper="CFG = {'a': {'b': [1]}}\n", polluters=["helper.CFG['a']['b'].append(2)"],
                        after="helper.CFG['a']['b'] == [1, 2]"),
    "set-add": dict(helper="S = set()\n", polluters=["helper.S.add(1)"], after="helper.S == {1}"),
    "class-attr": dict(helper="class C:\n    flag = False\n", polluters=["helper.C.flag = True"],
                       after="helper.C.flag is True"),
    "instance-attr": dict(helper="class O:\n    pass\nOBJ = O()\nOBJ.v = 1\n", polluters=["helper.OBJ.v = 2"],
                          after="helper.OBJ.v == 2"),
    "slots-attr": dict(helper="class SL:\n    __slots__ = ('v',)\n\n    def __init__(self):\n        self.v = 1\n"
                              "SLOT = SL()\n", polluters=["helper.SLOT.v = 2"], after="helper.SLOT.v == 2"),
    "default-arg": dict(helper="def f(x=[]):\n    return x\n", polluters=["helper.f().append(1)"],
                        after="helper.f() == [1]"),
    "closure-cell": dict(helper="def mk():\n    v = 0\n\n    def get():\n        return v\n\n    def put(n):\n"
                                "        nonlocal v\n        v = n\n    return get, put\nGET, PUT = mk()\n",
                         polluters=["helper.PUT(1)"], after="helper.GET() == 1"),
    "func-attr": dict(helper="def h():\n    return h.__dict__.get('k', 0)\n", polluters=["helper.h.k = 1"],
                      after="helper.h() == 1"),
    # a memo of an impure function: the first test fills it, the second changes what it reads; the victim sees the
    # stale memo only after both (running only the second gives the fresh value)
    "lru-impure": dict(helper="import functools\nX = {'v': 1}\n\n@functools.lru_cache\ndef g():\n    return X['v']\n",
                       polluters=["helper.g()", "helper.X['v'] = 2"], after="helper.g() == 1"),
    # the second polluter undoes the first: running only the first leaves the state the victim must not see
    "restore-chain": dict(polluters=["helper.STATE['mode'] = 'bad'", "helper.STATE['mode'] = 'good'"],
                          after="helper.STATE['mode'] == 'good'"),
    # the second polluter reads what the first wrote
    "read-chain": dict(helper="A = {'v': 0}\nB = {'v': 0}\n",
                       polluters=["helper.A['v'] = 1", "helper.B['v'] = helper.A['v'] + 1"],
                       after="helper.B['v'] == 2"),
    "import-side-effect": dict(extra={"side.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"},
                               polluters=["import side  # noqa: F401"], after="helper.STATE['mode'] == 'bad'"),
    "fixture-teardown": dict(fixture="    yield\n    helper.STATE['mode'] = 'bad'\n", polluters=["pass"],
                             after="helper.STATE['mode'] == 'bad'"),
    "module-fixture": dict(fixture_module="    helper.STATE['mode'] = 'bad'\n    yield\n", polluters=["pass"],
                           after="helper.STATE['mode'] == 'bad'"),
    # -- C objects held by a module --------------------------------------------------------------------------
    "sqlite-memory": dict(helper="import sqlite3\nDB = sqlite3.connect(':memory:')\nDB.execute('create table t(x)')\n",
                          polluters=["helper.DB.execute('insert into t values (1)')"],
                          after="helper.DB.execute('select count(*) from t').fetchone()[0] == 1"),
    "stringio": dict(helper="import io\nBUF = io.StringIO()\n", polluters=["helper.BUF.write('x')"],
                     after="helper.BUF.getvalue() == 'x'"),
    "itertools-count": dict(helper="import itertools\nCNT = itertools.count()\n", polluters=["next(helper.CNT)"],
                            after="next(helper.CNT) == 1"),
    "generator": dict(helper="def _g():\n    i = 0\n    while True:\n        yield i\n        i += 1\nGEN = _g()\n",
                      polluters=["next(helper.GEN)"], after="next(helper.GEN) == 1"),
    "array": dict(helper="import array\nARR = array.array('i')\n", polluters=["helper.ARR.append(1)"],
                  after="len(helper.ARR) == 1"),
    "bytearray": dict(helper="BA = bytearray()\n", polluters=["helper.BA.extend(b'x')"], after="helper.BA == b'x'"),
    "deque": dict(helper="import collections\nDQ = collections.deque()\n", polluters=["helper.DQ.append(1)"],
                  after="len(helper.DQ) == 1"),
    "random-instance": dict(helper="import random\nR = random.Random(1)\n", polluters=["helper.R.random()"],
                            imports="import random", after="helper.R.random() != random.Random(1).random()"),
    "hash-object": dict(helper="import hashlib\nH = hashlib.sha256()\n", polluters=["helper.H.update(b'x')"],
                        imports="import hashlib", after="helper.H.hexdigest() != hashlib.sha256().hexdigest()"),
    # -- interpreter state -----------------------------------------------------------------------------------
    "recursion-limit": dict(imports="import sys", polluters=["sys.setrecursionlimit(170)"],
                            after="sys.getrecursionlimit() == 170"),
    "int-max-str-digits": dict(imports="import sys", polluters=["sys.set_int_max_str_digits(1000)"],
                               after="sys.get_int_max_str_digits() == 1000"),
    "sys-path": dict(imports="import sys", polluters=["sys.path.insert(0, '/nonexistent-p061')"],
                     after="'/nonexistent-p061' in sys.path"),
    "sys-modules": dict(imports="import sys, types",
                        polluters=["sys.modules['p061fake'] = types.SimpleNamespace(v=1)"],
                        pre="try:\n    import p061fake  # noqa: F401\n    ok = True\nexcept ImportError:\n    ok = False",
                        after="ok"),
    "builtins": dict(imports="import builtins", polluters=["builtins.P061 = 1"], after="hasattr(builtins, 'P061')"),
    "excepthook": dict(imports="import sys", polluters=["sys.excepthook = lambda *a: None"],
                       after="sys.excepthook is not sys.__excepthook__"),
    "codecs-register": dict(imports="import codecs",
                            polluters=["codecs.register(lambda n: codecs.lookup('utf-8') if n == 'p061' else None)"],
                            pre="try:\n    codecs.lookup('p061')\n    ok = True\nexcept LookupError:\n    ok = False",
                            after="ok"),
    "audit-hook": dict(helper="EVENTS = []\n", imports="import sys",
                       polluters=["sys.addaudithook(lambda e, a: helper.EVENTS.append(e) if e == 'p061' else None)"],
                       pre="sys.audit('p061')", after="helper.EVENTS == ['p061']"),
    "gc-disabled": dict(imports="import gc", polluters=["gc.disable()"], after="not gc.isenabled()"),
    "gc-threshold": dict(imports="import gc", polluters=["gc.set_threshold(123)"], after="gc.get_threshold()[0] == 123"),
    "decimal-context": dict(imports="import decimal", polluters=["decimal.getcontext().prec = 3"],
                            after="decimal.getcontext().prec == 3"),
    "logging-disable": dict(imports="import logging", polluters=["logging.disable(logging.CRITICAL)"],
                            after="logging.root.manager.disable == logging.CRITICAL"),
    "socket-timeout": dict(imports="import socket", polluters=["socket.setdefaulttimeout(3)"],
                           after="socket.getdefaulttimeout() == 3"),
    "signal-handler": dict(imports="import signal", polluters=["signal.signal(signal.SIGUSR1, lambda *a: None)"],
                           after="signal.getsignal(signal.SIGUSR1) != signal.SIG_DFL"),
    "locale": dict(imports="import locale", polluters=["locale.setlocale(locale.LC_COLLATE, 'C.UTF-8')"],
                   after="locale.setlocale(locale.LC_COLLATE) == 'C.UTF-8'"),
    # -- process state outside the interpreter -------------------------------------------------------------
    "environ": dict(imports="import os", polluters=["os.environ['P061'] = '1'"], after="os.environ.get('P061') == '1'"),
    "putenv": dict(imports="import subprocess", polluters=["import os\n    os.putenv('P061P', '1')"],
                   pre="out = subprocess.run(['sh', '-c', 'printf %s \"$P061P\"'], capture_output=True, text=True).stdout",
                   after="out == '1'"),
    "chdir": dict(imports="import os", polluters=["os.chdir('/')"], after="os.getcwd() == '/'"),
    "umask": dict(imports="import os", polluters=["os.umask(0o077)"], pre="m = os.umask(0o022)\nos.umask(m)",
                  after="m == 0o077"),
    "file-written": dict(imports="import os", polluters=["open('p061.txt', 'w').write('x')"],
                         after="os.path.exists('p061.txt')"),
    "file-by-child": dict(imports="import os, subprocess", polluters=["subprocess.run(['sh', '-c', 'echo x > p061c.txt'])"],
                          after="os.path.exists('p061c.txt')"),
    "at-fork": dict(imports="import os",
                    polluters=["os.register_at_fork(after_in_child=lambda: open('p061f.txt', 'w').close())"],
                    pre="pid = os.fork()\nif pid == 0:\n    os._exit(0)\nos.waitpid(pid, 0)",
                    after="os.path.exists('p061f.txt')"),
    # a thread the polluter leaves running changes the state after the polluter ended
    "live-thread": dict(helper="import threading\nGO = threading.Event()\nDONE = threading.Event()\n",
                        imports="import threading",
                        polluters=["def w():\n        helper.GO.wait()\n        helper.STATE['mode'] = 'bad'\n"
                                   "        helper.DONE.set()\n    threading.Thread(target=w, daemon=True).start()"],
                        pre="helper.GO.set()\nhelper.DONE.wait(2)", after="helper.STATE['mode'] == 'bad'"),
}

TRIGGERS = ("fail", "new", "edit")
PARS = {"serial": (), "n2": ("-n", "2", "--dist", "loadgroup")}


def _write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _pytest(root, *args):
    for f in SCRATCH:
        try:
            os.unlink(root / f)
        except FileNotFoundError:
            pass
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly",
                        *args, "tests"], cwd=root, capture_output=True, text=True, env=env, timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")):
            out[line.split()[1]] = line.split()[0].lower()
    return p, out


def _counts(stdout):
    """(reused, ran) of a cached run's summary (serial: one line; -n: the controller's)."""
    reused = sum(int(x) for x in re.findall(r"reused (\d+) result", stdout))
    ran = re.findall(r"ran (\d+)", stdout)
    return reused, (int(ran[-1]) if ran else None)


def _project(ch, trigger, grouped):
    """The files of the cold run and of the warm run's change."""
    c = CH[ch]
    mark = "@pytest.mark.xdist_group('g')\n" if grouped else ""
    head = "import helper\n" + ("import pytest\n" if grouped or "fixture" in c or "fixture_module" in c else "")
    imports = (c.get("imports", "") + "\n") if c.get("imports") else ""
    poll = head + imports + "\n\n"
    if "fixture" in c:
        poll += f"@pytest.fixture\ndef fx():\n{c['fixture']}\n\n"
    if "fixture_module" in c:
        poll += f"@pytest.fixture(scope='module', autouse=True)\ndef fxm():\n{c['fixture_module']}\n\n"
    for i, body in enumerate(c["polluters"]):
        arg = "fx" if "fixture" in c else ""
        poll += f"{mark}def test_a{i}({arg}):\n    {body}\n\n\n"
    pre = textwrap.indent(c.get("pre", ""), "    ")
    sign = "not " if trigger == "fail" else ""
    victim = (head + imports + f"\n\n{mark}def test_victim():\n{pre}\n    assert {sign}({c['after']})\n")
    base = {"pytest.ini": INI, "helper.py": "STATE = {'mode': 'good'}\n" + c.get("helper", ""),
            "tests/a/test_a.py": poll, "tests/z/test_z.py": "def test_z():\n    pass\n", **c.get("extra", {})}
    if trigger == "new":
        return base, {"tests/b/test_b.py": victim}
    cold = {**base, "tests/b/test_b.py": victim}
    if trigger == "edit":
        return cold, {"tests/b/test_b.py": victim + "# edited between the runs\n"}
    return cold, {}


@pytest.mark.parametrize("par", list(PARS), ids=list(PARS))
@pytest.mark.parametrize("trigger", TRIGGERS)
@pytest.mark.parametrize("ch", list(CH))
def test_running_victim_sees_the_state_of_the_full_prefix(tmp_path, ch, trigger, par):
    args = PARS[par]
    cold, change = _project(ch, trigger, grouped=bool(args))
    cache = f"--det-cache={tmp_path / '.c'}"
    _write(tmp_path, cold)
    p1, _ = _pytest(tmp_path, "--det", cache, *args)
    assert p1.returncode in (0, 1), p1.stdout[-2000:]
    _write(tmp_path, change)
    p2, o2 = _pytest(tmp_path, "--det", cache, *args)
    det, do = _pytest(tmp_path, "--det", *args)
    want = "failed" if trigger == "fail" else "passed"
    assert do.get(VICTIM) == want, f"precondition: uncached --det gives {VICTIM} {do.get(VICTIM)}:\n{det.stdout[-2000:]}"
    assert o2 == do, (f"--det-cache reports {o2} (exit {p2.returncode}); uncached --det reports {do} "
                      f"(exit {det.returncode}):\n{p2.stdout[-2500:]}")
    assert p2.returncode == det.returncode


# -- reuse targets of phase 2 -------------------------------------------------------------------------------------

PHASE2 = pytest.mark.xfail(strict=True, reason="P-061 phase 2: precise tracking not implemented (every earlier test "
                                               "of the process reruns)")
N_FILES, N_TESTS = 3, 10


def _quiet_suite(modifier: bool):
    """N_FILES files of N_TESTS tests that leave no state behind (they reach helper and pytest, a library), plus
    optionally one modifier; tests/y holds the trigger."""
    files = {"pytest.ini": INI, "helper.py": "STATE = {'mode': 'good'}\nCOUNT = [0]\n"}
    for f in range(N_FILES):
        body = "import helper\nimport pytest\n\n"
        for t in range(N_TESTS):
            body += (f"@pytest.mark.parametrize('x', [1])\ndef test_{t}(x, monkeypatch):\n"
                     "    monkeypatch.setattr(helper, 'STATE', {'mode': 'tmp'})\n"
                     "    assert helper.STATE['mode'] == 'tmp' and x == 1\n\n\n")
        files[f"tests/f{f}/test_f{f}.py"] = body
    if modifier:
        files["tests/m/test_m.py"] = "import helper\n\n\ndef test_m():\n    helper.COUNT[0] += 1\n"
    return files


def _reuse_case(tmp_path, change, par, modifier=False):
    args = PARS[par]
    cache = f"--det-cache={tmp_path / '.c'}"
    _write(tmp_path, _quiet_suite(modifier))
    for name, text in change.get("cold", {}).items():
        _write(tmp_path, {name: text})
    _pytest(tmp_path, "--det", cache, *args)
    _write(tmp_path, change.get("warm", {}))
    p, o = _pytest(tmp_path, "--det", cache, *args)
    det, do = _pytest(tmp_path, "--det", *args)
    assert o == do, f"--det-cache reports {o}; uncached --det reports {do}:\n{p.stdout[-2000:]}"
    return _counts(p.stdout), p.stdout


@PHASE2
@pytest.mark.parametrize("par", list(PARS), ids=list(PARS))
def test_reuse_a_failing_test_reruns_alone(tmp_path, par):
    fail = {"tests/y/test_y.py": "import helper\n\n\ndef test_fails():\n    assert helper.COUNT == [7]\n"}
    (reused, ran), out = _reuse_case(tmp_path, {"cold": fail}, par)
    assert ran == 1 and reused == N_FILES * N_TESTS, f"reused {reused}, ran {ran}:\n{out[-1500:]}"


@PHASE2
@pytest.mark.parametrize("par", list(PARS), ids=list(PARS))
def test_reuse_a_failing_test_reruns_with_its_one_modifier(tmp_path, par):
    """the modifier writes helper.COUNT, which the failing test reads: both run, nothing else"""
    fail = {"tests/y/test_y.py": "import helper\n\n\ndef test_fails():\n    assert helper.COUNT == [7]\n"}
    (reused, ran), out = _reuse_case(tmp_path, {"cold": fail}, par, modifier=True)
    assert ran == 2 and reused == N_FILES * N_TESTS, f"reused {reused}, ran {ran}:\n{out[-1500:]}"


@PHASE2
@pytest.mark.parametrize("par", list(PARS), ids=list(PARS))
def test_reuse_a_new_test_runs_alone(tmp_path, par):
    new = {"tests/y/test_y.py": "import helper\n\n\ndef test_new():\n    assert helper.COUNT == [0]\n"}
    (reused, ran), out = _reuse_case(tmp_path, {"warm": new}, par)
    assert ran == 1 and reused == N_FILES * N_TESTS, f"reused {reused}, ran {ran}:\n{out[-1500:]}"


@PHASE2
@pytest.mark.parametrize("par", list(PARS), ids=list(PARS))
def test_reuse_an_edited_test_file_reruns_its_own_tests_only(tmp_path, par):
    """a comment added to the first file: at most that file's tests run; every later file is reused"""
    first = "tests/f0/test_f0.py"
    text = _quiet_suite(False)[first]
    (reused, ran), out = _reuse_case(tmp_path, {"warm": {first: text + "# edited\n"}}, par)
    assert ran <= N_TESTS and reused >= (N_FILES - 1) * N_TESTS, f"reused {reused}, ran {ran}:\n{out[-1500:]}"
