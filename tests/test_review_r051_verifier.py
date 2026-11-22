"""Review R-051, re-check of PR #11 (claude/verifier-cli @ 57d76c4, code 30f0260). Every test here FAILS on 57d76c4.

Run: python -m pytest -q -p no:randomly tests/test_review_r051_verifier.py

- R1 (#8, F-03): traces whose `inputs` object is empty are still "IDENTICAL: ... ran with the same inputs", exit 0.
  The fix covers a missing `inputs` key only.
- R2 (30f0260, F-03): "verify reads `urandom` in older traces as the same input" does not hold: an old trace
  (`urandom: controlled`) and a new one (`entropy: controlled`) of the same test are DIVERGENT, exit 1, with the hint
  "observed but not controlled".
- R3 (#9 class, F-02): `fenvix replay` of a target that is now skipped (its body never ran) says "the defect no longer
  fails the same way: fixed, or ...", exit 1. A replay that ran nothing must not suggest a fix.
- R4 (#5 replay-clients, F-01): TLS over memory BIOs binds to the first recorded socket found in the caller's frame,
  not to the socket the TLS runs over. With another connection opened first, the plaintext is recorded on the idle
  connection, the TLS socket's ciphertext is recorded as is, and the replay fails a test that passes without --det and
  in the recording run (`assert b'' == b'echo:hello'`).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

PY = sys.executable


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DETPY_", "PYTEST_"))}
    env.update(extra)
    return env


def _fenvix(cwd: Path, *args, timeout=900) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "detpy.fenvix", *args], cwd=cwd, capture_output=True, text=True, env=_env(),
                          timeout=timeout)


def _write(root: Path, files: dict) -> None:
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))


def test_r1_traces_with_an_empty_inputs_object_are_not_called_identical(tmp_path):
    head = {"type": "header", "format": "detpy-trace", "version": 1, "encoding": 2,
            "meta": {"controls": ["time"], "runner": "go test", "runtime": "go", "seed": 0, "inputs": {}},
            "order": []}
    rec = {"type": "test", "nodeid": "g1::TestTZ", "index": 0, "outcome": "passed",
           "fingerprint": "31af55e422bc4accd412eab03c7f8ad0", "n_events": 1, "truncated": False,
           "counts": {"outcome": 1}, "checkpoints": [],
           "events": [{"t": 0, "s": "outcome", "o": "outcome", "at": "<end>", "v": "passed"}]}
    traces = []
    for i in range(2):
        p = tmp_path / f"t{i}.jsonl"
        p.write_text(json.dumps(head) + "\n" + json.dumps(rec) + "\n")
        traces.append(str(p))
    r = _fenvix(tmp_path, "verify", *traces)
    assert r.returncode != 0 and "IDENTICAL: all" not in r.stdout, f"exit {r.returncode}\n{r.stdout}"


def test_r2_an_old_urandom_trace_and_a_new_entropy_trace_of_one_run_are_identical(tmp_path):
    _write(tmp_path, {"tests/test_x.py": "def test_x():\n    assert 1\n"})
    new = tmp_path / "new.jsonl"
    p = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
                        f"--det-trace={new}", "tests"], cwd=tmp_path, capture_output=True, text=True, env=_env(),
                       timeout=600)
    assert p.returncode == 0, p.stdout + p.stderr
    first, rest = new.read_text().split("\n", 1)
    h = json.loads(first)
    assert h["meta"]["inputs"].get("entropy") == "controlled", h["meta"]["inputs"]  # precondition: 30f0260's name
    h["meta"]["inputs"]["urandom"] = h["meta"]["inputs"].pop("entropy")  # the same run as an older engine wrote it
    old = tmp_path / "old.jsonl"
    old.write_text(json.dumps(h) + "\n" + rest)
    r = _fenvix(tmp_path, "verify", str(old), str(new))
    assert r.returncode == 0 and "IDENTICAL" in r.stdout, f"exit {r.returncode}\n{r.stdout}"


def test_r3_replay_of_a_target_that_is_now_skipped_does_not_suggest_a_fix(tmp_path):
    proj = tmp_path / "proj"
    _write(proj, {
        "tests/__init__.py": "",
        "tests/state.py": "FLAG = {}\n",
        "tests/test_a.py": "from tests.state import FLAG\ndef test_polluter():\n    FLAG['x'] = 1\n",
        "tests/test_b.py": "from tests.state import FLAG\ndef test_victim():\n    assert 'x' not in FLAG\n",
    })
    r = _fenvix(proj, "repro", "tests/test_b.py::test_victim", "--seeds", "2", "--confirm", "2",
                "--out", str(tmp_path / "rep"))
    assert r.returncode == 0, r.stdout + r.stderr
    bundle = next((tmp_path / "rep").glob("test_victim-*"))
    # the team quarantines the test: its body no longer runs, so a replay says nothing about the defect
    (proj / "tests/test_b.py").write_text("import pytest\nfrom tests.state import FLAG\n"
                                         "@pytest.mark.skip(reason='quarantined')\n"
                                         "def test_victim():\n    assert 'x' not in FLAG\n")
    r = _fenvix(proj, "replay", str(bundle), "--runs", "2")
    assert "fixed" not in r.stdout and r.returncode == 2, f"exit {r.returncode}:\n{r.stdout}{r.stderr}"


TWO_SOCKETS = '''
import os, socket, ssl

def _pump(sock, obj, inc, out, step):
    while True:
        try:
            r = step()
            if out.pending:
                sock.sendall(out.read())
            return r
        except ssl.SSLWantReadError:
            if out.pending:
                sock.sendall(out.read())
            data = sock.recv(65536)
            inc.write_eof() if not data else inc.write(data)

def test_second_socket():
    host, port = os.environ["TLS_TARGET"].split(":")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    idle = socket.create_connection((host, int(port)), timeout=5)   # another connection, opened first
    sock = socket.create_connection((host, int(port)), timeout=5)
    inc, out = ssl.MemoryBIO(), ssl.MemoryBIO()
    obj = ctx.wrap_bio(inc, out, server_hostname="svc.example")   # TLS over `sock`, not `idle`
    _pump(sock, obj, inc, out, obj.do_handshake)
    _pump(sock, obj, inc, out, lambda: obj.write(b"hello"))
    data = _pump(sock, obj, inc, out, lambda: obj.read(100))
    assert data == b"echo:hello"
'''


def test_r4_tls_over_memory_bios_is_bound_to_the_socket_it_runs_over(tmp_path):
    sys.path.insert(0, str(Path(__file__).parent))
    from test_network_gaps import _lan_ip

    ip = _lan_ip()
    if ip is None or shutil.which("openssl") is None:
        pytest.skip("no non-loopback interface or no openssl")
    key, cert = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=svc.example",
                    "-keyout", str(key), "-out", str(cert), "-days", "2"], check=True, capture_output=True)
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cert, key)
    srv = socket.create_server((ip, 0))
    stop = threading.Event()

    def handle(conn):
        try:
            with sctx.wrap_socket(conn, server_side=True) as s:
                s.sendall(b"echo:" + s.recv(100))
        except (OSError, ssl.SSLError):
            pass

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    (tmp_path / "test_two.py").write_text(TWO_SOCKETS)
    env = _env(TLS_TARGET=f"{ip}:{srv.getsockname()[1]}")
    cassette = tmp_path / "cassette.json"
    base = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly"]
    det = [*base, "--det", f"--det-cassette={cassette}"]
    try:
        plain = subprocess.run([*base, "test_two.py"], cwd=tmp_path, env=env, capture_output=True, text=True,
                               timeout=300)
        assert "1 passed" in plain.stdout, plain.stdout  # precondition: the test passes
        rec = subprocess.run([*det, "--det-record"], cwd=tmp_path, env=env, capture_output=True, text=True,
                             timeout=300)
        assert "1 passed" in rec.stdout, rec.stdout + rec.stderr
    finally:
        stop.set()
        srv.close()
    rep = subprocess.run(det, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert "1 passed" in rep.stdout, "replay of a recorded passing test:\n" + rep.stdout[-1500:]
