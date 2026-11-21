"""Item 3: the placement or the mode changes between the recording run and the cached run."""
import sys; sys.path.insert(0, sys.argv[1]); from h53 import scenario2
H = {"helper.py": "STATE = {'mode': 'good'}\n"}
POL = "import helper\n\ndef test_a():\n    helper.STATE['mode'] = 'bad'\n"
BEN = "def test_a():\n    pass\n"
VIC = "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n"
N2, N1 = ("-n", "2"), ("-n", "1")
ISO, ISOF = ("--det-isolate",), ("--det-isolate", "--det-isolate-scope=file")
base = {**H, "tests/test_a.py": POL, "tests/test_b.py": VIC}
# no code change: only the placement / mode
for p1, p2 in ((N2, N1), (N2, ()), (ISO, ()), (ISO, N1), (ISOF, ()), (ISOF, N1)):
    scenario2("P0 no edit, polluter always there", base, {}, p1, p2)
# S1-style edit plus a placement / mode change
for p1, p2 in ((N2, N1), (N2, ()), (ISO, ()), (ISO, N1), (ISOF, ()), (ISOF, N1)):
    scenario2("P1 earlier test edited to pollute", {**H, "tests/test_a.py": BEN, "tests/test_b.py": VIC},
              {"tests/test_a.py": POL}, p1, p2)
