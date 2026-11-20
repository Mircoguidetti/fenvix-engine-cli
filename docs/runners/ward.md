# ward under detpy (`python -m detpy ward ...`)

Code: `python/detpy/runners/ward_runner.py` (its own shell: ward is not built on unittest). Tests:
`tests/test_runners_ward.py`.

## Use

    python -m detpy ward --det [--det-cache=DIR] test [ward test arguments]

## Support: det + skip

| part | what happens |
|---|---|
| loop | `Suite.generate_test_runs` is replaced by the same loop (ward 0.68's: run a test, tear down its test-scoped fixtures, a module's fixtures after its last test, the global ones at the end) that first expands every test (parameterised instances), fixes the order, decides reuse, then yields a reused test's recorded result (`TestResult(test, PASS/SKIP/XFAIL)`) without running it and brackets the others |
| ids | `<file>::<function>`; ward tests are usually all named `_`: then the description as written (before formatting), `[i]` for a parameterised instance, `#n` for a repeated description |
| fixtures | a module- or global-scoped fixture is computed in `f|module|<test file>|<fixture file>::<name>` / `f|global|<fixture file>|<name>`, an input of every test that uses it, directly or through other fixtures (`test_module_and_global_fixture_reads_are_inputs_of_their_users`) |
| order | ward's collection order; `--det-seed`: modules, then tests in a module, shuffled with the seed (ward's own `--order random` is left out of the configuration and overridden) |
| own machinery | ward's collection (`_collect.py`) is infrastructure; building its test objects (uuid4 ids) is not an input |
| configuration | the command line without selection and output options; `[tool.ward]` in `pyproject.toml` is read by ward at start-up (an input of every test) |

## Not covered, and why

* The replaced loop follows ward 0.68.0b0's `generate_test_runs`; another ward version with a different loop needs
  the copy updated (the version is in the configuration digest through the runtime identity).
* Module- and global-scoped fixture state mutated by tests: the pytest plugin's rule for wider-scoped fixtures.
