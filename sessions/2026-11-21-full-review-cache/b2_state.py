import sys; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
S = []
def add(name, a_body, victim, good, bad, extra=None, modes=("serial", "n2", "n1")):
    a = "import os, sys\n\ndef test_a():\n    v = open(os.path.join(os.path.dirname(__file__), '..', '..', 'mode.txt')).read().strip()\n" + "".join("    " + l + "\n" for l in a_body.splitlines())
    v1 = {"helper.py": "STATE = {'mode': 'good'}\n", "tests/a/test_a.py": a, "tests/b/test_b.py": victim, "mode.txt": good, **(extra or {})}
    for m in modes:
        S.append(dict(name=name, v1=v1, v2={"mode.txt": bad}, mode=m))
add("D1 recursion limit", "sys.setrecursionlimit(int(v))",
    "def r(n):\n    return 0 if n == 0 else r(n - 1)\n\ndef test_victim():\n    assert r(400) == 0\n", "1000", "120")
add("D2 control: repository module global", "import helper\nhelper.STATE['mode'] = v",
    "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n", "good", "bad")
add("D3 os.environ write", "os.environ['R056_MODE'] = v",
    "import os\n\ndef test_victim():\n    assert os.environ.get('R056_MODE', 'good') == 'good'\n", "good", "bad")
add("D4 cwd (chdir)", "os.chdir(os.path.join(os.path.dirname(__file__), '..', '..', v))",
    "import os\n\ndef test_victim():\n    assert os.path.basename(os.getcwd()) != 'sub'\n", ".", "sub", {"sub/x.txt": "x"})
add("D5 umask", "os.umask(int(v, 8))",
    "import os\n\ndef test_victim():\n    m = os.umask(0o022)\n    assert m == 0o022\n", "022", "077")
add("D6 signal handler", "import signal\nsignal.signal(signal.SIGUSR1, signal.SIG_IGN if v == 'bad' else signal.SIG_DFL)",
    "import signal\n\ndef test_victim():\n    assert signal.getsignal(signal.SIGUSR1) == signal.SIG_DFL\n", "good", "bad")
add("D7 logging.disable", "import logging\nlogging.disable(logging.CRITICAL if v == 'bad' else logging.NOTSET)",
    "import logging\n\ndef test_victim():\n    assert logging.root.manager.disable == 0\n", "good", "bad")
add("D8 decimal context (C)", "import decimal\ndecimal.getcontext().prec = int(v)",
    "import decimal\n\ndef test_victim():\n    assert decimal.getcontext().prec == 28\n", "28", "5")
add("D9 sys.modules injection", "import types\nif v == 'bad':\n    sys.modules['r056zzz'] = types.ModuleType('r056zzz')",
    "import sys\n\ndef test_victim():\n    assert 'r056zzz' not in sys.modules\n", "good", "bad")
add("D10 sys.path append", "if v == 'bad':\n    sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'extra'))",
    "def test_victim():\n    try:\n        import extramod\n    except ImportError:\n        return\n    assert False, 'extramod importable'\n", "good", "bad", {"extra/extramod.py": "X = 1\n"})
add("D12 rlimit NOFILE", "import resource\ns, h = resource.getrlimit(resource.RLIMIT_NOFILE)\nresource.setrlimit(resource.RLIMIT_NOFILE, (int(v), h))",
    "import resource\n\ndef test_victim():\n    assert resource.getrlimit(resource.RLIMIT_NOFILE)[0] >= 1000\n", "1024", "512")
add("D14 gc.disable", "import gc\ngc.disable() if v == 'bad' else gc.enable()",
    "import gc\n\ndef test_victim():\n    assert gc.isenabled()\n", "good", "bad")
add("D22 builtins attribute", "import builtins\nif v == 'bad':\n    builtins.R056 = 1",
    "import builtins\n\ndef test_victim():\n    assert not hasattr(builtins, 'R056')\n", "good", "bad")
add("D23 int max str digits", "sys.set_int_max_str_digits(int(v))",
    "def test_victim():\n    assert len(str(10 ** 5000)) == 5001\n", "0", "4300")
add("D26 socket default timeout", "import socket\nsocket.setdefaulttimeout(None if v == 'good' else 3.0)",
    "import socket\n\ndef test_victim():\n    assert socket.getdefaulttimeout() is None\n", "good", "bad")
add("D27 locale.setlocale", "import locale\nlocale.setlocale(locale.LC_NUMERIC, 'C' if v == 'good' else 'C.UTF-8')",
    "import locale\n\ndef test_victim():\n    assert locale.setlocale(locale.LC_NUMERIC) == 'C'\n", "good", "bad")
add("D28 written file (in-process write)", "open(os.path.join(os.path.dirname(__file__), '..', '..', 'flag.txt'), 'w').write(v)",
    "import os\n\ndef test_victim():\n    p = os.path.join(os.path.dirname(__file__), '..', '..', 'flag.txt')\n    assert open(p).read() == 'good'\n", "good", "bad")
add("D29 sys.setswitchinterval", "sys.setswitchinterval(float(v))",
    "import sys\n\ndef test_victim():\n    assert sys.getswitchinterval() == 0.005\n", "0.005", "0.01")
add("D30 os.environ delete", "if v == 'bad':\n    os.environ.pop('HOME', None)",
    "import os\n\ndef test_victim():\n    assert 'HOME' in os.environ\n", "good", "bad")
add("D31 sys.stdout replaced (C-level print target)", "import io\nif v == 'bad':\n    sys.__dict__['dont_write_bytecode'] = True",
    "import sys\n\ndef test_victim():\n    assert not sys.dont_write_bytecode\n", "good", "bad")
run_all(S, workers=8)
