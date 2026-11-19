"""Django's in-memory caches of file contents, under the cache with proof (every runner: the pytest plugin with or
without pytest-django, and the driver's Django shell).

* Templates: Django's cached loader (the default, ``django.template.loaders.cached.Loader``) reads a template's file
  once and returns it from memory to every later caller. The read was an input of the first test that rendered it
  only: after the template changed, the second renderer kept its old pass (MEASURED under the driver and under
  pytest-django, ``tests/test_django_pytest_cache.py``). The template's file is read again at every lookup (and the
  missing names the loader remembers are probed again), so it is an input of every test that renders it.
* Translations: a catalog (``.mo`` files of every app) is loaded once per language and kept: it is loaded in the
  global context ("between tests"), an input of every test.

``ensure(cap)`` patches whatever of Django is imported (idempotent; called when the session's tests are
known and at every test start, so a Django imported late is patched before its first use by a test).
"""

from __future__ import annotations

import os
import sys

from ._patch import Patcher

_done: set = set()
_PATCHER = Patcher()


def ensure(cap) -> None:
    if "templates" not in _done and "django.template.loaders.cached" in sys.modules:
        _templates(_PATCHER)
    if "translations" not in _done and "django.utils.translation.trans_real" in sys.modules:
        _translations(_PATCHER, cap)


def uninstall() -> None:
    """End of the session (``_proof.stop_capture``)."""
    _PATCHER.undo_all()
    _done.clear()


def _touch(origin) -> None:
    name = getattr(origin, "name", None)
    if isinstance(name, str) and os.path.isabs(name):
        try:
            open(name, "rb").close()  # the capture takes the read (or the miss) as an input of the running test
        except OSError:
            pass


def _templates(patcher) -> None:
    try:
        from django.template import TemplateDoesNotExist
        from django.template.loaders.cached import Loader
    except ImportError:  # pragma: no cover
        return
    _done.add("templates")
    real = Loader.get_template

    def get_template(loader, template_name, skip=None):
        try:
            t = real(loader, template_name, skip)
        except TemplateDoesNotExist as e:
            for origin, _status in getattr(e, "tried", ()) or ():
                _touch(origin)
            raise
        _touch(getattr(t, "origin", None))
        return t

    get_template.__wrapped__ = real
    patcher.set(Loader, "get_template", get_template)


def _translations(patcher, cap) -> None:
    try:
        from django.utils.translation import trans_real
    except ImportError:  # pragma: no cover
        return
    cls = getattr(trans_real, "DjangoTranslation", None)
    if cls is None:
        return
    _done.add("translations")
    real = cls.__init__

    def init(self, *args, **kw):
        if cap is None or not cap.active:
            return real(self, *args, **kw)
        prev = cap.ctx
        cap.switch("s")
        try:
            return real(self, *args, **kw)
        finally:
            cap.switch(prev)

    init.__wrapped__ = real
    patcher.set(cls, "__init__", init)
