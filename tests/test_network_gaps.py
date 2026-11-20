"""F-01 network: regression tests for audit gaps G-0165 (sendmsg/recvmsg recorded), G-0166 (a replay whose request
differs is refused), G-0167 (secrets never reach the cassette), G-1519 (recording dates, --det-cassette-max-age),
G-1520 (child processes meet the closed network through their proxy variables), G-2199 (reverse lookups guarded),
G-2200 (`fenvix cassette list|rename|drop`).

The "internet" is a local HTTP server reached through ``HTTP_PROXY``: a local proxy counts as external under --det,
so it is blocked, recorded and replayed like a remote host (as in tests/test_network.py).
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import threading

import pytest


class _Upstream(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        body = json.dumps({"path": self.path, "auth": self.headers.get("Authorization", "")[:6]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def upstream(monkeypatch):
    _Upstream.hits = 0
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{srv.server_port}")
    yield srv
    srv.shutdown()


SECRET = "Bearer SECRET-TOKEN-12345"

CLIENT = '''
import json, os, urllib.request
def test_fetch():
    req = urllib.request.Request("http://api.example.invalid/v1/" + os.environ.get("NET_PATH", "items"),
                                 headers={"Authorization": os.environ.get("NET_AUTH", "")})
    body = json.loads(urllib.request.urlopen(req, timeout=5).read())
    print("BODY", body)
    assert body["path"].endswith("/v1/items")
'''


def test_secrets_are_masked_and_a_different_request_is_refused(pytester, run_det, upstream, monkeypatch):
    """G-0167: the Authorization value is not in the cassette (not even base64); replay still matches the same
    request. G-0166: a request for another path is not answered with the recorded response."""
    pytester.makepyfile(test_c=CLIENT)
    cassette = pytester.path / "cassette.json"
    monkeypatch.setenv("NET_AUTH", SECRET)
    rec, _ = run_det(f"--det-cassette={cassette}", "--det-record")
    rec.assert_outcomes(passed=1)
    text = cassette.read_text()
    import base64

    decoded = b"".join(base64.b64decode(s["data"]) for c in json.loads(text)["tests"].values() for x in c
                       for s in x["segments"])
    assert b"SECRET-TOKEN" not in decoded and b"Authorization: " + b"*" * len(SECRET) in decoded
    upstream.shutdown()
    ok, _ = run_det(f"--det-cassette={cassette}")
    ok.assert_outcomes(passed=1)
    monkeypatch.setenv("NET_PATH", "other")  # same host, another request
    bad, (_, tests, _) = run_det(f"--det-cassette={cassette}")
    bad.assert_outcomes(failed=1)
    bad.stdout.fnmatch_lines(["*replay refused for 1 test(s): the request differs from the recorded one*"])
    assert any(e["o"] == "replay.mismatch" for e in tests["test_c.py::test_fetch"]["events"])


RAW = '''
import os, socket
def test_raw():
    host, port = os.environ["HTTP_PROXY"].rsplit(":", 1)
    s = socket.create_connection((host.split("//")[1], int(port)), timeout=5)
    s.sendmsg([b"GET http://api.example.invalid/v1/items HTTP/1.0\\r\\n", b"Host: api.example.invalid\\r\\n\\r\\n"])
    data = b""
    while True:
        chunk, _, _, _ = s.recvmsg(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    print("RAW", data.split(b"\\r\\n\\r\\n", 1)[1])
    assert b"/v1/items" in data
'''


def test_sendmsg_and_recvmsg_are_recorded_and_replayed(pytester, run_det, upstream):
    """G-0165: a connection used through sendmsg/recvmsg is recorded with its bytes and replays them."""
    pytester.makepyfile(test_r=RAW)
    cassette = pytester.path / "cassette.json"
    rec, _ = run_det(f"--det-cassette={cassette}", "--det-record", "-s")
    rec.assert_outcomes(passed=1)
    segs = json.loads(cassette.read_text())["tests"]["test_r.py::test_raw"][0]["segments"]
    assert [s["dir"] for s in segs] == ["send", "recv"], segs
    upstream.shutdown()
    rep, _ = run_det(f"--det-cassette={cassette}", "-s")
    rep.assert_outcomes(passed=1)
    rep.stdout.fnmatch_lines(["*RAW*v1/items*"])


def test_old_recordings_are_not_replayed_past_max_age(pytester, run_det, upstream):
    """G-1519: every test's recording date is in the cassette; --det-cassette-max-age refuses older ones."""
    pytester.makepyfile(test_c=CLIENT)
    cassette = pytester.path / "cassette.json"
    run_det(f"--det-cassette={cassette}", "--det-record")
    data = json.loads(cassette.read_text())
    assert data["recorded"]["test_c.py::test_fetch"][:4].isdigit()
    upstream.shutdown()
    fresh, _ = run_det(f"--det-cassette={cassette}", "--det-cassette-max-age=30")
    fresh.assert_outcomes(passed=1)
    data["recorded"]["test_c.py::test_fetch"] = "2020-01-01T00:00:00+00:00"
    cassette.write_text(json.dumps(data))
    old, _ = run_det(f"--det-cassette={cassette}", "--det-cassette-max-age=30")
    old.assert_outcomes(failed=1)
    old.stdout.fnmatch_lines(["*1 recording(s) older than --det-cassette-max-age not replayed*"])


