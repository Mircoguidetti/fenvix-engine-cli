"""Runners other than pytest under ``--det`` / ``--det-cache``: ``python -m detpy <runner> [--det ...] [args]``.

One driver (``driver.DetRun``: the same lifecycle and the same Rust objects as the pytest plugin) and thin shells:
the unittest family (``unittest_shell``: unittest, Django, nose2, doctest, zope.testrunner) and ward. See
``docs/ALL-RUNNERS.md`` and ``docs/runners/<runner>.md``.
"""

from __future__ import annotations

import importlib
import sys

RUNNERS = {
    "unittest": "unittest_runner",
    "django": "django_runner",
    "nose2": "nose2_runner",
    "doctest": "doctest_runner",
    "zope-testrunner": "zope_runner",
    "ward": "ward_runner",
}


def _detpy_runner_entry(mod, ns, rest: list[str]) -> int:
    """The outermost frame of the runner's shell: the capture takes a read, probe or environment read whose calling
    frames reach this one without passing test code as the shell's own (not an input), as pytest's own frames are
    infrastructure (``crates/detpy-py/src/capture.rs``, ``is_runner_entry``)."""
    return mod.main(ns, rest)


# the module each runner needs (a clear message when it is not installed: audit G-2001..G-2004)
NEEDS = {"django": "django", "nose2": "nose2", "ward": "ward", "zope-testrunner": "zope.testrunner"}
DESCRIBE = {
    "unittest": "unittest suites (python -m unittest), deterministically",
    "django": "Django's test runner (manage.py test), deterministically",
    "nose2": "nose2 suites, deterministically",
    "doctest": "doctest files and modules, deterministically",
    "zope-testrunner": "zope.testrunner suites, deterministically",
    "ward": "ward suites, deterministically",
}


def det_help(name: str) -> str:
    """The ``--det*`` options of the runner shells (the same table as ``pytest --help``: audit G-1535, G-0983)."""
    from .driver import parser

    return (f"fenvix {name} [--det options] [{name} arguments]: {DESCRIBE.get(name, name)}\n"
            f"Every other argument goes to the runner unchanged (its own options are those of {name}).\n\n" + parser(f"fenvix {name}").format_help())


def main(name: str, argv: list[str]) -> int:
    from .._level0 import OPTIONS, UsageError
    from .driver import parse

    if any(a in ("-h", "--help", "--det-help") for a in argv) and "--" not in argv:
        print(det_help(name))
        return 0
    need = NEEDS.get(name)
    if need is not None:
        from importlib.util import find_spec

        try:
            found = find_spec(need) is not None
        except ModuleNotFoundError:
            found = False
        if not found:
            print(f"fenvix {name}: the {need} package is not installed in this environment "
                  f"({sys.executable}); install it, or run your suite through pytest", file=sys.stderr)
            return 4
    known = {f for flags, _ in OPTIONS for f in flags}
    head = argv[:argv.index("--")] if "--" in argv else argv
    bad = [a for a in head if a.startswith("--det") and a.split("=", 1)[0] not in known]
    if bad:
        import difflib

        hint = difflib.get_close_matches(bad[0].split("=", 1)[0], sorted(known), n=1)
        print(f"fenvix {name}: error: unknown option {bad[0]}" + (f" (did you mean {hint[0]}?)" if hint else "")
              + f"; `fenvix {name} --help` lists the --det options", file=sys.stderr)
        return 4
    mod = importlib.import_module(f".{RUNNERS[name]}", __name__)
    try:
        ns, rest = parse(argv, prog=f"detpy {name}")
        return _detpy_runner_entry(mod, ns, rest)
    except UsageError as e:
        print(f"detpy {name}: error: {e}", file=sys.stderr)
        return 4
