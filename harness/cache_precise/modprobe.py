"""P-061 premise probe: how many tests of a suite leave in-memory state behind (docs/CACHE-PRECISE.md section 4).

A pytest plugin, independent of detpy, used only for measurement. Around each test's whole protocol (setup, call,
teardown) it digests every non-infrastructure module's globals (deep, in Python: slow, a prototype of the Rust walk),
a few interpreter cells, and the set of modules; it writes, per test, the cells whose digest changed.

    PYTHONPATH=harness/cache_precise P061_PROBE_OUT=/tmp/probe.json python -m pytest -p modprobe tests

The output has the number of tests, how many modified something, the most frequent cells, how many cells were
opaque (C objects with no probe here, digested by identity only), and the walk time.
"""
from __future__ import annotations

import collections
import decimal
import gc
import json
import os
import signal
import socket
import sys
import time
import types

import pytest

INFRA = ("_pytest", "pytest", "pluggy", "xdist", "execnet", "detpy", "py", "_py", "iniconfig", "modprobe",
         "_hypothesis_pytestplugin", "pytest_")
# declared pure memos (docs/CACHE-PRECISE.md section 4)
MEMO = {("re", "_cache"), ("re", "_cache2"), ("linecache", "cache"), ("typing", "_caches"), ("typing", "_cleanups"),
        ("encodings", "_cache"), ("sys", "path_importer_cache")}
LEAF = (int, float, complex, str, bytes, bool, type(None), type(Ellipsis), range)
ROOT_BUDGET = int(os.environ.get("P061_PROBE_ROOT_BUDGET", "20000"))


def _infra(name: str) -> bool:
    top = name.split(".", 1)[0]
    return any(top == p or (p.endswith("_") and top.startswith(p)) for p in INFRA)


class Walk:
    """Per-root structural digests: each root (one module global) is walked on its own, with a cycle guard and a
    node budget (``P061_PROBE_ROOT_BUDGET``); a root over budget digests as truncated (counted, not compared)."""

    def __init__(self):
        self.n = 0
        self.opaque = collections.Counter()
        self.truncated = 0

    def digest(self, root, owner: str):
        seen: dict = {}  # id -> object: kept alive, so a freed temporary's id is never taken for a visited one
        count = [0]

        def h(o, depth):
            count[0] += 1
            if count[0] > ROOT_BUDGET:
                raise OverflowError
            if isinstance(o, LEAF):
                return hash((type(o).__name__, o)) if not isinstance(o, float) or o == o else 7
            i = id(o)
            if i in seen:
                return 1  # a cycle or a shared object: its content is digested where first met
            seen[i] = o
            if isinstance(o, (types.ModuleType, types.BuiltinFunctionType, types.CodeType, types.MethodWrapperType,
                              types.WrapperDescriptorType, types.MethodDescriptorType, types.GetSetDescriptorType,
                              types.MemberDescriptorType)):
                return i
            if isinstance(o, type):
                # a class is walked where it is defined; elsewhere it is a reference
                if getattr(o, "__module__", None) != owner:
                    return i
                return hash((i, tuple((k, h(v, depth + 1)) for k, v in list(vars(o).items())
                                      if k not in ("__dict__", "__weakref__", "__doc__"))))
            if isinstance(o, dict):
                return hash(("d", tuple((h(k, depth + 1), h(v, depth + 1)) for k, v in list(o.items()))))
            if isinstance(o, (list, tuple, collections.deque)):
                return hash((type(o).__name__, tuple(h(v, depth + 1) for v in list(o))))
            if isinstance(o, (set, frozenset)):
                return hash((type(o).__name__, frozenset(h(v, depth + 1) for v in list(o))))
            if isinstance(o, (bytearray, memoryview)):
                return hash(bytes(o))
            if isinstance(o, types.FunctionType):
                if getattr(o, "__module__", None) != owner:
                    return i
                cells = []
                for c in o.__closure__ or ():
                    try:
                        cells.append(h(c.cell_contents, depth + 1))
                    except ValueError:
                        cells.append(0)
                return hash((i, h(o.__defaults__, depth + 1), h(o.__kwdefaults__, depth + 1), h(o.__dict__, depth + 1),
                             tuple(cells)))
            extra = 0
            if callable(getattr(o, "cache_info", None)):
                try:
                    extra = hash(tuple(o.cache_info()))
                except Exception:
                    pass
            d = getattr(o, "__dict__", None)
            if isinstance(d, dict):
                return hash((id(type(o)), extra, h(d, depth + 1)))
            slots = getattr(type(o), "__slots__", None)
            if slots:
                names = (slots,) if isinstance(slots, str) else slots
                return hash((id(type(o)), tuple(h(getattr(o, s, None), depth + 1) for s in names)))
            if extra:
                return extra
            try:
                r = o.__reduce_ex__(4)
                return hash(("r", h(r[1:] if isinstance(r, tuple) else r, depth + 1)))
            except Exception:
                self.opaque[type(o).__qualname__] += 1
                return i

        try:
            v = h(root, 0)
        except (OverflowError, RecursionError):
            self.truncated += 1
            v = "T"
        self.n += count[0]
        return v


