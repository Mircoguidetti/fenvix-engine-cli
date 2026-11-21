"""C5 second cause: does a followed child's write withdraw the reuse of a later reader (no test-file edit)?"""
import sys; sys.path.insert(0, sys.argv[1]); import h53
from h53 import scenario
par = tuple(sys.argv[2:])
FLAGV = ("def test_victim():\n    try:\n        with open('flag.txt') as f:\n            assert f.read() != 'bad'\n"
         "    except FileNotFoundError:\n        pass\n")
_run = h53.run
def run(root, *a):
    r = _run(root, *a)
    print("   ", [l for l in r[3].splitlines() if l.startswith(("not reused", "not cacheable", "reused ", "withdrawn", "written"))])
    return r
h53.run = run
0 and scenario("K4 child copies a data file that appears",
         {"tests/test_b.py": FLAGV,
          "tests/test_a.py": "import subprocess, sys\n\ndef test_a():\n    subprocess.run([sys.executable, '-c', "
                             "\"import os, shutil; os.path.exists('src.txt') and shutil.copy('src.txt', 'flag.txt')\"], check=True)\n"},
         {"src.txt": "bad"}, par)
0 and scenario("K3 config module turns on a child that writes the file the victim reads",
         {"cfg.py": "WRITE = False\n", "tests/test_b.py": FLAGV,
          "tests/test_a.py": "import subprocess, sys, cfg\n\ndef test_a():\n    if cfg.WRITE:\n"
                             "        subprocess.run([sys.executable, '-c', \"open('flag.txt', 'w').write('bad')\"], check=True)\n"},
         {"cfg.py": "WRITE = True\n"}, par)
0 and scenario("K3i same, in-process write (control)",
         {"cfg.py": "WRITE = False\n", "tests/test_b.py": FLAGV,
          "tests/test_a.py": "import cfg\n\ndef test_a():\n    if cfg.WRITE:\n        open('flag.txt', 'w').write('bad')\n"},
         {"cfg.py": "WRITE = True\n"}, par)
scenario("K6 data file read at run time turns on a child that writes the file the victim reads",
         {"mode.txt": "no", "tests/test_b.py": FLAGV,
          "tests/test_a.py": "import subprocess, sys\n\ndef test_a():\n    if open('mode.txt').read() == 'spawn':\n"
                             "        subprocess.run([sys.executable, '-c', \"open('flag.txt', 'w').write('bad')\"], check=True)\n"},
         {"mode.txt": "spawn"}, par)
scenario("K6i same, in-process write (control)",
         {"mode.txt": "no", "tests/test_b.py": FLAGV,
          "tests/test_a.py": "def test_a():\n    if open('mode.txt').read() == 'spawn':\n        open('flag.txt', 'w').write('bad')\n"},
         {"mode.txt": "spawn"}, par)
