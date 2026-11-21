import sys; sys.path.insert(0, sys.argv[1]); from h53 import scenario
par = tuple(sys.argv[2:])
H = {"helper.py": "STATE = {'mode': 'good'}\n", "tests/a/test_a.py": "def test_a():\n    pass\n"}
VIC = "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n"
scenario("K1g existing tests/a/conftest.py gains an import-time write", {**H, "tests/b/test_b.py": VIC,
         "tests/a/conftest.py": "import helper\n"}, {"tests/a/conftest.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"}, par)
scenario("K1h new tests/a/test_new.py that writes the state", {**H, "tests/b/test_b.py": VIC},
         {"tests/a/test_new.py": "import helper\n\ndef test_new():\n    helper.STATE['mode'] = 'bad'\n"}, par)
scenario("K1i new tests/a/__init__.py writes the state at import", {**H, "tests/b/test_b.py": VIC},
         {"tests/a/__init__.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"}, par)
