"""The closed network in Rust (``crates/detpy-py/src/network.rs``) against the Python original
(``tests/rust_hotpaths_ref/_ref_l0_network.py``).

* whole sessions, run with the reference path (``-p _l0ref``, ``DETPY_L0_REF=1``) and with the Rust path, on a
  project that opens blocked connections (TCP to IPv4 / IPv6 literals, bytes hosts, names, odd ports; UDP
  ``sendto``), looks names and numeric hosts up (``getaddrinfo``, ``gethostbyname[_ex]``), talks to loopback servers
  and over ``AF_UNIX``, uses ``--det-allow-host`` and goes through local HTTP and TLS "proxies" taken from the
  ``*_PROXY`` variables: block, ``--det-record`` (cassettes compared byte for byte) and replay of that cassette
  (``--det`` traces byte-identical in every mode), ``--det-cache`` stores and warm receipts identical;
* unit level, on large generated inputs: ``ipaddress.ip_address`` and the flags the policy reads, ``_is_local_name``,
  ``_is_ip``, ``_resolves_local``, ``_proxy_endpoints``, the policy (``external``, ``hostname``, ``fake_ip``,
  ``has_recording``), ``_target`` and the wrappers themselves (results, errors and recorded events) in block, record
  and replay modes;
* the wrappers' disguise (method descriptors, binding, pickling);
* the per-call cost of both paths (MEASURED, printed).
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import pickle
import random
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REF = Path(__file__).parent / "rust_hotpaths_ref"
PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "no_proxy",
              "NO_PROXY")

# -- upstream servers (the "internet" behind local proxies) ---------------------------------------------------------


def _serve_forever(srv: socket.socket, handle) -> None:
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def _read_until(conn, end: bytes, limit: int = 1 << 16) -> bytes:
    buf = b""
    while end not in buf and len(buf) < limit:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def _http_handle(conn) -> None:
    """A proxy answering every request itself, deterministically (no Date / Server headers)."""
    with conn:
        try:
            req = _read_until(conn, b"\r\n\r\n")
            line = req.split(b"\r\n", 1)[0].decode("latin-1")
            body = json.dumps({"request": line}).encode()
            conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                         % (len(body), body))
        except OSError:
            pass


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory):
    if shutil.which("openssl") is None:
        return None
    d = tmp_path_factory.mktemp("tls")
    r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost",
                        "-days", "2", "-keyout", str(d / "key.pem"), "-out", str(d / "cert.pem")],
                       capture_output=True)
    return (d / "cert.pem", d / "key.pem") if r.returncode == 0 else None


@pytest.fixture
def upstream(tls_files):
    """`(http_port, tls_port)`: an HTTP proxy and a TLS service on loopback (tls_port 0 without openssl)."""
    socks = []
    http = socket.create_server(("127.0.0.1", 0))
    socks.append(http)
    threading.Thread(target=_serve_forever, args=(http, _http_handle), daemon=True).start()
    tls_port = 0
    if tls_files is not None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(tls_files[0]), str(tls_files[1]))

        def tls_handle(conn):
            try:
                with ctx.wrap_socket(conn, server_side=True) as s:
                    data = b""
                    while len(data) < 10:
                        chunk = s.recv(10 - len(data))
                        if not chunk:
                            break
                        data += chunk
                    s.sendall(b"TLS:" + data.upper())
            except (OSError, ssl.SSLError):
                conn.close()

        tls = socket.create_server(("127.0.0.1", 0))
        socks.append(tls)
        tls_port = tls.getsockname()[1]
        threading.Thread(target=_serve_forever, args=(tls, tls_handle), daemon=True).start()
    yield http.getsockname()[1], tls_port
    for s in socks:
        s.close()


# -- the project -----------------------------------------------------------------------------------------------------

PROJECT = {
    "conftest.py": '''
import os

import detpy.network as _net

if os.environ.get("NET_MODE") == "record":
    # the "internet's" DNS: api.example.invalid is the TLS service (on loopback, behind the proxy port); both paths
    # read network._real_getaddrinfo at call time
    _real = _net._real_getaddrinfo

    def _resolve(host, port, *a, **k):
        if host in ("api.example.invalid", b"api.example.invalid"):
            host = "127.0.0.1"
        return _real(host, port, *a, **k)

    _net._real_getaddrinfo = _resolve
''',
    "test_net.py": '''
import http.client
import http.server
import os
import socket
import ssl
import threading
import urllib.error
import urllib.request

import pytest

from detpy import NetworkBlockedError

MODE = os.environ.get("NET_MODE", "block")
HTTP_PORT = int(os.environ["UP_HTTP_PORT"])
TLS_PORT = int(os.environ["UP_TLS_PORT"])
external_only = pytest.mark.skipif(MODE == "record", reason="real attempts in record mode")


def test_0_cacheable():
    # first in the file: a reusable result (under the prefix rule, review R-020, every test after a refused one in
    # the same process is refused too)
    assert MODE in ("block", "replay", "record")


def outcome(f, *a, **k):
    try:
        r = f(*a, **k)
        return ("ok", r if not isinstance(r, list) else r[:2])
    except Exception as e:
        return ("err", type(e).__name__, str(e) if "detpy" in str(e) else "")


@external_only
def test_blocked_tcp():
    out = []
    for addr in [("203.0.113.5", 80), ("2001:db8::1", 443), (b"198.51.100.7", 8080), ("example.com", 80),
                 ("Example.COM.", 443), ("203.0.113.5", "80"), ("203.0.113.5", 70000), ("caf\\u00e9.example", 1),
                 ("api.localhost", 9), ("0.0.0.0", 1), ("::ffff:127.0.0.1", 1), ("127.0.0.1%lo", 1),
                 ("::ffff:10.0.0.1", 2), ("1.2.3.04", 5)]:
        s = socket.socket()
        s.settimeout(0.3)
        out.append((addr, outcome(s.connect, addr), outcome(s.connect_ex, addr)))
        s.close()
    with pytest.raises(NetworkBlockedError, match="network access to 203.0.113.5:80 blocked"):
        socket.create_connection(("203.0.113.5", 80), timeout=1)
    print("VAL", out)


@external_only
def test_dns():
    out = []
    for host in ["example.com", "EXAMPLE.org.", b"example.net", "xn--bcher-kva.example", "203.0.113.5", "::1",
                 "localhost", "LocalHost.", "api.localhost", "127.1", "fe80::1%lo", "allowed.example", None, 7,
                 "api.example.invalid", b"\\xffbad"]:
        out.append((host, outcome(socket.getaddrinfo, host, 80), outcome(socket.gethostbyname, host),
                    outcome(socket.gethostbyname_ex, host)))
    out.append(outcome(socket.getaddrinfo, "localhost", "http", type=socket.SOCK_STREAM))
    out.append(outcome(socket.getaddrinfo, host="example.com", port=None))
    with pytest.raises(urllib.error.URLError, match="detpy"):
        urllib.request.urlopen("http://example.com/", timeout=2)
    print("VAL", out)


@external_only
def test_udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    out = [outcome(s.sendto, b"x", ("192.0.2.1", 53)), outcome(s.sendto, b"x", 0, ("example.com", 53)),
           outcome(s.sendto, b"x", ("allowed.example", 53))]
    s.close()
    print("VAL", out)


def test_udp_loopback():
    a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    a.bind(("127.0.0.1", 0))
    b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    b.sendto(b"ping", a.getsockname())
    b.sendto(b"pong", ("localhost", a.getsockname()[1]))
    print("VAL", a.recvfrom(10)[0], a.recvfrom(10)[0])
    a.close()
    b.close()


def test_loopback_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"local ok")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # record mode maps an address to the last name looked up for it for the rest of the session (both paths):
        # no "localhost" lookups there, the proxy on 127.0.0.1 keeps its address as recorded host
        name = "127.0.0.1" if MODE == "record" else "localhost"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        body = opener.open("http://%s:%d/" % (name, srv.server_port), timeout=5).read()
        s = socket.socket()
        assert s.connect_ex(("127.0.0.1", srv.server_port)) == 0
        s.close()
        print("VAL", body, socket.getaddrinfo(name, 80)[0][4], socket.gethostbyname(name))
    finally:
        srv.shutdown()


def test_unix(tmp_path):
    a, b = socket.socketpair()
    a.sendall(b"x")
    assert b.recv(1) == b"x"
    path = str(tmp_path / "s")
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(path)
    srv.listen()
    c = socket.socket(socket.AF_UNIX)
    c.connect(path)
    conn, _ = srv.accept()
    c.send(b"unix")
    print("VAL", conn.recv(4))
    for s in (a, b, c, conn, srv):
        s.close()


@external_only
def test_allow_host():
    s = socket.socket()
    s.settimeout(0.2)
    r = s.connect_ex(("203.0.113.9", 9))  # a real attempt, no NetworkBlockedError
    s.close()
    print("VAL", isinstance(r, int), outcome(socket.getaddrinfo, "Allowed.Example.", 80)[0])


def test_proxy_http():
    try:
        # a proxied request by hand: urllib's proxy handling reads the whole environment, whose digest (cache)
        # includes the variable that selects the reference path
        conn = http.client.HTTPConnection("127.0.0.1", HTTP_PORT, timeout=5)
        conn.request("GET", "http://api.example.invalid/v1/items?q=1")
        body = conn.getresponse().read()
        conn.close()
    except NetworkBlockedError as e:
        body = ("blocked", str(e))
    print("VAL", body)


def test_proxy_raw():
    try:
        s = socket.create_connection(("127.0.0.1", HTTP_PORT), timeout=5)
    except NetworkBlockedError as e:
        print("VAL", "blocked", e)
        return
    with s:
        n = s.send(b"GET /raw HTTP/1.0\\r\\n")
        s.sendall(memoryview(b"Host: x\\r\\n\\r\\n"))
        buf = bytearray(8)
        got = s.recv_into(buf)
        rest = b""
        while True:
            chunk = s.recv(1024)
            if not chunk:
                break
            rest += chunk
        print("VAL", n, got, bytes(buf[:got]) + rest, s.getpeername()[1] == HTTP_PORT)


def _tls_exchange(raw, server_hostname):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    peer = raw.getpeername()
    with ctx.wrap_socket(raw, server_hostname=server_hostname) as s:
        s.sendall(b"hello")
        s.write(b"world")
        data = b""
        while len(data) < 14:
            chunk = s.read(14 - len(data))
            if not chunk:
                break
            data += chunk
        return peer[0], data, s.version() is not None


@pytest.mark.skipif(TLS_PORT == 0, reason="no TLS service")
def test_tls_by_address():
    raw = socket.socket()
    raw.settimeout(5)
    try:
        r = raw.connect_ex(("127.0.0.1", TLS_PORT))
    except NetworkBlockedError as e:
        print("VAL", "blocked", e)
        return
    print("VAL", r, _tls_exchange(raw, None))


@pytest.mark.skipif(TLS_PORT == 0, reason="no TLS service")
def test_tls_by_name():
    try:
        info = socket.getaddrinfo("api.example.invalid", TLS_PORT, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        print("VAL", "dns", str(e))
        return
    raw = socket.create_connection(info[0][4][:2], timeout=5)
    print("VAL", info[0][4], _tls_exchange(raw, "api.example.invalid"))
''',
}


def _write(root: Path, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


@pytest.fixture
def net_env(monkeypatch, upstream):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(REF), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep))
    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
    http_port, tls_port = upstream
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{http_port}")
    if tls_port:
        monkeypatch.setenv("https_proxy", f"localhost:{tls_port}")
    monkeypatch.setenv("UP_HTTP_PORT", str(http_port))
    monkeypatch.setenv("UP_TLS_PORT", str(tls_port))
    return upstream


ALLOW = ("--det-allow-host=203.0.113.9", "--det-allow-host=Allowed.EXAMPLE")


def _run(pytester, impl: str, net_mode: str, *args):
    os.environ["DETPY_L0_REF"] = "1" if impl == "ref" else "0"
    os.environ["NET_MODE"] = net_mode
    try:
        r = pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", "-s", "-p", "_l0ref", *ALLOW, *args)
    finally:
        del os.environ["DETPY_L0_REF"], os.environ["NET_MODE"]
    out = r.stdout.str()
    assert "INTERNALERROR" not in out and " passed" in out, out[-4000:]
    assert "failed" not in out.split("short test summary")[-1].splitlines()[-1], out[-4000:]
    return r


def _vals(r) -> list:
    return [line[line.index("VAL "):] for line in r.stdout.lines if "VAL " in line]


def _trace(path: Path) -> bytes:
    # the header's precompile duration is the only wall-clock value in a trace
    return re.sub(rb'"precompile_s":[0-9.]+,', b"", path.read_bytes())


def test_reference_plugin_installs_network(pytester, net_env):
    pytester.makepyfile(test_x="import socket, detpy.network as n\ndef test_x():\n"
                               "    print('REF', type(socket.socket.connect).__name__,"
                               " type(socket.getaddrinfo).__name__, n.__file__.endswith('network.py'),"
                               " hasattr(n, '_conns'))\n")
    ref = _run(pytester, "ref", "block")
    new = _run(pytester, "new", "block")
    assert "REF function function True True" in ref.stdout.str()
    assert "REF method_descriptor net_function_stand_in True False" in new.stdout.str()


def test_sessions_match_reference(pytester, net_env):
    """Block, record (cassettes compared) and replay sessions: traces byte-identical, printed values identical."""
    _write(pytester.path, PROJECT)
    p = pytester.path
    out = {}
    for net_mode in ("block", "record", "replay"):
        for impl in ("ref", "new"):
            t = p / f"trace-{net_mode}-{impl}.jsonl"
            cassette = p / (f"cassette-{impl}.json" if net_mode == "record" else "cassette-ref.json")
            args = [f"--det-trace={t}"]
            if net_mode != "block":
                args.append(f"--det-cassette={cassette}")
            if net_mode == "record":
                args.append("--det-record")
            r = _run(pytester, impl, net_mode, *args)
            out[net_mode, impl] = (_trace(t), _vals(r))
    for net_mode in ("block", "record", "replay"):
        (tr, vr), (tn, vn) = out[net_mode, "ref"], out[net_mode, "new"]
        lines_ref, lines_new = tr.decode().splitlines(), tn.decode().splitlines()
        assert len(lines_ref) == len(lines_new), net_mode
        for a, b in zip(lines_ref, lines_new):
            assert a == b, net_mode
        assert tr == tn, net_mode
        assert vr == vn, net_mode
    assert (p / "cassette-ref.json").read_bytes() == (p / "cassette-new.json").read_bytes()
    # the sessions did what they claim
    cas = json.loads((p / "cassette-ref.json").read_text())
    conns = [c for t in cas["tests"].values() for c in t]
    hosts = {(c["host"], c["tls"]) for c in conns}
    assert ("127.0.0.1", False) in hosts, hosts
    events = {m: [json.loads(x) for x in out[m, "new"][0].decode().splitlines() if '"type":"test"' in x]
              for m in ("block", "record", "replay")}
    values = {m: {e["v"] for t in ev for e in t.get("events", []) if e["s"] == "net"} for m, ev in events.items()}
    assert any(v.endswith(" blocked") and "(udp)" not in v for v in values["block"])
    assert any(v.startswith("example.com blocked") for v in values["block"])
    assert any("record#" in v for v in values["record"])
    assert any("replay#" in v for v in values["replay"])
    vals = "\n".join(out["replay", "new"][1])
    assert "local ok" in vals and "v1/items" in vals
    if net_env[1]:
        assert ("api.example.invalid", True) in hosts and ("127.0.0.1", True) in hosts, hosts
        assert any(v == "api.example.invalid replay" for v in values["replay"]), values["replay"]
        assert "198.18.0." in vals and "TLS:HELLOWORLD" in vals
        assert "TLS:HELLOWORLD" in "\n".join(out["record", "new"][1])


def test_cache_matches_reference(pytester, net_env):
    _write(pytester.path, PROJECT)
    p = pytester.path
    cassette = p / "cassette.json"
    _run(pytester, "ref", "record", f"--det-cassette={cassette}", "--det-record")
    out = {}
    for impl in ("ref", "new"):
        for net_mode, extra in (("block", ()), ("replay", (f"--det-cassette={cassette}",))):
            cache = p / f".cache-{impl}-{net_mode}"
            o1, o2 = p / f"o-{impl}-{net_mode}-c.json", p / f"o-{impl}-{net_mode}-w.json"
            _run(pytester, impl, net_mode, f"--det-cache={cache}", f"--det-outcomes={o1}", *extra)
            # the run id (time and pid) and the measured durations are the only wall-clock values of a store
            store = re.sub(rb'"(run|duration)":("[^"]*"|[0-9.e-]+)', b"", (cache / "proof-cache.json").read_bytes())
            _run(pytester, impl, net_mode, f"--det-cache={cache}", f"--det-outcomes={o2}", *extra)
            receipts = [re.sub(r'"(run|duration)": ("[^"]*"|[0-9.e-]+)', "", x)
                        for x in (cache / "receipts.jsonl").read_text().splitlines()]
            oc, ow = json.loads(o1.read_text()), json.loads(o2.read_text())
            keys = ("reused", "ran", "recorded", "not_cached")
            out[impl, net_mode] = (store, receipts, oc.get("outcomes"), ow.get("outcomes"),
                                   {k: (oc.get("cache") or {}).get(k) for k in keys},
                                   {k: (ow.get("cache") or {}).get(k) for k in keys})
    for net_mode in ("block", "replay"):
        ref, new = out["ref", net_mode], out["new", net_mode]
        assert ref[0] == new[0], net_mode          # the store, byte for byte
        assert ref[1] == new[1], net_mode          # warm receipts
        assert ref[2:] == new[2:], net_mode
        assert new[5]["reused"], new[5]


# -- unit level ------------------------------------------------------------------------------------------------------


def _ref_module():
    """The reference module loaded under another name (its relative imports resolve to the real detpy modules)."""
    spec = importlib.util.spec_from_file_location("detpy._ref_network", REF / "_ref_l0_network.py")
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    finally:
        del sys.modules[spec.name]
    return m


@pytest.fixture
def ref():
    return _ref_module()


def _outcome(f, *a, **k):
    try:
        return ("ok", f(*a, **k))
    except Exception as e:  # the same exception, with the same text
        return ("err", type(e).__name__, str(e))


def _ip_inputs(n: int) -> list:
    rnd = random.Random(11)
    edge = ["", "0", "1.2.3.4", "01.2.3.4", "1.2.3.04", "1.2.3.0", "1.2.3", "1.2.3.4.5", "256.1.1.1", "255.255.255.255",
            "1..2.3", ".1.2.3", "1.2.3.", "1.2.3.4 ", " 1.2.3.4", "١.٢.٣.٤", "１.2.3.4", "0.0.0.0", "00.0.0.0",
            "127.0.0.1", "127.255.255.255", "126.0.0.1", "128.0.0.1", "1.2.3.4/32", "1.2.3.4%x", "::", ":::", "::1",
            "::0", "1::", "1::1", ":1::1", "1::1:", "1:2:3:4:5:6:7:8", "1:2:3:4:5:6:7:8:9", "1:2:3:4:5:6:7::",
            "::2:3:4:5:6:7:8", "1:2:3:4:5:6:7::8", "1::2::3", "::ffff:127.0.0.1", "::ffff:7f00:1", "::FFFF:0.0.0.0",
            "::ffff:10.0.0.1", "::ffff:1.2.3", "::ffff:01.2.3.4", "::1.2.3.4", "1:2:3:4:5:6:1.2.3.4",
            "1:2:3:4:5:6:7:1.2.3.4", "fe80::1%eth0", "fe80::1%", "fe80::1%a%b", "fe80::1%é", "::1%lo", "::1%/",
            "12345::", "0000:0000:0000:0000:0000:0000:0000:0001", "00000::1", "g::1", "::ffff:127.0.0.1%3",
            "0:0:0:0:0:ffff:127.0.0.1", "0:0:0:0:0:0:0:0", "::%", "1:2", "1:2:3", ":", "%", "::1 ", "::1\n",
            "1:2:3:4:5:6:7:8:", ":1:2:3:4:5:6:7:8", "1::2:3:4:5:6:7:8", "::1:2:3:4:5:6:7", "ABCD::EF01", "abcd" * 12,
            "1:2:3:4:5:6:7:8%" + "x" * 50, "1" * 46, "::" + "1." * 3 + "1", "\udcff", "1.2.3.\udcff", "::\udcff"]
    alphabet = "0123456789abcdefABCDEFgx:.%/ \u0661\uff11"
    out = list(edge)
    for i in range(n):
        k = i % 6
        if k == 0:
            out.append(".".join(rnd.choice(["0", "1", "00", "01", "10", "99", "127", "255", "256", "999", "", "1000"])
                                for _ in range(rnd.choice([3, 4, 4, 4, 5]))))
        elif k == 1:
            parts = [rnd.choice(["", "0", "1", "ffff", "FFFF", "abcd", "12345", "g", "00000", "fe80", "7f00"])
                     for _ in range(rnd.randint(2, 10))]
            s = ":".join(parts)
            if rnd.random() < 0.3:
                s += ":" + ".".join(str(rnd.choice([0, 1, 127, 255, 256])) for _ in range(4))
            if rnd.random() < 0.2:
                s += "%" + rnd.choice(["", "eth0", "1", "%", "é"])
            out.append(s)
        elif k == 2:
            v = rnd.getrandbits(128)
            if rnd.random() < 0.5:
                v = (0xFFFF << 32) | rnd.choice([0, 0x7F000001, rnd.getrandbits(32)])
            out.append(rnd.choice([str(ipaddress.IPv6Address(v)), ipaddress.IPv6Address(v).exploded,
                                   ipaddress.IPv6Address(v).exploded.upper()]))
        elif k == 3:
            out.append(str(ipaddress.IPv4Address(rnd.getrandbits(32))))
        else:
            out.append("".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 20))))
    return out


def test_ip_address_matches_ipaddress():
    from detpy import _core

    for s in _ip_inputs(200_000):
        try:
            ip = ipaddress.ip_address(s)
            exp = (ip.version, int(ip))
            mapped = getattr(ip, "ipv4_mapped", None)
            flags = (ip.is_loopback, ip.is_unspecified, mapped is not None and mapped.is_loopback)
        except ValueError:
            exp = flags = None
        assert _core.net_ip_address(s) == exp, s
        assert _core.net_ip_flags(s) == flags, s


HOSTS = ["localhost", "LOCALHOST", "localhost.", "localhost..", "Localhost.LocalDomain", "ip6-localhost",
         "ip6-loopback", "", ".", "foo.localhost", "FOO.LOCALHOST.", "localhost.com", "xlocalhost", "a.localhost.x",
         "127.0.0.1", "127.1.2.3", "127.0.0.01", "0.0.0.0", "0.0.0.0.", "::1", "::", "::ffff:127.0.0.1",
         "::ffff:0.0.0.0", "::FFFF:7F00:1", "::ffff:10.0.0.1", "0:0:0:0:0:0:0:1", "::1%lo", "127.0.0.1%x", "::1%",
         "10.0.0.1", "203.0.113.5", "2001:db8::1", "example.com", "EXAMPLE.ORG.", "caf\u00e9", "LOCALHOST\u212a",
         "\u0130localhost", "LOCALHO\u017fT", "\uff4cocalhost", "\u0661\u0662\u0667.0.0.1", "\udcff", "loc\udc80alhost",
         "api.example.invalid", "fe80::1%eth0", "1.2.3.4/8"]


def test_local_name_and_is_ip_match_reference(ref):
    from detpy import network

    hosts = HOSTS + _ip_inputs(30_000) + [h.upper() + "." for h in HOSTS]
    for h in hosts:
        assert _outcome(network._is_local_name, h) == _outcome(ref._is_local_name, h), h
        assert _outcome(network._is_ip, h) == _outcome(ref._is_ip, h), h

    class Odd:
        def lower(self):
            return "LocalHost.."

        def split(self, *a):
            return ["::1"]

    class OddBytes:
        def lower(self):
            return self

        def rstrip(self, chars):
            return b"localhost"

    for h in [b"localhost", bytearray(b"x"), 7, None, 1.5, Odd(), OddBytes(), ["localhost"]]:
        assert _outcome(network._is_local_name, h) == _outcome(ref._is_local_name, h), h
        assert _outcome(network._is_ip, h) == _outcome(ref._is_ip, h), h


def _fake_resolver(real):
    table = {
        "runsc": [("127.0.1.1", 0)], "mapped.example": [("::ffff:127.0.0.1", 0)], "any.example": [("0.0.0.0", 0)],
        "v6any.example": [("::", 0)], "scoped.example": [("fe80::1%eth0", 0), ("::1%lo", 0)],
        "corp-proxy.example": [("203.0.113.7", 0)], "garbage.example": [("not-an-ip", 0), ("10.0.0.1", 0)],
        "empty.example": [], "mixed.example": [("10.0.0.2", 0), ("127.0.0.53", 0)],
        "mapped0.example": [("::ffff:0.0.0.0", 0)],
    }

    def fake(host, port, *a, **k):
        if host in ("proxy.unresolvable.invalid", "bad"):
            raise socket.gaierror(socket.EAI_NONAME, "no such name")
        if host == "unicode.example":
            raise UnicodeError("label too long")
        if host == "value.example":
            raise ValueError("propagates")
        if host in table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a, _ in table[host]]
        return real(host, port, *a, **k)

    return fake, list(table) + ["proxy.unresolvable.invalid", "unicode.example", "value.example", "localhost",
                                "127.0.0.1", "::1", "1.2.3.4"]


PROXY_VALUES = ["http://127.0.0.1:3128", "localhost:8080", "https://[::1]:443", "https://[::1]", "socks5://runsc",
                "socks5h://Mapped.Example:1081", "http://user:pw@LOCALHOST:99/x", "http://[bad", "http://host:notaport",
                "http://host:99999", "http://:80", "", "corp-proxy.example:8080", "http://127.0.0.1:0",
                "  http://127.0.0.1:81", "http://proxy.unresolvable.invalid:3128", "ftp://any.example",
                "unicode.example:1", "http://garbage.example:2", "http://empty.example:3", "http://mixed.example:4",
                "http://[fe80::1%25eth0]:5", "http://scoped.example:6", "http://203.0.113.9:7", "https://v6any.example",
                "http://mapped0.example:8", "http://API.LOCALHOST:9", "http://0.0.0.0:10",
                "http://[::ffff:127.0.0.1]:11"]


def test_proxy_endpoints_and_resolves_local_match_reference(ref, monkeypatch):
    from detpy import network

    fake, names = _fake_resolver(network._real_getaddrinfo)
    monkeypatch.setattr(network, "_real_getaddrinfo", fake)
    monkeypatch.setattr(ref, "_real_getaddrinfo", fake)
    for h in names:
        for port in (80, 0, "x"):
            assert _outcome(network._resolves_local, h, port) == _outcome(ref._resolves_local, h, port), h
    rnd = random.Random(5)
    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
    combos = [[v] for v in PROXY_VALUES] + [rnd.sample(PROXY_VALUES, 6) for _ in range(150)]
    seen = set()
    for values in combos:
        for var, val in zip(PROXY_VARS[:6], values + [""] * 6):
            monkeypatch.setenv(var, val)
        new, old = _outcome(network._proxy_endpoints), _outcome(ref._proxy_endpoints)
        assert new == old, values
        if new[0] == "ok":
            seen |= new[1]
    assert ("*", 3128) in seen and ("runsc", 1080) in seen and ("mapped.example", 1081) in seen, seen


def _policies(ref, mode, allow, cassette_new=None, cassette_ref=None):
    from detpy import network

    return network._Policy(mode, cassette_new, allow), ref._Policy(mode, cassette_ref, allow)


def test_policy_matches_reference(ref, monkeypatch):
    from detpy import _core, _state

    fake, _ = _fake_resolver(socket.getaddrinfo)
    from detpy import network

    monkeypatch.setattr(network, "_real_getaddrinfo", fake)
    monkeypatch.setattr(ref, "_real_getaddrinfo", fake)
    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:3128")
    monkeypatch.setenv("https_proxy", "runsc:41047")
    monkeypatch.setenv("ALL_PROXY", "socks5://corp-proxy.example:1080")
    allow = ["Allowed.Example", "203.0.113.9", "CAF\u00c9.example", "\udcff.x"]
    new, old = _policies(ref, "block", allow)
    assert new.proxies == old.proxies and new.allow == old.allow and new.mode == old.mode
    hosts = HOSTS + ["allowed.example", "ALLOWED.EXAMPLE", "allowed.example.", "203.0.113.9", "caf\u00e9.example",
                     "\udcff.x", "runsc", "127.0.1.1", "corp-proxy.example"]
    ports = [80, 3128, 41047, 1080, 0, 65535, True, 3128.0, "3128", None, 2 ** 70, -1, [1], (3128,)]
    for h in hosts:
        for p in ports:
            assert _outcome(new.external, h, p) == _outcome(old.external, h, p), (h, p)
        assert new.hostname(h) == old.hostname(h)
    for h in hosts * 2 + [f"h{i}" for i in range(600)]:
        assert new.fake_ip(h) == old.fake_ip(h)
    assert new.fake_ip_of == old.fake_ip_of
    for ip in list(new.fake_ip_of.values())[:50] + ["198.18.9.9"]:
        assert new.hostname(ip) == old.hostname(ip)
        assert new.external(ip, 443) == old.external(ip, 443)
    # has_recording against a cassette, for the node id of the running test
    cn, co = _core.Cassette(), _core.Cassette()
    for c in (cn, co):
        c.open_connection("unit::test", "api.example.invalid", 443)
        c.open_connection("unit::test", "127.0.0.1", 8080)
        c.open_connection("other::test", "other.example", 443)
    new, old = _policies(ref, "replay", allow, cn, co)
    saved = _state.STATE.nodeid
    try:
        for nodeid in ("unit::test", "other::test", None, "\udcff"):
            _state.STATE.nodeid = nodeid
            for h in ["api.example.invalid", "127.0.0.1", "other.example", "API.example.invalid", "\udcff", 7]:
                assert _outcome(new.has_recording, h) == _outcome(old.has_recording, h), (nodeid, h)
    finally:
        _state.STATE.nodeid = saved
    new.start_test()
    assert new.counters == {} and new.mismatches == []


class _Events:
    def __init__(self) -> None:
        self.events: list = []

    def record(self, source, op, site, value, thread=0):
        self.events.append((source, op, site, value, thread))


@pytest.fixture
def capture():
    from detpy import _state

    st = _state.STATE
    saved = (st.recorder, st.nodeid, st.threads)
    rec = _Events()
    st.recorder, st.nodeid = rec, "unit::test"
    _state.reset_threads()
    try:
        yield rec
    finally:
        st.recorder, st.nodeid, st.threads = saved


def _same_site(f, *args, **kwargs):
    return f(*args, **kwargs)                    # one call line for both paths: identical sites


def _norm(o):
    """An outcome with the objects that differ by identity (sockets) made comparable."""
    if isinstance(o, tuple) and o and o[0] == "ok" and isinstance(o[1], socket.socket):
        return ("ok", "socket")
    return o


def _drive(mod, sock_factory, hosts, ports):
    out = []
    for h in hosts:
        out.append(_outcome(_same_site, mod._getaddrinfo, h, 80))
        out.append(_outcome(_same_site, mod._gethostbyname, h))
        out.append(_outcome(_same_site, mod._gethostbyname_ex, h))
    out.append(_outcome(_same_site, mod._getaddrinfo, "api.example.invalid", "https", 0, socket.SOCK_DGRAM, 17))
    out.append(_outcome(_same_site, mod._getaddrinfo, "api.example.invalid", None))
    out.append(_outcome(_same_site, mod._getaddrinfo, "api.example.invalid", "no-such-service"))
    out.append(_outcome(_same_site, mod._getaddrinfo, host="example.com", port=1, flags=0))
    out.append(_outcome(_same_site, mod._getaddrinfo, "example.com"))
    for h in hosts:
        for p in ports:
            s = sock_factory()
            out.append((h, p, _outcome(_same_site, mod._connect, s, (h, p))))
            out.append((h, p, _outcome(_same_site, mod._connect_ex, s, (h, p))))
            s.close()
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for h in hosts[:12]:
        out.append(_outcome(_same_site, mod._sendto, u, b"x", (h, 53)))
        out.append(_outcome(_same_site, mod._sendto, u, b"x", 0, (h, 53)))
    out.append(_outcome(_same_site, mod._sendto, u, b"x"))
    out.append(_outcome(_same_site, mod._sendto, u, b"x", None))
    u.close()
    s = sock_factory()
    for addr in [("203.0.113.5",), "203.0.113.5", ("203.0.113.5", 80, 0, 0), [("x", 1)], None, (b"\xff.example", 1)]:
        out.append(_outcome(_same_site, mod._connect, s, addr))
    s.close()
    out.append(_outcome(_same_site, mod._connect, socket.socket(socket.AF_UNIX), "/nonexistent/sock"))
    return [_norm(o) for o in out]


DNS_HOSTS = ["example.com", "EXAMPLE.com.", b"example.net", b"\xffbad.example", "203.0.113.5", "localhost",
             "allowed.example", "Allowed.Example.", "api.example.invalid", "127.0.0.1", "::1", None, 7,
             "\udcff.example", "caf\u00e9.example"]


@pytest.mark.parametrize("mode", ["block", "replay"])
def test_wrappers_match_reference(ref, capture, mode, monkeypatch):
    """The connect / sendto / DNS wrappers: results, errors (types and texts) and events, block and replay."""
    from detpy import _core, network

    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:3128")
    cassettes = []
    for _ in range(2):
        c = _core.Cassette()
        if mode == "replay":
            for host, port in [("api.example.invalid", 443), ("203.0.113.5", 80), ("127.0.0.1", 3128),
                               ("api.example.invalid", 443)]:
                i = c.open_connection("unit::test", host, port)
                c.append("unit::test", i, "send", b"ping")
                c.append("unit::test", i, "recv", b"pong")
        cassettes.append(c if mode == "replay" else None)
    allow = ["allowed.example"]
    monkeypatch.setattr(network, "POLICY", network._Policy(mode, cassettes[0], allow))
    monkeypatch.setattr(ref, "POLICY", ref._Policy(mode, cassettes[1], allow))
    hosts = ["203.0.113.5", "api.example.invalid", "localhost", "127.0.0.1", "allowed.example", "example.com",
             b"203.0.113.5", "\udcff.example"]
    ports = [80, 443, 3128, "443", 70000]
    out_ref = _drive(ref, socket.socket, DNS_HOSTS, ports[:0]) + _drive(ref, lambda: _sock(), hosts, ports)
    n_ref = len(capture.events)
    out_new = _drive(network, socket.socket, DNS_HOSTS, ports[:0]) + _drive(network, lambda: _sock(), hosts, ports)
    assert out_new == out_ref
    ev = capture.events
    assert len(ev) == 2 * n_ref and ev[:n_ref] == ev[n_ref:]
    ops = {e[1] for e in ev}
    assert {"socket.connect", "socket.sendto", "dns"} <= ops
    if mode == "replay":
        assert any(" replay#" in e[3] for e in ev) and any(e[3] == "api.example.invalid replay" for e in ev)
        assert network.POLICY.counters == ref.POLICY.counters and network.POLICY.counters
        assert network.POLICY.fake_ip_of == ref.POLICY.fake_ip_of


def _sock():
    s = socket.socket()
    s.settimeout(0.2)
    return s


def test_replayed_socket_matches_reference(ref, capture, monkeypatch):
    """Replay end to end in-process: the socketpair conversation, getpeername, setsockopt, mismatches."""
    from detpy import _core, network

    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
    results = []
    for mod in (ref, network):
        c = _core.Cassette()
        i = c.open_connection("unit::test", "api.example.invalid", 443)
        c.append("unit::test", i, "send", b"GET /")
        c.append("unit::test", i, "recv", b"200 OK")
        monkeypatch.setattr(mod, "POLICY", mod._Policy("replay", c, []))
        mod.start_test()
        ip = _same_site(mod._gethostbyname, "api.example.invalid")
        s = socket.socket()
        s.settimeout(5)
        r = _same_site(mod._connect_ex, s, (ip, 443))
        peer = mod._getpeername(s)
        opt = mod._setsockopt(s, socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.sendall(b"PUT /x")                     # not what was recorded: a mismatch
        got = s.recv(100)
        s.close()
        tls = mod._wrap_socket(ssl.create_default_context(), socket.socket(), server_hostname="h")
        for _ in range(100):
            if mod.POLICY.mismatches:
                break
            threading.Event().wait(0.05)
        results.append((ip, r, peer, opt, got, list(mod.POLICY.mismatches), type(tls).__name__))
        tls.close()
    assert results[0] == results[1]
    assert results[1][2] == ("198.18.0.2", 443) and results[1][4] == b"200 OK" and results[1][5]
    ev = capture.events
    assert len(ev) == 4 and ev[:2] == ev[2:]


def test_record_wrappers_match_reference(ref, capture, monkeypatch, tmp_path):
    """Record mode: the connection bookkeeping, every recording wrapper, host_of_ip and the cassettes."""
    from detpy import _core, network

    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{port}")

    def echo(conn):
        with conn:
            while True:
                d = conn.recv(4096)
                if not d:
                    return
                conn.sendall(d.upper())

    threading.Thread(target=_serve_forever, args=(srv, echo), daemon=True).start()
    fake, _ = _fake_resolver(socket.getaddrinfo)

    def resolve(host, p, *a, **k):
        if host == "api.example.invalid":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", p))]
        return fake(host, p, *a, **k)

    cassettes, outs = [], []
    try:
        for mod in (ref, network):
            monkeypatch.setattr(mod, "_real_getaddrinfo", resolve)
            c = _core.Cassette()
            monkeypatch.setattr(mod, "POLICY", mod._Policy("record", c, []))
            out = [_outcome(_same_site, mod._getaddrinfo, "api.example.invalid", port),
                   _outcome(_same_site, mod._getaddrinfo, "runsc", port), mod.POLICY.hostname("127.0.0.1")]
            s = socket.socket()
            out.append(_same_site(mod._connect, s, ("127.0.0.1", port)))
            out.append(mod._rec_send(s, b"abc"))
            out.append(mod._rec_send(s, memoryview(b"defgh")[1:], 0))
            out.append(mod._rec_sendall(s, bytearray(b"ij")))
            import array
            out.append(mod._rec_sendall(s, array.array("H", [0x6b6b])))
            data = b""
            while len(data) < 11:
                data += mod._rec_recv(s, 100)
            out.append(data)
            out.append(mod._rec_send(s, b"xyz", 0))
            buf = bytearray(10)
            n = 0
            while n < 3:
                n += mod._rec_recv_into(s, memoryview(buf)[n:], 0, 0)
            out.append(bytes(buf))
            out.append(_outcome(mod._rec_recv, s))
            out.append(_outcome(mod._rec_send, s, b"", 0, 1))
            out.append(_outcome(mod._rec_sendall, s, b"", flags=0))
            s.close()
            local = socket.socket()
            local.settimeout(1)
            out.append(_outcome(_same_site, mod._connect_ex, local, ("localhost", 1)))
            local.close()
            outs.append(out)
            cassettes.append(c)
    finally:
        srv.close()
    assert outs[0] == outs[1]
    assert outs[1][2] == "api.example.invalid"
    paths = []
    for i, c in enumerate(cassettes):
        p = tmp_path / f"cassette-{i}.json"
        c.save(p)
        paths.append(p)
    assert paths[0].read_bytes() == paths[1].read_bytes()
    data = json.loads(paths[1].read_text())
    segs = data["tests"]["unit::test"][0]["segments"]
    assert [s["dir"] for s in segs] == ["send", "recv", "send", "recv"] and segs[0]["data"]
    ev = capture.events
    assert len(ev) % 2 == 0 and ev[: len(ev) // 2] == ev[len(ev) // 2:]
    assert any("record#0" in e[3] for e in ev)


def test_wrapper_argument_errors_match_reference(ref, monkeypatch):
    from detpy import network

    monkeypatch.setattr(network, "POLICY", network._Policy("block", None, []))
    monkeypatch.setattr(ref, "POLICY", ref._Policy("block", None, []))
    s = socket.socket()
    try:
        for name, args, kwargs in [("_connect", (), {}), ("_connect", (1, 2), {}), ("_connect", (), {"address": None}),
                                   ("_connect", (), {"addr": 1}), ("_connect", ((1, 2),), {"address": 1}),
                                   ("_sendto", (), {}), ("_sendto", (), {"data": b"x"}), ("_sendto", (b"x",), {"x": 1}),
                                   ("_sendto", (b"x",), {"data": 1}), ("_rec_send", (), {}),
                                   ("_rec_send", (b"x", 0, 1), {}), ("_rec_recv", (), {"flags": 0}),
                                   ("_rec_recv_into", (), {}), ("_setsockopt", (), {"level": 1}),
                                   ("_getpeername", (1,), {}), ("_rec_ssl_read", (), {"len": 1, "x": 2})]:
            if name.startswith("_rec_ssl"):
                continue
            got_new = _outcome(getattr(network, name), s, *args, **kwargs)
            got_ref = _outcome(getattr(ref, name), s, *args, **kwargs)
            if got_ref[0] == "err" and got_ref[1] == "TypeError":
                assert got_new == got_ref, (name, args, kwargs)
        for name, args, kwargs in [("_getaddrinfo", (), {}), ("_getaddrinfo", ("x",), {}),
                                   ("_getaddrinfo", ("x", 1, 0, 0, 0, 0, 0), {}), ("_getaddrinfo", ("x", 1), {"y": 1}),
                                   ("_gethostbyname", (), {}), ("_gethostbyname", ("a", "b"), {}),
                                   ("_gethostbyname_ex", (), {"host": "localhost", "x": 1})]:
            assert _outcome(getattr(network, name), *args, **kwargs) == _outcome(getattr(ref, name), *args, **kwargs)
    finally:
        s.close()


def test_target_matches_reference(ref, monkeypatch):
    from detpy import network

    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://localhost:3128")

    class Addr(tuple):
        def __len__(self):
            return 1

    for allow in ([], ["example.com"]):
        monkeypatch.setattr(network, "POLICY", network._Policy("block", None, allow))
        monkeypatch.setattr(ref, "POLICY", ref._Policy("block", None, allow))
        socks = [socket.socket(), socket.socket(socket.AF_INET, socket.SOCK_DGRAM), socket.socket(socket.AF_UNIX)]
        try:
            for s in socks:
                for addr in [("example.com", 80), ("127.0.0.1", 3128), ("127.0.0.2", 3128), (b"example.com", 80),
                             ("localhost", 3128), ("::1", 3128), ("127.0.0.1", 80), "x", None, ("x",), (1, 2),
                             Addr(("example.com", 80)), ("example.com", 80, 0, 0), ("EXAMPLE.COM", 80)]:
                    assert _outcome(network._target, s, addr) == _outcome(ref._target, s, addr), (s, addr)
        finally:
            for s in socks:
                s.close()


def test_disguise_and_binding():
    from detpy import network
    from detpy._patch import Patcher, binds_as_method

    assert repr(network._connect) == repr(socket.socket.connect) == "<method 'connect' of '_socket.socket' objects>"
    assert network._connect.__doc__ == socket.socket.connect.__doc__
    assert repr(network._rec_ssl_read) == "<method 'read' of 'SSLSocket' objects>"
    assert repr(network._gethostbyname) == "<built-in function gethostbyname>"
    assert not binds_as_method(network._gethostbyname) and binds_as_method(network._getaddrinfo)
    assert network._getaddrinfo.__wrapped__ is network._real_getaddrinfo
    assert (network._gethostbyname.__name__, network._gethostbyname.__module__) == ("gethostbyname", "socket")
    p = Patcher()
    try:
        network.install(p, False, None, [])
        assert socket.gethostbyname is network._gethostbyname        # set as is, not wrapped again
        assert pickle.loads(pickle.dumps(socket.gethostbyname)) is socket.gethostbyname
        assert pickle.loads(pickle.dumps(socket.getaddrinfo)) is socket.getaddrinfo

        class Holder:
            lookup = socket.gethostbyname
            resolve = socket.getaddrinfo

        h = Holder()
        assert h.lookup("localhost") == "127.0.0.1"
        assert h.resolve.__self__ is h and h.resolve.__func__ is network._getaddrinfo   # binds like a function
        s = socket.socket()
        assert s.connect.__self__ is s
        with pytest.raises(TypeError, match="doesn't apply to a 'int' object"):
            socket.socket.connect(1, ("x", 1))
        s.close()
    finally:
        p.undo_all()
        network.uninstall()
    assert socket.socket.connect is network._real_connect


# -- timing ----------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(sys.version_info < (3, 12), reason="timing only")
def test_wrappers_are_faster_than_the_reference(pytester, monkeypatch):
    """Not an equivalence check: the per-call cost of both paths inside a test (MEASURED, printed)."""
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(REF), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep))
    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
    pytester.makepyfile(test_t='''
import os, socket, _socket
import pytest


def test_t():
    from detpy.clock import real_perf_counter as clock
    record = os.environ["NET_MODE"] == "record"
    a, b = socket.socketpair()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    closed = srv.getsockname()[1]                  # bound, not listening: a loopback connect is refused at once
    loop = socket.socket()
    blocked = socket.socket()
    best = {}
    for _ in range(5):
        n = 5000
        t0 = clock()
        if not record:
            for _ in range(n):
                try:
                    blocked.connect(("203.0.113.5", 80))
                except ConnectionError:
                    pass
        t1 = clock()
        for _ in range(n):
            loop.connect_ex(("127.0.0.1", closed))
        t2 = clock()
        for _ in range(n // 5):
            socket.getaddrinfo("localhost", 80)
        t3 = clock()
        for i in range(n):
            a.send(b"x")
            if i % 50 == 49:                       # drain (the real method): the buffer holds few 1-byte skbs
                _socket.socket.recv(b, 65536)
        t4 = clock()
        rows = [("connect_loopback", (t2 - t1) / n), ("getaddrinfo_localhost", (t3 - t2) / (n // 5)),
                ("send", (t4 - t3) / n)]
        if not record:
            rows.append(("connect_blocked", (t1 - t0) / n))
        for label, dt in rows:
            best[label] = min(best.get(label, dt), dt)
    for label, dt in best.items():
        print("NSPERCALL", label, round(dt * 1e9))
''')
    res = {}
    for net_mode, args in (("block", ()), ("record", ("--det-record", f"--det-cassette={pytester.path / 'c.json'}"))):
        for impl in ("ref", "new"):
            os.environ["DETPY_L0_REF"] = "1" if impl == "ref" else "0"
            os.environ["NET_MODE"] = net_mode
            try:
                r = pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", "-s", "-p", "_l0ref",
                                                  "--det-max-events=100", *args)
            finally:
                del os.environ["DETPY_L0_REF"], os.environ["NET_MODE"]
            for line in r.stdout.lines:
                if "NSPERCALL" in line:
                    _, label, ns = line[line.index("NSPERCALL"):].split()[:3]
                    res.setdefault(f"{net_mode}:{label}", {})[impl] = int(ns)
    print("ns per call in a test (best of 5):", json.dumps(res, sort_keys=True))
    assert res["block:connect_blocked"]["new"] < res["block:connect_blocked"]["ref"], res
    assert res["record:connect_loopback"]["new"] < res["record:connect_loopback"]["ref"], res
