import sys; sys.path.insert(0, sys.argv[1]); from h53 import scenario as _sc
par = tuple(sys.argv[2:])
scenario = lambda n, a, b: _sc(n, a, b, par)
H = {"pkg/__init__.py": "", "helper.py": "STATE = {'mode': 'good'}\n"}
POL = "import helper as H_; STATE = H_.STATE\n\ndef test_a():\n    STATE['mode'] = 'bad'\n"
BEN = "def test_a():\n    pass\n"
VIC = "import helper as H_; STATE = H_.STATE\n\ndef test_victim():\n    assert STATE['mode'] == 'good'\n"
FAIL0 = "def test_victim():\n    assert 0\n"
SUB0 = "import subprocess, sys\n\ndef test_victim():\n    subprocess.run([sys.executable, '-c', 'pass'], check=True)\n"
OTH = "def test_0():\n    assert 1\n"
# S1: only the earlier test changes (benign -> polluter); the victim passed and has an entry
scenario("S1 earlier test starts polluting, victim had an entry",
         {**H, "tests/test_a.py": BEN, "tests/test_b.py": VIC}, {"tests/test_a.py": POL})
# S3: victim failed in run 1 for its own reason (loose needs computed from its old code); victim edited
scenario("S3 victim failed (no entry), victim edited to read the polluted state",
         {**H, "tests/test_a.py": POL, "tests/test_b.py": FAIL0}, {"tests/test_b.py": VIC})
# S4: same, victim was not cacheable (subprocess)
scenario("S4 victim not cacheable (subprocess), then edited to read the polluted state",
         {**H, "tests/test_a.py": POL, "tests/test_b.py": SUB0}, {"tests/test_b.py": VIC})
# S5: victim had an entry (passed, reads nothing), then edited to read the polluted state
scenario("S5 victim passed (entry) reading nothing, then edited to read the polluted state",
         {**H, "tests/test_a.py": POL, "tests/test_b.py": "def test_victim():\n    assert 1\n"}, {"tests/test_b.py": VIC})
