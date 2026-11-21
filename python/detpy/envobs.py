"""The environment control (``env``): every read of ``os.environ`` by the code under test is an event.

``os.environ[k]``, ``os.environ.get(k)``, ``os.getenv(k)``, ``k in os.environ`` and enumerations of the
environment become events of source ``other`` with op ``env.get`` / ``env.has`` / ``env.list`` and the value
``NAME=set`` / ``NAME=<unset>`` (which variable, never its value). Every variable's value is a run input
(``_level0.env_inputs``, CI-volatile ones excepted): two runs where a test read a variable with different values are
reported ``input-differs`` for that test, naming the variable (design A, 2026-11-20).

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
    """``NAME=set`` / ``NAME=<unset>``: which variable the test read, not its value (design A, 2026-11-20). The value
    is a run input (``_level0.env_inputs``): when it differs between runs, the verifier reports the tests that read
    it as ``input-differs`` (named), not as diverged."""
    return f"{_name(key)}=<unset>" if value is None else f"{_name(key)}=set"


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


# names of the variables read outside any test (module scope of a test file or conftest, a plugin or a dependency
# at import): no test's event, so the header lists them and the verifier counts them as read by every test
# (R-054 N2); "*" when the environment was enumerated
OUTSIDE: set = set()


def _outside(name: str) -> None:
    if not _state.is_quiet():
        OUTSIDE.add(name)


def _note_value(op, key, v) -> None:
    if _state.STATE.nodeid is None:
        _outside(_name(key))
        return
    if _state.is_quiet():
        return
    try:
        _state.record("other", op, _dig(key, v), 2)
    except Exception:
        pass


def _note_flag(key, present) -> None:
    if _state.STATE.nodeid is None:
        _outside(_name(key))
        return
    if _state.is_quiet():
        return
    try:
        _state.record("other", "env.has", f"{_name(key)}={'set' if present else 'unset'}", 2)
    except Exception:
        pass


def _note_list(env) -> None:
    if _state.STATE.nodeid is None:
        _outside("*")
        return
    if _state.is_quiet():
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
