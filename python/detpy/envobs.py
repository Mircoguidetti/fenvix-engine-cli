"""The environment control (``env``): every read of ``os.environ`` by the code under test is an event.

``os.environ[k]``, ``os.environ.get(k)``, ``os.getenv(k)``, ``k in os.environ`` and enumerations of the
environment become events of source ``other`` with op ``env.get`` / ``env.has`` / ``env.list`` and the value
``NAME=<digest of the value>`` (never the value itself: environments hold secrets). Two runs where a test read a
variable with different values diverge at that read, and the verifier names the variable (G-1517). Variables read by
C code or by child processes leave no event: every variable is also a run input (``_level0.env_inputs``), so a
difference there is reported for every test.

The time zone and the locale are pinned by their own controls (``_level0.pin_tz_locale``); the other variables are
the project's own configuration and are not changed, only observed.
"""

from __future__ import annotations

import os

from . import _core, _state

_ACTIVE = False
_PATCHED = False


def _name(key) -> str:
    """The variable's name as valid text (bytes that are not UTF-8 escaped): events are JSON."""
    try:
        raw = key if isinstance(key, bytes) else os.fsencode(key)
    except Exception:
        return repr(key)
    return raw.decode("utf-8", "backslashreplace")


def _dig(key, value) -> str:
    if value is None:
        return f"{_name(key)}=<unset>"
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8", "surrogateescape")
    return f"{_name(key)}={_core.digest(raw)[:12]}"


def _make(base):
    class _Observed(base):
        def __getitem__(self, key):
            try:
                v = base.__getitem__(self, key)
            except KeyError:
                if _ACTIVE:
                    _note_value("env.get", key, None)
                raise
            if _ACTIVE:
                _note_value("env.get", key, v)
            return v

        def __contains__(self, key):
            r = base.__contains__(self, key)
            if _ACTIVE:
                _note_flag(key, r)
            return r

        def __iter__(self):
            if _ACTIVE:
                _note_list(self)
            return base.__iter__(self)

    _Observed.__name__ = base.__name__
    _Observed.__qualname__ = base.__qualname__
    return _Observed


def _note_value(op, key, v) -> None:
    if _state.STATE.nodeid is None or _state.is_quiet():
        return
    try:
        _state.record("other", op, _dig(key, v), 2)
    except Exception:
        pass


def _note_flag(key, present) -> None:
    if _state.STATE.nodeid is None or _state.is_quiet():
        return
    try:
        _state.record("other", "env.has", f"{_name(key)}={'set' if present else 'unset'}", 2)
    except Exception:
        pass


def _note_list(env) -> None:
    if _state.STATE.nodeid is None or _state.is_quiet():
        return
    try:
        names = sorted(k if isinstance(k, bytes) else os.fsencode(k)
                       for k in dict.keys(env._data))  # noqa: SLF001 (no event for our own read)
        _state.record("other", "env.list", f"{len(names)}:{_core.digest(bytes(1).join(names))[:12]}", 2)
    except Exception:
        pass


def install() -> None:
    """Observe os.environ / os.environb (the class of the instances is swapped once; ``uninstall`` only stops the
    events, so a later wrapper, such as the cache's, is never undone)."""
    global _ACTIVE, _PATCHED
    _ACTIVE = True
    if _PATCHED:
        return
    _PATCHED = True
    for name in ("environ", "environb"):
        o = getattr(os, name, None)
        if o is not None:
            try:
                o.__class__ = _make(type(o))
            except TypeError:  # pragma: no cover
                pass


def uninstall() -> None:
    global _ACTIVE
    _ACTIVE = False
