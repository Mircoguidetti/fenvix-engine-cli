"""``python -m detpy ward [--det ...] [ward arguments]``: ward under the driver.

ward is not built on unittest: its suite (``ward._suite.Suite.generate_test_runs``) runs each test
(``Test.run(cache)``) and yields its result; fixtures are resolved per test from a cache keyed by scope (test,
module, global). This module replaces ``generate_test_runs`` with the same loop (ward 0.6x's, kept in step with its
source) that first expands every test (parameterised instances), gives ids ``<file>::<function>`` (``[i]`` for a
parameterised instance), fixes the order (the runner's; with ``--det-seed``, modules then tests shuffled), decides
reuse, then yields a reused test's recorded result without running it, and brackets the others. A module- or
global-scoped fixture is computed in an ``f|<scope>|<owner>|<fixture>`` context, an input of every test that uses it
(directly or through other fixtures); a test-scoped one runs inside the test. A module's fixtures are torn down
after its last test, the global ones at the end (between tests: inputs of every test). Configuration: the command
line (selection and output options left out) and ``[tool.ward]`` in ``pyproject.toml`` (ward reads it at
start-up: an input of every test).
"""

from __future__ import annotations

import os

from .driver import DetRun, TestItem

_VOLATILE = {"--progress-style", "--hide-captured-output", "--show-slowest", "--show-diff-symbols", "--fail-limit",
             "--dry-run", "--order", "--search", "--tags", "-t", "--exclude", "--path", "-p"}


def config_of(argv: list[str]) -> dict:
    kept: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        name = a.split("=", 1)[0]
        takes = name in _VOLATILE and "=" not in a and i + 1 < len(argv) and not argv[i + 1].startswith("-")
        if name not in _VOLATILE:
            kept.append(a)
        i += 2 if takes else 1
    return {"args": kept}


