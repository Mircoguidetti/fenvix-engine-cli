"""File times under the virtual clock (part of the ``time`` control; audit G-1516).

A file the test writes gets its times from the kernel's real clock, while ``time.time()`` is virtual: a test that
compares a file's ``st_mtime`` with the clock saw a file "from the future", with a value that differed at every run.
Under --det, the files a test opens for writing (``open``/``io.open`` in a writing mode, ``os.open`` with a writing
flag, and the destination of ``os.rename`` / ``os.replace`` of such a file) are remembered with the virtual wall
time of the write; ``os.stat`` and ``os.lstat`` of them (so ``os.path.getmtime``, ``Path.stat``, ``Path.exists``...)
return their access, modification and change times as that virtual time. Nothing is changed on disk: files the test
did not write (the checkout, libraries) keep their real times, and tools in C keep seeing the real ones (the cache
with proof treats those times as real clock reads).
"""

from __future__ import annotations

import builtins
import io
import os

from . import _core, _state

_written: dict = {}
_ACTIVE = False
_real_open = io.open
_real_os_open = os.open
_real_stat = os.stat
_real_lstat = os.lstat
_real_rename = os.rename
_real_replace = os.replace
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _key(path):
    try:
        if isinstance(path, int):
            return None
        p = os.fspath(path)
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        return os.path.abspath(p)
    except TypeError:
        return None


def _note(path) -> None:
    if not _ACTIVE or _state.STATE.nodeid is None:
        return
    k = _key(path)
    if k is not None:
        # the current virtual time, read without advancing the clock (a write is not a clock read)
        _written[k] = _core.clock_wall_ns(_core.clock_state().get("elapsed", 0))


def open_(file, mode="r", *args, **kwargs):
    f = _real_open(file, mode, *args, **kwargs)
    if _ACTIVE and isinstance(mode, str) and any(c in mode for c in "wax+"):
        _note(file)
    return f


def os_open(path, flags, *args, **kwargs):
    fd = _real_os_open(path, flags, *args, **kwargs)
    if _ACTIVE and flags & _WRITE_FLAGS:
        _note(path)
    return fd


def _moved(real):
    def move(src, dst, *args, **kwargs):
        r = real(src, dst, *args, **kwargs)
        if _ACTIVE:
            ks = _key(src)
            if ks is not None and ks in _written:
                kd = _key(dst)
                if kd is not None:
                    _written[kd] = _written.pop(ks)
        return r

    move.__name__ = real.__name__
    move.__doc__ = real.__doc__
    return move


def _virtual(res, ns: int):
    t10 = tuple(res)
    secs = ns // 1_000_000_000
    t10 = t10[:7] + (secs, secs, secs)
    f = ns / 1e9
    extra = {name: getattr(res, name) for name in ("st_blksize", "st_blocks", "st_rdev", "st_flags", "st_gen",
                                                   "st_birthtime", "st_birthtime_ns", "st_file_attributes",
                                                   "st_fstype", "st_rsize", "st_creator", "st_type",
                                                   "st_reparse_tag") if hasattr(res, name)}
    extra.update(st_atime=f, st_mtime=f, st_ctime=f, st_atime_ns=ns, st_mtime_ns=ns, st_ctime_ns=ns)
    try:
        return os.stat_result(t10, extra)
    except TypeError:  # pragma: no cover - a platform with other fields: the real result
        return res


def _stat_of(real):
    def stat(path, *args, **kwargs):
        res = real(path, *args, **kwargs)
        if _ACTIVE and _written and not isinstance(path, int):
            k = _key(path)
            ns = _written.get(k) if k is not None else None
            if ns is not None:
                return _virtual(res, ns)
        return res

    stat.__name__ = real.__name__
    stat.__doc__ = real.__doc__
    return stat


def install(patcher) -> None:
    global _ACTIVE
    _ACTIVE = True
    patcher.set(io, "open", open_)
    patcher.set(builtins, "open", open_)
    patcher.set(os, "open", os_open)
    patcher.set(os, "rename", _moved(_real_rename))
    patcher.set(os, "replace", _moved(_real_replace))
    for name, real in (("stat", _real_stat), ("lstat", _real_lstat)):
        from ._patch import nonbinding

        wrapper = _stat_of(real)
        wrapper.__wrapped__ = real
        # one object for every binding, so the cache (and anyone comparing by identity) sees the same function
        wrapper = nonbinding(wrapper, "os", name)
        patcher.set(os, name, wrapper)
        # references bound before the session (``from os import stat`` in a plugin loaded at startup) follow, as the
        # cache with proof rebinds them: the cache then finds them by this wrapper (the import system's ``posix``
        # module and detpy's own modules are left alone)
        import sys

        own = os.path.dirname(os.path.abspath(__file__)) + os.sep
        for mod in list(sys.modules.values()):
            d = getattr(mod, "__dict__", None)
            if not isinstance(d, dict) or mod is os or getattr(mod, "__name__", "") in ("posix", "nt") \
                    or str(getattr(mod, "__file__", "") or "").startswith(own):
                continue
            for k, v in list(d.items()):
                if v is real:
                    try:
                        patcher.set(mod, k, wrapper)
                    except Exception:
                        pass


def start_test() -> None:
    _written.clear()


def uninstall() -> None:
    global _ACTIVE
    _ACTIVE = False
    _written.clear()
