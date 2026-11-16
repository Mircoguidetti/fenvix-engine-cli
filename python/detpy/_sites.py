"""Call-site resolution and path normalisation.

Events carry the call site of the code that touched a non-deterministic
source. The site is the first frame that is neither standard library nor
infrastructure (pytest, pluggy, detpy): that is the line a developer wants to
see. Events whose first non-stdlib frame is infrastructure (e.g. pytest
creating ``tmp_path``) are not recorded at all.

Paths are normalised so traces are comparable across machines, virtualenvs
and pytest's numbered temporary directories.
"""

from __future__ import annotations

import os
import re
import sys
import sysconfig
import tempfile

_STDLIB = "stdlib"
_INFRA = "infra"
_USER = "user"

# Captured at import: tools such as blockbuster replace os.getcwd to forbid
# blocking calls in an event loop; detpy's own bookkeeping must not trip them.
_real_getcwd = os.getcwd
_cache: dict[str, tuple[str, str]] = {}
_rootdir: str | None = None
_basetemp_provider = None  # callable returning pytest's basetemp (or None)


def set_basetemp_provider(fn) -> None:
    global _basetemp_provider
    _basetemp_provider = fn


def _dirs() -> tuple[list[str], list[str], list[str]]:
    paths = sysconfig.get_paths()
    stdlib = {v for p in (paths.get("stdlib"), paths.get("platstdlib")) if p
              for v in (os.path.realpath(p), os.path.normpath(p))}
    site = set()
    for key in ("purelib", "platlib"):
        p = paths.get(key)
        if p:
            site.update((os.path.realpath(p), os.path.normpath(p)))
    for p in sys.path:
        if p.endswith("site-packages") or p.endswith("dist-packages"):
            site.update((os.path.realpath(p), os.path.normpath(p)))
    infra = []
    for name in ("_pytest", "pytest", "pluggy", "detpy", "_hypothesis_pytestplugin", "xdist", "execnet",
                 "pytest_cov", "coverage", "iniconfig"):
        mod = sys.modules.get(name)
        f = getattr(mod, "__file__", None)
        if f:
            for v in (os.path.realpath(f), os.path.normpath(os.path.abspath(f))):
                infra.append(os.path.dirname(v) if os.path.basename(f) == "__init__.py" else v)
    return sorted(stdlib, key=len, reverse=True), sorted(site, key=len, reverse=True), infra


_stdlib_dirs, _site_dirs, _infra_paths = _dirs()
_TMP = os.path.realpath(tempfile.gettempdir())
_HOME = os.path.expanduser("~")
_PYTEST_TMP = re.compile(r"pytest-of-[^/\\]+[/\\]pytest-\d+")


def refresh(rootdir: str | None = None) -> None:
    """Recompute directory classes (after pytest and plugins are imported)."""
    global _stdlib_dirs, _site_dirs, _infra_paths, _rootdir
    _stdlib_dirs, _site_dirs, _infra_paths = _dirs()
    if rootdir is not None:
        _rootdir = os.path.realpath(rootdir)
    _cache.clear()


def norm_path(path: object) -> str:
    """Machine independent rendering of a filesystem path argument."""
    if isinstance(path, int):
        return "<fd>"
    if path is None:
        return "."
    try:
        s = os.fsdecode(os.fspath(path))  # type: ignore[arg-type]
    except TypeError:
        return f"<{type(path).__name__}>"
    if not s:
        s = _real_getcwd()
    elif not os.path.isabs(s):
        s = os.path.normpath(os.path.join(_real_getcwd(), s))
    else:
        s = os.path.normpath(s)
    return _shorten(s)


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base + os.sep)


def _rel(path: str, base: str) -> str:
    """Relative path of an absolute ``path`` under ``base``, by string only
    (os.path.relpath would call os.getcwd)."""
    return "." if path == base else path[len(base) + 1:]


def _shorten(s: str) -> str:
    if _basetemp_provider is not None:
        bt = _basetemp_provider()
        if bt and _under(s, bt):
            return "<basetemp>/" + _rel(s, bt).replace(os.sep, "/")
    if _rootdir and _under(s, _rootdir):
        rel = _rel(s, _rootdir)
        return rel.replace(os.sep, "/")
    for d in _site_dirs:
        if _under(s, d):
            return "<site>/" + _rel(s, d).replace(os.sep, "/")
    for d in _stdlib_dirs:
        if _under(s, d):
            return "<stdlib>/" + _rel(s, d).replace(os.sep, "/")
    s = _PYTEST_TMP.sub("pytest-of-U/pytest-N", s)
    if _under(s, _TMP):
        return "<tmp>/" + _rel(s, _TMP).replace(os.sep, "/")
    if _HOME and _HOME != "/" and _under(s, _HOME):
        return "~/" + _rel(s, _HOME).replace(os.sep, "/")
    return s.replace(os.sep, "/")


def _classify(filename: str) -> tuple[str, str]:
    hit = _cache.get(filename)
    if hit is not None:
        return hit
    if filename.startswith("<"):
        # <frozen importlib._bootstrap>, <string>, <doctest ...>
        kind = _STDLIB if filename.startswith("<frozen") else _USER
        res = (kind, filename)
    else:
        # normpath, not realpath: no filesystem access on the hot path (it may
        # run in an event loop guarded against blocking calls).
        real = os.path.normpath(filename)
        if any(_under(real, p) or real == p for p in _infra_paths):
            kind = _INFRA
        elif any(_under(real, d) for d in _site_dirs):
            kind = _USER
        elif any(_under(real, d) for d in _stdlib_dirs):
            kind = _STDLIB
        else:
            kind = _USER
        res = (kind, _shorten(real))
    _cache[filename] = res
    return res


def resolve(depth: int) -> str | None:
    """Site of the first user frame above ``depth``; None if infrastructure."""
    try:
        f = sys._getframe(depth + 1)
    except ValueError:
        return "<unknown>"
    first = None
    while f is not None:
        kind, norm = _classify(f.f_code.co_filename)
        if kind == _USER:
            return f"{norm}:{f.f_lineno}"
        if kind == _INFRA:
            return None
        if first is None:
            first = f"{norm}:{f.f_lineno}"
        f = f.f_back
    return first or "<unknown>"
