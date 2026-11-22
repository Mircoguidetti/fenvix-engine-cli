import sys, os; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import h56
from h56 import scenario, show
SP = open("HERE/sp.txt").read().strip()
def put(rel, text):
    p = os.path.join(SP, rel)
    if text is None:
        if os.path.exists(p): os.unlink(p)
    else:
        open(p, "w").write(text)
VB = "import builtins\n\ndef test_victim():\n    assert not hasattr(builtins, 'R056')\n"
POISON = "import builtins\nbuiltins.R056 = 1\n"
CASES = [
 ("G1 installed dist module edited in place (same version)", {"r056lib.py": "MODE = 'good'\n"}, {"r056lib.py": "MODE = 'bad'\n"}, "import r056lib\n\ndef test_victim():\n    assert r056lib.MODE == 'good'\n"),
 ("G2 sitecustomize added", {"sitecustomize.py": None}, {"sitecustomize.py": POISON}, VB),
 ("G3 sitecustomize edited", {"sitecustomize.py": "X = 1\n"}, {"sitecustomize.py": POISON}, VB),
 ("G4 .pth import line added", {"r056pth.py": POISON, "r056.pth": None}, {"r056.pth": "import r056pth\n"}, VB),
 ("G5 module run by an unchanged .pth edited", {"r056pth.py": "X = 1\n", "r056.pth": "import r056pth\n"}, {"r056pth.py": POISON}, VB),
 ("G7 loose module in site-packages (no dist) edited", {"r056loose.py": "MODE = 'good'\n"}, {"r056loose.py": "MODE = 'bad'\n"}, "import r056loose\n\ndef test_victim():\n    assert r056loose.MODE == 'good'\n"),
]
allf = {"r056lib.py", "sitecustomize.py", "r056pth.py", "r056.pth", "r056loose.py"}
for name, before, after, victim in CASES:
    for mode in ("serial", "n2"):
        for f in allf - {"r056lib.py"}: put(f, None)
        put("r056lib.py", "MODE = 'good'\n")
        for k, v in before.items(): put(k, v)
        r = scenario(name, {"tests/a/test_a.py": "def test_a():\n    pass\n", "tests/b/test_b.py": victim}, mode=mode,
                     between=lambda root, after=after: [put(k, v) for k, v in after.items()])
        show(r)
for f in allf - {"r056lib.py"}: put(f, None)
put("r056lib.py", "MODE = 'good'\n")
