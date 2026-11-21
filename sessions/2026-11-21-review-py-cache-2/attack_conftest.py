"""New finding K1: a conftest.py in the earlier test's directory (test files unchanged) starts writing the state."""
import sys; sys.path.insert(0, sys.argv[1]); from h53 import scenario
par = tuple(sys.argv[2:])
H = {"helper.py": "STATE = {'mode': 'good'}\n", "tests/a/test_a.py": "def test_a():\n    pass\n"}
VIC = "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n"
AUTO = "import pytest, helper\n\n@pytest.fixture(autouse=True)\ndef pol():\n    helper.STATE['mode'] = 'bad'\n"
scenario("K1 new tests/a/conftest.py, autouse fixture writes the state", {**H, "tests/b/test_b.py": VIC},
         {"tests/a/conftest.py": AUTO}, par)
scenario("K1c existing tests/a/conftest.py, empty autouse fixture edited to write the state",
         {**H, "tests/a/conftest.py": "import pytest\n\n@pytest.fixture(autouse=True)\ndef pol():\n    pass\n",
          "tests/b/test_b.py": VIC}, {"tests/a/conftest.py": AUTO}, par)
scenario("K1d new tests/a/conftest.py writes the state at import (collection)", {**H, "tests/b/test_b.py": VIC},
         {"tests/a/conftest.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"}, par)
scenario("K1e new tests/a/conftest.py, autouse fixture lowers the recursion limit (C state, victim imports nothing)",
         {**H, "tests/b/test_b.py": "def r(n):\n    return 0 if n == 0 else r(n - 1)\n\ndef test_victim():\n    assert r(400) == 0\n"},
         {"tests/a/conftest.py": "import pytest, sys\n\n@pytest.fixture(autouse=True)\ndef pol():\n    sys.setrecursionlimit(120)\n"}, par)
scenario("K1f new tests/a/conftest.py, autouse fixture writes a file the victim reads",
         {**H, "tests/b/test_b.py": "import os\n\ndef test_victim():\n    assert not os.path.exists('flag.txt')\n"},
         {"tests/a/conftest.py": "import pytest\n\n@pytest.fixture(autouse=True)\ndef pol():\n    open('flag.txt', 'w').write('bad')\n"}, par)
