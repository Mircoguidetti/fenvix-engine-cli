# zope.testrunner under detpy (`python -m detpy zope-testrunner ...`)

Code: `python/detpy/runners/zope_runner.py` over the unittest shell (`unittest.md`). Tests: `tests/test_runners_zope.py`.

## Use

    python -m detpy zope-testrunner --det [--det-cache=DIR] [zope-testrunner arguments, e.g. --test-path=src]

## Support: det + skip

zope.testrunner runs unittest cases layer by layer: `Runner.run_tests` takes `ordered_layers()`, and `run_layer`
sets each layer (and its bases) up, then runs the layer's tests one by one with the layers' `testSetUp` /
`testTearDown` around each. The unittest shell brackets every test (`TestCase.__call__`); added here:

| hook | role |
|---|---|
| `Runner.ordered_layers` | every layer's tests decided before the first layer runs; order kept (layers by bases; a `--det-seed` shuffle stays inside a layer); reused tests replaced by stand-ins |
| `setup_layer` | a layer's set-up in `f|layer|<layer>|setUp`, an input of every test of that layer and of layers built on it (`test_layer_setup_read_is_an_input_and_a_reused_layer_is_not_set_up`) |
| `run_layer` | a layer whose tests are all reused is not set up; stand-ins skip `testSetUp` / `testTearDown` |
| `find.import_name` | a module's `test_suite()` runs in its collection context `c|<file>` (`test_test_suite_function_reads_are_inputs`) |
| `Runner.run_tests` | `-j N` forced to 1 under `--det` (`zope.testrunner -j N -> 1 under --det`) |

zope.testrunner's discovery (`find.py`) is infrastructure (its walk over the test paths is not an input).

Unit of reuse: a `TestCase` class; a layer's set-up is an input of its tests (not a unit: a layer's state mutated by
tests follows the pytest plugin's rule for wider-scoped fixtures).

## Refused / not reused

* A layer that cannot be torn down (`NotImplementedError` in `tearDown`) makes zope.testrunner run the remaining
  layers in a subprocess (`--resume-layer`): that subprocess runs outside the driver. The session then started a
  process: the capture's subprocess rule applies (followed under strace, or not cached), and the subprocess's tests
  have no detpy fingerprint.
* Layer tear-down reads happen between tests (global context: inputs of every test).
