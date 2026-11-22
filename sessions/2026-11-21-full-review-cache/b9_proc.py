import sys, os, shutil; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
S = []
LIB = open("HERE/clib/librd.so", "rb").read()
def cp_lib(root, dst):
    os.makedirs(os.path.dirname(root / dst), exist_ok=True); shutil.copy("HERE/clib/librd.so", root / dst)
for m in ("serial", "n2"):
    S.append(dict(name="P3 conftest child (at import) writes a file the victim reads", mode=m,
        v1={"ver.txt": "1", "tests/conftest.py": "import subprocess\nsubprocess.run(['sh', '-c', 'cat ver.txt > out.txt'])\n",
            "tests/b/test_b.py": "def test_victim():\n    assert open('out.txt').read().strip() == '1'\n"}, v2={"ver.txt": "2"}, ctx1={"clean": ["out.txt"]}))
    S.append(dict(name="P5 test forks; child reads a file, exit code is the result", mode=m,
        v1={"ver.txt": "1", "tests/b/test_b.py": "import os\n\ndef test_victim():\n    pid = os.fork()\n    if pid == 0:\n        os._exit(0 if open('ver.txt').read().strip() == '1' else 1)\n    assert os.waitpid(pid, 0)[1] == 0\n"}, v2={"ver.txt": "2"}))
    S.append(dict(name="P6 repository native library (ctypes) reads a file in C", mode=m,
        v1={"ver.txt": "1", "tests/b/test_b.py": "import ctypes\n\ndef test_victim():\n    lib = ctypes.CDLL('./lib/librd.so')\n    assert lib.first_char(b'ver.txt') == ord('1')\n"}, v2={"ver.txt": "2"},
        between=None))
    S.append(dict(name="P7 installed (out-of-repo) native library reads a file in C", mode=m,
        v1={"ver.txt": "1", "tests/b/test_b.py": "import ctypes\n\ndef test_victim():\n    lib = ctypes.CDLL('HERE/clib/librd.so')\n    assert lib.first_char(b'ver.txt') == ord('1')\n"}, v2={"ver.txt": "2"}))
import h56
_w = h56.write
def w2(root, files):
    _w(root, files)
    if "tests/b/test_b.py" in files and "./lib/librd.so" in files["tests/b/test_b.py"]:
        cp_lib(root, "lib/librd.so")
h56.write = w2
run_all(S, workers=8)
