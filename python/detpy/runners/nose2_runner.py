"""``python -m detpy nose2 [--det ...] [nose2 arguments]``: nose2 under the driver.

nose2 runs unittest suites (its function, generator and parameterised tests are ``unittest.FunctionTestCase``
subclasses or generated methods), so the unittest shell does the work; this module adds nose2's own module loader
(``PluggableTestLoader.loadTestsFromModule``: its plugins load a module's tests there, ``load_tests`` included) as a
collection context, and nose2's discovery and loader plugins as infrastructure (their listings are not inputs, as
pytest's collection is not). nose2's configuration files (``unittest.cfg``, ``nose2.cfg``, ``pyproject.toml``) are
read by nose2's session at start-up: those reads are inputs of every test. Plugins are modules: their code is an
input like any other module's. The multiprocess plugin (``-N`` / ``--processes``) is refused under ``--det``: its
workers run outside the driver.
"""

from __future__ import annotations

import os

from .._level0 import UsageError
from .driver import DetRun
from .unittest_shell import UnittestShell, unittest_infra_files

_VOLATILE_FLAGS = {"-v", "--verbose", "-q", "--quiet", "-F", "--fail-fast", "--log-capture", "-h", "--help",
                   "--collect-only", "--pretty-assert"}
_VALUE_OPTIONS = {"-s", "--start-dir", "-t", "--top-level-directory", "-c", "--config", "--plugin",
                  "--exclude-plugin", "-A", "--attribute", "-E", "--eval-attribute", "-N", "--processes",
                  "--log-level", "--junit-xml-path", "--output-buffer"}


def config_of(argv: list[str]) -> dict:
    """The command line without test names (selection) and output-only flags."""
    kept: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        name = a.split("=", 1)[0]
        if name in _VALUE_OPTIONS and "=" not in a and i + 1 < len(argv):
            kept.append(f"{a}={argv[i + 1]}")
            i += 2
            continue
        if a.startswith("-"):
            if name not in _VOLATILE_FLAGS and not (a.startswith("-v") and set(a[1:]) == {"v"}):
                kept.append(a)
        i += 1
    return {"args": kept}


def _nose2_infra() -> list[str]:
    import importlib

    out = []
    for m in ("nose2.loader", "nose2.plugins.loader.discovery", "nose2.plugins.loader.testcases",
              "nose2.plugins.loader.testclasses", "nose2.plugins.loader.functions", "nose2.plugins.loader.generators",
              "nose2.plugins.loader.parameters", "nose2.plugins.loader.loadtests", "nose2.runner", "nose2.result",
              "nose2.suite", "nose2.main"):
        try:
            out.append(importlib.import_module(m).__file__)
        except ImportError:  # pragma: no cover - an older nose2
            pass
    return out


def main(ns, argv: list[str]) -> int:
    if ns.det and any(a in ("-N", "--processes") or a.startswith("--processes=") for a in argv):
        raise UsageError("nose2's multiprocess plugin (-N / --processes) is not supported under --det: its workers "
                         "run outside detpy")
    run = DetRun("nose2", ns, os.getcwd())
    run.start()
    import nose2
    import nose2.loader

    shell = UnittestShell(run).install()
    shell.wrap_module_loader(nose2.loader.PluggableTestLoader, "loadTestsFromModule")
    version = getattr(nose2, "__version__", None)
    if version is None:
        from importlib.metadata import version as _v

        version = _v("nose2")
    run.configure(version, config_of(argv), unittest_infra_files() + _nose2_infra())
    code = 0
    try:
        nose2.discover(argv=["nose2", *argv], exit=True)
    except SystemExit as e:
        code = e.code
    finally:
        shell.uninstall()
        run.finish(code)
    if isinstance(code, int):
        return code
    return 0 if not code else 1
