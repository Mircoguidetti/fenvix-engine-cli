import sys; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
S = []
def add(name, imports, a_body, victim, good, bad, modes=("serial", "n2", "n1")):
    a = imports + "\n\ndef test_a():\n    v = open('mode.txt').read().strip()\n" + "".join("    " + l + "\n" for l in a_body.splitlines())
    v1 = {"tests/a/test_a.py": a, "tests/b/test_b.py": victim, "mode.txt": good}
    for m in modes:
        S.append(dict(name=name, v1=v1, v2={"mode.txt": bad}, mode=m))
add("D1p recursion limit", "import sys", "sys.setrecursionlimit(int(v))",
    "def r(n):\n    return 0 if n == 0 else r(n - 1)\n\ndef test_victim():\n    assert r(400) == 0\n", "1000", "120")
add("D5p umask (posix)", "import posix", "posix.umask(int(v, 8))",
    "import posix\n\ndef test_victim():\n    m = posix.umask(0o022)\n    assert m == 0o022\n", "022", "077")
add("D6p signal (_signal)", "import _signal", "_signal.signal(_signal.SIGUSR1, _signal.SIG_IGN if v == 'bad' else _signal.SIG_DFL)",
    "import _signal\n\ndef test_victim():\n    assert _signal.getsignal(_signal.SIGUSR1) == _signal.SIG_DFL\n", "good", "bad")
add("D22p builtins", "import builtins", "if v == 'bad':\n    builtins.R056 = 1\nelif hasattr(builtins, 'R056'):\n    del builtins.R056",
    "import builtins\n\ndef test_victim():\n    assert not hasattr(builtins, 'R056')\n", "good", "bad")
add("D23p int max str digits", "import sys", "sys.set_int_max_str_digits(int(v))",
    "def test_victim():\n    assert len(str(10 ** 5000)) == 5001\n", "0", "4300")
add("D14p gc", "import gc", "gc.disable() if v == 'bad' else gc.enable()",
    "import gc\n\ndef test_victim():\n    assert gc.isenabled()\n", "good", "bad")
add("D9p sys.modules", "import sys", "if v == 'bad':\n    sys.modules['r056zzz'] = sys",
    "import sys\n\ndef test_victim():\n    assert 'r056zzz' not in sys.modules\n", "good", "bad")
add("D4p chdir (posix)", "import posix", "posix.chdir(v)",
    "import posix\n\ndef test_victim():\n    assert 'mode.txt' in posix.listdir('.')\n", ".", "tests")
add("D3p putenv/environ (posix)", "import posix", "posix.putenv(b'R056', v.encode())",
    "import posix\n\ndef test_victim():\n    assert True\n", "good", "bad")
add("D32p rlimit (resource)", "import resource", "s, h = resource.getrlimit(resource.RLIMIT_NOFILE)\nresource.setrlimit(resource.RLIMIT_NOFILE, (int(v), h))",
    "import resource\n\ndef test_victim():\n    assert resource.getrlimit(resource.RLIMIT_NOFILE)[0] >= 1000\n", "1024", "512")
add("D33p file written in-process (builtin open)", "", "open('flag.txt', 'w').write(v)",
    "def test_victim():\n    assert open('flag.txt').read() == 'good'\n", "good", "bad")
run_all(S, workers=8)
