"""Item 3: both files on the same -n 2 worker (xdist_group + --dist loadgroup; a third file for the other worker)."""
import sys; sys.path.insert(0, sys.argv[1]); from h53 import scenario
G = "import pytest\npytestmark = pytest.mark.xdist_group(name='g')\n"
H = {"helper.py": "STATE = {'mode': 'good'}\n", "tests/test_z.py": "import time\n\ndef test_z():\n    time.sleep(0.2)\n"}
POL = G + "import helper\n\ndef test_a():\n    helper.STATE['mode'] = 'bad'\n"
BEN = G + "def test_a():\n    pass\n"
VIC = G + "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n"
REC = G + "def r(n):\n    return 0 if n == 0 else r(n - 1)\n\ndef test_victim():\n    assert r(400) == 0\n"
FLAGV = G + ("def test_victim():\n    try:\n        with open('flag.txt') as f:\n            assert f.read() != 'bad'\n"
             "    except FileNotFoundError:\n        pass\n")
CHILD = G + ("import subprocess, sys\n\ndef test_a():\n    subprocess.run([sys.executable, '-c', "
             "\"open('flag.txt', 'w').write('bad')\"], check=True)\n")
for par in (("-n", "1"), ("-n", "2", "--dist", "loadgroup")):
    scenario("S1 same worker", {**H, "tests/test_a.py": BEN, "tests/test_b.py": VIC}, {"tests/test_a.py": POL}, par)
    scenario("S3 same worker", {**H, "tests/test_a.py": POL, "tests/test_b.py": G + "def test_victim():\n    assert 0\n"},
             {"tests/test_b.py": VIC}, par)
    scenario("S5 same worker", {**H, "tests/test_a.py": POL, "tests/test_b.py": G + "def test_victim():\n    assert 1\n"},
             {"tests/test_b.py": VIC}, par)
    scenario("C3 same worker", {**H, "tests/test_a.py": BEN, "tests/test_b.py": REC},
             {"tests/test_a.py": G + "import sys\n\ndef test_a():\n    sys.setrecursionlimit(120)\n"}, par)
    scenario("C5 same worker", {**H, "tests/test_a.py": BEN, "tests/test_b.py": FLAGV}, {"tests/test_a.py": CHILD}, par)
    # the edited file is collected AFTER the other worker's file but before the victim (code prefix superset)
    scenario("S1 same worker, other-worker file between", {**H, "tests/test_a.py": BEN, "tests/test_aa_other.py":
             "def test_o():\n    pass\n", "tests/test_b.py": VIC}, {"tests/test_a.py": POL}, par)
