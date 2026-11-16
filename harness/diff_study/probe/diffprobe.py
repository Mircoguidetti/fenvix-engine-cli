"""Prototype probe for the execution-diff study (not part of detpy).

Loaded with ``-p diffprobe`` next to ``--det``. For every test it records,
with ``sys.monitoring`` (Python >= 3.12), three digests that detpy's event
trace does not carry today:

* ``calls``: the sequence of functions of the project (non-test files) that
  started, by qualified name only (a line-independent "call graph" event);
* ``rets``: the sequence of (function, summary of the returned value) for the
  same functions (a prototype "return value" event type);
* ``files``: the set of project files (tests included) whose code ran.

Output: JSON ``{nodeid: {"calls": hex, "rets": hex, "n_calls": n, "n_rets": n,
"files": [...]}}`` at ``$DIFFPROBE_OUT``. Project root: ``$DIFFPROBE_ROOT``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import zlib

import pytest

_ROOT = os.path.realpath(os.environ.get("DIFFPROBE_ROOT", os.getcwd()))
_OUT = os.environ.get("DIFFPROBE_OUT")
_TOOL = 4
_mon = getattr(sys, "monitoring", None)
_ADDR = re.compile(r"0x[0-9a-fA-F]+")

_SIMPLE = (int, float, bool, type(None), complex)
_TEXT = (str, bytes)
_SIZED = (list, tuple, dict, set, frozenset)

_kind_cache: dict[str, int] = {}  # 0 = not project, 1 = project source, 2 = project test file


def _kind(filename: str) -> int:
    k = _kind_cache.get(filename)
    if k is not None:
        return k
    k = 0
    if filename and not filename.startswith("<"):
        real = os.path.realpath(filename)
        if real.startswith(_ROOT + os.sep):
            rel = real[len(_ROOT) + 1:]
            parts = rel.split(os.sep)
            if any(p in (".venv", "venv", ".tox", ".nox", "site-packages") for p in parts):
                k = 0
            else:
                base = parts[-1]
                is_test = (base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"
                           or any(p in ("tests", "test", "testing", "t") for p in parts[:-1]))
                k = 2 if is_test else 1
    _kind_cache[filename] = k
    return k


def _summary(v) -> str:
    t = type(v)
    if t is int and not -2**31 <= v < 2**31:
        return "bigint"  # hashes and ids depend on memory addresses
    if t in _SIMPLE:
        return repr(v)
    if t in _TEXT:
        return repr(v[:64]) + f"/{len(v)}"
    if t in _SIZED:
        return f"{t.__name__}/{len(v)}"
    return t.__qualname__


class _Probe:
    def __init__(self):
        self.active = False
        self.calls = 0
        self.rets = 0
        self.n_calls = 0
        self.n_rets = 0
        self.files: set = set()
        self.results: dict = {}

    def start(self, code, offset):
        k = _kind(code.co_filename)
        if k == 0:
            return _mon.DISABLE
        if not self.active:
            return None
        self.files.add(code.co_filename)
        if k == 1:
            self.n_calls += 1
            self.calls = zlib.crc32(code.co_qualname.encode(), self.calls)
        return None

    def ret(self, code, offset, value):
        if _kind(code.co_filename) != 1:
            return _mon.DISABLE
        if not self.active:
            return None
        self.n_rets += 1
        try:
            s = "int" if code.co_name == "__hash__" else _summary(value)
        except Exception:
            s = "?"
        s = _ADDR.sub("0x?", s)
        self.rets = zlib.crc32(f"{code.co_qualname}={s}".encode("utf-8", "replace"), self.rets)
        return None

    def begin(self):
        self.calls = self.rets = self.n_calls = self.n_rets = 0
        self.files = set()
        self.active = True

    def end(self, nodeid):
        self.active = False
        rel = sorted(os.path.relpath(os.path.realpath(f), _ROOT).replace(os.sep, "/") for f in self.files)
        self.results[nodeid] = {"calls": f"{self.calls:08x}", "rets": f"{self.rets:08x}",
                                "n_calls": self.n_calls, "n_rets": self.n_rets, "files": rel}


_P = _Probe()
_enabled = False


def pytest_configure(config):
    global _enabled
    if _mon is None or not _OUT or _enabled:
        return
    try:
        _mon.use_tool_id(_TOOL, "diffprobe")
    except ValueError:
        return
    E = _mon.events
    _mon.register_callback(_TOOL, E.PY_START, _P.start)
    _mon.register_callback(_TOOL, E.PY_RETURN, _P.ret)
    _mon.set_events(_TOOL, E.PY_START | E.PY_RETURN)
    _enabled = True


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    if _enabled:
        _P.begin()
    try:
        yield
    finally:
        if _enabled:
            _P.end(item.nodeid)


def pytest_sessionfinish(session, exitstatus):
    if not _enabled or hasattr(session.config, "workerinput"):
        return
    _mon.set_events(_TOOL, 0)
    os.makedirs(os.path.dirname(os.path.abspath(_OUT)), exist_ok=True)
    with open(_OUT, "w") as f:
        json.dump(_P.results, f)
