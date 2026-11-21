import sys; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
HELPER = "STATE = {'mode': 'good'}\n"
BASE = {"helper.py": HELPER, "tests/a/test_a.py": "def test_a():\n    pass\n",
        "tests/b/test_b.py": "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n"}
S = []
def add(name, v1, v2, modes=("serial", "n2", "n1")):
    for m in modes:
        S.append(dict(name=name, v1={**BASE, **v1}, v2=v2, mode=m))
add("A16 later test's decorator module: decorator body changes", {"zdeco.py": "def deco(f):\n    return f\n", "tests/z/test_z.py": "import zdeco\n\n@zdeco.deco\ndef test_z():\n    pass\n"},
    {"zdeco.py": "import helper\n\ndef deco(f):\n    helper.STATE['mode'] = 'bad'\n    return f\n"})
add("A18 later test's metaclass module changes", {"zmeta.py": "class Meta(type):\n    pass\n", "tests/z/test_z.py": "import zmeta\n\nclass TestZ(metaclass=zmeta.Meta):\n    def test_z(self):\n        pass\n"},
    {"zmeta.py": "import helper\n\nclass Meta(type):\n    def __new__(m, *a):\n        helper.STATE['mode'] = 'bad'\n        return super().__new__(m, *a)\n"})
add("A21 module imported by a later conftest changes", {"zcfg.py": "X = 1\n", "tests/z/conftest.py": "import zcfg\n", "tests/z/test_z.py": "def test_z():\n    pass\n"},
    {"zcfg.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"})
add("A21b module imported by an earlier conftest changes", {"zcfg.py": "X = 1\n", "tests/a/conftest.py": "import zcfg\n"},
    {"zcfg.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"})
add("A24 later conftest's fixture used only by its tests changes (control: needs)", {"tests/z/conftest.py": "import pytest\n\n@pytest.fixture\ndef fx():\n    return 1\n", "tests/z/test_z.py": "def test_z(fx):\n    pass\n"},
    {"tests/z/conftest.py": "import pytest, helper\n\n@pytest.fixture\ndef fx():\n    helper.STATE['mode'] = 'bad'\n    return 1\n"})
add("A2b conftest in a test-less dir collected first", {"tests/0/data.txt": "x"}, {"tests/0/conftest.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"})
add("A2c conftest in a test-less subdir of an earlier test dir", {"tests/a/sub/data.txt": "x"}, {"tests/a/sub/conftest.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"})
run_all(S, workers=8)
