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

In Rust (``crates/detpy-py/src/network.rs``): the policy (``_Policy``: local names, numeric hosts, local proxies,
allowed hosts, fake addresses, replay counters), the connect / UDP / DNS decisions, the recorded-stream bookkeeping
and the cassette lookups. The socket wrappers are method descriptors of ``_socket.socket`` / ``ssl.SSLSocket`` whose
code is Rust; the DNS wrappers are Rust callables. They read this module's globals (``POLICY``, ``_real_*``, ...) at
every call, as the Python functions did. What stays here is interface: the replay server (socketpair and thread),
``ReplayTLSSocket``, ``SSLContext.wrap_socket`` and the patching. The Python original is
``tests/rust_hotpaths_ref/_ref_l0_network.py``.
"""

from __future__ import annotations

import _socket
import os
import socket
import ssl
import threading
from urllib.parse import urlsplit  # noqa: F401 - read by the Rust proxy parsing

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


_is_local_name = _core.net_is_local_name
_is_ip = _core.net_is_ip
_proxy_endpoints = _core.net_proxy_endpoints  # reads os.environ, urlsplit and _resolves_local from here
_resolves_local = _core.net_resolves_local  # a real lookup through _real_getaddrinfo (read at call time)
_Policy = _core.NetPolicy  # (mode, cassette, allow_hosts)
_blocked = _core.net_blocked
_target = _core.net_target

POLICY: _Policy | None = None


def _method(kind: str, owner: type, real) -> object:
    return _core.net_method(kind, real.__name__, owner, getattr(real, "__doc__", None))


_connect = _method("connect", _socket.socket, _real_connect)
_connect_ex = _method("connect_ex", _socket.socket, _real_connect_ex)
_sendto = _method("sendto", _socket.socket, _real_sendto)
_rec_send = _method("send", _socket.socket, _real_send)
_rec_sendall = _method("sendall", _socket.socket, _real_sendall)
_rec_recv = _method("recv", _socket.socket, _real_recv)
_rec_recv_into = _method("recv_into", _socket.socket, _real_recv_into)
_rec_ssl_send = _method("ssl_send", ssl.SSLSocket, _real_ssl_send)
_rec_ssl_write = _method("ssl_write", ssl.SSLSocket, _real_ssl_write)
_rec_ssl_read = _method("ssl_read", ssl.SSLSocket, _real_ssl_read)
_setsockopt = _method("setsockopt", _socket.socket, _real_setsockopt)  # replay: ignored on replayed sockets
_getpeername = _method("getpeername", _socket.socket, _real_getpeername)  # replay: the fake address
_getaddrinfo = _core.net_stand_in("getaddrinfo", "socket", "getaddrinfo", _real_getaddrinfo)
_gethostbyname = _core.net_stand_in("gethostbyname", "socket", "gethostbyname", _real_gethostbyname)
_gethostbyname_ex = _core.net_stand_in("gethostbyname_ex", "socket", "gethostbyname_ex", _real_gethostbyname_ex)


def _wrap_socket(self, sock, *args, **kwargs):
    if _core.net_is_replayed(sock):
        hostname = kwargs.get("server_hostname")
        if hostname is None and len(args) >= 3:
            hostname = args[2]
        return ReplayTLSSocket(sock, self, hostname)
    entry = _core.net_conn_of(sock)
    ssl_sock = _real_wrap_socket(self, sock, *args, **kwargs)
    if entry is not None:
        _core.net_conn_tls(ssl_sock, entry)  # the TLS socket records into the same connection
    return ssl_sock


# Replay ---------------------------------------------------------------------
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
                # secret header values are compared masked (a cassette stores them masked: audit G-0167)
                if _core.net_redact(got) != _core.net_redact(data):
                    mismatches.append((label, len(data), len(got), _core.digest(data), _core.digest(got)))
                    # the test sent another request than the recorded one: the recorded answer is not served
                    # (audit G-0166: a stale cassette answered requests it never saw); the test reads end of file
                    break
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


def _attach_replay(sock, segments, label: str, mismatches) -> None:
    """Re-point ``sock`` to a socketpair whose other end plays ``segments`` (called by the Rust connect once it chose
    the recorded connection)."""
    ours, peer = _real_socketpair()
    timeout = sock.gettimeout()
    os.dup2(ours.fileno(), sock.fileno(), inheritable=False)
    ours.close()
    sock.settimeout(timeout)
    _core.net_set_replay(sock, label)
    threading.Thread(target=_serve, args=(peer, segments, label, mismatches), daemon=True,
                     name=f"detpy-replay-{label}").start()


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


# Additions of claude/verifier-cli (Python, on top of the Rust wrappers) ---------------------------------------
_real_sendmsg = getattr(socket.socket, "sendmsg", None)
_real_recvmsg = getattr(socket.socket, "recvmsg", None)
_real_recvmsg_into = getattr(socket.socket, "recvmsg_into", None)
_real_gethostbyaddr = socket.gethostbyaddr
_real_getnameinfo = socket.getnameinfo
_real_getfqdn = socket.getfqdn
REFUSED: list = []  # (test, label) whose replay was refused (the request differed from the recording)
STALE: list = []  # tests whose recording is older than --det-cassette-max-age (not replayed)
BLACKHOLE_PROXY = "http://127.0.0.1:9"  # the discard port: nothing listens, a connection is refused at once
PROXY_KEYS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy")


def _record_bytes(sock, direction: str, data) -> None:
    """Append bytes moved by sendmsg / recvmsg of a recorded connection (audit G-0165: they were not recorded)."""
    if POLICY is None or POLICY.mode != "record" or not data:
        return
    try:
        entry = _core.net_conn_of(sock)
    except TypeError:
        return
    if entry is not None:
        POLICY.cassette.append(entry[0], entry[1], direction, bytes(data))


def _rec_sendmsg(self, buffers, *args, **kwargs):
    bufs = [bytes(b) for b in buffers]
    n = _real_sendmsg(self, bufs, *args, **kwargs)
    _record_bytes(self, "send", b"".join(bufs)[:n])
    return n


def _rec_recvmsg(self, *args, **kwargs):
    res = _real_recvmsg(self, *args, **kwargs)
    _record_bytes(self, "recv", res[0])
    return res


def _rec_recvmsg_into(self, buffers, *args, **kwargs):
    bufs = list(buffers)
    res = _real_recvmsg_into(self, bufs, *args, **kwargs)
    n, left = res[0], res[0]
    out = bytearray()
    for b in bufs:
        mv = memoryview(b).cast("B")
        take = min(left, len(mv))
        out += mv[:take]
        left -= take
        if not left:
            break
    _record_bytes(self, "recv", bytes(out[:n]))
    return res


def _guarded_host(host) -> bool:
    """Whether a reverse or auxiliary lookup of ``host`` may go to the real resolver: a local name, an allowed host,
    or record mode."""
    if POLICY is None or POLICY.mode == "record":
        return True
    try:
        h = host.decode() if isinstance(host, bytes) else str(host)
    except Exception:
        return False
    if _is_local_name(h):
        return True
    return h.lower().rstrip(".") in {a.lower() for a in POLICY.allow}


def _fake_host(ip) -> str | None:
    if POLICY is None:
        return None
    try:
        return POLICY.host_of_ip.get(ip)
    except Exception:
        return None


def _blocked_lookup(what: str):
    _state.record_at("net", "dns.blocked", "<lookup>", what)
    return socket.herror(1, f"fenvix --det: reverse lookup of {what} blocked (closed network; --det-allow-host or "
                            f"--det-record to reach it)")


def gethostbyaddr(ip):
    """Reverse lookups under --det (audit G-2199): local addresses and allowed hosts go to the resolver; the fake
    addresses of replayed hosts answer with their host; anything else is blocked."""
    host = _fake_host(ip)
    if host is not None:
        return (host, [], [ip])
    if _guarded_host(ip):
        return _real_gethostbyaddr(ip)
    raise _blocked_lookup(str(ip))


def getnameinfo(sockaddr, flags):
    host = _fake_host(sockaddr[0]) if isinstance(sockaddr, tuple) and sockaddr else None
    if host is not None:
        return (host, str(sockaddr[1]))
    if not isinstance(sockaddr, tuple) or not sockaddr or _guarded_host(sockaddr[0]):
        return _real_getnameinfo(sockaddr, flags)
    raise _blocked_lookup(str(sockaddr[0]))


def getfqdn(name=""):
    """``socket.getfqdn``: the local host's name stays real (it is configuration); another name is answered without
    a lookup (the name itself, what getfqdn returns when the resolver knows nothing more) unless it may be looked
    up."""
    if not name or name == "0.0.0.0" or _guarded_host(name):
        return _real_getfqdn(name)
    host = _fake_host(name)
    return host if host is not None else name


def _child_env(env):
    """The environment of a child process under a closed network (audit G-1520): proxy variables point at a port
    where nothing listens, local hosts and allowed hosts excepted (NO_PROXY), so curl, wget, git, pip and other
    programs that honour them cannot reach the network. A child that ignores them is an uncontrolled source of the
    test (``uncontrolled.child``)."""
    allow = sorted(POLICY.allow) if POLICY is not None else []
    no_proxy = ",".join(["localhost", "127.0.0.1", "::1", *allow])
    out = dict(env)
    for k in PROXY_KEYS:
        out[k] = BLACKHOLE_PROXY
    out["NO_PROXY"] = out["no_proxy"] = no_proxy
    return out


def _closed_children(real_init):
    def __init__(self, args, *a, **kwargs):
        if POLICY is None or POLICY.mode == "record" or _state.STATE.nodeid is None:
            return real_init(self, args, *a, **kwargs)
        if "env" in kwargs and kwargs["env"] is not None:
            kwargs["env"] = _child_env(kwargs["env"])
            return real_init(self, args, *a, **kwargs)
        if len(a) >= 9 and a[8] is not None:  # env passed by position (args, bufsize, ..., cwd, env)
            a = (*a[:8], _child_env(a[8]), *a[9:])
            return real_init(self, args, *a, **kwargs)
        # inherited environment: set the variables for the spawn only
        saved = {k: os.environ.get(k) for k in (*PROXY_KEYS, "NO_PROXY", "no_proxy")}
        try:
            with _state.quiet():
                os.environ.update(_child_env({}))
            return real_init(self, args, *a, **kwargs)
        finally:
            with _state.quiet():
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    __init__.__doc__ = real_init.__doc__
    return __init__


def _stale_tests(cassette, max_age_days: float) -> list:
    """Tests whose recording is older than ``max_age_days`` (or has no date) (audit G-1519)."""
    import datetime as _dt

    if not max_age_days or max_age_days <= 0:
        return []
    now = _dt.datetime.now(_dt.timezone.utc)
    out = []
    for t in cassette.tests():
        when = cassette.recorded(t)
        try:
            age = (now - _dt.datetime.fromisoformat(when)).total_seconds() / 86400 if when else None
        except ValueError:
            age = None
        if age is None or age > max_age_days:
            out.append(t)
    return out


# Installation ---------------------------------------------------------------
def install(patcher: Patcher, record: bool, cassette_path: str | None, allow_hosts, max_age_days: float = 0) -> str:
    global POLICY
    if record:
        mode, cassette = "record", _core.Cassette()
    elif cassette_path and os.path.exists(cassette_path):
        mode, cassette = "replay", _core.Cassette.load(cassette_path)
        STALE[:] = _stale_tests(cassette, max_age_days)
        for t in STALE:  # an outdated recording is not replayed: the test meets the closed network
            cassette.clear_test(t)
    else:
        mode, cassette = "block", None
    REFUSED.clear()
    POLICY = _Policy(mode, cassette, allow_hosts)
    patcher.set(socket, "gethostbyaddr", gethostbyaddr)
    patcher.set(socket, "getnameinfo", getnameinfo)
    patcher.set(socket, "getfqdn", getfqdn)
    import subprocess

    patcher.set(subprocess.Popen, "__init__", _closed_children(subprocess.Popen.__init__))
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
        if _real_sendmsg is not None:
            patcher.set(socket.socket, "sendmsg", _rec_sendmsg)
        if _real_recvmsg is not None:
            patcher.set(socket.socket, "recvmsg", _rec_recvmsg)
        if _real_recvmsg_into is not None:
            patcher.set(socket.socket, "recvmsg_into", _rec_recvmsg_into)
    return mode


def start_test() -> None:
    if POLICY is not None:
        POLICY.start_test()


def end_test() -> None:
    if POLICY is None:
        return
    for label, n_exp, n_got, d_exp, d_got in sorted(POLICY.mismatches):
        _state.record_at("net", "replay.mismatch", "<end>", f"{label} expected {n_exp}B:{d_exp} got {n_got}B:{d_got}")
        REFUSED.append((_state.STATE.nodeid, label))


def save_recordings(cassette_path: str) -> int:
    """Merge recordings into the cassette file; returns the number of tests saved."""
    if POLICY is None or POLICY.mode != "record":
        return 0
    recorded = POLICY.cassette
    if not recorded.tests():
        return 0
    import datetime as _dt

    when = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()  # real date: staleness (G-1519)
    for t in recorded.tests():
        recorded.set_recorded(t, when)
    target = _core.Cassette.load(cassette_path) if os.path.exists(cassette_path) else _core.Cassette()
    target.merge(recorded)
    target.save(cassette_path)
    return len(recorded.tests())


def uninstall() -> None:
    global POLICY
    POLICY = None


_core.net_configure(globals())