CHILD = '''
import subprocess, sys
def test_child():
    code = ("import os, urllib.request\\n"
            "print('PROXY', os.environ.get('http_proxy'), os.environ.get('NO_PROXY'))\\n"
            "try:\\n"
            "    urllib.request.urlopen('http://192.0.2.1/', timeout=20)\\n"
            "    print('REACHED')\\n"
            "except Exception as e:\\n"
            "    print('BLOCKED', type(e).__name__)\\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60).stdout
    print(out)
    assert "BLOCKED" in out and "http://127.0.0.1:9" in out
'''


def test_child_processes_meet_the_closed_network(pytester, run_det, monkeypatch):
    """G-1520: a child that honours the proxy variables (curl, wget, git, pip, urllib) cannot reach the network."""
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY",
              "no_proxy"):
        monkeypatch.delenv(v, raising=False)
    pytester.makepyfile(test_ch=CHILD)
    res, _ = run_det("-s")
    res.assert_outcomes(passed=1)


DNS = '''
import socket
def test_reverse():
    out = {}
    for name, call in (("byaddr", lambda: socket.gethostbyaddr("8.8.8.8")),
                       ("nameinfo", lambda: socket.getnameinfo(("8.8.8.8", 53), 0)),
                       ("local", lambda: socket.gethostbyaddr("127.0.0.1")[2])):
        try:
            out[name] = repr(call())
        except Exception as e:
            out[name] = type(e).__name__ + ": " + str(e)
    out["fqdn"] = socket.getfqdn("example.com")
    print("DNS", out)
    assert "blocked" in out["byaddr"] and "blocked" in out["nameinfo"]
    assert "127.0.0.1" in out["local"] and out["fqdn"] == "example.com"
'''


def test_reverse_lookups_are_guarded(pytester, run_det):
    """G-2199: gethostbyaddr, getnameinfo and getfqdn do not reach the resolver for external hosts."""
    pytester.makepyfile(test_d=DNS)
    res, _ = run_det("-s")
    res.assert_outcomes(passed=1)