class WardShell:
    def __init__(self, run: DetRun):
        self.run = run
        from .._patch import Patcher

        self.patcher = Patcher()
        self.ids: dict[int, str] = {}

    # -- identities ------------------------------------------------------------------------------
    def nid(self, test, index: int | None) -> str:
        """``<file>::<function>``; ward's tests are usually all named ``_``: then the description as written
        (before its formatting with the arguments)."""
        rel = self.run.rel(str(test.path)) or str(test.path)
        name = test.name
        if name == "_":
            meta = getattr(test.fn, "ward_meta", None)
            name = getattr(meta, "description", None) or test.description or name
        base = f"{rel}::{name}"
        return base if index is None else f"{base}[{index}]"

    def fixture_ctx(self, fixture_fn, scope, test) -> str | None:
        from ward.models import Scope

        name = getattr(fixture_fn, "__qualname__", getattr(fixture_fn, "__name__", "?"))
        owner = self.run.rel(getattr(getattr(fixture_fn, "__code__", None), "co_filename", "")) or "?"
        if scope == Scope.Module:
            return f"f|module|{self.run.rel(str(test.path))}|{owner}::{name}"
        if scope == Scope.Global:
            return f"f|global|{owner}|{name}"
        return None

    def fixtures_of(self, test) -> list[str]:
        """Contexts of the module- and global-scoped fixtures ``test`` uses, through other fixtures too."""
        from ward.fixtures import Fixture
        from ward.testing import is_fixture

        out, seen = [], set()
        resolver = test.resolver
        todo = [a for a in resolver._get_args_for_iteration().values() if is_fixture(a)]
        while todo:
            fn = todo.pop()
            if id(fn) in seen:
                continue
            seen.add(id(fn))
            ctx = self.fixture_ctx(fn, Fixture(fn).scope, test)
            if ctx:
                out.append(ctx)
            todo += [a for a in resolver.get_default_args(func=fn).values() if is_fixture(a)]
        return out

    # -- installation ----------------------------------------------------------------------------
    def install(self) -> "WardShell":
        from ward._suite import Suite
        from ward.testing import TestArgumentResolver

        shell = self
        p = self.patcher
        real_resolve = TestArgumentResolver._resolve_single_arg

        def resolve_single_arg(resolver, arg, cache):
            if not hasattr(arg, "ward_meta"):
                return real_resolve(resolver, arg, cache)
            from ward.fixtures import Fixture

            ctx = shell.fixture_ctx(arg, Fixture(arg).scope, resolver.test)
            if ctx is None:
                return real_resolve(resolver, arg, cache)
            with shell.run.context(ctx):
                return real_resolve(resolver, arg, cache)

        p.set(TestArgumentResolver, "_resolve_single_arg", resolve_single_arg)
        import ward._collect as C
        import ward._run as WR

        real_get_tests = C.get_tests_in_modules

        def get_tests_in_modules(*a, **kw):
            with shell.run.own_work():  # ward's Test objects draw uuid4 ids
                return real_get_tests(*a, **kw)

        p.set(C, "get_tests_in_modules", get_tests_in_modules)
        if getattr(WR, "get_tests_in_modules", None) is real_get_tests:
            p.set(WR, "get_tests_in_modules", get_tests_in_modules)
        p.set(Suite, "generate_test_runs", lambda suite, dry_run=False, capture_output=True:
              shell.generate_test_runs(suite, dry_run, capture_output))
        return self

    def uninstall(self) -> None:
        self.patcher.undo_all()

    # -- the loop --------------------------------------------------------------------------------
    def expand(self, suite) -> list:
        """[(test, generated instances or the parameterisation error)] in the runner's order."""
        from ward._errors import ParameterisationError

        out = []
        for test in suite.tests:
            try:
                out.append((test, test.get_parameterised_instances(), None))
            except ParameterisationError as e:
                out.append((test, [], e))
        return out

    def order(self, expanded: list) -> list:
        run = self.run
        if not (run.ordered and run.cfg.shuffle):
            return expanded
        mods: dict[str, list] = {}
        names: list[str] = []
        for e in expanded:
            k = str(e[0].path)
            if k not in mods:
                mods[k] = []
                names.append(k)
            mods[k].append(e)
        out = []
        for p in run.shuffle(names):
            members = mods[names[p]]
            ids = [self.nid(t, None) for t, _, _ in members]
            out += [members[q] for q in run.shuffle(ids)]
        return out

    def generate_test_runs(self, suite, dry_run: bool, capture_output: bool):
        from ward.fixtures import TeardownResult  # noqa: F401
        from ward.models import Scope
        from ward.testing import TestOutcome, TestResult

        run = self.run
        with run.own_work():  # ward's Test objects draw uuid4 ids
            expanded = self.order(self.expand(suite))
        ids, items = [], {}
        seen: dict = {}
        for test, gen, err in expanded:
            if err is not None:
                continue
            many = len(gen) > 1 or test.is_parameterised
            for i, g in enumerate(gen):
                nid = self.nid(test, i if many else None)
                n = seen.get(nid, 0)
                seen[nid] = n + 1
                nid = nid if n == 0 else f"{nid}#{n}"
                self.ids[id(g)] = nid
                ids.append(nid)
                items[nid] = TestItem(nid, test.fn)
        reused = run.decide(ids, items) if not dry_run else set()
        counts: dict = {}
        for test, _, _ in expanded:
            counts[test.path] = counts.get(test.path, 0) + 1
        for test, gen, err in expanded:
            counts[test.path] -= 1
            if err is not None:
                yield test.fail_with_error(err)
                continue
            for g in gen:
                nid = self.ids[id(g)]
                if nid in reused:
                    yield self.replay(g, nid, TestOutcome, TestResult)
                    continue
                result = self.bracket(g, nid, suite, dry_run, capture_output, test, TestOutcome, Scope)
                yield result
            if counts[test.path] == 0:
                suite.cache.teardown_fixtures_for_scope(Scope.Module, scope_key=test.path,
                                                        capture_output=capture_output)
        suite.cache.teardown_global_fixtures(capture_output=capture_output)

    def bracket(self, g, nid, suite, dry_run, capture_output, test, TestOutcome, Scope):
        run = self.run
        run.begin(nid, self.fixtures_of(g))
        result = None
        try:
            result = g.run(suite.cache, dry_run=dry_run)
            teardown_results = suite.cache.teardown_fixtures_for_scope(Scope.Test, scope_key=g.id,
                                                                       capture_output=capture_output)
            first = next((r for r in teardown_results or () if r.captured_exception is not None), None)
            if first is not None:
                result = test.fail_with_error(first.captured_exception)
        finally:
            o = getattr(result, "outcome", None)
            if o in (TestOutcome.PASS,):
                run.report(nid, "call", "passed")
            elif o == TestOutcome.SKIP:
                reason = getattr(getattr(g, "marker", None), "reason", "") or ""
                run.report(nid, "call", "skipped", (run.rel(str(g.path)) or "", 0, f"Skipped: {reason}"))
            elif o == TestOutcome.XFAIL:
                run.report(nid, "call", "skipped", wasxfail="")
            elif o == TestOutcome.XPASS:
                run.report(nid, "call", "passed", wasxfail="")
            else:
                err = getattr(result, "error", None)
                exc = [type(err).__name__, "call", str(err).splitlines()[0][:200] if str(err) else "", ""] \
                    if err is not None else ["NoOutcome", "call", "", ""]
                run.report(nid, "call", "failed", exception=exc)
            run.end(nid)
        return result

    def replay(self, g, nid, TestOutcome, TestResult):
        rep, _fp = self.run.reused_info(nid)
        call = rep.get("call") or {}
        outcome = call.get("outcome", "passed")
        if "wasxfail" in call and outcome == "skipped":
            o = TestOutcome.XFAIL
        elif outcome == "skipped":
            o = TestOutcome.SKIP
        else:
            o = TestOutcome.PASS
        for s in (g.sout, g.serr):
            try:
                s.close()
            except Exception:  # pragma: no cover
                pass
        return TestResult(g, o)


def main(ns, argv: list[str]) -> int:
    run = DetRun("ward", ns, os.getcwd())
    run.start()
    from importlib.metadata import version

    shell = WardShell(run).install()
    import ward._collect
    import ward._run

    run.configure(version("ward"), config_of(argv), [ward._collect.__file__])
    code = 0
    try:
        ward._run.run.main(args=list(argv), prog_name="ward", standalone_mode=True)
    except SystemExit as e:
        code = e.code
    finally:
        shell.uninstall()
        run.finish(code)
    if isinstance(code, int):
        return code
    return 0 if not code else 1
