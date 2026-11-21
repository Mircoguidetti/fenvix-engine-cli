import sys; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
HELPER = "STATE = {'mode': 'good'}\n\ndef poison(f=None):\n    STATE['mode'] = 'bad'\n    return f\n\nclass Poison:\n    def __init_subclass__(cls, **kw):\n        STATE['mode'] = 'bad'\n"
BASE = {"helper.py": HELPER, "tests/a/test_a.py": "def test_a():\n    pass\n",
        "tests/b/test_b.py": "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n",
        "tests/z/test_z.py": "def test_z():\n    pass\n"}
S = []
def add(name, v2, v1=None):
    for m in ("serial", "n2", "n1"):
        S.append(dict(name=name, v1={**BASE, **(v1 or {})}, v2=v2, mode=m))
add("A1 later conftest import-time write", {"tests/z/conftest.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"})
add("A2 conftest in a dir with no test files", {"tests/c/conftest.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"}, {"tests/c/data.txt": "x"})
add("A3 later __init__.py import-time write", {"tests/z/__init__.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"})
add("A4 later test file gains a bare decorator", {"tests/z/test_z.py": "import helper\n\n@helper.poison\ndef test_z():\n    pass\n"})
add("A6 later test file gains a module annotation", {"tests/z/test_z.py": "import helper\nX: helper.poison() = 1\n\ndef test_z():\n    pass\n"})
add("A6b later test file: return annotation", {"tests/z/test_z.py": "import helper\n\ndef test_z() -> helper.poison():\n    pass\n"})
add("A7 later test file's module changes import-time code", {"zmod.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"}, {"zmod.py": "import helper\n", "tests/z/test_z.py": "import zmod\n\ndef test_z():\n    pass\n"})
add("A8 -p plugin module changes", {"localplug.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"}, {"localplug.py": "import helper\n", "pytest.ini": "[pytest]\npythonpath = .\naddopts = -p localplug\n"})
add("A9 pytest_plugins module of root conftest changes", {"localplug.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"}, {"localplug.py": "import helper\n", "conftest.py": "pytest_plugins = ['localplug']\n"})
add("A11 later conftest: collection_modifyitems hook writes", {"tests/z/conftest.py": "import helper\n\ndef pytest_collection_modifyitems(items):\n    helper.STATE['mode'] = 'bad'\n"})
add("A12 later conftest: collection_finish hook writes", {"tests/z/conftest.py": "import helper\n\ndef pytest_collection_finish(session):\n    helper.STATE['mode'] = 'bad'\n"})
add("A14 later test class subclasses a base with __init_subclass__", {"tests/z/test_z.py": "import helper\n\nclass TestZ(helper.Poison):\n    def test_z(self):\n        pass\n"})
add("A15 control: later test file with an effect default arg", {"tests/z/test_z.py": "import helper\n\ndef test_z(x=helper.poison()):\n    pass\n"})
run_all(S, workers=8)
