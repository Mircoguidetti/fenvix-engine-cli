import sys, os; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import scenario, show
SP = open("HERE/sp.txt").read().strip()
d = os.path.join(SP, "r056plug-1.0.dist-info"); os.makedirs(d, exist_ok=True)
open(os.path.join(d, "METADATA"), "w").write("Metadata-Version: 2.1\nName: r056plug\nVersion: 1.0\n")
open(os.path.join(d, "RECORD"), "w").write("r056plug.py,,\n")
open(os.path.join(d, "entry_points.txt"), "w").write("[pytest11]\nr056plug = r056plug\n")
mod = os.path.join(SP, "r056plug.py")
try:
    for mode in ("serial", "n2"):
        open(mod, "w").write("X = 1\n")
        r = scenario("G8 entry-point pytest plugin edited in place (same version)", {"tests/a/test_a.py": "def test_a():\n    pass\n",
             "tests/b/test_b.py": "import builtins\n\ndef test_victim():\n    assert not hasattr(builtins, 'R056')\n"}, mode=mode,
             between=lambda root: open(mod, "w").write("import builtins\nbuiltins.R056 = 1\n"))
        show(r)
finally:
    import shutil; shutil.rmtree(d); os.unlink(mod)
