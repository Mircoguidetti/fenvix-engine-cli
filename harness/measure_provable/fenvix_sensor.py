"""Measurement sensor for the PROVABLE study. Not product code: loaded with -p, used only here.

Two jobs:
  1. Mark the test phase in the syscall stream, so syscalls can be attributed to
     "before the test" / "during the test" / "after the test". The marks are stats of
     non-existent paths under /FENVIXMARK, which cost one syscall and no real I/O.
  2. Record, with sys.addaudithook, the Python-level operations that carry outside
     information (open, listdir, scandir, dlopen, exec, fork, connect, import). A syscall
     whose path appears here was made by Python; one that does not was made by native code.
"""
from __future__ import annotations

import os
import sys

_MARK_DIR = "/FENVIXMARK"
_AUDIT: list = []
_WATCH = frozenset((
    "open", "os.listdir", "os.scandir", "os.chdir", "os.system", "os.exec",
    "os.fork", "os.forkpty", "os.posix_spawn", "subprocess.Popen", "socket.connect",
    "socket.getaddrinfo", "socket.gethostbyname", "socket.bind", "socket.sendto",
    "ctypes.dlopen", "ctypes.dlsym", "import", "cpython.run_file", "glob.glob",
))
_PHASE = ["start"]


def _mark(what: str) -> None:
    try:
        os.stat(f"{_MARK_DIR}/{what}")
    except OSError:
        pass


def _hook(event: str, args) -> None:
    if event in _WATCH:
        a = args[0] if args else None
        if not isinstance(a, (str, bytes, int, type(None))):
            a = type(a).__name__
        if isinstance(a, bytes):
            try:
                a = a.decode("utf-8", "replace")
            except Exception:  # pragma: no cover
                a = "<bytes>"
        _AUDIT.append((_PHASE[0], event, a))


def pytest_configure(config):
    sys.addaudithook(_hook)


def pytest_runtest_logstart(nodeid, location):
    _PHASE[0] = "test"
    _mark("S")


def pytest_runtest_logfinish(nodeid, location):
    _mark("E")
    _PHASE[0] = "after"


def pytest_unconfigure(config):
    path = os.environ.get("FENVIX_SENSOR_AUDIT")
    if not path:
        return
    _mark("W")  # the sensor's own write starts here
    try:
        with open(path, "w") as fh:
            for phase, event, arg in _AUDIT:
                fh.write(f"{phase}\t{event}\t{arg}\n")
    except OSError:
        pass
