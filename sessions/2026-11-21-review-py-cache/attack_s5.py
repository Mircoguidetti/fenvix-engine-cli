import sys; sys.path.insert(0, sys.argv[1]); from harness import scenario
BEN = "def test_a():\n    pass\n"
def go(name, a2, vic, a1=BEN, extra={}):
    scenario(name, {**extra, "tests/test_a.py": a1, "tests/test_b.py": vic}, {"tests/test_a.py": a2})
# file channel (no imports anywhere)
go("C1 file: earlier test starts writing a file the later test reads",
   "def test_a():\n    with open('flag.txt', 'w') as f:\n        f.write('bad')\n",
   "def test_victim():\n    try:\n        with open('flag.txt') as f:\n            assert f.read() != 'bad'\n    except FileNotFoundError:\n        pass\n")
# env var: later test reads the environment (reaches a library: every earlier test is carried)
go("C2 env var: earlier test starts setting it",
   "import os\n\ndef test_a():\n    os.environ['R052_MODE'] = 'bad'\n",
   "import os\n\ndef test_victim():\n    assert os.environ.get('R052_MODE') != 'bad'\n")
# interpreter C state read with no import by the victim (recursion limit)
go("C3 C state (recursion limit), victim imports nothing",
   "import sys\n\ndef test_a():\n    sys.setrecursionlimit(120)\n",
   "def r(n):\n    return 0 if n == 0 else r(n - 1)\n\ndef test_victim():\n    assert r(400) == 0\n")
# C extension state (decimal context)
go("C4 C extension state (decimal context), victim imports decimal",
   "import decimal\n\ndef test_a():\n    decimal.getcontext().prec = 3\n",
   "import decimal\n\ndef test_victim():\n    assert str(decimal.Decimal(1) / decimal.Decimal(7)).startswith('0.142857')\n")
# PY-08: earlier test starts a subprocess that writes a file the later test reads
go("C5 PY-08 subprocess: earlier test's child process writes the file",
   "import subprocess, sys\n\ndef test_a():\n    subprocess.run([sys.executable, '-c', \"open('flag.txt','w').write('bad')\"], check=True)\n",
   "def test_victim():\n    try:\n        with open('flag.txt') as f:\n            assert f.read() != 'bad'\n    except FileNotFoundError:\n        pass\n")
# PY-08: later test not cacheable (subprocess inherits env); earlier test starts setting env
go("C6 PY-08 later test's child process inherits an env var the earlier test starts setting",
   "import os\n\ndef test_a():\n    os.environ['R052_MODE'] = 'bad'\n",
   "import subprocess, sys\n\ndef test_victim():\n    subprocess.run([sys.executable, '-c', \"import os; assert os.environ.get('R052_MODE') != 'bad'\"], check=True)\n")
