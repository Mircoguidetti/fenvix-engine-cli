"""Normalised filesystem enumeration order.

``os.listdir``, ``os.scandir`` (and therefore ``os.walk``, ``shutil``, ...),
``glob.glob``/``iglob``, ``Path.iterdir``/``glob``/``rglob`` return entries
sorted by name. Each enumeration done by the code under test is recorded as an
event (normalised directory, number of entries, digest of the names).
"""

from __future__ import annotations

import glob
import os
import pathlib

from . import _sites, _state
from ._patch import Patcher, disguise

_real_listdir = os.listdir
_real_scandir = os.scandir
_real_glob = glob.glob
_real_iglob = glob.iglob
_real_iterdir = pathlib.Path.iterdir
_real_path_glob = pathlib.Path.glob
_real_path_rglob = pathlib.Path.rglob


def _event(op: str, where: object, names: list, depth: int = 2) -> None:
    if _state.STATE.nodeid is None or _state.is_quiet():
        return
    _state.record("fs", op, f"{_sites.norm_path(where)}|{len(names)}|{_state.digest_names(names)}", depth=depth)


def listdir(path=None):
    names = _real_listdir() if path is None else _real_listdir(path)
    names.sort()
    _event("os.listdir", path, names)
    return names


class SortedScandir:
    """Drop-in for the iterator returned by ``os.scandir`` (sorted by name)."""

    __slots__ = ("_entries", "_it")

    def __init__(self, entries: list) -> None:
        self._entries = entries
        self._it = iter(entries)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self) -> None:
        self._it = iter(())

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def scandir(path=None):
    it = _real_scandir() if path is None else _real_scandir(path)
    with it:
        entries = sorted(it, key=lambda e: e.name)
    _event("os.scandir", path, [e.name for e in entries])
    return SortedScandir(entries)


def _quietly(fn, *args, **kwargs):
    with _state.quiet():
        return fn(*args, **kwargs)


def glob_glob(*args, **kwargs):
    res = sorted(_quietly(_real_glob, *args, **kwargs))
    _event("glob.glob", args[0] if args else kwargs.get("pathname"), [_sites.norm_path(p) for p in res])
    return res


def glob_iglob(*args, **kwargs):
    # Lazy like the original: the directory is read on the first next(), in
    # the thread that iterates (asyncio code runs it in a worker thread).
    def gen():
        res = sorted(_quietly(lambda: list(_real_iglob(*args, **kwargs))))
        _event("glob.iglob", args[0] if args else kwargs.get("pathname"), [_sites.norm_path(p) for p in res])
        yield from res

    return gen()


def path_iterdir(self):
    def gen():
        res = sorted(_quietly(lambda: list(_real_iterdir(self))), key=lambda p: p.name)
        _event("Path.iterdir", self, [p.name for p in res])
        yield from res

    return gen()


def path_glob(self, *args, **kwargs):
    def gen():
        res = sorted(_quietly(lambda: list(_real_path_glob(self, *args, **kwargs))), key=str)
        _event("Path.glob", self, [_sites.norm_path(p) for p in res])
        yield from res

    return gen()


def path_rglob(self, *args, **kwargs):
    def gen():
        res = sorted(_quietly(lambda: list(_real_path_rglob(self, *args, **kwargs))), key=str)
        _event("Path.rglob", self, [_sites.norm_path(p) for p in res])
        yield from res

    return gen()


def install(patcher: Patcher) -> None:
    patcher.set(os, "listdir", disguise(listdir, "os", "listdir"))
    patcher.set(os, "scandir", disguise(scandir, "os", "scandir"))
    patcher.set(glob, "glob", disguise(glob_glob, "glob", "glob", binds=True))
    patcher.set(glob, "iglob", disguise(glob_iglob, "glob", "iglob", binds=True))
    # Python 3.13+: pathlib globbing binds os.scandir at class creation.
    globber = getattr(glob, "_StringGlobber", None)
    if globber is not None and "scandir" in vars(globber):
        patcher.set(globber, "scandir", staticmethod(scandir))
    patcher.set(pathlib.Path, "iterdir", path_iterdir)
    patcher.set(pathlib.Path, "glob", path_glob)
    patcher.set(pathlib.Path, "rglob", path_rglob)