def snapshot() -> tuple:
    w = Walk()
    cells = {}
    for name, m in list(sys.modules.items()):
        if m is None or _infra(name):
            continue
        d = getattr(m, "__dict__", None)
        if not isinstance(d, dict):
            continue
        for k, v in list(d.items()):
            if (name, k) in MEMO or k in ("__warningregistry__", "__loader__", "__spec__", "__builtins__"):
                continue
            cells[(name, k)] = w.digest(v, name)
    cells[("sys", "<modules>")] = hash(frozenset(sys.modules))
    cells[("sys", "<path>")] = hash(tuple(sys.path))
    cells[("sys", "<limits>")] = hash((sys.getrecursionlimit(), sys.get_int_max_str_digits(), sys.getswitchinterval()))
    cells[("gc", "<state>")] = hash((gc.isenabled(), gc.get_threshold()))
    cells[("os", "<environ>")] = hash(frozenset(os.environ.items()))
    cells[("os", "<cwd>")] = hash(os.getcwd())
    c = decimal.getcontext()
    cells[("decimal", "<context>")] = hash((c.prec, c.rounding, c.Emin, c.Emax))
    cells[("signal", "<handlers>")] = hash(tuple(id(signal.getsignal(s)) for s in (signal.SIGINT, signal.SIGTERM,
                                                                                    signal.SIGUSR1, signal.SIGALRM)))
    cells[("socket", "<timeout>")] = hash(socket.getdefaulttimeout())
    return cells, w


class Probe:
    def __init__(self):
        self.rows = []
        self.walk_s = 0.0
        self.opaque = collections.Counter()
        self.prev = None

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        t0 = time.perf_counter()
        before = snapshot()[0] if self.prev is None else self.prev
        self.walk_s += time.perf_counter() - t0
        yield
        t0 = time.perf_counter()
        after, w = snapshot()
        self.walk_s += time.perf_counter() - t0
        self.opaque.update(w.opaque)
        common = set(before) & set(after)
        # a truncated root (over the node budget) cannot be compared: listed apart, as unknown
        trunc = sorted(f"{m}.{k}" for (m, k) in common if "T" in (before[(m, k)], after[(m, k)]))
        mods = sorted(f"{m}.{k}" for (m, k) in common
                      if "T" not in (before[(m, k)], after[(m, k)]) and before[(m, k)] != after[(m, k)])
        old_mods = {m for (m, _) in before}
        mods += [f"{m}.* (first import)" for m in sorted({m for (m, _) in after} - old_mods)]
        self.rows.append({"nodeid": item.nodeid, "mods": mods, "truncated": trunc, "objects": w.n})
        self.prev = after

    def pytest_sessionfinish(self, session):
        path = os.environ.get("P061_PROBE_OUT")
        if not path:
            return
        n = len(self.rows)
        modifying = [r for r in self.rows if r["mods"]]
        cells = collections.Counter(c for r in modifying for c in r["mods"])
        trunc = collections.Counter(c for r in self.rows for c in r["truncated"])
        with open(path, "w") as fh:
            json.dump({"tests": n, "modifying": len(modifying), "quiet": n - len(modifying),
                       "with_truncated_cells": sum(1 for r in self.rows if r["truncated"]),
                       "truncated_cells": trunc.most_common(20), "walk_s": round(self.walk_s, 2),
                       "top_cells": cells.most_common(40), "opaque_types": self.opaque.most_common(30),
                       "rows": self.rows}, fh, indent=1)


def pytest_configure(config):
    config.pluginmanager.register(Probe(), "p061-modprobe")
