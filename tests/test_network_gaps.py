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
