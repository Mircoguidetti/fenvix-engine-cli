"""New: the earlier test starts polluting through a NON-test file (conftest, helper module, data, child process),
test files unchanged; and C5's second cause (a followed child's write) without any test-file edit."""
import sys; sys.path.insert(0, sys.argv[1]); from h53 import scenario
par = tuple(sys.argv[2:])
H = {"helper.py": "STATE = {'mode': 'good'}\n"}
VIC = "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n"
FLAGV = ("def test_victim():\n    try:\n        with open('flag.txt') as f:\n            assert f.read() != 'bad'\n"
         "    except FileNotFoundError:\n        pass\n")
# K1: a new conftest in the earlier test's directory, autouse fixture writes the state
scenario("K1 new conftest (autouse) in the earlier test's dir",
         {**H, "tests/a/test_a.py": "def test_a():\n    pass\n", "tests/b/test_b.py": VIC},
         {"tests/a/conftest.py": "import pytest, helper\n\n@pytest.fixture(autouse=True)\ndef pol():\n"
                                 "    helper.STATE['mode'] = 'bad'\n"}, par)
# K1b: an existing conftest fixture the earlier test requests, its body edited
scenario("K1b conftest fixture body edited",
         {**H, "tests/a/conftest.py": "import pytest\n\n@pytest.fixture\ndef fx():\n    pass\n",
          "tests/a/test_a.py": "def test_a(fx):\n    pass\n", "tests/b/test_b.py": VIC},
         {"tests/a/conftest.py": "import pytest, helper\n\n@pytest.fixture\ndef fx():\n    helper.STATE['mode'] = 'bad'\n"}, par)
# K2: a helper module only the earlier test uses, edited to write the state
scenario("K2 non-test module of the earlier test edited",
         {**H, "tools.py": "def setup():\n    pass\n", "tests/test_a.py": "import tools\n\ndef test_a():\n    tools.setup()\n",
          "tests/test_b.py": VIC},
         {"tools.py": "import helper\n\ndef setup():\n    helper.STATE['mode'] = 'bad'\n"}, par)
# K2b: C state through a non-test module
scenario("K2b non-test module starts changing the recursion limit",
         {"tools.py": "def setup():\n    pass\n", "tests/test_a.py": "import tools\n\ndef test_a():\n    tools.setup()\n",
          "tests/test_b.py": "def r(n):\n    return 0 if n == 0 else r(n - 1)\n\ndef test_victim():\n    assert r(400) == 0\n"},
         {"tools.py": "import sys\n\ndef setup():\n    sys.setrecursionlimit(120)\n"}, par)
# K3: C5 second cause, no test-file edit: a config module makes the earlier test start a writing child
scenario("K3 config module turns on a child that writes the file the victim reads",
         {"cfg.py": "WRITE = False\n", "tests/test_b.py": FLAGV,
          "tests/test_a.py": "import subprocess, sys, cfg\n\ndef test_a():\n    if cfg.WRITE:\n"
                             "        subprocess.run([sys.executable, '-c', \"open('flag.txt', 'w').write('bad')\"], check=True)\n"},
         {"cfg.py": "WRITE = True\n"}, par)
# K4: the earlier test always starts a child (runs every time); the child copies src.txt when it exists; src.txt added
scenario("K4 child copies a data file that appears",
         {"tests/test_b.py": FLAGV,
          "tests/test_a.py": "import subprocess, sys\n\ndef test_a():\n    subprocess.run([sys.executable, '-c', "
                             "\"import os, shutil; os.path.exists('src.txt') and shutil.copy('src.txt', 'flag.txt')\"], check=True)\n"},
         {"src.txt": "bad"}, par)
# K5: same as K4, the earlier test is cacheable in run 1 (no child), the data file appears; the in-process copy
scenario("K5 in-process copy of a data file that appears",
         {"tests/test_b.py": FLAGV,
          "tests/test_a.py": "import os, shutil\n\ndef test_a():\n    os.path.exists('src.txt') and shutil.copy('src.txt', 'flag.txt')\n"},
         {"src.txt": "bad"}, par)
