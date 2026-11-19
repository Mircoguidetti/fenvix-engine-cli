"""Closed network with optional record/replay.

* Connections (TCP ``connect``/``connect_ex``, UDP ``sendto``) and DNS lookups
  towards non-local hosts raise :class:`NetworkBlockedError`
  (``socket.gaierror`` for DNS). Loopback, ``AF_UNIX`` and hosts passed with
  ``--det-allow-host`` are allowed. Local HTTP(S) proxies taken from the
  ``*_PROXY`` environment variables count as external (otherwise every request
  would leak through them).
* ``--det-record``: external connections are allowed and their byte streams
  are recorded per test into a cassette (plaintext above TLS).
* When a cassette exists and ``--det-record`` is not given, recorded
  connections are *replayed*: the socket is transparently re-pointed to a local
  socketpair served by a thread that plays the recorded conversation;
  ``SSLContext.wrap_socket`` returns a plaintext stand-in for replayed sockets.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import ssl
import threading
import weakref
from urllib.parse import urlsplit

from . import _core, _state
from ._patch import Patcher

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_sendto = socket.socket.sendto
_real_send = socket.socket.send
_real_sendall = socket.socket.sendall
_real_recv = socket.socket.recv
_real_recv_into = socket.socket.recv_into
_real_getaddrinfo = socket.getaddrinfo
_real_gethostbyname = socket.gethostbyname
_real_gethostbyname_ex = socket.gethostbyname_ex
_real_wrap_socket = ssl.SSLContext.wrap_socket
_real_ssl_send = ssl.SSLSocket.send
_real_ssl_write = ssl.SSLSocket.write
_real_ssl_read = ssl.SSLSocket.read
_real_socketpair = socket.socketpair
_real_setsockopt = socket.socket.setsockopt
_real_getpeername = socket.socket.getpeername


class NetworkBlockedError(ConnectionRefusedError):
    """Raised when the code under test tries to reach an external host under --det."""


_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", ""}


def _is_local_name(host: str) -> bool:
    h = host.lower().rstrip(".")
    if h in _LOCAL_NAMES or h.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


def _proxy_endpoints() -> set:
    out = set()
    for var in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        val = os.environ.get(var)
        if not val:
            continue
        try:
            parts = urlsplit(val if "://" in val else "http://" + val)
            port = parts.port or {"https": 443, "socks5": 1080, "socks5h": 1080}.get(parts.scheme, 80)
        except ValueError:
            continue
        host = (parts.hostname or "").lower()
        if host and (_is_local_name(host) or _resolves_local(host, port)):
            # any loopback address on that port is the proxy (127.0.1.1, ::1, a name mapped in /etc/hosts)
            out.add(("*", port))
            out.add((host, port))
    return out


def _resolves_local(host: str, port: int) -> bool:
    """A proxy name other than localhost that maps to loopback (/etc/hosts: "runsc", the machine name ->
    127.0.1.1), or that cannot be resolved here: conservatively local (review R-002c)."""
    if _is_ip(host):
        return False
    try:
        infos = _real_getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:
            continue
        mapped = getattr(ip, "ipv4_mapped", None)
        if ip.is_loopback or ip.is_unspecified or (mapped is not None and mapped.is_loopback):
            return True
    return not infos


class _Policy:
    def __init__(self, mode: str, cassette, allow_hosts) -> None:
        self.mode = mode  # block | record | replay
        self.cassette = cassette  # recordings (record) or source (replay)
        self.allow = {h.lower() for h in allow_hosts}
        self.proxies = _proxy_endpoints()
        self.host_of_ip: dict[str, str] = {}
        self.fake_ip_of: dict[str, str] = {}
        self.host_of_fake: dict[str, str] = {}
        self.counters: dict = {}
        self.mismatches: list = []
        self.lock = threading.Lock()

    def start_test(self) -> None:
        self.counters = {}
        self.mismatches = []

    def hostname(self, host: str) -> str:
        return self.host_of_fake.get(host) or self.host_of_ip.get(host) or host

    def external(self, host: str, port) -> bool:
        if (host.lower(), port) in self.proxies or (("*", port) in self.proxies and _is_local_name(host)):
            return True
        if _is_local_name(host):
            return False
        return self.hostname(host).lower() not in self.allow

    def has_recording(self, host: str) -> bool:
        if self.cassette is None or _state.STATE.nodeid is None:
            return False
        return any(self.cassette.info(_state.STATE.nodeid, i)[0] == host for i in range(self._n_conns()))

    def _n_conns(self) -> int:
        nodeid = _state.STATE.nodeid
        n = 0
        while True:
            try:
                self.cassette.info(nodeid, n)
            except KeyError:
                return n
            n += 1

    def fake_ip(self, host: str) -> str:
        with self.lock:
            ip = self.fake_ip_of.get(host)
            if ip is None:
                n = len(self.fake_ip_of) + 1
                ip = f"198.18.{n // 250}.{n % 250 + 1}"  # RFC 2544 benchmarking range
                self.fake_ip_of[host] = ip
                self.host_of_fake[ip] = host
            return ip


POLICY: _Policy | None = None
_conns: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()  # socket -> (nodeid, idx)
_replays: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()  # socket -> label


def _blocked(what: str) -> NetworkBlockedError:
    hint = (
        "no recording for it in this test: re-run with --det-record"
        if POLICY is not None and POLICY.mode == "replay"
        else "use --det-record to record real responses, or --det-allow-host to allow it"
    )
    return NetworkBlockedError(
        f"detpy: network access to {what} blocked (Level 0 closes the network; localhost is allowed); {hint}"
    )


def _target(sock, address):
    """(host, port) if ``address`` is an external endpoint, else None."""
    if POLICY is None or sock.family not in (socket.AF_INET, socket.AF_INET6):
        return None
    if not isinstance(address, tuple) or len(address) < 2:
        return None
    host, port = address[0], address[1]
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str) or not POLICY.external(host, port):
        return None
    return POLICY.hostname(host), port


def _connect_common(sock, address, real):
    target = _target(sock, address)
    if target is None:
        return real(sock, address)
    host, port = target
    mode = POLICY.mode
    nodeid = _state.STATE.nodeid
    if mode == "record" and nodeid is not None:
        result = real(sock, address)
        idx = POLICY.cassette.open_connection(nodeid, host, int(port))
        _conns[sock] = (nodeid, idx)
        _state.record("net", "socket.connect", f"{host}:{port} record#{idx}", depth=2)
        return result
    if mode == "record":  # outside a test: allow, do not record
        return real(sock, address)
    if mode == "replay" and nodeid is not None and _start_replay(sock, host, int(port)):
        return 0 if real is _real_connect_ex else None
    _state.record("net", "socket.connect", f"{host}:{port} blocked", depth=2)
    raise _blocked(f"{host}:{port}")


def _connect(self, address):
    return _connect_common(self, address, _real_connect)


def _connect_ex(self, address):
    return _connect_common(self, address, _real_connect_ex)


def _sendto(self, data, *args):
    address = args[-1] if args else None
    target = _target(self, address) if address is not None else None
    if target is not None and POLICY.mode != "record":
        _state.record("net", "socket.sendto", f"{target[0]}:{target[1]} blocked")
        raise _blocked(f"{target[0]}:{target[1]} (udp)")
    return _real_sendto(self, data, *args)


# DNS ------------------------------------------------------------------------
def _dns_check(host, port=None):
    """None to resolve for real, a fake address for replay, or raise."""
    if POLICY is None or host is None:
        return None
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if _is_local_name(host) or _is_ip(host) or host.lower().rstrip(".") in POLICY.allow:
        return None
    if POLICY.mode == "record":
        return None
    if POLICY.mode == "replay" and POLICY.has_recording(host):
        _state.record("net", "dns", f"{host} replay", depth=2)
        return POLICY.fake_ip(host)
    _state.record("net", "dns", f"{host} blocked", depth=2)
    raise socket.gaierror(socket.EAI_NONAME, f"detpy: DNS lookup of {host!r} blocked (Level 0 closes the network)")


def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    fake = _dns_check(host, port)
    if fake is not None:
        try:
            p = int(port) if port is not None else 0
        except ValueError:
            p = socket.getservbyname(port)
        return [(socket.AF_INET, type or socket.SOCK_STREAM, proto or socket.IPPROTO_TCP, "", (fake, p))]
    res = _real_getaddrinfo(host, port, family, type, proto, flags)
    if POLICY is not None and POLICY.mode == "record" and isinstance(host, str) and not _is_ip(host):
        for *_, sa in res:
            POLICY.host_of_ip[sa[0]] = host
    return res


def _gethostbyname(host):
    fake = _dns_check(host)
    return fake if fake is not None else _real_gethostbyname(host)


def _gethostbyname_ex(host):
    fake = _dns_check(host)
    return (host, [], [fake]) if fake is not None else _real_gethostbyname_ex(host)


# Recording ------------------------------------------------------------------
def _append(sock, direction, data) -> None:
    entry = _conns.get(sock)
    if entry is not None and data:
        POLICY.cassette.append(entry[0], entry[1], direction, bytes(data))


def _rec_send(self, data, flags=0):
    n = _real_send(self, data, flags)
    _append(self, "send", memoryview(data)[:n])
    return n


def _rec_sendall(self, data, flags=0):
    r = _real_sendall(self, data, flags)
    _append(self, "send", data)
    return r


def _rec_recv(self, bufsize, flags=0):
    data = _real_recv(self, bufsize, flags)
    _append(self, "recv", data)
    return data


def _rec_recv_into(self, buffer, nbytes=0, flags=0):
    n = _real_recv_into(self, buffer, nbytes, flags)
    _append(self, "recv", memoryview(buffer)[:n])
    return n


def _rec_ssl_send(self, data, flags=0):
    n = _real_ssl_send(self, data, flags)
    _append(self, "send", memoryview(data)[:n])
    return n


def _rec_ssl_write(self, data):
    n = _real_ssl_write(self, data)
    _append(self, "send", memoryview(data)[:n])
    return n


def _rec_ssl_read(self, len=1024, buffer=None):
    r = _real_ssl_read(self, len, buffer)
    if buffer is not None:
        _append(self, "recv", memoryview(buffer)[:r])
    else:
        _append(self, "recv", r)
    return r


def _wrap_socket(self, sock, *args, **kwargs):
    if sock in _replays:
        hostname = kwargs.get("server_hostname")
        if hostname is None and len(args) >= 3:
            hostname = args[2]
        return ReplayTLSSocket(sock, self, hostname)
    entry = _conns.get(sock)
    ssl_sock = _real_wrap_socket(self, sock, *args, **kwargs)
    if entry is not None:
        _conns[ssl_sock] = entry
        POLICY.cassette.set_tls(entry[0], entry[1])
    return ssl_sock


# Replay ---------------------------------------------------------------------
def _setsockopt(self, *args):
    # A replayed socket is an AF_UNIX socketpair end: TCP options (TCP_NODELAY,
    # keep-alive tuning) would fail with EOPNOTSUPP, so they are ignored.
    if self in _replays:
        return None
    return _real_setsockopt(self, *args)


def _getpeername(self):
    label = _replays.get(self)
    if label is not None:
        host, _, rest = label.rpartition(":")
        return (POLICY.fake_ip(host) if POLICY else host, int(rest.split("#")[0]))
    return _real_getpeername(self)


def _recv_upto(peer, n: int) -> bytes:
    buf = bytearray()
    peer.settimeout(10.0)
    while len(buf) < n:
        try:
            chunk = peer.recv(n - len(buf))
        except (TimeoutError, socket.timeout, OSError):
            break
        if not chunk:
            break
        buf += chunk
        peer.settimeout(0.5)  # the client may legitimately send less than recorded
    return bytes(buf)


def _serve(peer, segments, label, mismatches) -> None:
    try:
        for direction, data in segments:
            if direction == "send":
                got = _recv_upto(peer, len(data))
                if got != data:
                    mismatches.append((label, len(data), len(got), _core.digest(data), _core.digest(got)))
            else:
                peer.sendall(data)
        try:
            peer.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        peer.settimeout(5.0)
        while peer.recv(65536):
            pass
    except OSError:
        pass
    finally:
        peer.close()


def _start_replay(sock, host: str, port: int) -> bool:
    nodeid = _state.STATE.nodeid
    key = (host, port)
    nth = POLICY.counters.get(key, 0)
    idx = POLICY.cassette.find(nodeid, host, port, nth)
    if idx is None:
        return False
    POLICY.counters[key] = nth + 1
    segments = POLICY.cassette.segments(nodeid, idx)
    ours, peer = _real_socketpair()
    timeout = sock.gettimeout()
    os.dup2(ours.fileno(), sock.fileno(), inheritable=False)
    ours.close()
    sock.settimeout(timeout)
    label = f"{host}:{port}#{idx}"
    _replays[sock] = label
    threading.Thread(target=_serve, args=(peer, segments, label, POLICY.mismatches), daemon=True,
                     name=f"detpy-replay-{label}").start()
    _state.record("net", "socket.connect", f"{host}:{port} replay#{idx}", depth=3)
    return True


class ReplayTLSSocket:
    """Plaintext stand-in returned by ``SSLContext.wrap_socket`` for replayed sockets."""

    def __init__(self, sock, context, server_hostname) -> None:
        self._sock = sock
        self.context = context
        self.server_hostname = server_hostname
        self.session = None
        self.session_reused = False

    def __getattr__(self, name):
        return getattr(self._sock, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._sock.close()

    def do_handshake(self, block=False):
        return None

    def getpeercert(self, binary_form=False):
        if binary_form:
            return b""
        host = self.server_hostname or ""
        return {"subject": ((("commonName", host),),), "subjectAltName": (("DNS", host),)}

    def version(self):
        return "TLSv1.3"

    def cipher(self):
        return ("TLS_AES_128_GCM_SHA256", "TLSv1.3", 128)

    def shared_ciphers(self):
        return [self.cipher()]

    def compression(self):
        return None

    def selected_alpn_protocol(self):
        return None

    def selected_npn_protocol(self):
        return None

    def get_channel_binding(self, cb_type="tls-unique"):
        return None

    def pending(self):
        return 0

    def unwrap(self):
        return self._sock

    def read(self, len=1024, buffer=None):
        if buffer is not None:
            return self._sock.recv_into(buffer, len)
        return self._sock.recv(len)

    def write(self, data):
        return self._sock.send(data)

    def fileno(self):
        return self._sock.fileno()


# Installation ---------------------------------------------------------------
def install(patcher: Patcher, record: bool, cassette_path: str | None, allow_hosts) -> str:
    global POLICY
    if record:
        mode, cassette = "record", _core.Cassette()
    elif cassette_path and os.path.exists(cassette_path):
        mode, cassette = "replay", _core.Cassette.load(cassette_path)
    else:
        mode, cassette = "block", None
    POLICY = _Policy(mode, cassette, allow_hosts)
    patcher.set(socket.socket, "connect", _connect)
    patcher.set(socket.socket, "connect_ex", _connect_ex)
    patcher.set(socket.socket, "sendto", _sendto)
    patcher.set(socket, "getaddrinfo", _getaddrinfo)
    patcher.set(socket, "gethostbyname", _gethostbyname)
    patcher.set(socket, "gethostbyname_ex", _gethostbyname_ex)
    patcher.set(ssl.SSLContext, "wrap_socket", _wrap_socket)
    if mode == "replay":
        patcher.set(socket.socket, "setsockopt", _setsockopt)
        patcher.set(socket.socket, "getpeername", _getpeername)
    if mode == "record":
        patcher.set(socket.socket, "send", _rec_send)
        patcher.set(socket.socket, "sendall", _rec_sendall)
        patcher.set(socket.socket, "recv", _rec_recv)
        patcher.set(socket.socket, "recv_into", _rec_recv_into)
        patcher.set(ssl.SSLSocket, "send", _rec_ssl_send)
        patcher.set(ssl.SSLSocket, "write", _rec_ssl_write)
        patcher.set(ssl.SSLSocket, "read", _rec_ssl_read)
    return mode


def start_test() -> None:
    if POLICY is not None:
        POLICY.start_test()


def end_test() -> None:
    if POLICY is None:
        return
    for label, n_exp, n_got, d_exp, d_got in sorted(POLICY.mismatches):
        _state.record_at("net", "replay.mismatch", "<end>", f"{label} expected {n_exp}B:{d_exp} got {n_got}B:{d_got}")


def save_recordings(cassette_path: str) -> int:
    """Merge recordings into the cassette file; returns the number of tests saved."""
    if POLICY is None or POLICY.mode != "record":
        return 0
    recorded = POLICY.cassette
    if not recorded.tests():
        return 0
    target = _core.Cassette.load(cassette_path) if os.path.exists(cassette_path) else _core.Cassette()
    target.merge(recorded)
    target.save(cassette_path)
    return len(recorded.tests())


def uninstall() -> None:
    global POLICY
    POLICY = None
