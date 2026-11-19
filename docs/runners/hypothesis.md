# Hypothesis under every runner

Code: `python/detpy/seeds.py` (`_hypothesis`, called by `seeds.start_test`, i.e. under pytest and under every runner
of the driver). Test: `tests/test_runners_unittest.py::test_hypothesis_is_seeded_per_test_and_has_no_database`.

Under `--det`, at the start of every test once Hypothesis is imported:

| what | why |
|---|---|
| the per-thread generator Hypothesis draws each test's seed from (`hypothesis.core.threadlocal._hypothesis_global_random`) is dropped | Hypothesis creates it once and draws from it at every test, so a test's examples depended on how many tests drew before it (another order, or tests the cache skipped). Created again, it is a `Random()` seeded by the seeds control from the test id: a test's examples are a function of its id and `--det-seed` |
| the example database is off (`settings.database` is None) | replaying failures saved by earlier runs made a run depend on history; its reads under `.hypothesis/` were not cache inputs either |
| Hypothesis's storage is off (`set_hypothesis_home_dir` to a path that cannot exist) | its caches of local constants and of the Unicode table made the first run on a machine differ from later ones (cache written vs read); computed every run instead (cost: the Unicode table, once per process when text strategies are used) |
| local constants are off (`providers._get_local_constants` returns nothing) | Hypothesis biases examples with the constants of every local module loaded so far: a test's examples depended on which modules earlier tests imported and on code it never ran (not an input of the cache) |

`@seed`, `derandomize` and `--hypothesis-seed` keep their meaning. Under `--det`, Hypothesis's `deadline` reads the
virtual clock.
