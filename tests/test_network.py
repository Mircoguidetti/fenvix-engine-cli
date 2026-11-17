"""Point 5: closed network, localhost allowed, record/replay."""

import http.server
import json
import socket
import threading

import pytest

from detpy import network


def test_external_access_is_blocked_with_a_clear_error(pytester, run_det):
    pytester.makepyfile(
        test_n="""
        import socket, urllib.request, urllib.error
        import pytest
        from detpy import NetworkBlockedError

        def test_ip_literal():
            with pytest.raises(NetworkBlockedError, match="network access to 203.0.113.5:80 blocked"):
                socket.create_connection(("203.0.113.5", 80), timeout=1)

        def test_connect_ex():
            s = socket.socket()
            with pytest.raises(ConnectionError):
                s.connect_ex(("2001:db8::1", 443)) if False else s.connect_ex(("198.51.100.7", 443))

        def test_dns():
            with pytest.raises(socket.gaierror, match="detpy: DNS lookup of 'example.com' blocked"):
                socket.getaddrinfo("example.com", 443)
            with pytest.raises(socket.gaierror):
                socket.gethostbyname("example.com")

        def test_urllib():
            with pytest.raises(urllib.error.URLError, match="detpy"):
                urllib.request.urlopen("http://example.com/", timeout=2)

        def test_udp():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            with pytest.raises(NetworkBlockedError):
                s.sendto(b"x", ("192.0.2.1", 53))
        """
    )
    result, (_, tests, _) = run_det()
    result.assert_outcomes(passed=5)
    ev = [e for e in tests["test_n.py::test_ip_literal"]["events"] if e["s"] == "net"]
    assert ev[0]["v"] == "203.0.113.5:80 blocked"
    assert ev[0]["at"].startswith("test_n.py:")


def test_localhost_is_allowed(pytester, run_det):
    pytester.makepyfile(
        test_l="""
        import http.server, threading, urllib.request, socket

        def test_local_http_server():
            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200); self.end_headers(); self.wfile.write(b"local ok")
                def log_message(self, *a): pass
            srv = http.server.HTTPServer(("127.0.0.1", 0), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                url = "http://localhost:%d/" % srv.server_port
                assert urllib.request.urlopen(url, timeout=5).read() == b"local ok"
                socket.getaddrinfo("localhost", 80)
            finally:
                srv.shutdown()

        def test_unix_socket(tmp_path):
            a, b = socket.socketpair()
            a.sendall(b"x"); assert b.recv(1) == b"x"
        """
    )
    result, _ = run_det()
    result.assert_outcomes(passed=2)


def test_allow_host(pytester, run_det):
    pytester.makepyfile(
        test_a="""
        import socket
        def test_allowed():
            s = socket.socket(); s.settimeout(0.2)
            assert isinstance(s.connect_ex(("203.0.113.9", 9)), int)  # real attempt, no NetworkBlockedError
        """
    )
    result, _ = run_det("--det-allow-host=203.0.113.9")
    result.assert_outcomes(passed=1)


