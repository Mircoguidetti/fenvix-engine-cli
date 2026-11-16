"""Reversible monkeypatching."""

from __future__ import annotations

import sys
from typing import Any, Callable

_MISSING = object()


class Patcher:
    """Set attributes and remember how to undo it (LIFO)."""

    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, Any]] = []

    def set(self, obj: Any, name: str, value: Any) -> Any:
        """Replace ``obj.name`` with ``value`` and return the original."""
        previous = getattr(obj, name, None)
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


def disguise(fn: Any, module: str, name: str) -> Any:
    """Make a replacement function pickle (by reference) as ``module.name``."""
    try:
        fn.__module__ = module
        fn.__qualname__ = name
        fn.__name__ = name
    except (AttributeError, TypeError):  # pragma: no cover
        pass
    return fn


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
