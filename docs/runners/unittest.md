# unittest under detpy (`python -m detpy unittest`)

Owner: the all-runners Python builder. Code: `python/detpy/runners/unittest_runner.py` (command line),
`python/detpy/runners/unittest_shell.py` (the hooks shared by the whole unittest family), `python/detpy/runners/driver.py`
(the runner-neutral driver, `DetRun`). Tests: `tests/test_runners_unittest.py`.

## Use

    python -m detpy unittest --det [--det-cache=DIR] [--det-seed=N] [any `python -m unittest` arguments]

Everything `python -m unittest` accepts works (`discover`, `-s`, `-p`, `-t`, `-k`, module / class / method names,
`-b`, `-f`, `-c`, `-v`). The `--det*` options are the pytest plugin's (same table, `_level0.OPTIONS`) and may appear
anywhere on the line. `--det-outcomes=PATH` works without `--det` (plain run, outcomes and per-test times only).

## Support: det + skip

| part | what happens |
|---|---|
| Level 0 (`--det`) | the same controls as pytest (`_level0`): hash-seed re-exec, clock, seeds, file-system order, network, bytecode; per test the recorder's bracket and every per-test control (`_level0.begin_test` / `end_test`). Trace header: `runner: "unittest"` |
| order | the runner's order (the loader's sorted names); `--det-seed=N`: modules, classes in a module, methods in a class shuffled with the seed (each class stays contiguous: `setUpClass` runs once) |
| test ids | `<file>::<Class>::<method>` (pytest-like); function tests `<file>::<name>`; a second test with the same id (a `load_tests` that adds one case twice) gets `[1]`, `[2]` |
| cache (`--det-cache`) | the same Rust objects as pytest: `CaptureCore` (capture), `CacheSession` (decide, report, record, receipts), `ProofCache` (store) |
| reused tests | replaced in the suite by a stand-in that reports the recorded outcome to the runner's result (`addSuccess`, `addSkip` with the recorded reason, `addExpectedFailure`) without running; counted in `Ran N tests` and in the summary |
| verify | `--det-cache-verify=F` as for pytest |

## Hooks (all on unittest's own classes)

| hook | role |
|---|---|
| `TestLoader.loadTestsFromModule` | collection context `c|<file>` (a module's `load_tests`); an input of every test it returned |
| `TestSuite.run` (top level) | flatten, order, ids, decision, stand-ins |
| `TestSuite._handleClassSetUp` / `_tearDownPreviousClass` | `f|class|<file>::<Class>|setUpClass` / `tearDownClass` contexts |
| `TestSuite._handleModuleFixture` / `_handleModuleTearDown` | `f|module|<file>|setUpModule` / `tearDownModule` contexts |
| `TestSuite._createClassOrModuleLevelException` | a tear-down error of a class / module is a teardown error of every test of it that ran (never reused) |
| `TestCase.__call__` | the test's bracket; a proxy of the result turns `add*` calls into phase reports |

The runner's own modules (`unittest/loader.py`, `main.py`, `suite.py`, `runner.py`, `result.py`) are infrastructure,
like pytest's: their directory listings and existence probes during discovery are not inputs. Code the project runs
from them (`load_tests`, `setUpClass`, tests) is.

## Unit of reuse: the class

Methods of a `TestCase` class run in order in one process and share the class's attributes and what `setUpClass`
built. When method A must run (its code changed) and method B were reused, B's recorded result would come from a run
where A's old version prepared the class state; nothing in the capture sees in-memory state. So a class is reused as
a whole or not at all (`CacheSession.regroup`, receipt `unit: <test> runs`). Test:
`test_class_state_makes_the_class_the_unit_of_reuse` (a per-method reuse keeps `test_b`'s old pass; a full run fails).
Module-level state across classes follows the pytest plugin's rule (the test is the unit; the module's set-up and
import are inputs of its tests).

## Configuration digest

The arguments that can change a result: discovery's start directory, pattern and top-level directory (they decide
module names and which modules are imported), `-b`, `-c`. Left out, as pytest leaves them out: test names and `-k`
(selection), `-v`, `-q`, `--locals`, `--durations`, `-f`.

## Not covered, and why

* In-memory state left by a test module's import (a module that patches a library or sets a variable at import
  time) for tests of other modules: the same rule and limit as the pytest plugin (an import-time read of a test
  module serves only its own tests). A new test module with such side effects is not seen by the tests of the
  other modules.
* `unittest.main()` inside a test module run as a script (`python test_x.py`): not through the driver; use
  `python -m detpy unittest test_x`.
* Output: under the virtual clock unittest prints `Ran N tests in 0.000s` (its own timer reads the virtual clock).
