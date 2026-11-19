"""``python -m detpy unittest [--det ...] [unittest arguments]``: ``python -m unittest`` under the driver.

Everything ``python -m unittest`` accepts works (``discover``, ``-k``, module / class / method names, ``-p``, ``-s``,
``-t``). The configuration digest holds the arguments that can change a result: discovery's start directory, pattern
and top-level directory (the module names, the files imported), ``-b`` (buffered output), ``-c``. Not in it, as for
pytest: test names and ``-k`` (selection), ``-v`` / ``-q`` / ``--locals`` / ``--durations`` (output), ``-f``
(stop at the first failure).
"""

from __future__ import annotations

import os
import platform
import unittest

from .driver import DetRun
from .unittest_shell import UnittestShell, unittest_infra_files

_VALUE_OPTIONS = {"-k", "-p", "--pattern", "-s", "--start-directory", "-t", "--top-level-directory", "--durations"}
_VOLATILE = {"-v", "--verbose", "-q", "--quiet", "--locals", "-f", "--failfast", "-k", "--durations"}


def config_of(argv: list[str]) -> dict:
    """The part of a ``python -m unittest`` command line that can change a result."""
    kept: list[str] = []
    discover = bool(argv) and argv[0] == "discover"
    i = 1 if discover else 0
    while i < len(argv):
        a = argv[i]
        name = a.split("=", 1)[0]
        value = None
        if name in _VALUE_OPTIONS and "=" not in a and i + 1 < len(argv):
            value = argv[i + 1]
            i += 1
        if a.startswith("-"):
            if name not in _VOLATILE:
                kept.append(a if value is None else f"{a}={value}")
        elif discover:
            kept.append(a)  # positional start directory, pattern, top-level directory
        i += 1
    return {"discover": discover, "args": kept}


def main(ns, argv: list[str]) -> int:
    run = DetRun("unittest", ns, os.getcwd())
    run.start()
    shell = UnittestShell(run).install()
    run.configure(platform.python_version(), config_of(argv), unittest_infra_files())
    code = 0
    try:
        unittest.main(module=None, argv=["python -m unittest", *argv])
    except SystemExit as e:
        code = e.code
    finally:
        shell.uninstall()
        run.finish(code)
    return code if isinstance(code, int) else (0 if not code else 1)
