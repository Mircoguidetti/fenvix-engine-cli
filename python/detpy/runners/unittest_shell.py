"""The unittest family's hooks (unittest, Django's test runner, nose2, doctest suites, zope.testrunner): one shell
over ``unittest``'s own objects, driving ``DetRun``.

Hooks (all on ``unittest``'s classes, so every runner built on them is covered):

* ``TestLoader.loadTestsFromModule`` (and a runner's own module loader, ``wrap_module_loader``): what runs while a
  test module's tests are loaded (its ``load_tests`` function) is the collection context ``c|<file>`` of the module,
  and an input of every test it returned;
* ``TestSuite.run`` at the top level: the suite is flattened in run order, ids are given, the order is fixed (or
  shuffled with ``--det-seed``: modules, classes in a module, methods in a class, so ``setUpModule`` /
  ``setUpClass`` still run once), reuse is decided, and every reused test is replaced by a stand-in that reports
  its recorded outcome to the runner's result without running;
* ``TestSuite._handleClassSetUp`` / ``_tearDownPreviousClass`` / ``_handleModuleFixture`` /
  ``_handleModuleTearDown``: class and module set-up and tear-down run in ``f|class|<file>::<Class>|<method>`` and
  ``f|module|<file>|<function>`` contexts, inputs of the tests of that class / module;
* ``_createClassOrModuleLevelException``: an error in a class or module tear-down is a teardown error of every test
  of that class / module that ran (never reused, as pytest attributes it to the last test);
* ``TestCase.__call__`` (and a runner's override, ``bracket``): the bracket of a test that runs (begin, the result's
  ``add*`` calls as phase reports, end).

Unit of reuse: a ``TestCase`` class (all its methods are reused together or none). Methods of a class run in order in
one process and share the class's attributes (and what ``setUpClass`` built): when method A ran fresh (its code
changed) and method B were reused, B's recorded result would come from a run where A's old version prepared the
class state. Nothing in the capture sees in-memory state, so the class is the unit. Module-level state between
classes follows the pytest shell's rule (the test is the unit; module set-up is an input of its tests).
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import case as _case
from unittest import suite as _suite

from .._patch import Patcher
from .driver import DetRun, DoctestItem, TestItem, exception_of

SHELL: "UnittestShell | None" = None
_real_call = unittest.TestCase.__call__
_real_suite_run = unittest.TestSuite.run
_FIXTURE_CLASSES = (unittest.FunctionTestCase,)


def _isnotsuite(test) -> bool:
    try:
        iter(test)
    except TypeError:
        return True
    return False


def unittest_infra_files() -> list[str]:
    """unittest's own loader, loop and result: its directory listings and existence probes during discovery are
    not inputs (as pytest's collection's are not)."""
    import importlib

    return [importlib.import_module(f"unittest.{m}").__file__ for m in ("loader", "main", "result", "runner", "suite")]


class _ResultProxy:
    """The runner's result, seen by one test that runs: every ``add*`` call is also a phase report."""

    def __init__(self, result, shell: "UnittestShell", test, nid: str):
        object.__setattr__(self, "_r", result)
        object.__setattr__(self, "_shell", shell)
        object.__setattr__(self, "_test", test)
        object.__setattr__(self, "_nid", nid)
        object.__setattr__(self, "_events", [])

    def __getattr__(self, name):
        attr = getattr(self._r, name)
        if name in ("addSuccess", "addFailure", "addError", "addSkip", "addExpectedFailure",
                    "addUnexpectedSuccess", "addSubTest"):
            events = self._events

            def add(*args, **kw):
                events.append((name, args))
                return attr(*args, **kw)

            return add
        return attr

    def __setattr__(self, name, value):
        setattr(self._r, name, value)

    def __delattr__(self, name):
        delattr(self._r, name)


