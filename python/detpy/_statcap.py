"""Probes of paths as inputs of the cache with proof (and the directories the import system searched for a module
it did not find, see ``_find_and_load``): ``os.stat``, ``os.lstat``, ``os.readlink``, ``os.access`` and
``os.path.exists`` / ``isfile`` / ``isdir`` / ``islink`` / ``lexists`` (``pathlib``'s ``exists``, ``is_file``,
``is_dir``, ``stat`` and ``os.path.getsize`` / ``getmtime`` / ``realpath`` go through them).

The interpreter raises no audit event for these calls, so a test that decided something on whether a file exists,
on its size, mode or modification time, or on a symlink's target, had none of it as an input: its result was
reused after the file appeared, grew or was re-pointed (MEASURED before this module: three wrong reuses of four in
the probe of 2026-11-19, ``docs/runners/BUILD-python.md``). Each probe is handed to the capture
(``_core.cap_note_stat``, ``CaptureCore.probe`` in ``crates/detpy-py/src/capture.rs``), which keeps it as a
dependency of its own (``detpy_core::proof::probe_now``): existence and kind for the ``exists`` family, kind,
permission bits, size and modification time (a symlink's target) for ``stat`` / ``lstat``. Probes by the
interpreter's and the installed libraries' own files, and by infrastructure, are left out by the capture as reads
are. Not seen: ``os.DirEntry.stat()`` / ``is_dir()`` of a ``scandir`` entry (the listing's names are an input, an
entry turning from a file into a directory of the same name is not), ``os.stat`` bound before the capture started
(``from os import stat`` at import time), C code calling ``stat`` itself.
"""

from __future__ import annotations

import os
import posixpath
import stat as _st
import sys

from . import _core
from ._patch import Patcher

_note = _core.cap_note_stat
_real_stat = os.stat
_real_lstat = os.lstat
_real_readlink = os.readlink
_real_access = os.access
_PATCHER = Patcher()


def _stat(path, *args, dir_fd=None, follow_symlinks=True):
    if dir_fd is None and not args:
        _note(path, "s" if follow_symlinks else "S")
    return _real_stat(path, *args, dir_fd=dir_fd, follow_symlinks=follow_symlinks)


def _lstat(path, *args, dir_fd=None):
    if dir_fd is None and not args:
        _note(path, "S")
    return _real_lstat(path, *args, dir_fd=dir_fd)


def _readlink(path, *args, dir_fd=None):
    if dir_fd is None and not args:
        _note(path, "S")
    return _real_readlink(path, *args, dir_fd=dir_fd)


def _access(path, mode, *args, dir_fd=None, effective_ids=False, follow_symlinks=True):
    if dir_fd is None and not args:
        _note(path, "s" if follow_symlinks else "S")
    return _real_access(path, mode, *args, dir_fd=dir_fd, effective_ids=effective_ids,
                        follow_symlinks=follow_symlinks)


def _kind(path, follow: bool):
    _note(path, "e" if follow else "E")
    try:
        return (_real_stat if follow else _real_lstat)(path)
    except (OSError, ValueError):
        return None


def exists(path):
    """Test whether a path exists. Returns False for broken symbolic links"""
    return _kind(path, True) is not None


def lexists(path):
    """Test whether a path exists. Returns True for broken symbolic links"""
    return _kind(path, False) is not None


def isfile(path):
    """Test whether a path is a regular file"""
    st = _kind(path, True)
    return st is not None and _st.S_ISREG(st.st_mode)


def isdir(s):
    """Return true if the pathname refers to an existing directory."""
    st = _kind(s, True)
    return st is not None and _st.S_ISDIR(st.st_mode)


def islink(path):
    """Test whether a path is a symbolic link"""
    st = _kind(path, False)
    return st is not None and _st.S_ISLNK(st.st_mode)


def _searched(name: str) -> list:
    """The directories the import system searched for ``name`` (its parent package's ``__path__``, else
    ``sys.path``; the empty entry is the working directory)."""
    parent, _, _ = name.rpartition(".")
    if parent:
        dirs = list(getattr(sys.modules.get(parent), "__path__", None) or ())
    else:
        dirs = list(sys.path)
    out = []
    for d in dirs:
        if isinstance(d, str):
            out.append(d or os.getcwd())
    return out


def _note_miss(name: str) -> None:
    """Every path the import system's path finder would have found ``name`` at, in every searched directory: a
    package or namespace directory, a source, bytecode or extension module (existence probes)."""
    last = name.rpartition(".")[2]
    for d in _searched(name):
        base = os.path.join(d, last)
        _note(base, "M")
        for suffix in _SUFFIXES:
            _note(base + suffix, "M")


try:
    import importlib.machinery as _im

    _SUFFIXES = tuple(dict.fromkeys(_im.all_suffixes()))
except ImportError:  # pragma: no cover
    _SUFFIXES = (".py", ".pyc")


_bootstrap = sys.modules.get("importlib._bootstrap")
_real_find_and_load = getattr(_bootstrap, "_find_and_load", None)


def _find_and_load(name, import_):
    """The import system's ``_find_and_load``: a module it does not find makes the paths it would have been found at
    inputs of the importing test (an optional module that appears later is then seen: the import system's own cache
    of a directory's listing kept it out of the test's inputs)."""
    try:
        return _real_find_and_load(name, import_)
    except ModuleNotFoundError as e:
        if e.name == name:
            _note_miss(name)
        raise


def _find_spec(name, package=None):
    """``importlib.util.find_spec``: a module it does not find is a resolution miss too."""
    spec = _real_find_spec(name, package)
    if spec is None:
        try:
            import importlib.util

            _note_miss(importlib.util.resolve_name(name, package) if name.startswith(".") else name)
        except (ImportError, ValueError):
            pass
    return spec


try:
    import importlib.util as _iu

    _real_find_spec = _iu.find_spec
except ImportError:  # pragma: no cover
    _iu = None
    _real_find_spec = None


def install() -> None:
    """Patch the probes (``_proof.start_capture``). There is no switch to leave them out: a probed path is an input.
    (The equivalence test of the Rust capture with its pre-probe Python reference replaces this function from its
    own test-only plugin, ``tests/rust_hotpaths_ref/_capref.py``.)"""
    p = _PATCHER
    p.set(os, "stat", _stat)
    p.set(os, "lstat", _lstat)
    p.set(os, "readlink", _readlink)
    p.set(os, "access", _access)
    for name, fn in (("exists", exists), ("lexists", lexists), ("isfile", isfile), ("isdir", isdir),
                     ("islink", islink)):
        if getattr(posixpath, name, None) is not None and os.path is posixpath:
            p.set(posixpath, name, fn)
    if _real_find_and_load is not None:
        p.set(_bootstrap, "_find_and_load", _find_and_load)
    if _real_find_spec is not None:
        p.set(_iu, "find_spec", _find_spec)


def uninstall() -> None:
    _PATCHER.undo_all()
