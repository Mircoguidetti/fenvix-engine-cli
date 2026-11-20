# Django's test runner under detpy (`python -m detpy django manage.py test ...`)

Code: `python/detpy/runners/django_runner.py` over the unittest shell (`unittest.md`). Tests:
`tests/test_runners_django.py`.

## Use

    python -m detpy django manage.py test --det [--det-cache=DIR] [manage.py test arguments]
    python -m detpy django runtests.py --det [...]          # a script around Django's runner (DRF, Wagtail style)
    python -m detpy django django-admin test --det [...]    # = python -m django test (DJANGO_SETTINGS_MODULE set)

## Support: det + skip

Everything of the unittest shell, plus:

| part | what happens |
|---|---|
| `--parallel` | forced to 1 under `--det`, said in the summary (`Django --parallel N -> 1 under --det`): Django's parallel runner forks workers that run outside the driver (no order, clock or capture control there) |
| order | Django's own (it already groups `reorder_by`: `TestCase`, then `SimpleTestCase` / `TransactionTestCase`, then others); a `--det-seed` shuffle is followed by Django's grouping again (a stable sort on the group), as the pytest plugin keeps pytest-django's groups |
| bracket | `SimpleTestCase.__call__` (Django's `_pre_setup`: a `TransactionTestCase`'s fixtures and database flush are inside the test) |
| class set-up | `TestCase.setUpClass` (`setUpTestData`, the class's `fixtures = [...]`) is the `f|class|...|setUpClass` context: JSON fixture files and the fixture directories Django lists are inputs of that class's tests |
| database | created before the first test (the global context: migrations, the database settings are inputs of every test). The walks use sqlite |
| templates | Django's cached loader returns a template from memory to every test after the first: detpy reads the template's file again (or probes the missing names the loader remembers), so the file is an input of every test that renders it (`test_template_from_the_cached_loader_is_an_input_of_every_renderer`: without it, the second renderer keeps its old pass). Shared code (`detpy/_django.py`), also active under pytest / pytest-django (`tests/test_django_pytest_cache.py`) |
| translations | `.mo` catalogs are loaded in the global context: inputs of every test |
| configuration | every argument but the output-only ones (`-v`, `--timing`, `--no-color`, `--durations`, `--parallel`); test labels stay in (an option's value and a label look alike in an unknown script) |

## Not covered, and why

* Every Django test depends on the whole environment: Django's test client imports `wsgiref.handlers`, which reads
  every variable at import time (the same under pytest-django; the cache-proof step 1 report names it). Reuse across
  CI jobs whose environments differ needs the founder's decision on volatile variables (step 1 report).
* `TZ`: Django sets it from `settings.TIME_ZONE` at start-up (the settings are inputs).
* Databases other than sqlite: the database server's state is not an input (a test that reads it through a socket
  is not cached: the capture refuses network connections, loopback included).
* Other caches inside Django that keep file contents in memory across tests beyond templates and translations
  (static file finders' storages, a project's own caches): the pytest plugin's rule and limit (in-memory state).
