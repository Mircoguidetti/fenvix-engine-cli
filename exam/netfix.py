"""Network fixtures of the F-01 network probes (cassette, replay-clients, service-host).

The servers run in the exam's own process (never under the engine) on this machine's non-loopback address: the
engines treat only loopback names and addresses as local, so to them this is an external host, as in the audit's
netproj2 runs (PY3-019/PY3-021). That makes "replay without network" exact: the exam stops the server, and a replayed
test can then only pass from its recording. Every response echoes the request it answers (method, path, the
`X-Exam` header), so a stale or swapped recording is visible in what the test received.
"""
from __future__ import annotations

import http.server
import os
import shutil
import socket
import ssl
import subprocess
import threading
from pathlib import Path

# proxy variables are removed for the probe commands: a request to this machine's own address must not go through a
# proxy (GitHub-hosted runners set none; a developer machine may)
NO_PROXY_ENV = {k: None for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")}


def lan_ip() -> str | None:
    """This machine's non-loopback IPv4 address (the one its default route uses; no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ip = None
    try:
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
    except OSError:
        pass
    finally:
        s.close()
    if not ip or ip.startswith("127.") or ip == "0.0.0.0":
        try:
            out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=10).stdout.split()
        except (OSError, subprocess.SubprocessError):
            out = []
        ip = next((x for x in out if x.count(".") == 3 and not x.startswith("127.")), None)
    return ip


def echo_body(method: str, path: str, xexam: str) -> str:
    return f"{method} {path} x-exam={xexam}"


class _Echo(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: a client's connection serves several requests (and tests)

    def _reply(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        body = echo_body(self.command, self.path, self.headers.get("X-Exam", "")).encode()
        self.server.seen.append((self.command, self.path, self.headers.get("X-Exam", "")))
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _reply

    def log_message(self, *a):
        pass


class EchoServer:
    """HTTP/1.1 (keep-alive) echo server on `ip`, optionally TLS (cert, key). `port` may be given to come back on the
    same address after a stop (a recording is matched by host and port)."""

    def __init__(self, ip: str, tls: tuple | None = None, port: int = 0):
        http.server.ThreadingHTTPServer.allow_reuse_address = True
        self.srv = http.server.ThreadingHTTPServer((ip, port), _Echo)
        self.srv.daemon_threads = True
        self.srv.seen = []
        if tls:
            c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            c.load_cert_chain(str(tls[0]), str(tls[1]))
            self.srv.socket = c.wrap_socket(self.srv.socket, server_side=True)
        self.ip, self.port = ip, self.srv.server_address[1]
        self.url = f"{'https' if tls else 'http'}://{ip}:{self.port}"
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    @property
    def seen(self) -> list:
        return self.srv.seen

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


def cert(d: Path, ip: str) -> tuple:
    """A self-signed certificate for `ip` (the clients trust it as their CA file)."""
    d.mkdir(parents=True, exist_ok=True)
    c, k = d / f"exam-cert-{ip}.pem", d / f"exam-key-{ip}.pem"
    if not c.exists():
        if not shutil.which("openssl"):
            raise RuntimeError("openssl not found: no TLS certificate for the echo server")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(k), "-out", str(c),
                        "-days", "2", "-subj", f"/CN={ip}", "-addext", f"subjectAltName=IP:{ip}"],
                       check=True, capture_output=True, timeout=120)
    return c, k


H2_SERVER = r"""
const http2 = require('node:http2'), fs = require('node:fs');
const [ip, cert, key] = process.argv.slice(2);
const s = http2.createSecureServer({ cert: fs.readFileSync(cert), key: fs.readFileSync(key) });
s.on('stream', (st, h) => {
  st.respond({ ':status': 200, 'content-type': 'text/plain' });
  st.end(`${h[':method']} ${h[':path']} x-exam=${h['x-exam'] || ''}`);
});
s.listen(0, ip, () => { process.stdout.write(String(s.address().port) + '\n'); });
"""


class H2Server:
    """An HTTP/2 (TLS) echo server in a plain `node` process (never under the engine)."""

    def __init__(self, work: Path, ip: str, tls: tuple):
        js = work / "exam-h2-server.js"
        js.write_text(H2_SERVER)
        env = {k: v for k, v in os.environ.items() if k not in ("NODE_OPTIONS",)}
        self.p = subprocess.Popen(["node", str(js), ip, str(tls[0]), str(tls[1])], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env)
        line = self.p.stdout.readline().strip()
        if not line.isdigit():
            self.stop()
            raise RuntimeError(f"node http2 server did not start: {line!r}")
        self.port = int(line)
        self.url = f"https://{ip}:{self.port}"

    def stop(self):
        try:
            self.p.kill()
            self.p.wait(timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