class _Upstream(http.server.BaseHTTPRequestHandler):
    """Plays an HTTP proxy that answers every request itself."""

    protocol_version = "HTTP/1.0"
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        body = json.dumps({"path": self.path, "hit": type(self).hits}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
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
    # A local proxy counts as external: requests through it are blocked,
    # recorded or replayed like any other external access.
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{srv.server_port}")
    yield srv
    srv.shutdown()


CLIENT = """
import json, urllib.request
def test_fetch():
    body = json.loads(urllib.request.urlopen("http://api.example.invalid/v1/items", timeout=5).read())
    print("BODY", body)
    assert body["path"] == "http://api.example.invalid/v1/items"
    assert body["hit"] == 1
"""


def test_proxy_is_treated_as_external(pytester, run_det, upstream):
    pytester.makepyfile(test_c=CLIENT)
    result, _ = run_det()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*network access to 127.0.0.1:*blocked*"])
    assert _Upstream.hits == 0


def test_record_then_replay(pytester, run_det, upstream):
    pytester.makepyfile(test_c=CLIENT)
    cassette = pytester.path / "cassette.json"
    rec, _ = run_det(f"--det-cassette={cassette}", "--det-record")
    rec.assert_outcomes(passed=1)
    assert _Upstream.hits == 1
    data = json.loads(cassette.read_text())
    conn = data["tests"]["test_c.py::test_fetch"][0]
    assert conn["host"] == "127.0.0.1" and [s["dir"] for s in conn["segments"]] == ["send", "recv"]
    rec.stdout.fnmatch_lines(["*network: recorded 1 test(s)*"])

    upstream.shutdown()  # the "internet" goes away
    r1, (h1, t1, _) = run_det(f"--det-cassette={cassette}", "-s")
    r2, (_, t2, _) = run_det(f"--det-cassette={cassette}")
    r1.assert_outcomes(passed=1)
    r2.assert_outcomes(passed=1)
    assert _Upstream.hits == 1  # served from the cassette
    assert h1["meta"]["network"] == "replay"
    ev = [e for e in t1["test_c.py::test_fetch"]["events"] if e["s"] == "net"]
    assert ev[0]["v"].endswith("replay#0")
    assert not [e for e in ev if e["o"] == "replay.mismatch"]
    assert t1["test_c.py::test_fetch"]["fingerprint"] == t2["test_c.py::test_fetch"]["fingerprint"]


def test_replay_without_recording_is_blocked(pytester, run_det, upstream):
    pytester.makepyfile(test_c=CLIENT)
    cassette = pytester.path / "cassette.json"
    run_det(f"--det-cassette={cassette}", "--det-record")
    pytester.makepyfile(test_other=CLIENT.replace("test_fetch", "test_new"))
    result, _ = run_det(f"--det-cassette={cassette}", "test_other.py")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*no recording for it in this test: re-run with --det-record*"])


def test_replay_tls_stand_in():
    a, b = socket.socketpair()
    try:
        s = network.ReplayTLSSocket(a, None, "example.com")
        assert s.version() == "TLSv1.3"
        assert s.getpeercert()["subjectAltName"] == (("DNS", "example.com"),)
        s.write(b"ping")
        assert b.recv(4) == b"ping"
        b.sendall(b"pong")
        buf = bytearray(4)
        assert s.read(4, buf) == 4 and bytes(buf) == b"pong"
        assert s.fileno() == a.fileno()
    finally:
        a.close()
        b.close()


def test_local_name_detection():
    assert network._is_local_name("localhost")
    assert network._is_local_name("127.0.0.53")
    assert network._is_local_name("::1")
    assert network._is_local_name("0.0.0.0")
    assert network._is_local_name("api.localhost")
    assert not network._is_local_name("example.com")
    assert not network._is_local_name("10.0.0.1")


def test_proxy_named_other_than_localhost_that_maps_to_loopback(monkeypatch):
    # review R-002c: HTTPS_PROXY=http://runsc:41047 with /etc/hosts mapping runsc to 127.0.0.1 (or the machine name
    # to 127.0.1.1): any loopback connect to that port is the proxy, so it is external
    real = network._real_getaddrinfo

    def fake(host, port, *a, **k):
        if host == "runsc":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.1.1", port))]
        if host == "proxy.unresolvable.invalid":
            raise socket.gaierror("no such name")
        if host == "corp-proxy.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", port))]
        return real(host, port, *a, **k)

    monkeypatch.setattr(network, "_real_getaddrinfo", fake)
    for var in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://runsc:41047")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.unresolvable.invalid:3128")
    monkeypatch.setenv("ALL_PROXY", "http://corp-proxy.example:8080")
    policy = network._Policy("block", None, [])
    for host in ("127.0.0.1", "127.0.1.1", "::1", "localhost"):
        assert policy.external(host, 41047)
        assert policy.external(host, 3128)  # not resolvable here: conservatively loopback
    assert not policy.external("127.0.0.1", 8080)  # the proxy is not on loopback: its address is external anyway
    assert not policy.external("127.0.0.1", 5432)  # other loopback ports stay local
