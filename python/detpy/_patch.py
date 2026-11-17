"""Reversible monkeypatching."""

from __future__ import annotations

import sys
import types
from typing import Any, Callable

_MISSING = object()


class Patcher:
    """Set attributes and remember how to undo it (LIFO)."""

    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, Any]] = []

    def set(self, obj: Any, name: str, value: Any) -> Any:
        """Replace ``obj.name`` with ``value`` and return the original.

        On a module, a replacement keeps the binding behaviour of the original:
        if the original does not bind as a method when stored as a class
        attribute (builtins, bound methods), a Python-function replacement is
        made non-binding too (review E4: os.system, socket.gethostbyname, ...).
        """
        previous = getattr(obj, name, None)
        if (isinstance(obj, types.ModuleType) and isinstance(value, types.FunctionType)
                and previous is not None and callable(previous) and not binds_as_method(previous)):
            value = nonbinding(value, obj.__name__, name)
        own = obj.__dict__.get(name, _MISSING) if hasattr(obj, "__dict__") else _MISSING
        # Inherited attribute (own is _MISSING): restoring means deleting our override.
        self._undo.append((obj, name, own))
        setattr(obj, name, value)
        return previous

    def set_type_attr(self, tp: type, name: str, value: Any) -> Any:
        """Set an attribute on a built-in (C, immutable) type such as ``datetime.datetime``.

        Uses the type's underlying dict and ``PyType_Modified`` (CPython only):
        identity, ``isinstance`` and subclassing of the type are unaffected.
        """
        import ctypes
        import gc

        d = gc.get_referents(tp.__dict__)[0]
        previous = d.get(name, _MISSING)
        d[name] = value
        ctypes.pythonapi.PyType_Modified(ctypes.py_object(tp))

        def undo() -> None:
            if previous is _MISSING:
                d.pop(name, None)
            else:
                d[name] = previous
            ctypes.pythonapi.PyType_Modified(ctypes.py_object(tp))

        self._undo.append((undo, None, None))
        return previous

    def wrap(self, obj: Any, name: str, factory: Callable[[Any], Any]) -> Any:
        """Replace ``obj.name`` with ``factory(original)``."""
        original = getattr(obj, name)
        self.set(obj, name, factory(original))
        return original

    def undo_all(self) -> None:
        while self._undo:
            obj, name, original = self._undo.pop()
            try:
                if name is None:
                    obj()
                elif original is _MISSING:
                    delattr(obj, name)
                else:
                    setattr(obj, name, original)
            except (AttributeError, TypeError):  # pragma: no cover - best effort
                pass

    def __len__(self) -> int:
        return len(self._undo)


def disguise(fn: Any, module: str, name: str, binds: bool = False) -> Any:
    """Stand-in for ``module.name`` that pickles by reference as ``module.name``.

    The objects detpy replaces (time.time, os.urandom, random.random, ...) are
    builtins or bound methods: stored as a class attribute and called through an
    instance they receive no ``self``. A plain Python function would bind
    (``timer = time.time`` then ``self.timer()`` -> TypeError, DRF throttling).
    Unless ``binds`` is true (the original is itself a Python function, e.g.
    glob.glob), the stand-in is a callable object without ``__get__``.
    """
    try:
        fn.__module__ = module
        fn.__qualname__ = name
        fn.__name__ = name
    except (AttributeError, TypeError):  # pragma: no cover
        pass
    return fn if binds else nonbinding(fn, module, name)


class _NonBinding:
    """Base of the non-binding stand-ins (see ``disguise``)."""

    def __reduce__(self):
        return self.__qualname__  # pickled by reference, like the builtin

    def __repr__(self):
        return f"<built-in function {self.__name__}>"


class _Probe:
    pass


def binds_as_method(obj: Any) -> bool:
    """True when ``obj`` stored as a class attribute is bound on instance access
    (it receives ``self``): Python functions, cython binding functions... False
    for builtins, bound methods, classes and other plain callables."""
    if isinstance(obj, type):
        return False
    try:
        _Probe.attr = obj
        return _Probe().attr is not obj
    except Exception:  # pragma: no cover - exotic descriptors
        return False
    finally:
        try:
            del _Probe.attr
        except AttributeError:  # pragma: no cover
            pass


def nonbinding(fn: Any, module: str, name: str) -> Any:
    """A callable object that calls ``fn`` directly (``__call__`` is a staticmethod:
    no extra Python frame) and, like a builtin, does not bind as a method."""
    if isinstance(fn, _NonBinding):
        return fn
    cls = type(name, (_NonBinding,), {"__call__": staticmethod(fn), "__module__": module})
    obj = cls()
    obj.__name__ = name
    obj.__qualname__ = name
    obj.__module__ = module
    obj.__doc__ = getattr(fn, "__doc__", None)
    obj.__wrapped__ = getattr(fn, "__wrapped__", fn)
    return obj


def rebind_module_references(
    patcher: Patcher, replacements: dict[int, tuple[Any, Any]], skip: Callable[[str, Any], bool]
) -> list[str]:
    """Replace module-level references to real objects with their fakes.

    ``replacements`` maps ``id(real) -> (real, fake)``. This covers modules that
    were imported *before* detpy installed its controls and did
    ``from time import time`` / ``from datetime import datetime``.
    Returns ``["module.attr", ...]`` that were rebound.
    """
    rebound = []
    for modname, mod in list(sys.modules.items()):
        if mod is None or skip(modname, mod):
            continue
        try:
            items = list(vars(mod).items())
        except TypeError:
            continue
        for attr, value in items:
            entry = replacements.get(id(value))
            if entry is not None and entry[0] is value:
                patcher.set(mod, attr, entry[1])
                rebound.append(f"{modname}.{attr}")
    return rebound