def test_cassette_command_lists_renames_and_drops(pytester, run_det, upstream):
    """G-2200: a renamed test keeps its recording with `fenvix cassette rename`."""
    pytester.makepyfile(test_c=CLIENT)
    cassette = pytester.path / "cassette.json"
    run_det(f"--det-cassette={cassette}", "--det-record")
    fx = [sys.executable, "-m", "detpy.fenvix", "cassette", "--cassette", str(cassette)]
    p = subprocess.run([*fx, "list"], capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.startswith("test_c.py::test_fetch\t1 connection(s)\trecorded 2"), p.stdout
    pytester.makepyfile(test_c=CLIENT.replace("test_fetch", "test_fetch_renamed"))
    upstream.shutdown()
    blocked, _ = run_det(f"--det-cassette={cassette}")
    blocked.assert_outcomes(failed=1)
    p = subprocess.run([*fx, "rename", "test_c.py::test_fetch", "test_c.py::test_fetch_renamed"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    ok, _ = run_det(f"--det-cassette={cassette}")
    ok.assert_outcomes(passed=1)
    p = subprocess.run([*fx, "drop", "test_c.py::test_fetch_renamed"], capture_output=True, text=True)
    assert p.returncode == 0 and "dropped 1" in p.stdout
    assert json.loads(cassette.read_text())["tests"] == {}


ASYNC = '''
import asyncio, os
def test_async():
    async def main():
        host, port = os.environ["HTTP_PROXY"].rsplit(":", 1)
        r, w = await asyncio.open_connection(host.split("//")[1], int(port))
        w.write(b"GET http://api.example.invalid/v1/items HTTP/1.0\\r\\nHost: api.example.invalid\\r\\n\\r\\n")
        await w.drain()
        data = await r.read()
        w.close()
        return data
    data = asyncio.run(main())
    print("ASYNC", data[-30:])
    assert b"/v1/items" in data
'''


def test_asyncio_clients_are_recorded_and_replayed(pytester, run_det, upstream):
    """G-0516: a connection opened by asyncio (non-blocking connect) is recorded and replayed."""
    pytester.makepyfile(test_as=ASYNC)
    cassette = pytester.path / "cassette.json"
    rec, _ = run_det(f"--det-cassette={cassette}", "--det-record")
    rec.assert_outcomes(passed=1)
    rec.stdout.fnmatch_lines(["*network: recorded 1 test(s)*"])
    upstream.shutdown()
    rep, _ = run_det(f"--det-cassette={cassette}")
    rep.assert_outcomes(passed=1)


UDP_ECHO = '''
import os, socket
def test_udp():
    host, port = os.environ["UDP_TARGET"].split(":")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    s.sendto(b"ping-1", (host, int(port)))
    a, src = s.recvfrom(100)
    s.sendto(b"ping-2", (host, int(port)))
    b = bytearray(100)
    n, src2 = s.recvfrom_into(b)
    print("UDP", a, bytes(b[:n]), src[1] == int(port), src2[1] == int(port))
    assert a == b"pong:ping-1" and bytes(b[:n]) == b"pong:ping-2"
'''


def _lan_ip():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # no packet is sent: the kernel picks the outbound interface
        ip = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if ip.startswith("127.") else ip


def test_udp_is_recorded_and_replayed(tmp_path):
    """G-1518: a UDP request/response is recorded datagram by datagram and replayed (source address kept). The
    "external" host is this machine's own non-loopback address (external for --det, reachable for the test)."""
    ip = _lan_ip()
    if ip is None:
        pytest.skip("no non-loopback interface")
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind((ip, 0))
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                data, addr = srv.recvfrom(100)
            except OSError:
                continue
            srv.sendto(b"pong:" + data, addr)

    threading.Thread(target=serve, daemon=True).start()
    (tmp_path / "test_u.py").write_text(UDP_ECHO)
    cassette = tmp_path / "cassette.json"
    env = dict(os.environ, UDP_TARGET=f"{ip}:{srv.getsockname()[1]}")
    env.pop("PYTEST_ADDOPTS", None)
    base = [sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "--det", f"--det-cassette={cassette}"]
    blocked = subprocess.run(base, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert "1 failed" in blocked.stdout, blocked.stdout  # closed network: blocked before any recording
    rec = subprocess.run([*base, "--det-record"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    stop.set()
    srv.close()
    assert "1 passed" in rec.stdout, rec.stdout + rec.stderr
    conn = json.loads(cassette.read_text())["tests"]["test_u.py::test_udp"][0]
    assert conn["udp"] and [s["dir"] for s in conn["segments"]] == ["send", "recv", "send", "recv"], conn
    rep = subprocess.run(base, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)  # server gone
    assert "1 passed" in rep.stdout and "UDP b'pong:ping-1' b'pong:ping-2' True True" in rep.stdout, rep.stdout


TLS_CLIENT = '''
import hashlib, os, socket, ssl
def test_tls():
    host, port = os.environ["TLS_TARGET"].split(":")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    raw = socket.create_connection((host, int(port)), timeout=5)
    with ctx.wrap_socket(raw, server_hostname="svc.example") as s:
        s.sendall(b"hello")
        data = s.recv(100)
        der = s.getpeercert(binary_form=True)
        print("TLS", data, isinstance(s, ssl.SSLSocket), s.selected_alpn_protocol(), s.version(),
              hashlib.sha256(der).hexdigest()[:16])
    assert data == b"echo:hello"
'''


def test_tls_replay_answers_what_the_handshake_negotiated(tmp_path):
    """G-1522: on replay the TLS socket is an ssl.SSLSocket and returns the recorded version, ALPN protocol and peer
    certificate (DER)."""
    import shutil
    import ssl as _ssl

    ip = _lan_ip()
    if ip is None or shutil.which("openssl") is None:
        pytest.skip("no non-loopback interface or no openssl")
    key, cert = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=svc.example",
                    "-keyout", str(key), "-out", str(cert), "-days", "2"], check=True, capture_output=True)
    sctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cert, key)
    sctx.set_alpn_protocols(["http/1.1"])
    srv = socket.create_server((ip, 0))
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            try:
                with sctx.wrap_socket(conn, server_side=True) as s:
                    s.sendall(b"echo:" + s.recv(100))
            except (OSError, _ssl.SSLError):
                pass

    threading.Thread(target=serve, daemon=True).start()
    (tmp_path / "test_t.py").write_text(TLS_CLIENT)
    cassette = tmp_path / "cassette.json"
    env = dict(os.environ, TLS_TARGET=f"{ip}:{srv.getsockname()[1]}")
    env.pop("PYTEST_ADDOPTS", None)
    base = [sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "--det", f"--det-cassette={cassette}"]
    rec = subprocess.run([*base, "--det-record"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    stop.set()
    srv.close()
    assert "1 passed" in rec.stdout, rec.stdout + rec.stderr
    line_rec = next(x for x in rec.stdout.splitlines() if "TLS b" in x)
    rep = subprocess.run(base, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert "1 passed" in rep.stdout, rep.stdout + rep.stderr
    line_rep = next(x for x in rep.stdout.splitlines() if "TLS b" in x)
    assert line_rep.split("TLS", 1)[1] == line_rec.split("TLS", 1)[1], (line_rec, line_rep)
    assert "True http/1.1" in line_rep, line_rep
