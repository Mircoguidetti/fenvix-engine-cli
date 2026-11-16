# P-009 item 7: django-beam, 0 known flaky on Actions vs 11/11 locally

Same commit (43b2111f5c65), same Python (3.9.25), identical `uv pip freeze` (only paths differ), same seeds (`--randomly-seed=1000..1009`).

| | Actions (runs 43946229556, 43962563115) | local container |
|---|---|---|
| xdist baseline, 10 runs | 10/10 exit 0; known flaky unstable 0/11 | 6/10 runs fail; known flaky unstable 11/11 |
| same seeds, serial (`-n 0`) | 0 failures for every seed | 1000: 2, 1003: 11, 1004: 9, 1005: 2, 1006: 11, 1008: 11, others 0 |
| order given by pytest-randomly for the same seed | different from local for 10/10 seeds | |

Cause: plugin registration order. pytest loads `pytest11` entry points in the order `importlib.metadata.distributions()`
lists them, i.e. the (unsorted, filesystem-dependent) directory listing of site-packages. pytest-randomly and pytest-django
both implement `pytest_collection_modifyitems` with `tryfirst=True`; between equal hooks pluggy calls the plugin registered
last first.

* local: `pytest_randomly-4.0.1.dist-info` is listed before `pytest_django-4.11.1.dist-info`, so pytest-django sorts first and
  randomly's shuffle is final: polluting orders, 11 order-dependent failures (LookupError on a Mock app label).
* Actions runner: the other way round. Randomly shuffles, then pytest-django stably moves the database tests to the front:
  an order in which no polluter precedes its victims.

Check: locally forcing pytest-django to register first (`-p no:django -p pytest_django.plugin`) gives exactly the Actions
order for 10/10 seeds (md5 of the collected order identical) and 80/80 passing tests for every seed.
