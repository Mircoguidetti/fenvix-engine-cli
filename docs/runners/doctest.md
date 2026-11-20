# doctest under detpy (`python -m detpy doctest FILE...`)

Code: `python/detpy/runners/doctest_runner.py` over the unittest shell (`unittest.md`). Tests:
`tests/test_runners_doctest.py`.

## Use

    python -m detpy doctest --det [--det-cache=DIR] [-v] [-o OPTION]... [-f] FILE...

As `python -m doctest`: a `.py` file is imported (its directory first on `sys.path` for the import) and its
docstrings are tests; another file is a doctest text file (`testfile`).

## Support: det + skip

* Each docstring (each text file) is one test, run by `doctest.DocTestRunner` through `DocTestSuite` / `DocFileSuite`
  (unittest cases): the unittest shell brackets and reuses them. Ids: `<file>::<name>` (`m.py::m.func`,
  `README.txt::README.txt`).
* A doctest's own file is an input as a whole (`DoctestItem`, as pytest's doctest items): a docstring edit reruns the
  file's doctests; a text file's read is its collection context `c|<file>`. What the examples execute and read is
  captured as for any test.
* `-o` options and `-f` are configuration (`test_option_change_is_configuration`).
* The report is unittest's (`Ran N tests`, `FAILED (failures=1)`) instead of doctest's own summary; the exit status
  is the same (0, or 1 when an example fails).

## Not covered, and why

* `doctest.testmod()` called from a module's `__main__` block (`python m.py`): not through the driver; run
  `python -m detpy doctest m.py`.
* Doctests run by pytest (`--doctest-modules`, `--doctest-glob`) are pytest's (already covered by the plugin).
