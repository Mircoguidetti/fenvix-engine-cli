"""``python -m detpy zope-testrunner [--det ...] [zope-testrunner arguments]``: zope.testrunner under the driver.

zope.testrunner runs unittest cases layer by layer (``Runner.run_tests``: ``ordered_layers``, then for each layer
``run_layer``: set up the layer and its bases, run the layer's tests one by one with the layer's
``testSetUp`` / ``testTearDown`` around each). The unittest shell brackets every test (``TestCase.__call__``);
this module adds:

* the decision over every layer's tests before the first layer runs (``Runner.ordered_layers``), the run order
  (the runner's, layers by bases; a ``--det-seed`` shuffle stays inside a layer), reused tests replaced by
  stand-ins;
* a layer's set-up in an ``f|layer|<layer>|setUp`` context, an input of every test of that layer and of the layers
  built on it; a layer whose tests are all reused is not set up (its ``testSetUp`` / ``testTearDown`` do not run for
  stand-ins);
* a module's ``test_suite()`` function runs in the module's collection context ``c|<file>``;
* ``-j N`` is forced to 1 under ``--det`` (one process). A layer that cannot be torn down makes zope.testrunner run
  the remaining layers in a subprocess (``resume_layer``): that subprocess runs outside the driver, so the session
  started a process and nothing it ran is reused (the capture's subprocess rule).
"""

from __future__ import annotations

import os

from .driver import DetRun
from .unittest_shell import UnittestShell, _Reused, unittest_infra_files

_VOLATILE = {"-v", "--verbose", "-q", "--quiet", "--progress", "-p", "--no-progress", "-1", "--hooks-only",
             "--list-tests", "--color", "-c", "--no-color", "-C", "--slow-test", "--subunit", "--subunit-v2", "-x",
             "--stop-on-error", "--stop-on-failure"}
_VALUE_OPTIONS = {"--test-path", "--package", "-s", "--path", "-u", "-f", "--layer", "--tests-pattern",
                  "--test-file-pattern", "-j", "--slow-test", "-t", "--test", "-m", "--module", "--repeat", "-N"}
_SELECTION = {"-t", "--test", "-m", "--module", "--layer"}


def config_of(argv: list[str]) -> dict:
    kept: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        name = a.split("=", 1)[0]
        value = None
        if name in _VALUE_OPTIONS and "=" not in a and i + 1 < len(argv):
            value = argv[i + 1]
            i += 1
        if name in _SELECTION or name in _VOLATILE or (a.startswith("-v") and set(a[1:]) == {"v"}):
            pass
        elif name in ("-j",):
            pass  # forced to 1 under --det
        else:
            kept.append(a if value is None else f"{a}={value}")
        i += 1
    return {"args": kept}


class ZopeHooks:
    def __init__(self, shell: UnittestShell, run: DetRun):
        self.shell = shell
        self.run = run
        self.layer_of: dict[int, list[str]] = {}  # id(test) -> fixture contexts of its layers

    def install(self) -> "ZopeHooks":
        import zope.testrunner.find as F
        import zope.testrunner.runner as R

        p = self.shell.patcher
        hooks, shell, run = self, self.shell, self.run

        real_run_tests = R.Runner.run_tests

        def run_tests(runner):
            if run.det and getattr(runner.options, "processes", 1) > 1:
                run.adjust(f"zope.testrunner -j {runner.options.processes} -> 1 under --det (one process)")
                runner.options.processes = 1
            return real_run_tests(runner)

        p.set(R.Runner, "run_tests", run_tests)

        real_ordered = R.Runner.ordered_layers

        def ordered_layers(runner):
            layers = list(real_ordered(runner))
            if not shell.prepared:
                shell.prepared = True
                hooks.prepare(layers, R)
            return iter(layers)

        p.set(R.Runner, "ordered_layers", ordered_layers)

        real_setup = R.setup_layer

        def setup_layer(options, layer, setup_layers):
            with run.context(f"f|layer|{R.name_from_layer(layer)}|setUp"):
                return real_setup(options, layer, setup_layers)

        p.set(R, "setup_layer", setup_layer)

        real_run_layer = R.run_layer

        def run_layer(options, layer_name, layer, tests, setup_layers, failures, errors, skipped, import_errors):
            if tests and all(isinstance(t, _Reused) for t in tests):
                # every test of the layer is reused: the layer is not set up
                return R.run_tests(options, tests, layer_name, failures, errors, skipped, import_errors)
            return real_run_layer(options, layer_name, layer, tests, setup_layers, failures, errors, skipped,
                                  import_errors)

        p.set(R, "run_layer", run_layer)

        for name in ("testSetUp", "testTearDown"):
            real = getattr(R.TestResult, name)

            def per_test(result, _real=real):
                if shell.replaying:
                    return None
                return _real(result)

            p.set(R.TestResult, name, per_test)

        real_import = F.import_name

        def import_name(name):
            module = real_import(name)
            suite_fn = getattr(module, "test_suite", None)
            rel = shell.rel_of_module(module)
            if callable(suite_fn) and rel is not None and not getattr(suite_fn, "_detpy_wrapped", False):
                def test_suite(*a, **kw):
                    with run.collecting(rel):
                        suite = suite_fn(*a, **kw)
                    shell.tag(suite, "c|" + rel)
                    return suite

                test_suite._detpy_wrapped = True
                test_suite.__wrapped__ = suite_fn
                module.test_suite = test_suite
            return module

        p.set(F, "import_name", import_name)
        shell.extra_fixtures = lambda test: hooks.layer_of.get(id(test), [])
        return self

    def prepare(self, layers: list, R) -> None:
        """Every layer's tests: ids, order (inside each layer), the decision, stand-ins for reused tests."""
        shell = self.shell
        flat_by_layer = []
        for i, (layer_name, layer, tests) in enumerate(layers):
            gathered: list = []
            R.gather_layers(layer, gathered)
            fx = [f"f|layer|{R.name_from_layer(ly)}|{m}" for ly in gathered for m in ("setUp", "tearDown")]
            flat: list = []
            opaque: list = []
            shell.flatten(tests, flat, opaque) if not isinstance(tests, list) else shell.flatten(
                _ListSuite(tests), flat, opaque)
            for t in shell.iter_tests(_ListSuite(flat)):
                self.layer_of[id(t)] = fx
            flat_by_layer.append(shell.order(flat))
        all_flat = [t for flat in flat_by_layer for t in flat]
        reused = shell.decide_flat(all_flat)
        out = []
        for (layer_name, layer, _tests), flat in zip(layers, flat_by_layer):
            new = [(_Reused(t, shell.ids[id(t)], shell) if shell.is_reused(t, reused) else t) for t in flat]
            out.append((layer_name, layer, new))
        layers[:] = out


class _ListSuite:
    """A list of tests seen as a suite (``iter``)."""

    def __init__(self, tests):
        self.tests = list(tests)

    def __iter__(self):
        return iter(self.tests)


def main(ns, argv: list[str]) -> int:
    run = DetRun("zope-testrunner", ns, os.getcwd())
    run.start()
    import zope.testrunner
    from importlib.metadata import version

    shell = UnittestShell(run).install()
    ZopeHooks(shell, run).install()
    run.configure(version("zope.testrunner"), config_of(argv), unittest_infra_files())
    code = 0
    try:
        zope.testrunner.run(args=["zope-testrunner", *argv])
    except SystemExit as e:
        code = e.code
    finally:
        shell.uninstall()
        run.finish(code)
    if isinstance(code, int):
        return code
    return 0 if not code else 1
