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


def _install_ctypes_getenv() -> None:
    """``getenv``/``secure_getenv`` looked up through ctypes (``CDLL(None).getenv``): their reads are events too. The C
    code of an extension that calls getenv itself is not observed (docs/VERIFY-INPUTS.md, gap)."""
    try:
        import ctypes
    except ImportError:  # pragma: no cover
        return
    base = ctypes.CDLL
    if getattr(base, "_detpy_getenv", False):
        return
    real_getattr, real_getitem = base.__getattr__, base.__getitem__

    def wrap(fn):
        if getattr(fn, "_detpy_getenv", False):
            return fn  # CDLL.__getattr__ goes through __getitem__: wrapped there already

        class _Getenv:
            _detpy_getenv = True
            __slots__ = ("_f",)

            def __init__(self, f):
                object.__setattr__(self, "_f", f)

            def __call__(self, key, *a):
                v = self._f(key, *a)
                if _ACTIVE:
                    _note_value("env.get", key, v)
                return v

            def __getattr__(self, n):
                return getattr(self._f, n)

            def __setattr__(self, n, v):
                setattr(self._f, n, v)
        return _Getenv(fn)

    def __getattr__(self, name):
        f = real_getattr(self, name)
        return wrap(f) if name in ("getenv", "secure_getenv") else f

    def __getitem__(self, name):
        f = real_getitem(self, name)
        return wrap(f) if name in ("getenv", "secure_getenv") else f

    base.__getattr__, base.__getitem__ = __getattr__, __getitem__
    base._detpy_getenv = True


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


class _PosixEnviron(dict):
    """``posix.environ`` under the env control: the same bytes mapping ``os.environ`` keeps (its ``_data``), whose
    reads are events like ``os.environ``'s (docs/VERIFY-INPUTS.md: a read through posix.environ was no event). A dict
    subclass over the live data: every read goes to that data, so ``os.environ`` writes are seen."""

    def __init__(self, data):
        super().__init__()
        self._d = data

    def __getitem__(self, key):
        try:
            v = self._d[key]
        except KeyError:
            if _ACTIVE:
                _note_value("env.get", key, None)
            raise
        if _ACTIVE:
            _note_value("env.get", key, v)
        return v

    def get(self, key, default=None):
        v = self._d.get(key)
        if _ACTIVE:
            _note_value("env.get", key, v)
        return default if v is None else v

    def __contains__(self, key):
        r = key in self._d
        if _ACTIVE:
            _note_flag(key, r)
        return r

    def _listed(self):
        if _ACTIVE:
            _note_list(os.environ)
        return self._d

    def __iter__(self):
        return iter(self._listed())

    def __len__(self):
        return len(self._d)

    def keys(self):
        return self._listed().keys()

    def items(self):
        return self._listed().items()

    def values(self):
        return self._listed().values()

    def copy(self):
        return dict(self._listed())

    def __repr__(self):
        return repr(self._d)

    def __setitem__(self, key, value):
        self._d[key] = value

    def __delitem__(self, key):
        del self._d[key]


def _install_posix() -> None:
    try:
        import posix
    except ImportError:  # pragma: no cover - not POSIX
        return
    data = getattr(os.environ, "_data", None)
    if isinstance(data, dict) and not isinstance(posix.environ, _PosixEnviron):
        posix.environ = _PosixEnviron(data)


def install() -> None:
    """Observe os.environ / os.environb (the class of the instances is swapped once; ``uninstall`` only stops the
    events, so a later wrapper, such as the cache's, is never undone), and posix.environ."""
    global _ACTIVE, _PATCHED
    _ACTIVE = True
    if _PATCHED:
        return
    _PATCHED = True
    _install_posix()
    _install_ctypes_getenv()
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
