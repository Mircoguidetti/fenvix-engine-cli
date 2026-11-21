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
            _tls.inside = True
            try:
                v = base.__getitem__(self, key)
            except KeyError:
                if _ACTIVE:
                    _note_value("env.get", key, None)
                raise
            finally:
                _tls.inside = False
            if _ACTIVE:
                _note_value("env.get", key, v)
            return v

        def __contains__(self, key):
            _tls.inside = True
            try:
                r = base.__contains__(self, key)
            finally:
                _tls.inside = False
            if _ACTIVE:
                _note_flag(key, r)
            return r

        def __iter__(self):
            if _ACTIVE:
                _note_list(self)
            _tls.inside = True
            try:
                keys = list(dict.keys(self._data))  # (base.__iter__ lists _data: read silently here)
            finally:
                _tls.inside = False
            for k in keys:
                yield self.decodekey(k)

    _Observed.__name__ = base.__name__
    _Observed.__qualname__ = base.__qualname__
    return _Observed


# names of the variables read outside any test (module scope of a test file or conftest, a plugin or a dependency
# at import): no test's event, so the header lists them and the verifier counts them as read by every test
# (R-054 N2); "*" when the environment was enumerated
OUTSIDE: set = set()


def _infra_reader() -> bool:
    """The read outside a test comes from the runner's machinery (pytest, its plugins, detpy: the first frame past the
    standard library), not from the project's code: not an input of the tests."""
    import sys

    from . import _level0, _sites

    f = sys._getframe(3)
    while f is not None:
        kind = _sites._classify(f.f_code.co_filename)[0]
        if kind != _sites._STDLIB and not f.f_code.co_filename.startswith(_OWN_DIR):
            top = str(f.f_globals.get("__name__") or "").split(".", 1)[0]
            return kind == _sites._INFRA or top in _level0.INFRA_PACKAGES or top.startswith("pytest_")
        f = f.f_back
    return True


_OWN_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep


def _outside(name: str) -> None:
    if not _state.is_quiet() and not _infra_reader():
        OUTSIDE.add(name)


def _untracked(name: str) -> bool:
    """A variable whose value is no run input although it reaches the test: CI-volatile and kept (TMPDIR,
    RUNNER_TEMP...), and the proxy variables while the network is closed (R-055 V1, V2). Those a project declares
    with FENVIX_VOLATILE_ENV are its own declaration that the value does not matter, and are not."""
    from . import _level0

    if name in _level0.VOLATILE_KEPT and name != "FENVIX_VOLATILE_ENV":
        return True
    if name in _level0.PROXY_ENV:
        cfg = _state.STATE.config
        return cfg is not None and "net" in cfg.controls and not getattr(cfg, "record_net", False)
    return False


def _note_untracked(key) -> None:
    """A test that reads such a variable cannot be proven identical: ``uncontrolled.env``."""
    name = _name(key)
    if _untracked(name):
        from . import uncontrolled

        uncontrolled._mark("env", f"{name}: read, but its value is no run input", 3)


def _note_value(op, key, v) -> None:
    if _state.STATE.nodeid is None:
        _outside(_name(key))
        return
    if _state.is_quiet():
        return
    _note_untracked(key)
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
    _note_untracked(key)
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


import threading as _threading

_tls = _threading.local()  # inside: os.environ's own methods are reading _data (their read is the event)


class _RecData(dict):
    """``os.environ._data``, ``os.environb._data`` and ``posix.environ`` under the env control: the same storage (a
    dict holding the environment, as before), whose reads by the code under test are events like ``os.environ``'s
    (R-055 V11; posix.environ in docs/VERIFY-INPUTS.md). os.environ's own methods read it silently (their read is
    already the event); the engine reads it with ``dict`` methods, which bypass these."""

    def _rec(self):
        return _ACTIVE and not getattr(_tls, "inside", False)

    def __getitem__(self, key):
        try:
            v = dict.__getitem__(self, key)
        except KeyError:
            if self._rec():
                _note_value("env.get", key, None)
            raise
        if self._rec():
            _note_value("env.get", key, v)
        return v

    def get(self, key, default=None):
        v = dict.get(self, key)
        if self._rec():
            _note_value("env.get", key, v)
        return default if v is None else v

    def __contains__(self, key):
        r = dict.__contains__(self, key)
        if self._rec():
            _note_flag(key, r)
        return r

    def _listed(self):
        if self._rec():
            _note_list(os.environ)

    def __iter__(self):
        self._listed()
        return dict.__iter__(self)

    def keys(self):
        self._listed()
        return dict.keys(self)

    def items(self):
        self._listed()
        return dict.items(self)

    def values(self):
        self._listed()
        return dict.values(self)

    def copy(self):
        self._listed()
        return dict(dict.items(self))


def _install_posix() -> None:
    data = getattr(os.environ, "_data", None)
    if not isinstance(data, dict) or isinstance(data, _RecData):
        return
    rec = _RecData(dict.items(data))
    os.environ._data = rec
    if getattr(os, "environb", None) is not None and getattr(os.environb, "_data", None) is data:
        os.environb._data = rec
    try:
        import posix

        if posix.environ is data:
            posix.environ = rec
    except ImportError:  # pragma: no cover - not POSIX
        pass


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
