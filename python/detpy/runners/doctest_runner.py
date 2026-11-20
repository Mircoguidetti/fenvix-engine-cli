"""``python -m detpy doctest [--det ...] [-v] [-o OPTION] [-f] FILE...``: ``python -m doctest`` under the driver.

Like ``python -m doctest``, a ``.py`` file is imported (its directory first on ``sys.path``) and its docstrings'
examples are tests, another file is a doctest text file (``testfile``). Each docstring (each text file) is one
test, run by ``doctest.DocTestRunner`` through ``doctest.DocTestSuite`` / ``DocFileSuite`` (unittest cases) so the
unittest shell does the work. Test ids: ``<file>::<name>`` (``mod.func``, or the text file's name). A doctest's
input is its own file's whole content (``DoctestItem``) besides what its examples execute and read; a text file's
read is the collection context ``c|<file>``. Options ``-o`` and ``-f`` are configuration. The report is unittest's
(``Ran N tests``, ``FAILED``) instead of doctest's; the exit status is the same (0, or 1 when an example fails).
"""

from __future__ import annotations

import argparse
import doctest
import os
import platform
import sys
import unittest

from .._level0 import UsageError
from .driver import DetRun
from .unittest_shell import UnittestShell, unittest_infra_files


def parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="detpy doctest", add_help=False)
    p.add_argument("-v", "--verbose", action="store_true", default=False)
    p.add_argument("-o", "--option", action="append", choices=doctest.OPTIONFLAGS_BY_NAME.keys(), default=[])
    p.add_argument("-f", "--fail-fast", action="store_true")
    p.add_argument("file", nargs="+")
    return p.parse_args(argv)


def build(run: DetRun, shell: UnittestShell, args) -> unittest.TestSuite:
    flags = 0
    for option in args.option:
        flags |= doctest.OPTIONFLAGS_BY_NAME[option]
    if args.fail_fast:
        flags |= doctest.FAIL_FAST
    suite = unittest.TestSuite()
    for filename in args.file:
        rel = run.rel(filename) or filename
        with run.collecting(rel):
            if filename.endswith(".py"):
                # as doctest._test: the file's directory first on sys.path, import by name
                dirname, base = os.path.split(filename)
                sys.path.insert(0, dirname)
                try:
                    m = __import__(base[:-3])
                finally:
                    del sys.path[0]
                sub = doctest.DocTestSuite(m, optionflags=flags)
            else:
                sub = doctest.DocFileSuite(filename, module_relative=False, optionflags=flags)
        shell.tag(sub, "c|" + rel)
        suite.addTest(sub)
    return suite


def main(ns, argv: list[str]) -> int:
    try:
        args = parse(argv)
    except SystemExit as e:
        raise UsageError("usage: detpy doctest [--det ...] [-v] [-o OPTION] [-f] FILE...") from e
    run = DetRun("doctest", ns, os.getcwd())
    run.start()
    shell = UnittestShell(run).install()
    run.configure(platform.python_version(), {"options": sorted(args.option), "fail_fast": args.fail_fast},
                  unittest_infra_files())
    code = 1
    try:
        suite = build(run, shell, args)
        result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
        code = 0 if result.wasSuccessful() else 1
    finally:
        shell.uninstall()
        run.finish(code)
    return code
