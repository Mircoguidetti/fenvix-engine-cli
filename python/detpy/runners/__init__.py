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


def main(name: str, argv: list[str]) -> int:
    from .._level0 import UsageError
    from .driver import parse

    mod = importlib.import_module(f".{RUNNERS[name]}", __name__)
    try:
        ns, rest = parse(argv, prog=f"detpy {name}")
        return _detpy_runner_entry(mod, ns, rest)
    except UsageError as e:
        print(f"detpy {name}: error: {e}", file=sys.stderr)
        return 4
