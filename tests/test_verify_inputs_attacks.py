"""Attacks on the verifier, one per channel a Python test can read its environment or inputs through
(docs/VERIFY-INPUTS.md). Each case runs one project twice under `pytest --det`, changing only that channel between the
runs; the test writes what it observed. The invariant: `fenvix verify` says IDENTICAL only if the test observed the
same value in both runs. For a channel `--det` does not control ("raw"), the attack must also show the change (the
observed values differ), so the verdict must not be IDENTICAL.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

PY = sys.executable

WRITE = '''
import os
def _w(v):
    with open(os.environ["ATK_OUT"], "w") as fh:
        fh.write(repr(v))
'''

T = "tests/test_atk.py"


def _case(body: str, extra: dict | None = None) -> dict:
    return {T: WRITE + textwrap.dedent(body), **(extra or {})}


# name: (files, kind, how the two runs differ: env a, env b, or a callable(run_index, project, tmp) before each run,
# extra det args)
CASES = {
    # --- environment variables -------------------------------------------------------------------------------------
    "body-os.environ": (_case("def test_x():\n    _w(os.environ.get('ATK_V'))\n"), "raw", {"ATK_V": "1"}, {"ATK_V": "2"}),
    "body-os.getenv": (_case("def test_x():\n    _w(os.getenv('ATK_V'))\n"), "raw", {"ATK_V": "1"}, {"ATK_V": "2"}),
    "body-os.environb": (_case("def test_x():\n    _w(os.environb.get(b'ATK_V'))\n"), "raw", {"ATK_V": "1"},
                         {"ATK_V": "2"}),
    "body-posix.environ": (_case("import posix\ndef test_x():\n    _w(posix.environ.get(b'ATK_V'))\n"), "raw",
                           {"ATK_V": "1"}, {"ATK_V": "2"}),
    "body-enumeration": (_case("def test_x():\n    _w(dict(os.environ).get('ATK_V'))\n"), "raw", {"ATK_V": "1"},
                         {"ATK_V": "2"}),
    "body-in-a-thread": (_case("import threading\ndef test_x():\n    r = []\n"
                               "    t = threading.Thread(target=lambda: r.append(os.environ.get('ATK_V')))\n"
                               "    t.start(); t.join()\n    _w(r[0])\n"), "raw", {"ATK_V": "1"}, {"ATK_V": "2"}),
    "module-scope": (_case("V = os.environ.get('ATK_V')\ndef test_x():\n    _w(V)\n"), "raw", {"ATK_V": "1"},
                     {"ATK_V": "2"}),
    "conftest-module-scope": (_case("import conftest\ndef test_x():\n    _w(conftest.V)\n",
                                    {"tests/conftest.py": "import os\nV = os.environ.get('ATK_V')\n"}), "raw",
                              {"ATK_V": "1"}, {"ATK_V": "2"}),
    "conftest-hook": (_case("def test_x(request):\n    _w(request.config.atk)\n",
                            {"tests/conftest.py": "import os\ndef pytest_configure(config):\n"
                                                  "    config.atk = os.environ.get('ATK_V')\n"}), "raw",
                      {"ATK_V": "1"}, {"ATK_V": "2"}),
    **{f"fixture-{scope}": (_case(f"import pytest\n@pytest.fixture(scope='{scope}')\ndef v():\n"
                                  f"    return os.environ.get('ATK_V')\n"
                                  "def test_a(v):\n    pass\ndef test_x(v):\n    _w(v)\n"), "raw",
                            {"ATK_V": "1"}, {"ATK_V": "2"})
       for scope in ("function", "class", "module", "session")},
    "dependency-at-import": (_case("import atklib\ndef test_x():\n    _w(atklib.V)\n",
                                   {"tests/atklib.py": "import os\nV = os.environ.get('ATK_V')\n"}), "raw",
                             {"ATK_V": "1"}, {"ATK_V": "2"}),
    "dependency-lazy-import": (_case("def test_x():\n    import atklib2\n    _w(atklib2.V)\n",
                                     {"tests/atklib2.py": "import os\nV = os.environ.get('ATK_V')\n"}), "raw",
                               {"ATK_V": "1"}, {"ATK_V": "2"}),
    "child-process": (_case("import subprocess\ndef test_x():\n"
                            "    _w(subprocess.run(['sh', '-c', 'echo $ATK_V'], capture_output=True, text=True).stdout)\n"),
                      "raw", {"ATK_V": "1"}, {"ATK_V": "2"}),
    "native-getenv": (_case("import ctypes\ndef test_x():\n    libc = ctypes.CDLL(None)\n"
                            "    libc.getenv.restype = ctypes.c_char_p\n    _w(libc.getenv(b'ATK_V'))\n"), "raw",
                      {"ATK_V": "1"}, {"ATK_V": "2"}),
    # --- files -----------------------------------------------------------------------------------------------------
    "file-outside-the-project": (_case("def test_x():\n    _w(open(os.environ['ATK_FILE']).read())\n"), "raw",
                                 "file-outside", "file-outside"),
    "file-in-the-project": (_case("import pathlib\ndef test_x():\n"
                                  "    _w((pathlib.Path(__file__).parent / 'data.txt').read_text())\n"), "raw",
                            "file-inside", "file-inside"),
    # --- controlled by --det: the value the test sees does not change ----------------------------------------------
    "time": (_case("import time\ndef test_x():\n    _w(time.time())\n"), "controlled", "sleep", "sleep"),
    "entropy": (_case("def test_x():\n    _w(os.urandom(8).hex())\n"), "controlled", {}, {}),
    "entropy-observed": (_case("def test_x():\n    _w(os.urandom(8).hex())\n"), "raw", {}, {}, ["--det-entropy=observe"]),
    "hostname": (_case("import socket\ndef test_x():\n    _w(socket.gethostname())\n"), "controlled", {}, {}),
    "cpu-count": (_case("def test_x():\n    _w(os.cpu_count())\n"), "controlled", "taskset", "taskset"),
    "time-zone": (_case("import time\ndef test_x():\n    _w(time.strftime('%Z %z', time.localtime(0)))\n"), "controlled",
                  {"TZ": "UTC"}, {"TZ": "Asia/Tokyo"}),
    "locale": (_case("import locale\ndef test_x():\n    _w(locale.setlocale(locale.LC_ALL, ''))\n"), "controlled",
               {"LC_ALL": "C.UTF-8"}, {"LC_ALL": "C"}),
    # --- network ---------------------------------------------------------------------------------------------------
    "network-localhost": (_case("import socket\ndef test_x():\n"
                                "    s = socket.create_connection(('127.0.0.1', int(os.environ['ATK_PORT'])), timeout=5)\n"
                                "    _w(s.recv(100)); s.close()\n"), "raw", "server", "server"),
}


def _server(payload: bytes):
    srv = socket.create_server(("127.0.0.1", 0))

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            with c:
                c.sendall(payload)

    threading.Thread(target=serve, daemon=True).start()
    return srv


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DETPY_", "PYTEST_", "ATK_"))}
    env.update(FENVIX_VOLATILE_ENV="ATK_OUT,ATK_FILE,ATK_PORT", **extra)
    return env


@pytest.mark.parametrize("name", list(CASES))
def test_verify_is_never_identical_when_what_the_test_observed_differs(tmp_path, name):
    files, kind, a, b, *rest = CASES[name]
    det = rest[0] if rest else []
    proj = tmp_path / "p"
    for rel, text in files.items():
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text(text)
    vals, traces = [], []
    for i, how in enumerate((a, b)):
        env = _env()
        pre = []
        srv = None
        if isinstance(how, dict):
            env.update(how)
        elif how == "file-outside":
            f = tmp_path / "outside.txt"
            f.write_text(f"v{i}")
            env["ATK_FILE"] = str(f)
        elif how == "file-inside":
            (proj / "tests" / "data.txt").write_text(f"v{i}")
        elif how == "sleep" and i == 1:
            time.sleep(1.1)
        elif how == "taskset" and i == 1:
            if not os.path.exists("/usr/bin/taskset") or len(os.sched_getaffinity(0)) < 2:
                pytest.skip("no taskset or a single CPU")
            pre = ["taskset", "-c", "0"]
        elif how == "server":
            srv = _server(f"v{i}".encode())
            env["ATK_PORT"] = str(srv.getsockname()[1])
        out, trace = tmp_path / f"out{i}", tmp_path / f"t{i}.jsonl"
        env["ATK_OUT"] = str(out)
        try:
            p = subprocess.run([*pre, PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
                                f"--det-trace={trace}", *det, "tests"], cwd=proj, env=env, capture_output=True,
                               text=True, timeout=600)
        finally:
            if srv is not None:
                srv.close()
        assert out.exists(), p.stdout[-2000:] + p.stderr[-2000:]
        vals.append(out.read_text())
        traces.append(str(trace))
    v = subprocess.run([PY, "-m", "detpy.fenvix", "verify", *traces], cwd=proj, env=_env(), capture_output=True,
                       text=True, timeout=300)
    identical = v.returncode == 0
    if kind == "raw":
        assert vals[0] != vals[1], f"{name}: the attack did not change what the test observed ({vals})"
    assert not (identical and vals[0] != vals[1]), f"{name}: IDENTICAL although the test observed {vals}\n{v.stdout}"
