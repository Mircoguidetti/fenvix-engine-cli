"""Normalised filesystem enumeration order.

``os.listdir``, ``os.scandir`` (and therefore ``os.walk``, ``shutil``, ...),
``glob.glob``/``iglob``, ``Path.iterdir``/``glob``/``rglob`` return entries
sorted by name. Each enumeration done by the code under test is recorded as an
event (normalised directory, number of entries, digest of the names).

In Rust (``crates/detpy-py/src/fsorder.rs``): the ``os.listdir`` / ``os.scandir`` stand-ins (which read
``_real_listdir`` / ``_real_scandir`` below at every call), ``SortedScandir``, the event and the quiet, sorted
listing behind the ``glob`` / ``pathlib`` wrappers (``_core.fs_sorted``); the wrappers stay Python functions (they
bind as methods like the originals, and their generators stay lazy). The Python original is
``tests/rust_hotpaths_ref/_ref_l0_fsorder.py``.
"""

from __future__ import annotations

import glob
import operator
import os
import pathlib

from . import _core
from ._patch import Patcher, disguise

_real_listdir = os.listdir
_real_scandir = os.scandir
_real_glob = glob.glob
_real_iglob = glob.iglob
_real_iterdir = pathlib.Path.iterdir
_real_path_glob = pathlib.Path.glob
_real_path_rglob = pathlib.Path.rglob
_BY_NAME = operator.attrgetter("name")  # the sort key of scandir / iterdir

listdir = _core.stand_in("listdir", globals(), "os", "listdir", wrapped=_real_listdir)
scandir = _core.stand_in("scandir", globals(), "os", "scandir", wrapped=_real_scandir)
SortedScandir = _core.SortedScandir
_sorted = _core.fs_sorted  # (op, where, real, args, kwargs, key, by_name, depth): event `depth` frames above


def glob_glob(*args, **kwargs):
    return _sorted("glob.glob", args[0] if args else kwargs.get("pathname"), _real_glob, args, kwargs, None, False)


def glob_iglob(*args, **kwargs):
    # Lazy like the original: the directory is read on the first next(), in
    # the thread that iterates (asyncio code runs it in a worker thread).
    def gen():
        yield from _sorted("glob.iglob", args[0] if args else kwargs.get("pathname"), _real_iglob, args, kwargs,
                           None, False)

    return gen()


def path_iterdir(self):
    def gen():
        yield from _sorted("Path.iterdir", self, _real_iterdir, (self,), None, _BY_NAME, True)

    return gen()


def path_glob(self, *args, **kwargs):
    def gen():
        yield from _sorted("Path.glob", self, _real_path_glob, (self, *args), kwargs, str, False)

    return gen()


def path_rglob(self, *args, **kwargs):
    def gen():
        yield from _sorted("Path.rglob", self, _real_path_rglob, (self, *args), kwargs, str, False)

    return gen()


def install(patcher: Patcher) -> None:
    patcher.set(os, "listdir", listdir)
    patcher.set(os, "scandir", scandir)
    patcher.set(glob, "glob", disguise(glob_glob, "glob", "glob", binds=True))
    patcher.set(glob, "iglob", disguise(glob_iglob, "glob", "iglob", binds=True))
    # Python 3.13: pathlib globbing binds os.scandir at class creation (3.14 wraps it in a function that
    # yields (entry, name, path) and looks os.scandir up at call time: leave that one alone).
    globber = getattr(glob, "_StringGlobber", None)
    if globber is not None and getattr(vars(globber).get("scandir"), "__func__", None) is _real_scandir:
        patcher.set(globber, "scandir", staticmethod(scandir))
    patcher.set(pathlib.Path, "iterdir", path_iterdir)
    patcher.set(pathlib.Path, "glob", path_glob)
    patcher.set(pathlib.Path, "rglob", path_rglob)