def outcome_of(events, test) -> tuple[str, object, str | None, list | None]:
    """(phase outcome, longrepr, wasxfail, exception) of a test from its result calls."""
    failed = None
    xfail = xpass = success = False
    skip = None
    for name, args in events:
        if name in ("addFailure", "addError"):
            failed = failed or args[1]
        elif name == "addSubTest":
            if len(args) > 2 and args[2] is not None:
                failed = failed or args[2]
        elif name == "addExpectedFailure":
            xfail = True
        elif name == "addUnexpectedSuccess":
            xpass = True
        elif name == "addSuccess":
            success = True
        elif name == "addSkip":
            if args and args[0] is test and skip is None:
                skip = str(args[1]) if len(args) > 1 else ""
    if failed is not None:
        exc = exception_of(failed) if isinstance(failed, tuple) and len(failed) == 3 else None
        return "failed", None, None, exc
    if xfail:
        return "skipped", None, "", None
    if xpass:
        return "passed", None, "", None
    if success:
        return "passed", None, None, None
    if skip is not None:
        return "skipped", ("", 0, f"Skipped: {skip}"), None, None
    return "failed", None, None, ["NoOutcome", "call", "the test reported no outcome", ""]


class _Reused(unittest.BaseTestSuite):
    """A reused test in the suite: reports its recorded outcome without running (a suite to unittest, so no class or
    module fixture is set up for it)."""

    def __init__(self, test, nid: str, shell: "UnittestShell"):
        super().__init__()
        self._test, self._nid, self._shell = test, nid, shell

    def countTestCases(self):
        return 1

    def run(self, result, debug=False):
        self._shell.replay(self._test, self._nid, result)
        return result

    def __repr__(self):
        return f"<reused {self._nid}>"


class _ReusedFailure(AssertionError):
    pass


