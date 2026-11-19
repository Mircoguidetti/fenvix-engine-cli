"""``python -m detpy django manage.py test [args]`` (also ``runtests.py [args]`` scripts around Django's runner,
and ``django-admin test [args]``): Django's ``DiscoverRunner`` under the driver.

Django's runner builds unittest suites, so the unittest shell (``unittest_shell``) does the work; this module adds:

* ``--parallel`` is forced to 1 under ``--det`` (one process: the order, the clock and the capture are this
  process's; Django's parallel runner forks workers that run outside the driver). Said in the summary.
* Django's group order is kept: ``reorder_by`` (TestCase, then SimpleTestCase and TransactionTestCase, then other
  unittest tests); a ``--det-seed`` shuffle stays inside each group (TestCase tests after a transactional test
  that flushed the database would fail only under the shuffle).
* ``SimpleTestCase.__call__`` is the test's bracket (Django's ``_pre_setup``: fixtures of a
  ``TransactionTestCase``, the database, are inside the test); ``TestCase.setUpClass`` (``setUpTestData``, class
  fixtures) is the class's ``f|class|...|setUpClass`` context.
* Reads through Django's caches (R-021 "reads through infrastructure"): a template the cached loader returns from
  memory is read again (its file is an input of every test that renders it, not only of the first one); a missing
  template the cached loader remembers is probed again; translation catalogs (``.mo`` files) are loaded in the
  global context (an input of every test).
* The test database: whatever the settings say; the walks use sqlite (``harness/cache_proof/specs/django-*``).
"""

from __future__ import annotations

import os
import runpy
import sys

from .._level0 import UsageError
from .driver import DetRun
from .unittest_shell import UnittestShell, unittest_infra_files

# options that select tests or only change the output (pytest's volatile options); every other argument is
# configuration
_VOLATILE_FLAGS = {"--no-color", "--force-color", "--timing", "--noinput", "--no-input", "--version", "--traceback"}
_VOLATILE_VALUE = {"-v", "--verbosity", "--durations", "--parallel"}


def config_of(script: str, argv: list[str]) -> dict:
    """The part of the command line that can change a result: every argument but the options that only change the
    output (``-v``, ``--timing``, ...). Test labels stay in (an option's value and a label look alike to a script
    detpy does not know, so nothing positional is dropped: another selection is another configuration)."""
    kept: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        name = a.split("=", 1)[0]
        if a.startswith("-v") and a[2:].isdigit():
            pass
        elif name in _VOLATILE_VALUE:
            if "=" not in a:
                i += 1
        elif name not in _VOLATILE_FLAGS:
            kept.append(a)
        i += 1
    return {"script": os.path.basename(script), "args": kept}


class DjangoHooks:
    def __init__(self, shell: UnittestShell, run: DetRun):
        self.shell = shell
        self.run = run

    def install(self) -> "DjangoHooks":
        from django.test import SimpleTestCase
        from django.test.runner import DiscoverRunner

        p = self.shell.patcher
        hooks = self
        real_run_tests = DiscoverRunner.run_tests

        def run_tests(runner, *args, **kw):
            if hooks.run.det:
                if getattr(runner, "parallel", 1) not in (0, 1):
                    hooks.run.adjust(f"Django --parallel {runner.parallel} -> 1 under --det (one process)")
                runner.parallel = 1
                order = tuple(getattr(runner, "reorder_by", ()) or ())

                def group_key(t, order=order):
                    for i, cls in enumerate(order):
                        if isinstance(t, cls):
                            return i
                    return len(order)

                hooks.shell.group_key = group_key
            return real_run_tests(runner, *args, **kw)

        run_tests.__wrapped__ = real_run_tests
        p.set(DiscoverRunner, "run_tests", run_tests)
        if "__call__" in vars(SimpleTestCase):
            self.shell.bracket(SimpleTestCase)
        self._templates()
        self._translations()
        return self

    def _templates(self) -> None:
        try:
            from django.template import TemplateDoesNotExist
            from django.template.loaders.cached import Loader
        except ImportError:  # pragma: no cover
            return
        real = Loader.get_template

        def touch(origin) -> None:
            name = getattr(origin, "name", None)
            if isinstance(name, str) and os.path.isabs(name):
                try:
                    open(name, "rb").close()  # the capture takes the read (or the miss) as the template's input
                except OSError:
                    pass

        def get_template(loader, template_name, skip=None):
            try:
                t = real(loader, template_name, skip)
            except TemplateDoesNotExist as e:
                for origin, _status in getattr(e, "tried", ()) or ():
                    touch(origin)
                raise
            touch(getattr(t, "origin", None))
            return t

        get_template.__wrapped__ = real
        self.shell.patcher.set(Loader, "get_template", get_template)

    def _translations(self) -> None:
        try:
            from django.utils.translation import trans_real
        except ImportError:  # pragma: no cover
            return
        cls = getattr(trans_real, "DjangoTranslation", None)
        if cls is None:
            return
        real = cls.__init__
        run = self.run

        def init(self, *args, **kw):
            with run.context("s"):
                return real(self, *args, **kw)

        init.__wrapped__ = real
        self.shell.patcher.set(cls, "__init__", init)


def _django_infra() -> list[str]:
    import django.test.runner

    return [django.test.runner.__file__]


def main(ns, argv: list[str]) -> int:
    if not argv:
        raise UsageError("usage: detpy django manage.py test [args] (or runtests.py [args], django-admin test [args])")
    script, args = argv[0], argv[1:]
    run = DetRun("django", ns, os.getcwd())
    run.start()
    import django

    shell = UnittestShell(run).install()
    DjangoHooks(shell, run).install()
    run.configure(django.get_version(), config_of(script, args), unittest_infra_files() + _django_infra())
    code = 0
    try:
        if script in ("django-admin", "django-admin.py"):
            from django.core.management import execute_from_command_line

            sys.argv = [script, *args]
            execute_from_command_line(sys.argv)
        else:
            path = os.path.abspath(script)
            sys.argv = [script, *args]
            sys.path.insert(0, os.path.dirname(path))
            runpy.run_path(path, run_name="__main__")
    except SystemExit as e:
        code = e.code
    finally:
        shell.uninstall()
        run.finish(code)
    if isinstance(code, int):
        return code
    return 0 if not code else 1
