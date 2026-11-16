# detpy Level 0: measurement report (`mixed`)

Generated 2026-11-16 16:34 UTC with detpy 0.1.0. Per repository: 10 baseline runs (random order from pytest-randomly with a different seed per run, pytest-xdist `-n 2` where the suite supports it) interleaved with 10 `--det` runs (fixed order, serial); then, for every test unstable in the baseline, exploration with `--det-seed=1..20` and 10/10 confirmation of the seed that makes it fail. Executor: GitHub Actions matrix, one repository per ubuntu-latest runner (run https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43892303433). Labels: MEASURED (by this harness), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host.

## Main metric

**Baseline-unstable tests made reproducible: 347/406 = 85.5%** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass; a test that fails under every `--det` configuration is broken by Level 0, not reproduced.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IDoFT dataset | 24 | 2568 | 361 | 337 | 93.4% | 16 | 8 | 0 |
| popular | 25 | 117082 | 45 | 10 | 22.2% | 35 | 0 | 0 |
| total | 49 | 119650 | 406 | 347 | 85.5% | 51 | 8 | 0 |

**(a, b) Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 0 (fixed order): 64, 1: 82, 2-5: 154, 6-10: 43, 11-20: 4; median 2.

**(c) First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `random` 270, `time` 62, `thread` 5, `entropy` 5, `fs` 5.

## IDoFT known flaky tests (MEASURED)

| known flaky tests (IDoFT, measured projects) | present in the collected suite | flaky in our baseline | reproduced |
|---:|---:|---:|---:|
| 509 | 509 | 355 | 337 |

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). These are false failures. **108 tests** (MEASURED), of which 106 fail in every `--det` run.

Cause: `fixed-order` = the test also fails in a serial fixed-order run *without* `--det` (the baseline hides it with random order and xdist: not a Level 0 failure); otherwise the controls whose `--det-disable` makes it pass again (one ablation run per control); `unexplained` = none does.

