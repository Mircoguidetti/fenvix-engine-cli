import sys, os; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
S = []
def one(name, files, ctx1=None, ctx2=None, v2=None, modes=("serial", "n2")):
    for m in modes:
        S.append(dict(name=name, v1={"tests/a/test_a.py": "def test_a():\n    pass\n", **files}, v2=v2, mode=m, ctx1=ctx1 or {}, ctx2=ctx2 or {}))
T = lambda body, imp="import os, posix": {"tests/b/test_b.py": imp + "\n\ndef test_victim():\n" + "".join("    " + l + "\n" for l in body.splitlines())}
BIND = lambda src, dst: ("unshare", "-m", "sh", "-c", f'mount --bind {src} {dst} && exec "$@"', "sh")
one("E1 allowlisted env var via posix.environ (GITHUB_JOB)", T("assert posix.environ.get(b'GITHUB_JOB') == b'job1'"), {"env": {"GITHUB_JOB": "job1"}}, {"env": {"GITHUB_JOB": "job2"}})
one("E1c control: allowlisted env var via os.environ", T("assert os.environ.get('GITHUB_JOB') == 'job1'"), {"env": {"GITHUB_JOB": "job1"}}, {"env": {"GITHUB_JOB": "job2"}})
one("E1d allowlisted env var via os.environ._data", T("assert os.environ._data.get(b'GITHUB_JOB') == b'job1'"), {"env": {"GITHUB_JOB": "job1"}}, {"env": {"GITHUB_JOB": "job2"}})
one("E2 PWD via posix.environ", T("assert posix.environ.get(b'PWD', b'').endswith(b'/one')"), {"env": {"PWD": "/x/one"}}, {"env": {"PWD": "/x/two"}})
one("E3 cwd (same absolute args, other directory)", T("assert os.path.basename(os.getcwd()) != 'tests'"), {}, {"cwd": "tests"})
one("E3b cwd relative open", T("assert open('rel.txt').read() == 'root'", ""), {}, {"cwd": "tests"}, v2=None) if False else None
S.append(dict(name="E3b cwd: relative open", v1={"tests/a/test_a.py": "def test_a():\n    pass\n", "rel.txt": "root", "tests/rel.txt": "sub", **T("assert open('rel.txt').read() == 'root'", "")}, mode="serial", ctx1={}, ctx2={"cwd": "tests"}))
one("E4 posix.stat size", T("assert posix.stat('data.txt').st_size == 4"), v2={"data.txt": "12345678"}, **{}) if False else None
for nm, body in [("E4 posix.stat size", "assert posix.stat('data.txt').st_size == 4"),
                 ("E4b os.stat size (control)", "assert os.stat('data.txt').st_size == 4"),
                 ("E4c posix.lstat size", "assert posix.lstat('data.txt').st_size == 4"),
                 ("E4d os.path.getsize", "assert os.path.getsize('data.txt') == 4")]:
    one(nm, {"data.txt": "abcd", **T(body)}, v2={"data.txt": "abcdefgh"})
one("E20 os.access existence", {"marker": "x", **T("assert os.access('marker', os.F_OK)")}, v2={"marker": None})
one("E20b posix.access existence", {"marker": "x", **T("assert posix.access('marker', posix.F_OK)")}, v2={"marker": None})
one("E20c os.access mode (chmod)", {"marker": "x", **T("assert os.access('marker', os.X_OK) is False")}, ctx2={}, v2=None) if False else None
one("E20d os.readlink target", {"tests/a/test_a.py": "def test_a():\n    pass\n", **T("assert os.readlink('lnk') == 'one'")}, v2=None) if False else None
one("E5 kernel release (setarch --uname-2.6)", T("assert not posix.uname().release.startswith('2.6')"), {}, {"prefix": ("setarch", "x86_64", "--uname-2.6")})
one("E5b platform.release()", T("import platform\nassert not platform.release().startswith('2.6')"), {}, {"prefix": ("setarch", "x86_64", "--uname-2.6")})
one("E6 machine (setarch i686)", T("assert posix.uname().machine == 'x86_64'"), {}, {"prefix": ("setarch", "i686")})
one("E6b platform.machine()", T("import platform\nassert platform.machine() == 'x86_64'"), {}, {"prefix": ("setarch", "i686")})
one("E7 name resolution (/etc/hosts)", T("import socket\nassert socket.gethostbyname('r056host') == '127.0.0.5'"), {"prefix": BIND("HERE/hosts1", "/etc/hosts")}, {"prefix": BIND("HERE/hosts2", "/etc/hosts")})
one("E7b localhost resolution (/etc/hosts)", T("import socket\nassert socket.gethostbyname('r056host') == '127.0.0.5'"), {"prefix": BIND("HERE/hosts1", "/etc/hosts")}, {"prefix": BIND("HERE/hosts1", "/etc/hosts")})
one("E9 /etc/localtime content", T("import time\nassert time.localtime(0).tm_hour == 0"), {}, {"prefix": BIND("/usr/share/zoneinfo/Asia/Tokyo", "/usr/share/zoneinfo/Etc/UTC")})
one("E17 file read by OpenSSL (load_verify_locations)", {"ca.pem": open("HERE/ca1.pem").read(), **T("import ssl\nssl.create_default_context(cafile='ca.pem')", "")}, v2={"ca.pem": "-----BEGIN CERTIFICATE-----\ngarbage\n-----END CERTIFICATE-----\n"})
one("E11 file mtime, content unchanged", {"data.txt": "abcd", **T("assert os.stat('data.txt').st_mtime < 2000000000")})
S[-1]["between"] = S[-2]["between"] = lambda root: os.utime(root / "data.txt", (2200000000, 2200000000))
one("E11b posix.stat mtime, content unchanged", {"data.txt": "abcd", **T("assert posix.stat('data.txt').st_mtime < 2000000000")})
S[-1]["between"] = S[-2]["between"] = lambda root: os.utime(root / "data.txt", (2200000000, 2200000000))
for s in S:
    s.setdefault("ctx1", {}); s["ctx1"].setdefault("cwd", "."); 
run_all([s for s in S if s], workers=8)
