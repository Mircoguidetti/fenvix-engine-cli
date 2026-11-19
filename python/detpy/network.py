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


_core.net_configure(globals())
