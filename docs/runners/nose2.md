# nose2 under detpy (`python -m detpy nose2 ...`)

Code: `python/detpy/runners/nose2_runner.py` over the unittest shell (`unittest.md`). Tests: `tests/test_runners_nose2.py`.

## Use

    python -m detpy nose2 --det [--det-cache=DIR] [nose2 arguments]

## Support: det + skip

nose2 runs unittest suites: its function tests, generator tests (`test_gen:1`, ...) and parameterised tests
(`@params`, `test_params:2`) are `unittest.FunctionTestCase` subclasses or generated methods, so the unittest shell
does the work. Added here:

* nose2's own module loader (`PluggableTestLoader.loadTestsFromModule`, where its loader plugins and `load_tests`
  run) is a collection context `c|<file>`;
* nose2's discovery and loader plugins, runner, result and suite modules are infrastructure (their listings are not
  inputs, as for unittest's loader);
* nose2's configuration files (`unittest.cfg`, `nose2.cfg`, `pyproject.toml`) are read by its session at start-up:
  inputs of every test (`test_configuration_file_is_an_input`); plugin modules are code like any other module's
  (`test_plugin_module_change_reruns`);
* ids: nose2's ids without the arguments it appends on a second line (`<file>::test_gen:1`).

Unit of reuse: a `TestCase` class (as for unittest); a function test alone.

Configuration digest: the command line without test names and output-only flags (`-v`, `-q`, `-F`, `--log-capture`,
`--pretty-assert`, `--collect-only`).

## Refused

* The multiprocess plugin (`-N` / `--processes`): its workers run outside the driver. Under `--det` the command
  stops with an error (exit 4) (`test_multiprocess_plugin_is_refused`). When the plugin is turned on from a
  configuration file instead, its workers are child processes: the session started processes and nothing is reused.
* nose2's `layers` plugin: not wired (no layer contexts); a layer's set-up runs between tests (global context: an
  input of every test, sound, coarse).