class UnittestShell:
    def __init__(self, run: DetRun, group_key=None):
        self.run = run
        self.patcher = Patcher()
        self.group_key = group_key  # runner order groups kept under a shuffle (Django: TestCase, transactional, ...)
        self.ids: dict[int, str] = {}
        self.objs: dict[str, object] = {}
        self.cctx: dict[int, tuple[object, set]] = {}
        self.prepared = False
        self.ran_by_group: dict[str, list[str]] = {}
        self.opaque_types: set[str] = set()

    # -- installation ---------------------------------------------------------------------------
    def install(self) -> "UnittestShell":
        global SHELL
        SHELL = self
        p = self.patcher
        self.wrap_module_loader(unittest.TestLoader, "loadTestsFromModule")
        shell = self

        def suite_run(suite, result, debug=False):
            if not shell.prepared and getattr(result, "_testRunEntered", False) is False:
                shell.prepared = True
                shell.prepare(suite)
            return _real_suite_run(suite, result, debug)

        p.set(unittest.TestSuite, "run", suite_run)
        self._fixture_hooks()
        self.bracket(unittest.TestCase)
        return self

    def uninstall(self) -> None:
        global SHELL
        self.patcher.undo_all()
        SHELL = None

    def wrap_module_loader(self, cls, name: str) -> None:
        """``cls.name(module, ...)`` loads a module's tests: it runs in ``c|<file>``, an input of every test returned."""
        real = getattr(cls, name)
        shell = self

        def load(loader, module, *args, **kw):
            rel = shell.rel_of_module(module)
            if rel is None:
                return real(loader, module, *args, **kw)
            with shell.run.collecting(rel):
                suite = real(loader, module, *args, **kw)
            shell.tag(suite, "c|" + rel)
            return suite

        load.__wrapped__ = real
        self.patcher.set(cls, name, load)

    def tag(self, suite, ctx: str) -> None:
        for t in self.iter_tests(suite):
            self.cctx.setdefault(id(t), (t, set()))[1].add(ctx)

    def bracket(self, cls) -> None:
        """``cls.__call__`` (``test(result)``) is the bracket of a test that runs: the outermost one counts."""
        real = cls.__dict__["__call__"]
        shell = self

        def call(test, *args, **kw):
            result = args[0] if args else kw.get("result")
            if shell.run.current is not None or result is None or not shell.prepared:
                return real(test, *args, **kw)
            nid = shell.id_of(test)
            proxy = _ResultProxy(result, shell, test, nid)
            shell.run.begin(nid, shell.fixtures_of(test))
            try:
                ret = real(test, proxy, *args[1:], **{k: v for k, v in kw.items() if k != "result"})
            finally:
                o, longrepr, wasxfail, exc = outcome_of(proxy._events, test)
                if longrepr is not None:
                    longrepr = (shell.run.rel(shell.file_of(test)) or "", 0, longrepr[2])
                shell.run.report(nid, "call", o, longrepr, wasxfail, exc)
                shell.run.end(nid)
                shell.ran_by_group.setdefault(shell.class_group(test), []).append(nid)
                shell.ran_by_group.setdefault(shell.module_group(test), []).append(nid)
            return result if ret is proxy else ret

        call.__wrapped__ = real
        self.patcher.set(cls, "__call__", call)

    def _fixture_hooks(self) -> None:
        p, shell, S = self.patcher, self, unittest.TestSuite
        r_class_setup, r_class_td = S._handleClassSetUp, S._tearDownPreviousClass
        r_mod_fixture, r_mod_td = S._handleModuleFixture, S._handleModuleTearDown
        r_exc = S._createClassOrModuleLevelException

        def class_setup(suite, test, result):
            cls = test.__class__
            if cls == getattr(result, "_previousTestClass", None):
                return r_class_setup(suite, test, result)
            with shell.run.context(shell.class_ctx(cls, "setUpClass")):
                return r_class_setup(suite, test, result)

        def class_teardown(suite, test, result):
            prev = getattr(result, "_previousTestClass", None)
            if prev is None or (test is not None and test.__class__ == prev):
                return r_class_td(suite, test, result)
            with shell.run.context(shell.class_ctx(prev, "tearDownClass")):
                return r_class_td(suite, test, result)

        def module_fixture(suite, test, result):
            mod = test.__class__.__module__
            prev = getattr(result, "_previousTestClass", None)
            if prev is not None and prev.__module__ == mod:
                return r_mod_fixture(suite, test, result)
            with shell.run.context(shell.module_ctx(mod, "setUpModule")):
                return r_mod_fixture(suite, test, result)

        def module_teardown(suite, result):
            prev = getattr(result, "_previousTestClass", None)
            if prev is None:
                return r_mod_td(suite, result)
            with shell.run.context(shell.module_ctx(prev.__module__, "tearDownModule")):
                return r_mod_td(suite, result)

        def level_exc(suite, result, exc, method_name, parent, info=None):
            if method_name.startswith("tearDown") and not isinstance(exc, unittest.SkipTest):
                shell.fixture_teardown_failed(method_name, parent, exc, info)
            return r_exc(suite, result, exc, method_name, parent, info)

        p.set(S, "_handleClassSetUp", class_setup)
        p.set(S, "_tearDownPreviousClass", class_teardown)
        p.set(S, "_handleModuleFixture", module_fixture)
        p.set(S, "_handleModuleTearDown", module_teardown)
        p.set(S, "_createClassOrModuleLevelException", level_exc)

    # -- identities ------------------------------------------------------------------------------
    def rel_of_module(self, module) -> str | None:
        f = getattr(module, "__file__", None)
        return self.run.rel(f) if f else None

    def module_rel(self, modname: str) -> str:
        m = sys.modules.get(modname)
        return self.rel_of_module(m) or modname

    def file_of(self, test) -> str | None:
        import doctest

        if isinstance(test, doctest.DocTestCase):
            return test._dt_test.filename
        if isinstance(test, unittest.FunctionTestCase):
            m = sys.modules.get(getattr(test._testFunc, "__module__", None) or "")
        else:
            m = sys.modules.get(type(test).__module__)
        return getattr(m, "__file__", None)

    def base_id(self, test) -> str:
        import doctest

        cls = type(test)
        if isinstance(test, doctest.DocTestCase):
            dt = test._dt_test
            return f"{self.run.rel(dt.filename) or dt.filename}::{dt.name}"
        if isinstance(test, unittest.FunctionTestCase):
            f = test._testFunc
            mod = getattr(f, "__module__", None) or ""
            tid = test.id()
            rest = tid[len(mod) + 1:] if mod and tid.startswith(mod + ".") else tid
            return f"{self.module_rel(mod)}::{rest}"
        tid = test.id() if callable(getattr(test, "id", None)) else repr(test)
        prefix = f"{cls.__module__}.{cls.__qualname__}."
        method = tid[len(prefix):] if tid.startswith(prefix) else getattr(test, "_testMethodName", tid)
        return f"{self.module_rel(cls.__module__)}::{cls.__qualname__}::{method}"

    def id_of(self, test) -> str:
        nid = self.ids.get(id(test))
        if nid is None:
            nid = self.base_id(test)
            self.ids[id(test)] = nid
        return nid

    def class_ctx(self, cls, method: str) -> str:
        return f"f|class|{self.module_rel(cls.__module__)}::{cls.__qualname__}|{method}"

    def module_ctx(self, modname: str, function: str) -> str:
        return f"f|module|{self.module_rel(modname)}|{function}"

    def class_group(self, test) -> str:
        return f"class:{type(test).__module__}.{type(test).__qualname__}"

    def module_group(self, test) -> str:
        return f"module:{type(test).__module__}"

    def fixtures_of(self, test) -> list[str]:
        cls = type(test)
        fx = [self.class_ctx(cls, "setUpClass"), self.class_ctx(cls, "tearDownClass"),
              self.module_ctx(cls.__module__, "setUpModule"), self.module_ctx(cls.__module__, "tearDownModule")]
        fx += sorted(self.cctx.get(id(test), (None, ()))[1])
        fx += self.extra_fixtures(test)
        return fx

    def extra_fixtures(self, test) -> list[str]:
        return []

    def item_of(self, test, nid: str):
        import doctest

        if isinstance(test, doctest.DocTestCase):
            return DoctestItem(nid)
        return TestItem(nid, type(test))

    def unit_of(self, test) -> str | None:
        """The unit of reuse a test belongs to (None: the test alone)."""
        import doctest

        if isinstance(test, (doctest.DocTestCase, unittest.FunctionTestCase)):
            return None
        return self.class_group(test)

    # -- the suite -------------------------------------------------------------------------------
    def iter_tests(self, suite):
        if _isnotsuite(suite):
            yield suite
            return
        for t in suite:
            yield from self.iter_tests(t)

    def flatten(self, suite, out: list, opaque: list) -> None:
        """Tests of ``suite`` in run order into ``out``; a suite whose ``run`` is not unittest's (a runner's custom
        suite) stays one element, its tests always run."""
        for t in suite:
            if _isnotsuite(t):
                out.append(t)
            elif type(t).run is _real_suite_run or type(t).run is unittest.TestSuite.run:
                self.flatten(t, out, opaque)
            else:
                self.opaque_types.add(f"{type(t).__module__}.{type(t).__qualname__}")
                out.append(t)
                opaque.append(t)

    def order(self, tests: list) -> list:
        """The run order under ``--det``: the runner's order; with ``--det-seed``, modules, classes within a module
        and tests within a class shuffled with the seed (the runner's groups kept, ``group_key``)."""
        run = self.run
        if not run.ordered:
            return tests
        if run.cfg.shuffle:
            tests = self._shuffled(tests)
        if self.group_key is not None:
            keyed = [(self.group_key(t), i, t) for i, t in enumerate(tests)]
            if any(k for k, _, _ in keyed):
                tests = [t for _, _, t in sorted(keyed, key=lambda x: (x[0], x[1]))]
        return tests

    def _shuffled(self, tests: list) -> list:
        def key(t, level):
            if not _isnotsuite(t):
                return (f"suite:{id(t)}",)[0]
            mod = type(t).__module__
            if level == 0:
                return mod
            if self.unit_of(t) is None:
                return self.id_of(t)
            return f"{mod}.{type(t).__qualname__}"

        def group(items, level):
            names, groups = [], {}
            for t in items:
                k = key(t, level)
                if k not in groups:
                    groups[k] = []
                    names.append(k)
                groups[k].append(t)
            perm = self.run.shuffle(names)
            out = []
            for p in perm:
                members = groups[names[p]]
                if level == 0:
                    out += group(members, 1)
                elif level == 1 and len(members) > 1:
                    ids = [self.id_of(m) if _isnotsuite(m) else str(i) for i, m in enumerate(members)]
                    out += [members[q] for q in self.run.shuffle(ids)]
                else:
                    out += members
            return out

        return group(tests, 0)

    def prepare(self, suite) -> None:
        """The top-level suite is about to run: flatten, order, identify, decide, replace reused tests."""
        run = self.run
        flat: list = []
        opaque: list = []
        self.flatten(suite, flat, opaque)
        flat = self.order(flat)
        entries = []  # (element, nid or None for an opaque suite)
        seen: dict[str, int] = {}
        opaque_ids: set[str] = set()
        for t in flat:
            members = [t] if _isnotsuite(t) else list(self.iter_tests(t))
            for m in members:
                base = self.id_of(m)
                n = seen.get(base, 0)
                seen[base] = n + 1
                nid = base if n == 0 else f"{base}[{n}]"
                self.ids[id(m)] = nid
                self.objs[nid] = m
                if not _isnotsuite(t):
                    opaque_ids.add(nid)
            entries.append(t)
        ids = [self.ids[id(m)] for t in entries for m in ([t] if _isnotsuite(t) else self.iter_tests(t))]
        explicit = run.explicit_order(ids) if run.det else None
        if explicit is not None:
            by_id = {self.ids[id(t)]: t for t in entries if _isnotsuite(t)}
            entries = [by_id[i] for i in explicit if i in by_id]
            ids = [self.ids[id(t)] for t in entries]
        if opaque:
            run.adjust("not reused (custom suites): " + ", ".join(sorted(self.opaque_types)))
        items = {nid: self.item_of(self.objs[nid], nid) for nid in ids}
        units: dict[str, list[str]] = {}
        for nid in ids:
            u = self.unit_of(self.objs[nid])
            if u is not None:
                units.setdefault(u, []).append(nid)
        reused = run.decide(ids, items, [u for u in units.values() if len(u) > 1], opaque_ids)
        new = []
        for t in entries:
            if _isnotsuite(t) and self.ids[id(t)] in reused:
                new.append(_Reused(t, self.ids[id(t)], self))
            else:
                new.append(t)
        suite._tests = new

    # -- reuse and fixture failures -------------------------------------------------------------------
    def replay(self, test, nid: str, result) -> None:
        rep, _fp = self.run.reused_info(nid)
        call = rep.get("call") or rep.get("setup") or {}
        outcome = call.get("outcome", "passed")
        result.startTest(test)
        try:
            if "wasxfail" in call and outcome == "skipped":
                try:
                    raise _ReusedFailure("expected failure (result reused with proof)")
                except _ReusedFailure:
                    result.addExpectedFailure(test, sys.exc_info())
            elif outcome == "skipped":
                lr = call.get("longrepr") or ["", 0, "Skipped: "]
                reason = str(lr[2])
                reason = reason[len("Skipped: "):] if reason.startswith("Skipped: ") else reason
                result.addSkip(test, reason)
            else:
                result.addSuccess(test)
            add_duration = getattr(result, "addDuration", None)
            if add_duration is not None:
                add_duration(test, 0.0)
        finally:
            result.stopTest(test)

    def fixture_teardown_failed(self, method_name: str, parent: str, exc, info) -> None:
        """A class or module tear-down failed: every test of that class / module that ran gets a teardown error."""
        if method_name.endswith("Class"):
            group = f"class:{parent}"
        else:
            group = f"module:{parent}"
        exc_info = info or (type(exc), exc, exc.__traceback__)
        for nid in self.ran_by_group.get(group, ()):
            self.run.report(nid, "teardown", "failed", exception=exception_of(exc_info, "teardown"))
