import sys; sys.path.insert(0, sys.argv[1]); from h53 import scenario
par = tuple(sys.argv[2:])
H = {"helper.py": "STATE = {'mode': 'good'}\n"}
HDR = "import helper as H_\n\n"
POL = "def test_a():\n    H_.STATE['mode'] = 'bad'\n"
BEN = "def test_a():\n    pass\n"
VIC = "def test_victim():\n    assert H_.STATE['mode'] == 'good'\n"
FAIL0 = "def test_victim():\n    assert 0\n"
PASS0 = "def test_victim():\n    assert 1\n"
F = "tests/test_ab.py"
scenario("S1n earlier test starts polluting (same file)", {**H, F: HDR + BEN + "\n\n" + VIC}, {F: HDR + POL + "\n\n" + VIC}, par)
scenario("S3n victim failed, edited (same file)", {**H, F: HDR + POL + "\n\n" + FAIL0}, {F: HDR + POL + "\n\n" + VIC}, par)
scenario("S5n victim passed reading nothing, edited (same file)", {**H, F: HDR + POL + "\n\n" + PASS0}, {F: HDR + POL + "\n\n" + VIC}, par)
