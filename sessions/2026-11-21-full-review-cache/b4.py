import sys, os; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
S = []
CA = open("HERE/ca1.pem").read()
BADCA = "-----BEGIN CERTIFICATE-----\ngarbage\n-----END CERTIFICATE-----\n"
def one(name, files, v2=None, ctx1=None, ctx2=None, modes=("serial", "n2")):
    for m in modes:
        S.append(dict(name=name, v1={"tests/a/test_a.py": "def test_a():\n    pass\n", **files}, v2=v2, mode=m, ctx1=ctx1 or {}, ctx2=ctx2 or {}))
T = lambda body, imp="import os, posix": {"tests/b/test_b.py": imp + "\n\ndef test_victim():\n" + "".join("    " + l + "\n" for l in body.splitlines())}
one("F1 os.open + os.read content", {"data.txt": "good", **T("fd = os.open('data.txt', os.O_RDONLY)\nassert os.read(fd, 10) == b'good'")}, v2={"data.txt": "bad!"})
one("F2 posix.open + posix.read content", {"data.txt": "good", **T("fd = posix.open('data.txt', posix.O_RDONLY)\nassert posix.read(fd, 10) == b'good'")}, v2={"data.txt": "bad!"})
one("F3 OpenSSL load_verify_locations on a context", {"ca.pem": CA, **T("import ssl\nc = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\nc.load_verify_locations('ca.pem')", "")}, v2={"ca.pem": BADCA})
one("F4 dbm.ndbm/gnu reading a db file (C)", {"mk.py": "", **T("import dbm.dumb as d\nassert True", "")})
one("F5 helper module runs a child process at import that reads a file", {"helper.py": "import subprocess\nV = subprocess.check_output(['cat', 'ver.txt']).decode().strip()\n", "ver.txt": "1", **T("import helper\nassert helper.V == '1'", "")}, v2={"ver.txt": "2"})
one("F6 conftest runs a child process at import that reads a file", {"tests/b/conftest.py": "import subprocess, helper\nhelper.V = subprocess.check_output(['cat', 'ver.txt']).decode().strip()\n", "helper.py": "V = None\n", "ver.txt": "1", **T("import helper\nassert helper.V == '1'", "")}, v2={"ver.txt": "2"})
one("F7 sqlite3 database content", {"db.py": "", **T("import sqlite3\nc = sqlite3.connect('d.db')\nassert c.execute('select v from t').fetchone()[0] == 'good'", "")})
S = [s for s in S if not s["name"].startswith(("F4", "F7"))]
# sqlite: build db files
import sqlite3, tempfile
def mkdb(path, v):
    if os.path.exists(path): os.unlink(path)
    c = sqlite3.connect(path); c.execute("create table t(v)"); c.execute("insert into t values (?)", (v,)); c.commit(); c.close()
for m in ("serial", "n2"):
    S.append(dict(name="F7 sqlite3 database content", mode=m, v1={"tests/a/test_a.py": "def test_a():\n    pass\n", **T("import sqlite3\nc = sqlite3.connect('d.db')\nassert c.execute('select v from t').fetchone()[0] == 'good'", "")},
                  ctx1={}, ctx2={}, between=lambda root: mkdb(str(root / "d.db"), "bad")))
    S[-1]["v1"]["mkdb"] = ""
import h56
_orig = h56.write
def w2(root, files):
    _orig(root, files)
    if "mkdb" in files: mkdb(str(root / "d.db"), "good")
h56.write = w2
run_all(S, workers=8)
