"""Review R-055 (full review of PR #12, claude/verifier-cli @ 688e4fe): failing tests, one per defect.

Each verify case runs one project twice under `pytest --det`, changing only one channel between the runs; the test
writes what it observed. The invariant of docs/VERIFY-INPUTS.md: `fenvix verify` says IDENTICAL (exit 0) only if the
test observed the same value in both runs. Every case here is a channel the list misses or gets wrong.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PY = sys.executable

WRITE = '''
import os
def _w(v):
    with open(os.environ["ATK_OUT"], "w") as fh:
        fh.write(repr(v))
'''


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DETPY_", "PYTEST_", "ATK_"))}
    env.update(FENVIX_VOLATILE_ENV="ATK_OUT,ATK_FILE,ATK_PORT", **extra)
    return env


def _write(proj: Path, files: dict) -> None:
    for rel, text in files.items():
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text(textwrap.dedent(text))


def attack(tmp_path: Path, files: dict, before=None, det=(), args=("tests",), cwd=None):
    """Two --det runs of one project; ``before(i, proj, env)`` changes the channel before run i. Returns
    (observed values, verify result)."""
    proj = tmp_path / "p"
    _write(proj, files)
    vals, traces = [], []
    for i in (0, 1):
        env = _env()
        out, trace = tmp_path / f"out{i}", tmp_path / f"t{i}.jsonl"
        env["ATK_OUT"] = str(out)
        run_cwd = proj
        if before is not None:
            r = before(i, proj, env)
            if r is not None:
                run_cwd = r
        run_args = args(i) if callable(args) else args
        p = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
                            f"--det-trace={trace}", *det, *run_args], cwd=run_cwd, env=env, capture_output=True, text=True,
                           timeout=600)
        assert out.exists(), p.stdout[-3000:] + p.stderr[-3000:]
        vals.append(out.read_text())
        traces.append(str(trace))
    v = subprocess.run([PY, "-m", "detpy.fenvix", "verify", *traces], cwd=proj, env=_env(), capture_output=True,
                       text=True, timeout=300)
    return vals, v


def check(vals, v, name):
    assert vals[0] != vals[1], f"{name}: the attack did not change what the test observed ({vals})"
    assert v.returncode != 0, f"{name}: IDENTICAL (exit 0) although the test observed {vals}\n{v.stdout}"


def T(body: str) -> dict:
    return {"tests/test_atk.py": WRITE + textwrap.dedent(body)}


def envset(a: dict, b: dict):
    def before(i, proj, env):
        env.update((a, b)[i])
    return before


# --- verify: channels missing from docs/VERIFY-INPUTS.md, or listed with a rule that does not hold ------------------
# Each builder returns (files, before, extra pytest kwargs). Every case FAILS on 688e4fe: verify exits 0 (IDENTICAL)
# although the test observed two different values.

def _outside_file(tmp_path, name="outside.txt"):
    f = tmp_path / name

    def before(i, proj, env):
        f.write_text(f"v{i}")
    return f, before


def c_volatile_env(tmp_path):  # V1: a CI-volatile variable (VOLATILE_KEPT) is no input and its read no value
    a, b = tmp_path / "ta", tmp_path / "tb"
    a.mkdir(), b.mkdir()
    return T("def test_x():\n    _w(os.environ['TMPDIR'])\n"), envset({"TMPDIR": str(a)}, {"TMPDIR": str(b)}), {}


def c_proxy_env(tmp_path):  # V2: proxy variables are no inputs while the network is closed, yet the test reads them
    return (T("def test_x():\n    _w(os.environ.get('HTTPS_PROXY'))\n"),
            envset({"HTTPS_PROXY": "http://a:1"}, {"HTTPS_PROXY": "http://b:2"}), {})


def c_file_module_scope(tmp_path):  # V3: a file read outside any test (module scope)
    f, before = _outside_file(tmp_path)
    return T(f"V = open({str(f)!r}).read()\ndef test_x():\n    _w(V)\n"), before, {}


def c_project_file_module_scope(tmp_path):  # V3: a project data file (untracked, generated) read at module scope
    def before(i, proj, env):
        (proj / "tests" / "data.txt").write_text(f"v{i}")
    return (T("import pathlib\nV = (pathlib.Path(__file__).parent / 'data.txt').read_text()\n"
              "def test_x():\n    _w(V)\n"), before, {})


def c_file_conftest(tmp_path):  # V3: a file read by conftest.py at import
    f, before = _outside_file(tmp_path)
    files = T("import conftest\ndef test_x():\n    _w(conftest.V)\n")
    files["tests/conftest.py"] = f"V = open({str(f)!r}).read()\n"
    return files, before, {}


def c_dirty_source(tmp_path):  # V4: the test's own code changed (uncommitted edit, same git HEAD)
    def before(i, proj, env):
        if i == 0:
            subprocess.run("git init -q && git add -A && git -c user.email=r@r -c user.name=r commit -qm x",
                           shell=True, cwd=proj, check=True)
        (proj / "tests" / "test_atk.py").write_text(WRITE + f"def test_x():\n    _w('v{i}')\n")
    return T("def test_x():\n    pass\n"), before, {}


def c_installed_dependency(tmp_path):  # V5: an installed dependency changed (site-packages)
    import sysconfig
    mod = Path(sysconfig.get_paths()["purelib"]) / "atk_r055_dep.py"

    def before(i, proj, env):
        mod.write_text(f"V = 'v{i}'\n")
    return T("import atk_r055_dep\ndef test_x():\n    _w(atk_r055_dep.V)\n"), before, {"cleanup": mod}


def c_stat_mtime(tmp_path):  # V6: file metadata
    f = tmp_path / "outside.txt"

    def before(i, proj, env):
        f.write_text("x")
        os.utime(f, (1000 + i, 1000 + i))
    return T(f"def test_x():\n    _w(os.stat({str(f)!r}).st_mtime)\n"), before, {}


def c_path_exists(tmp_path):  # V6: file existence
    f = tmp_path / "outside.txt"

    def before(i, proj, env):
        if i == 0:
            f.write_text("x")
        else:
            f.unlink()
    return T(f"def test_x():\n    _w(os.path.exists({str(f)!r}))\n"), before, {}


def c_sqlite(tmp_path):  # V7: a file read by C code (sqlite3)
    import sqlite3
    db = tmp_path / "o.db"

    def before(i, proj, env):
        if db.exists():
            db.unlink()
        c = sqlite3.connect(db)
        c.execute("create table t(v)")
        c.execute("insert into t values (?)", (f"v{i}",))
        c.commit()
        c.close()
    return (T(f"import sqlite3\ndef test_x():\n    _w(sqlite3.connect({str(db)!r}).execute('select v from t').fetchone())\n"),
            before, {})


def _udp_server(i, env):
    import socket
    import threading
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))

    def serve():
        try:
            _, a = s.recvfrom(100)
            s.sendto(f"v{i}".encode(), a)
        except OSError:
            pass
    threading.Thread(target=serve, daemon=True).start()
    env["ATK_PORT"] = str(s.getsockname()[1])


def c_udp_localhost(tmp_path):  # V8: a live endpoint over UDP (not marked uncontrolled.net)
    return (T("import socket\ndef test_x():\n    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
              "    s.settimeout(5)\n    s.sendto(b'q', ('127.0.0.1', int(os.environ['ATK_PORT'])))\n"
              "    _w(s.recvfrom(100)[0])\n"), lambda i, proj, env: _udp_server(i, env), {})


def c_unix_socket(tmp_path):  # V9: listed ("a unix socket ... marked uncontrolled.net"), but not marked
    import socket
    import threading
    path = tmp_path / "s.sock"

    def before(i, proj, env):
        if path.exists():
            path.unlink()
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(path))
        s.listen()

        def serve():
            c, _ = s.accept()
            c.sendall(f"v{i}".encode())
            c.close()
            s.close()
        threading.Thread(target=serve, daemon=True).start()
    return (T(f"import socket\ndef test_x():\n    s = socket.socket(socket.AF_UNIX)\n    s.settimeout(5)\n"
              f"    s.connect({str(path)!r})\n    _w(s.recv(10))\n"), before, {})


def c_argv(tmp_path):  # V10: the command line (listed gap, no test until now): one runner option differs
    return (T("import sys\ndef test_x():\n    _w([a for a in sys.argv if a.startswith('--tb')])\n"), None,
            {"args": lambda i: ("tests",) if i == 0 else ("--tb=short", "tests")})


def c_environ_data(tmp_path):  # V11: os.environ._data (the mapping under os.environ)
    return T("def test_x():\n    _w(os.environ._data.get(b'ATK_V'))\n"), envset({"ATK_V": "1"}, {"ATK_V": "2"}), {}


def c_sessionfinish(tmp_path):  # V12: a read after the trace header (listed gap, no test until now)
    files = T("def test_x():\n    pass\n")
    files["tests/conftest.py"] = ("import os\ndef pytest_sessionfinish(session):\n"
                                  "    open(os.environ['ATK_OUT'], 'w').write(repr(os.environ.get('ATK_V')))\n")
    return files, envset({"ATK_V": "1"}, {"ATK_V": "2"}), {}


def c_hash_no_reexec(tmp_path):  # V13: --det-no-reexec: the hash seed is "<random>" in both headers
    return T("def test_x():\n    _w(hash('abc'))\n"), None, {"det": ["--det-no-reexec"]}


def c_rusage(tmp_path):  # V14: resource usage of the process
    # coordinator (CI 44929696261): run 1 must really use more memory. PYTHONMALLOC=malloc_debug is read by the
    # interpreter in C (no run input) and adds the debug allocator's padding: a larger ru_maxrss (MEASURED locally
    # 43916 vs 48580 KiB)
    return (T("import resource\ndef test_x():\n    _w(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)\n"),
            envset({}, {"PYTHONMALLOC": "malloc_debug"}), {})


def c_native_getenv(tmp_path):  # V15: C code that calls getenv itself (listed gap, no test until now)
    import shutil
    if not shutil.which("cc"):
        pytest.skip("no C compiler")
    src = tmp_path / "atk.c"
    src.write_text('#include <stdlib.h>\nconst char* atk(void){ const char* v = getenv("ATK_V"); return v ? v : "-"; }\n')
    lib = tmp_path / "libatk.so"
    subprocess.run(["cc", "-shared", "-fPIC", "-o", str(lib), str(src)], check=True)
    return (T(f"import ctypes\ndef test_x():\n    f = ctypes.CDLL({str(lib)!r}).atk\n    f.restype = ctypes.c_char_p\n"
              "    _w(f())\n"), envset({"ATK_V": "1"}, {"ATK_V": "2"}), {})


VERIFY_CASES = {
    "V1-volatile-env-TMPDIR": c_volatile_env,
    "V2-proxy-env-closed-network": c_proxy_env,
    "V3-file-at-module-scope": c_file_module_scope,
    "V3-project-file-at-module-scope": c_project_file_module_scope,
    "V3-file-in-conftest-import": c_file_conftest,
    "V4-test-code-changed-dirty-tree": c_dirty_source,
    "V5-installed-dependency-changed": c_installed_dependency,
    "V6-file-mtime": c_stat_mtime,
    "V6-file-exists": c_path_exists,
    "V7-sqlite-file": c_sqlite,
    "V8-udp-localhost": c_udp_localhost,
    "V9-unix-socket": c_unix_socket,
    "V10-runner-options": c_argv,
    "V11-os.environ._data": c_environ_data,
    "V12-pytest_sessionfinish": c_sessionfinish,
    "V13-hash-without-reexec": c_hash_no_reexec,
    "V14-rusage": c_rusage,
    "V15-native-getenv-in-C": c_native_getenv,
}


# --- coordinator review of bf13934: five more wrong IDENTICALs ------------------------------------------------------

def p_access(tmp_path):  # os.access is not observed (VERIFY-CONTRACT s.2 lists it under fs.stat)
    f = tmp_path / "o.txt"

    def before(i, proj, env):
        if i == 0:
            f.write_text("x")
        elif f.exists():
            f.unlink()
    return T(f"def test_x():\n    _w(os.access({str(f)!r}, os.R_OK))\n"), before, {}


def p_stat_module(tmp_path):  # a stat outside any test is dropped; contract: files_read_outside_tests "stat:<value>"
    f = tmp_path / "o2.txt"

    def before(i, proj, env):
        if i == 0:
            f.write_text("x")
        elif f.exists():
            f.unlink()
    return T(f"FAST = os.path.exists({str(f)!r})\ndef test_x():\n    _w(FAST)\n"), before, {}


def p_late_import(tmp_path):  # a module imported inside a test is in no code input
    files = T("def test_x():\n    from calc_mod import V\n    _w(V)\n")
    files["tests/calc_mod.py"] = "V = 0\n"

    def before(i, proj, env):
        (proj / "tests" / "calc_mod.py").write_text(f"V = {i}\n")
    return files, before, {}


WARN = "import warnings\ndef test_x():\n    try:\n        warnings.warn('x'); r = 1\n    except UserWarning:\n        r = 2\n    _w(r)\n"


def p_plugin_switch(tmp_path):  # the argv input drops -p
    files = T(WARN)
    files["pytest.ini"] = "[pytest]\nfilterwarnings = error\n"
    return files, None, {"args": lambda i: ("tests",) if i == 0 else ("-p", "no:warnings", "tests")}


def p_addopts(tmp_path):  # PYTEST_ADDOPTS / ini addopts read by pytest itself never count
    return T(WARN), envset({}, {"PYTEST_ADDOPTS": "-W error::UserWarning"}), {}


VERIFY_CASES.update({
    "P-os.access": p_access,
    "P-stat-at-module-scope": p_stat_module,
    "P-module-imported-in-a-test": p_late_import,
    "P-plugin-switch": p_plugin_switch,
    "P-PYTEST_ADDOPTS": p_addopts,
})


@pytest.mark.parametrize("name", list(VERIFY_CASES))
def test_r055_verify_is_never_identical_when_the_test_observed_different_values(tmp_path, name):
    files, before, kw = VERIFY_CASES[name](tmp_path)
    cleanup = kw.pop("cleanup", None)
    try:
        vals, v = attack(tmp_path, files, before, **kw)
    finally:
        if cleanup is not None and cleanup.exists():
            cleanup.unlink()
    check(vals, v, name)


# --- explore: seeds whose run crashed are not findings ---------------------------------------------------------------

def test_r055_explore_does_not_report_clean_when_seeds_crashed(tmp_path):
    """E1: a test kills the process when it runs after another one (order-dependent crash). Plain pytest in the fixed
    order passes; under 3 of 4 seeds the run exits 1 with no test result. explore prints '0 flaky failing tests' and
    exits 0: a hidden bug the nightly exploration exists to find, reported as a clean suite."""
    proj = tmp_path / "p"
    _write(proj, {
        "tests/__init__.py": "",
        "tests/test_a.py": "STATE = []\ndef test_a():\n    STATE.append(1)\n",
        "tests/test_b.py": "import os\nfrom tests.test_a import STATE\ndef test_b():\n    if STATE:\n        os._exit(1)\n",
        "tests/test_c.py": "def test_c():\n    pass\n",
    })
    p = subprocess.run([PY, "-m", "detpy.fenvix", "explore", "--budget", "1", "--max-seeds", "4", "--out",
                        str(tmp_path / "out")], cwd=proj, env=_env(), capture_output=True, text=True, timeout=600)
    import json
    log = json.loads((tmp_path / "out" / "explore.json").read_text())["seeds_log"]
    crashed = [x for x in log if x.get("exit") not in (0, None) and not x.get("tests")]
    assert crashed, f"the attack did not crash any seed: {log}"
    assert p.returncode != 0, (f"explore exit 0 although {len(crashed)} of {len(log)} seeds crashed with no test "
                               f"result:\n{p.stdout}{p.stderr}")