| cause (controls) &#124; exception | tests | examples |
|---|---:|---|
| `time | AssertionError` | 58 | idoft-easypy: tests/test_concurrency.py::test_multiobject_concurrent_find_found: assert 2 == 1 (first diverging source: thread)<br>idoft-easypy: tests/test_concurrency.py::test_multiobject_concurrent_find_proper_shutdown: assert 9 <= 2 (first diverging source: thread) |
| `fs | BlockingError` | 36 | anyio: tests/test_fileio.py::TestPath::test_glob[asyncio+eager-False]: blockbuster.blockbuster.BlockingError: Blocking call to SortedScandir.__next__ (first diverging source: -)<br>anyio: tests/test_fileio.py::TestPath::test_glob[asyncio+eager-True]: blockbuster.blockbuster.BlockingError: Blocking call to SortedScandir.__next__ (first diverging source: -) |
| `net | ConnectionError` | 4 | requests: tests/test_requests.py::TestTimeout::test_connect_timeout[timeout0]: requests.exceptions.ConnectionError: HTTPConnectionPool(host='10.255.255.1', port=80): Max retries exceeded with url: / (Caused by NewConnec (first diverging source: -)<br>requests: tests/test_requests.py::TestTimeout::test_connect_timeout[timeout1]: requests.exceptions.ConnectionError: HTTPConnectionPool(host='10.255.255.1', port=80): Max retries exceeded with url: / (Caused by NewConnec (first diverging source: -) |
| `fixed-order (fails without --det too) | AssertionError` | 3 | idoft-coinbase-commerce-python: tests/api_resources/base/test_list_api_resource.py::TestListAPIResource::test_list: AssertionError: False is not true (first diverging source: random)<br>idoft-coinbase-commerce-python: tests/api_resources/test_charge.py::TestCharge::test_list_iter_mapping: AssertionError: <APIObject id=No ID> Serialized: { (first diverging source: -) |
| `time | unknown` | 3 | anyio: tests/streams/test_tls.py::TestTLSListener::test_handshake_fail[asyncio+eager]: BlockingError('Blocking call to os.path.abspath') [single exception in ExceptionGroup] (first diverging source: -)<br>anyio: tests/streams/test_tls.py::TestTLSListener::test_handshake_fail[asyncio+uvloop]: BlockingError('Blocking call to os.path.abspath') [single exception in ExceptionGroup] (first diverging source: -) |
| `time | Failed` | 2 | requests: tests/test_requests.py::TestTimeout::test_read_timeout[timeout0]: Failed: The recv() request should time out. (first diverging source: -)<br>requests: tests/test_requests.py::TestTimeout::test_read_timeout[timeout1]: Failed: The recv() request should time out. (first diverging source: -) |
| `fixed-order (fails without --det too) | RecursionError` | 1 | idoft-easypy: tests/test_sync.py::test_synchronization_coordinator_with_multiobject_exception: RecursionError: maximum recursion depth exceeded (first diverging source: thread) |
| `time | Timeout` | 1 | boltons: tests/test_socketutils.py::test_socketutils_netstring: boltons.socketutils.Timeout: socket operation timed out after 10000ms. 0 bytes unsent (first diverging source: thread) |

## Timing

Quiet timing pass: 10 repositories, one per GitHub-hosted runner, one repository per runner, 3 serial fixed-order normal runs vs 3 `--det` runs interleaved on the same machine; median per repository. Runner: cpus=4, platform=linux, RUNNER_NAME=GitHub Actions 1000007987, RUNNER_OS=Linux, RUNNER_ARCH=X64, RUNNER_ENVIRONMENT=github-hosted, ImageOS=ubuntu26, ImageVersion=20261111.196.1, cpu_model=AMD EPYC 9V45 96-Core Processor. Labelled **DECLARED-NOISY**: hosted runners are virtual machines on shared hardware.

**Slowdown of `--det` (MEASURED, DECLARED-NOISY): median 14.6%**, min -62.8%, max 183.2%.

| repo | tests | normal serial s (median) | --det s (median) | slowdown % | precompile s (per run) |
|---|---:|---:|---:|---:|---|
| attrs | 1412 | 5.51 | 6.92 | 25.5 | 5.15, 0.21, 0.22 |
| idoft-centreon-sdk-python | 44 | 0.32 | 0.78 | 143.8 | 1.02, 0.30, 0.30 |
| idoft-cloudnetpy | 439 | 6.24 | 6.14 | -1.6 | 2.50, 0.67, 0.66 |
| idoft-crom | 84 | 0.30 | 0.84 | 183.2 | 1.09, 0.34, 0.34 |
| idoft-easypy | 212 | 12.98 | 4.83 | -62.8 | 1.43, 0.49, 0.49 |
| idoft-eppy | 218 | 6.50 | 7.81 | 20.2 | 1.89, 0.72, 0.74 |
| networkx | 10181 | 134.62 | 148.38 | 10.2 | 10.74, 0.71, 0.72 |
| pygments | 5346 | 12.08 | 13.88 | 14.9 | 7.21, 0.30, 0.30 |
| rich | 981 | 5.05 | 3.92 | -22.4 | 7.59, 0.40, 0.41 |
| werkzeug | 1016 | 6.68 | 7.64 | 14.2 | 5.46, 0.25, 0.25 |

* Round timings, serial `--det` vs the random-order xdist `-n 2` baseline: median 78.2% — **NOT COMPARABLE** (different parallelism and order; reported only for completeness).
* Deterministic bytecode precompilation, first `--det` run of each repository: median 5.07 s, max 15.69 s; later runs (incremental check): median 0.34 s (MEASURED, NOISY).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 2; unstable in the baseline and stable under `--det`: 406
* stable in both modes but with a different majority outcome: 3324
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 116071 (99.7%); not covered: 346 (`entropy` 219, `thread` 82, `time` 33, `fs` 12)

## Per repository (MEASURED)

| repo | pool | py | xdist | tests | unstable | reproduced | seeds explored | broken by det | not covered | IDoFT present / flaky / reproduced |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [idoft-eppy](https://github.com/santoshphilip/eppy) | flaky | 3.9 | yes | 218 | 67 | 66 | 20 | 0 | 0 | 87 / 66 / 66 |
| [idoft-cloudnetpy](https://github.com/tukiains/cloudnetpy) | flaky | 3.9 | yes | 439 | 27 | 27 | 5 | 0 | 1 | 52 / 27 / 27 |
| [idoft-easypy](https://github.com/weka-io/easypy) | flaky | 3.9 | yes | 212 | 44 | 40 | 20 | 4 | 29 | 44 / 44 / 40 |
| [idoft-centreon-sdk-python](https://github.com/guillaumewatteeux/centreon-sdk-python) | flaky | 3.9 | yes | 44 | 41 | 36 | 20 | 0 | 0 | 41 / 41 / 36 |
| [idoft-crom](https://github.com/thegetty/crom) | flaky | 3.9 | yes | 84 | 13 | 11 | 20 | 0 | 21 | 38 / 13 / 11 |
| [idoft-pykicad](https://github.com/dvc94ch/pykicad) | flaky | 3.9 | yes | 48 | 28 | 28 | 2 | 0 | 0 | 28 / 28 / 28 |
| [idoft-flask-multi-redis](https://github.com/max-k/flask-multi-redis) | flaky | 3.9 | yes | 33 | 14 | 14 | 3 | 0 | 0 | 26 / 14 / 14 |
| [idoft-pymq](https://github.com/thrau/pymq) | flaky | 3.9 | yes | 127 | 1 | 0 | 20 | 5 | 50 | 20 / 1 / 0 |
| [idoft-py-autodoc](https://github.com/heavenshell/py-autodoc) | flaky | 3.9 | yes | 27 | 15 | 15 | 15 | 0 | 1 | 15 / 15 / 15 |
| [idoft-freezegun](https://github.com/spulec/freezegun) | flaky | 3.9 | yes | 112 | 8 | 6 | 20 | 2 | 0 | 15 / 6 / 6 |
| [idoft-odinweb](https://github.com/python-odin/odinweb) | flaky | 3.9 | yes | 450 | 12 | 12 | 1 | 0 | 8 | 14 / 12 / 12 |
| [idoft-tunacell](https://github.com/LeBarbouze/tunacell) | flaky | 3.9 | yes | 39 | 10 | 10 | 6 | 0 | 2 | 13 / 10 / 10 |
| [idoft-domain2idna](https://github.com/PyFunceble/domain2idna) | flaky | 3.9 | yes | 15 | 15 | 12 | 20 | 0 | 0 | 12 / 12 / 12 |
| [idoft-accessify](https://github.com/dmytrostriletskyi/accessify) | flaky | 3.9 | yes | 41 | 7 | 7 | 5 | 0 | 0 | 12 / 7 / 7 |
| [idoft-django-beam](https://github.com/django-beam/django-beam) | flaky | 3.9 | yes | 80 | 0 | 0 | 0 | 0 | 25 | 11 / 0 / 0 |
| [idoft-breathe](https://github.com/mrob95/Breathe) | flaky | 3.9 | yes | 24 | 8 | 8 | 10 | 0 | 0 | 11 / 8 / 8 |
| [idoft-todo-sync](https://github.com/tmurph/todo-sync) | flaky | 3.9 | yes | 223 | 10 | 9 | 20 | 0 | 0 | 11 / 10 / 9 |
| [idoft-devtracker](https://github.com/ConSou/devtracker) | flaky | 3.9 | yes | 19 | 6 | 6 | 2 | 0 | 0 | 9 / 6 / 6 |
| [idoft-supertunnel](https://github.com/alexrudy/supertunnel) | flaky | 3.9 | yes | 80 | 9 | 9 | 1 | 0 | 0 | 9 / 9 / 9 |
| [idoft-krllint](https://github.com/d4nuu8/krllint) | flaky | 3.9 | yes | 16 | 3 | 2 | 20 | 0 | 0 | 9 / 3 / 2 |
| [idoft-panamah-sdk-python](https://github.com/casamagalhaes/panamah-sdk-python) | flaky | 3.9 | yes | 23 | 4 | 0 | 20 | 0 | 3 | 8 / 4 / 0 |
| [idoft-coinbase-commerce-python](https://github.com/coinbase/coinbase-commerce-python) | flaky | 3.9 | yes | 79 | 7 | 7 | 2 | 3 | 0 | 8 / 7 / 7 |
| [idoft-ljson](https://github.com/daknuett/ljson) | flaky | 3.9 | yes | 33 | 4 | 4 | 3 | 0 | 0 | 8 / 4 / 4 |
| [idoft-mdutils](https://github.com/didix21/mdutils) | flaky | 3.9 | yes | 102 | 8 | 8 | 1 | 0 | 0 | 8 / 8 / 8 |
| [pygments](https://github.com/pygments/pygments) | popular | 3.13 | yes | 5346 | 0 | 0 | 0 | 0 | 0 |  |
| [networkx](https://github.com/networkx/networkx) | popular | 3.13 | yes | 10181 | 0 | 0 | 0 | 1 | 62 |  |
| [attrs](https://github.com/python-attrs/attrs) | popular | 3.13 | yes | 1412 | 0 | 0 | 0 | 0 | 1 |  |
| [rich](https://github.com/Textualize/rich) | popular | 3.13 | yes | 981 | 5 | 5 | 1 | 1 | 0 |  |
| [werkzeug](https://github.com/pallets/werkzeug) | popular | 3.13 | yes | 1016 | 0 | 0 | 0 | 0 | 33 |  |
| [flask](https://github.com/pallets/flask) | popular | 3.13 | yes | 494 | 0 | 0 | 0 | 0 | 1 |  |
| [click](https://github.com/pallets/click) | popular | 3.13 | yes | 2651 | 0 | 0 | 0 | 0 | 3 |  |
| [jinja](https://github.com/pallets/jinja) | popular | 3.13 | yes | 911 | 0 | 0 | 0 | 0 | 0 |  |
| [requests](https://github.com/psf/requests) | popular | 3.13 | yes | 635 | 0 | 0 | 0 | 7 | 67 |  |
| [faker](https://github.com/joke2k/faker) | popular | 3.13 | yes | 2473 | 0 | 0 | 0 | 1 | 0 |  |
| [marshmallow](https://github.com/marshmallow-code/marshmallow) | popular | 3.13 | yes | 1210 | 18 | 0 | 20 | 0 | 1 |  |
| [arrow](https://github.com/arrow-py/arrow) | popular | 3.13 | yes | 1904 | 2 | 2 | 2 | 0 | 0 |  |
| [dateutil](https://github.com/dateutil/dateutil) | popular | 3.13 | yes | 5344 | 0 | 0 | 0 | 0 | 0 |  |
| [more-itertools](https://github.com/more-itertools/more-itertools) | popular | 3.13 | yes | 771 | 0 | 0 | 0 | 0 | 1 |  |
| [boltons](https://github.com/mahmoud/boltons) | popular | 3.13 | yes | 621 | 0 | 0 | 0 | 2 | 5 |  |
| [toolz](https://github.com/pytoolz/toolz) | popular | 3.13 | yes | 193 | 0 | 0 | 0 | 0 | 0 |  |
| [sortedcontainers](https://github.com/grantjenks/python-sortedcontainers) | popular | 3.13 | yes | 366 | 0 | 0 | 0 | 0 | 0 |  |
| [packaging](https://github.com/pypa/packaging) | popular | 3.13 | yes | 63798 | 1 | 1 | 10 | 0 | 0 |  |
| [structlog](https://github.com/hynek/structlog) | popular | 3.13 | yes | 921 | 0 | 0 | 0 | 43 | 19 |  |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | popular | 3.13 | yes | 8529 | 2 | 2 | 2 | 0 | 0 |  |
| [sqlparse](https://github.com/andialbrecht/sqlparse) | popular | 3.13 | yes | 540 | 0 | 0 | 0 | 0 | 0 |  |
| [anyio](https://github.com/agronholm/anyio) | popular | 3.13 | yes | 4857 | 17 | 0 | 4 | 39 | 11 |  |
| [isort](https://github.com/PyCQA/isort) | popular | 3.13 | yes | 794 | 0 | 0 | 0 | 0 | 2 |  |
| [pluggy](https://github.com/pytest-dev/pluggy) | popular | 3.13 | yes | 226 | 0 | 0 | 0 | 0 | 0 |  |
| [humanize](https://github.com/python-humanize/humanize) | popular | 3.13 | no | 908 | 0 | 0 | 0 | 0 | 0 |  |

## Discarded candidates

| repo | pool | reason | detail |
|---|---|---|---|
| idoft-reframe | flaky | install-failed | /runtime.py", line 14, in <module> import reframe.core.config as config File "/tmp/work/src/idoft-reframe/reframe/core/config.py", line 10, in <module> import jsonschema ModuleNotFoundError: No module named 'jsonschema'  |
| idoft-webssh | flaky | collect-failed | ests/test_settings.py !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 5 errors during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 9 tests collected, 5 errors in 0.30s  |
| idoft-pygraph | flaky | install-failed | t call last): File "<string>", line 11, in <module> AttributeError: module 'poetry.masonry.api' has no attribute 'build_editable' hint: Build failures usually indicate a problem with the package or the build environment  |
| idoft-flask-smorest | flaky | collect-failed | flask_smorest/utils.py:6: in <module> from flask import _app_ctx_stack E ImportError: cannot import name '_app_ctx_stack' from 'flask' (/tmp/work/venvs/idoft-flask-smorest/lib/python3.10/site-packages/flask/__init__.py)  |
| idoft-pyradigm | flaky | collect-failed | se `np.nan` instead. !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 5 errors during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! no tests collected, 5 errors in 0.18s  |
| idoft-mythx-cli | flaky | collect-failed | ests/test_version.py !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 8 errors during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 67 tests collected, 8 errors in 0.34s  |
| idoft-flask-jwt-router | flaky | collect-failed | ests/test_routing.py !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 5 errors during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! no tests collected, 5 errors in 0.06s  |
| idoft-config-better | flaky | install-failed | y:318: UserWarning: Unknown distribution option: 'test_suite' warnings.warn(msg) error in config-better setup command: 'python_requires' must be a string containing valid version specifiers; Invalid specifier: '>=3.0.*'  |
| idoft-saga | flaky | install-failed | aga-vcs setup command: 'install_requires' must be a string or iterable of strings containing valid project/version requirement specifiers; Expected semicolon (after name with no version specifier) or end requests>-2.2 ^  |
| idoft-fooof | flaky | collect-failed | named 'pkg_resources' !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! no tests collected, 1 error in 0.28s  |
| idoft-cloud-validation-framework | flaky | install-failed | .25 depends on pytest==4.0.1, we can conclude that all versions of prancer-basic depend on pytest==4.0.1. And because you require pytest>=7,<8 and prancer-basic, we can conclude that your requirements are unsatisfiable.  |
| idoft-h5nav | flaky | collect-failed | ROR tests/test_cli.py !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! no tests collected, 1 error in 0.14s  |
| idoft-dynamic-conf | flaky | install-failed | t call last): File "<string>", line 11, in <module> AttributeError: module 'poetry.masonry.api' has no attribute 'build_editable' hint: Build failures usually indicate a problem with the package or the build environment  |
| idoft-qer | flaky | collect-failed | ger.hook.pytest_cmdline_parse( ImportError while loading conftest '/tmp/work/src/idoft-qer/tests/conftest.py'. tests/conftest.py:6: in <module> import pkg_resources E ModuleNotFoundError: No module named 'pkg_resources'  |
| idoft-req-compile | flaky | collect-failed | .pytest_cmdline_parse( ImportError while loading conftest '/tmp/work/src/idoft-req-compile/tests/conftest.py'. tests/conftest.py:6: in <module> import pkg_resources E ModuleNotFoundError: No module named 'pkg_resources'  |
| idoft-knack | flaky | collect-failed | tests/test_query.py !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 4 errors during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 179 tests collected, 4 errors in 0.11s  |
| idoft-plcx | flaky | install-failed | ailable and plcx==0.8 depends on pytest==5.2.2, we can conclude that all versions of plcx depend on pytest==5.2.2. And because you require pytest>=7,<8 and plcx, we can conclude that your requirements are unsatisfiable.  |
| idoft-pyswarms | flaky | collect-failed | o module named 'yaml' !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! no tests collected, 1 error in 0.21s  |
| idoft-securenative-python | flaky | collect-failed | _http_client_test.py !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 4 errors during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 26 tests collected, 4 errors in 0.14s  |
| idoft-aud | flaky | install-failed | lib/python3.10/site-packages/setuptools/build_meta.py", line 317, in run_setup exec(code, locals()) # noqa: S102 # exec is intentional here File "<string>", line 4, in <module> ModuleNotFoundError: No module named 'm2r'  |
| idoft-flask-sqlalchemy-booster | flaky | collect-failed | lalchemy/__init__.py) !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! no tests collected, 1 error in 0.19s  |
| pyparsing | popular | collect-failed | sts/test_diagram.py !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 2174 tests collected, 1 error in 0.42s  |
| tqdm | popular | too-slow | first baseline run took 600s |
| loguru | popular | collect-failed | markup_extended.py !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 1495 tests collected, 2 errors in 0.36s  |
| markdown | popular | collect-failed | test_md_in_html.py) !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 1355 tests collected, 1 error in 0.29s  |
| tomlkit | popular | collect-failed | ts/files-toml-1.1.0' !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 758 tests collected, 1 error in 0.16s  |
| httpx | popular | too-slow | first baseline run took 600s |
| babel | popular | collect-failed | unknown locale 'en' !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! 1332 tests collected, 1 error in 0.42s  |
| idoft-butter.mas.pythonapi |  | round: no-result | the matrix job produced no summary (job timeout or crash) |

## Reproduction

```bash
gh workflow run harness.yml -f runs=10 -f seeds=20 -f confirm=10
```
Per-test details in `<repo>.csv`, per-run details in `<repo>_runs.csv`; columns in `docs/HARNESS.md`.

## Notes

* The FlaPy dataset (Gruber et al.) is published on Zenodo, which the development environment cannot reach (HTTP 403 from the network proxy): the 'flaky' pool uses the Python section of IDoFT, each project pinned at the commit where its flaky tests were detected.
* Selection: the first 25 candidates per pool (in harness/repos.json and harness/flaky_candidates.json order) that clone, install, collect and finish their first baseline run within 120 s; every rejected candidate is listed above.
