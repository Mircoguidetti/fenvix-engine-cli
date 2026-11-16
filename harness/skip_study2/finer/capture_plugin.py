"""pytest plugin for the cache-skip study (loaded with ``-p capture_plugin``).

Environment:

* ``CACHE_SKIP_OUT``  JSON file written at the end of the session.
* ``CACHE_SKIP_ROOT`` repository root (only paths below it are recorded).
* ``CACHE_SKIP_MODE`` ``time`` (durations and outcomes only) or ``capture``
  (also per-test dependency capture). In ``capture`` mode the session must run
  under ``coverage run`` so that ``coverage.Coverage.current()`` exists; the
  plugin switches the coverage *dynamic context* so that every executed line is
  attributed to:

  - ``t|<nodeid>``: the test (setup, call, teardown, function-scoped fixtures);
  - ``f|<scope>|<baseid>|<argname>``: the setup of a fixture with a scope wider
    than ``function`` (shared by every test that uses it);
  - ``c|<file nodeid>``: collection of a test file (module import,
    parametrisation), shared by every test of that file;
  - ``s|session``: anything else (startup, between tests).

  A ``sys.addaudithook`` hook records, with the same attribution, files below
  the root that are opened (non-Python data inputs), directories that are
  listed, subprocesses spawned and inet sockets connected. ``sys.modules`` is
  scanned after each test to know when each repository module was first loaded.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

MODE = os.environ.get("CACHE_SKIP_MODE", "time")
OUT = os.environ.get("CACHE_SKIP_OUT", "cache_skip_out.json")
ROOT = os.path.abspath(os.environ.get("CACHE_SKIP_ROOT", os.getcwd()))
ROOT_SEP = ROOT + os.sep

_ctx = ["s|session"]
_cov = None
_fs: dict[str, dict[str, set]] = {}  # ctx -> {"open": set, "list": set}
_spawn: dict[str, int] = {}
_net: dict[str, int] = {}
_tests: dict[str, dict] = {}
_order: list[str] = []
_first_seen: dict[str, int] = {}  # repo module file (relative) -> index of the test after which it was seen (-1 = collection)
_nmods = [0]
_t0 = time.perf_counter()
_marks: dict[str, float] = {}

_SKIP_SUFFIX = (".py", ".pyc", ".pyo", ".so", ".pth")
_SKIP_PARTS = (os.sep + "__pycache__", os.sep + ".git" + os.sep, os.sep + ".pytest_cache", os.sep + ".coverage",
               os.sep + ".tox" + os.sep, os.sep + ".mypy_cache", os.sep + ".hypothesis")


def _rel(path) -> str | None:
    try:
        if isinstance(path, int):
            return None
        p = os.fsdecode(path)
    except Exception:
        return None
    if not os.path.isabs(p):
        try:
            p = os.path.join(os.getcwd(), p)
        except Exception:
            return None
    p = os.path.normpath(p)
    if p == ROOT:
        return "."
    if not p.startswith(ROOT_SEP):
        return None
    return p[len(ROOT_SEP):]


def _audit(event, args):
    if event == "open":
        r = _rel(args[0])
        if r is None or r.startswith("<") or r.endswith(_SKIP_SUFFIX) or any(s in os.sep + r for s in _SKIP_PARTS):
            return
        _fs.setdefault(_ctx[0], {}).setdefault("open", set()).add(r)
    elif event in ("os.listdir", "os.scandir"):
        try:  # import machinery caches directory contents to find modules: not a data dependency
            if sys._getframe(1).f_code.co_filename.startswith("<frozen importlib"):
                return
        except ValueError:
            pass
        r = _rel(args[0] if args and args[0] is not None else ".")
        if r is None or any(s in os.sep + r for s in _SKIP_PARTS):
            return
        _fs.setdefault(_ctx[0], {}).setdefault("list", set()).add(r)
    elif event in ("subprocess.Popen", "os.posix_spawn", "os.exec", "os.system", "os.fork", "os.spawn"):
        _spawn[_ctx[0]] = _spawn.get(_ctx[0], 0) + 1
    elif event == "socket.connect":
        addr = args[1] if len(args) > 1 else None
        if isinstance(addr, tuple):
            _net[_ctx[0]] = _net.get(_ctx[0], 0) + 1


# --- study 2: code objects executed per test (all files), for the name-read rule --------------------
_codes: dict = {}          # code object -> key
_code_list: list = []
_cur = [set()]
_fixture_codes: dict = {}  # fixture context -> set of keys
_MON = [None]


def _on_start(code, offset):
    k = _codes.get(code)
    if k is None:
        k = _codes[code] = len(_code_list)
        _code_list.append(code)
    _cur[0].add(k)
    return sys.monitoring.DISABLE


def _mon_start():
    if not hasattr(sys, "monitoring") or os.environ.get("CACHE_SKIP_NAMES") != "1":
        return
    for tid in (4, 3, 5):
        try:
            sys.monitoring.use_tool_id(tid, "skip-study2-names")
        except ValueError:
            continue
        sys.monitoring.register_callback(tid, sys.monitoring.events.PY_START, _on_start)
        sys.monitoring.set_events(tid, sys.monitoring.events.PY_START)
        _MON[0] = tid
        return


def _mon_reset(newset):
    _cur[0] = newset
    if _MON[0] is not None:
        sys.monitoring.restart_events()


def _special_classes():
    """Repository classes whose creation runs user code over the class body: a metaclass other than type /
    ABCMeta, or a base defining __init_subclass__. Also the classes that define __init_subclass__ or are
    metaclasses (their future subclasses are special)."""
    import abc
    special, hooks = set(), set()
    for name, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if not f or _rel(f) is None:
            continue
        rel = _rel(f)
        todo = [v for v in list(vars(m).values()) if isinstance(v, type) and getattr(v, "__module__", None) == name]
        seen = set()
        while todo:
            c = todo.pop()
            if id(c) in seen:
                continue
            seen.add(id(c))
            try:
                q = c.__qualname__
                if type(c) not in (type, abc.ABCMeta) or any("__init_subclass__" in vars(b) for b in c.__mro__[1:-1]):
                    special.add(rel + "::" + q)
                if "__init_subclass__" in vars(c) or issubclass(c, type):
                    hooks.add(rel + "::" + q)
                todo.extend(v for v in list(vars(c).values()) if isinstance(v, type)
                            and getattr(v, "__module__", None) == name)
            except Exception:
                special.add(rel + "::" + getattr(c, "__qualname__", "?"))
    return sorted(special), sorted(hooks)


def _switch(ctx: str) -> None:
    _ctx[0] = ctx
    if _cov is not None:
        _cov.switch_context(ctx)


def _scan_modules(index: int) -> None:
    mods = sys.modules
    if len(mods) == _nmods[0]:
        return
    _nmods[0] = len(mods)
    for m in list(mods.values()):
        f = getattr(m, "__file__", None)
        if not f:
            continue
        r = _rel(f)
        if r is not None and r not in _first_seen:
            _first_seen[r] = index


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    global _cov
    _marks["configure"] = time.perf_counter() - _t0
    if MODE == "capture":
        import coverage
        _cov = coverage.Coverage.current()
        if _cov is None:
            raise pytest.UsageError("CACHE_SKIP_MODE=capture needs `coverage run`")
        sys.addaudithook(_audit)
        _switch("s|session")
        _mon_start()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_make_collect_report(collector):
    if MODE != "capture" or not isinstance(collector, (pytest.File, pytest.Class)):
        yield
        return
    prev = _ctx[0]
    _switch("c|" + collector.nodeid.split("::")[0])
    try:
        yield
    finally:
        _switch(prev)


def pytest_collection_finish(session):
    _marks["collected"] = time.perf_counter() - _t0
    if MODE == "capture":
        _scan_modules(-1)
        if _MON[0] is not None:
            _marks["special"], _marks["hooks"] = _special_classes()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_fixture_setup(fixturedef, request):
    if MODE != "capture" or fixturedef.scope == "function":
        yield
        return
    prev = _ctx[0]
    fctx = f"f|{fixturedef.scope}|{fixturedef.baseid}|{fixturedef.argname}"
    _switch(fctx)
    outer = _cur[0]
    mine = set()
    _mon_reset(mine)
    try:
        yield
    finally:
        _switch(prev)
        _fixture_codes.setdefault(fctx, set()).update(mine)
        outer.update(mine)
        _mon_reset(outer)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    nid = item.nodeid
    idx = len(_order)
    _order.append(nid)
    rec = _tests.setdefault(nid, {"idx": idx, "dur": 0.0, "outcome": None})
    if MODE == "capture":
        fx = []
        info = getattr(item, "_fixtureinfo", None)
        if info is not None:
            for name in item.fixturenames:
                defs = info.name2fixturedefs.get(name)
                if defs and defs[-1].scope != "function":
                    d = defs[-1]
                    fx.append(f"f|{d.scope}|{d.baseid}|{d.argname}")
        rec["fixtures"] = sorted(set(fx))
        _switch("t|" + nid)
        _mon_reset(set())
    t = time.perf_counter()
    try:
        yield
    finally:
        rec["wall"] = time.perf_counter() - t
        if MODE == "capture" and _MON[0] is not None:
            rec["codes"] = sorted(_cur[0])
            _mon_reset(set())
        if MODE == "capture":
            _switch("s|session")
            _scan_modules(idx)


def pytest_runtest_logreport(report):
    rec = _tests.setdefault(report.nodeid, {"idx": -1, "dur": 0.0, "outcome": None})
    rec["dur"] += report.duration
    o = report.outcome
    if report.when == "call":
        if rec["outcome"] in (None, "passed"):
            rec["outcome"] = "xfailed" if hasattr(report, "wasxfail") and o == "skipped" else o
    elif o != "passed":
        if report.when == "setup" and o == "skipped":
            rec["outcome"] = "skipped"
        elif o == "failed":
            rec["outcome"] = "error"
    elif rec["outcome"] is None and report.when == "teardown":
        rec["outcome"] = "passed"


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    _marks["finish"] = time.perf_counter() - _t0
    out = {
        "mode": MODE,
        "root": ROOT,
        "exitstatus": int(exitstatus),
        "marks": _marks,
        "tests": _tests,
        "order": _order,
    }
    if MODE == "capture":
        _switch("s|session")
        out["fs"] = {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in _fs.items()}
        out["spawn"] = _spawn
        out["net"] = _net
        out["first_seen"] = _first_seen
        if _MON[0] is not None:
            idents, ix, code_ids = [], {}, []
            for c in _code_list:
                names = set(c.co_names)
                for k in c.co_consts:
                    if isinstance(k, str) and len(k) < 80 and k.isidentifier():
                        names.add(k)
                row = []
                for n in names:
                    j = ix.get(n)
                    if j is None:
                        j = ix[n] = len(idents)
                        idents.append(n)
                    row.append(j)
                code_ids.append(sorted(row))
            out["names"] = {"idents": idents, "codes": code_ids,
                            "code_files": [_rel(c.co_filename) or "" for c in _code_list],
                            "fixtures": {k: sorted(v) for k, v in _fixture_codes.items()}}
    with open(OUT, "w") as fh:
        json.dump(out, fh)
