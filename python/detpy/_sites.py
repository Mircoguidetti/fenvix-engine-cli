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

from . import _core

# bound once: a test may remove sys._getframe (attrs' test_missing_sys_getframe) while detpy's hooks run
_getframe = sys._getframe

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
    _core.l0_sites_cleared()


# norm_path(path): machine independent rendering of a filesystem path argument (an int: "<fd>", None: ".", not a
# path: "<TypeName>"; else made absolute against _real_getcwd() and normalised, then shortened); _shorten(s): an
# absolute path relative to the first of pytest's basetemp (provider above), _rootdir, _site_dirs, _stdlib_dirs,
# the temporary directory (pytest's numbered directories renamed) and the home directory that contains it. In Rust
# (``crates/detpy-py/src/fsorder.rs``), reading the globals above at every call; the Python original is
# ``tests/rust_hotpaths_ref/_ref_l0_sites_norm.py``.
norm_path = _core.l0_norm_path
_shorten = _core.l0_shorten


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base + os.sep)


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
    """Site of the first user frame ``depth`` frames above the caller; None if infrastructure.

    In Rust (``_core.l0_resolve``): the caller frames are walked with the classification cache above
    (``_classify``, ``_cache``); the Python original is ``tests/rust_hotpaths_ref/_ref_l0_sites.py``."""
    return _core.l0_resolve(depth)
