# detpy Level 0: measurement report (`mixed, with the 11 repositories affected by L0 bugs re-measured after the fixes (runs 43919160305, 43931114732)`)

Generated 2026-11-16 16:34 UTC with detpy 0.1.0. Per repository: 10 baseline runs (random order from pytest-randomly with a different seed per run, pytest-xdist `-n 2` where the suite supports it) interleaved with 10 `--det` runs (fixed order, serial); then, for every test unstable in the baseline, exploration with `--det-seed=1..20` and 10/10 confirmation of the seed that makes it fail. Executor: GitHub Actions matrix, one repository per ubuntu-latest runner (run https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43892303433). Labels: MEASURED (by this harness), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host.

## Main metric

**Baseline-unstable tests made reproducible: 358/388 = 92.3%** (MEASURED). Tests whose id changes between runs (ids built from time or random values: 18) are not flaky tests and are excluded; including them the figure was 358/406. A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass; a test that fails under every `--det` configuration is broken by Level 0, not reproduced.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IDoFT dataset | 24 | 2568 | 362 | 342 | 94.5% | 14 | 5 | 1 |
| popular | 25 | 117084 | 26 | 16 | 61.5% | 10 | 0 | 0 |
| total | 49 | 119652 | 388 | 358 | 92.3% | 24 | 5 | 1 |

Tests with unstable ids (excluded above, MEASURED): 18 — marshmallow: 18.

**Reproduced share by IDoFT category** (MEASURED). Most IDoFT flaky tests are order-dependent and were found by order shuffling, so reproducing them with a seeded order is the easy part; the NOD/NIO rows and the popular pool are the hard part.

| category | unstable in baseline | reproduced | % |
|---|---:|---:|---:|
| NOD | 15 | 10 | 66.7% |
| OD-Brit | 72 | 66 | 91.7% |
| OD-Vic | 269 | 265 | 98.5% |
| not in IDoFT | 6 | 1 | 16.7% |
| popular pool (no IDoFT label) | 26 | 16 | 61.5% |

**Reproduced tests by first diverging source** (passing vs failing `--det` fingerprint, MEASURED): `random` 272 (76.0%), `time` 70 (19.6%), `thread` 6 (1.7%), `entropy` 5 (1.4%), `fs` 5 (1.4%).

**(a, b) Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 0 (fixed order): 68, 1: 82, 2-5: 160, 6-10: 44, 11-20: 4; median 2.

**(c) First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `random` 272, `time` 70, `thread` 6, `entropy` 5, `fs` 5.

## IDoFT known flaky tests (MEASURED)

| known flaky tests (IDoFT, measured projects) | present in the collected suite | flaky in our baseline | reproduced |
|---:|---:|---:|---:|
| 509 | 509 | 356 | 341 |

## Tests that do not run under --det

A test that runs in every baseline run but in no `--det` run is worse than a false failure. **0 tests** (MEASURED). Tests present only under `--det` (an id that differs between modes): 2.

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). These are false failures. **10 tests** (MEASURED), of which 10 fail in every `--det` run.

Cause: `fixed-order` = the test also fails in a serial fixed-order run *without* `--det` (the baseline hides it with random order and xdist: not a Level 0 failure); otherwise the controls whose `--det-disable` makes it pass again (one ablation run per control); `unexplained` = none does.

| cause (controls) &#124; exception | tests | examples |
|---|---:|---|
| `net | ConnectionError` | 4 | requests: tests/test_requests.py::TestTimeout::test_connect_timeout[timeout0]: requests.exceptions.ConnectionError: HTTPConnectionPool(host='10.255.255.1', port=80): Max retries exceeded with url: / (Caused by NewConnec (first diverging source: -)<br>requests: tests/test_requests.py::TestTimeout::test_connect_timeout[timeout1]: requests.exceptions.ConnectionError: HTTPConnectionPool(host='10.255.255.1', port=80): Max retries exceeded with url: / (Caused by NewConnec (first diverging source: -) |
| `time | AssertionError` | 2 | idoft-pymq: tests/test_provider_ipc.py::IpcQueueTest::test_queue_get_blocking_timeout: AssertionError: 1 != 9.5367431640625e-07 within 0.3 delta (0.9999990463256836 difference) (first diverging source: -)<br>idoft-pymq: tests/test_provider_redis.py::RedisQueueTest::test_queue_get_blocking_timeout: AssertionError: 1 != 9.5367431640625e-07 within 0.3 delta (0.9999990463256836 difference) (first diverging source: -) |
| `net | gaierror` | 2 | anyio: tests/test_sockets.py::test_getaddrinfo[asyncio+eager]: socket.gaierror: [Errno -2] detpy: DNS lookup of 'xn--fa-hia.de' blocked (Level 0 closes the network) (first diverging source: -)<br>anyio: tests/test_sockets.py::test_getaddrinfo[asyncio]: socket.gaierror: [Errno -2] detpy: DNS lookup of 'xn--fa-hia.de' blocked (Level 0 closes the network) (first diverging source: -) |
| `fixed-order (fails without --det too) | RecursionError` | 1 | idoft-easypy: tests/test_sync.py::test_logged_condition_exception: RecursionError: maximum recursion depth exceeded (first diverging source: time) |
| `fixed-order (fails without --det too) | AssertionError` | 1 | idoft-coinbase-commerce-python: tests/api_resources/base/test_list_api_resource.py::TestListAPIResource::test_list: AssertionError: False is not true (first diverging source: random) |

## Timing

Quiet timing pass: 10 repositories, one per GitHub-hosted runner, one repository per runner, 3 serial fixed-order normal runs vs 3 `--det` runs interleaved on the same machine; median per repository. Every ratio compares two runs on the same runner, but the runners differ: 4 CPU models — AMD EPYC 7763 64-Core Processor (5 repositories); AMD EPYC 9V74 80-Core Processor (2 repositories); AMD EPYC 9V45 96-Core Processor (2 repositories); INTEL(R) XEON(R) PLATINUM 8573C (1 repository); 4 vCPUs, ubuntu26 20261111.196.1. Labelled **DECLARED-NOISY**: hosted runners are virtual machines on shared hardware.

**Slowdown of `--det` (MEASURED, DECLARED-NOISY): median 25.0%**, min -5.7%, max 202.1%.

* Without the suites that run in under 1 s (idoft-centreon-sdk-python, idoft-crom): median 16.3% over 8 repositories (MEASURED, DECLARED-NOISY).
* Absolute extra time of `--det` per suite run: median 1.72 s (MEASURED, DECLARED-NOISY). Fixed start-up cost: not measured in this pass (UNKNOWN).

| repo | tests | runner CPU | normal serial s (median) | --det s (median) | slowdown % | start-up cost s | precompile s (per run) |
|---|---:|---|---:|---:|---:|---:|---|
| attrs | 1412 | AMD EPYC 9V74 80-Core Processor | 7.56 | 9.61 | 27.1 | n/a | 6.33, 0.31, 0.31 |
| idoft-centreon-sdk-python | 44 | INTEL(R) XEON(R) PLATINUM 8573C | 0.41 | 1.10 | 171.8 | n/a | 1.48, 0.48, 0.49 |
| idoft-cloudnetpy | 439 | AMD EPYC 9V74 80-Core Processor | 6.97 | 7.24 | 3.8 | n/a | 2.93, 0.86, 0.84 |
| idoft-crom | 84 | AMD EPYC 7763 64-Core Processor | 0.38 | 1.14 | 202.1 | n/a | 1.42, 0.52, 0.51 |
| idoft-easypy | 212 | AMD EPYC 9V45 96-Core Processor | 11.04 | 10.42 | -5.7 | n/a | 0.81, 0.22, 0.21 |
| idoft-eppy | 218 | AMD EPYC 7763 64-Core Processor | 6.88 | 8.46 | 22.9 | n/a | 1.95, 0.80, 0.76 |
| networkx | 10191 | AMD EPYC 9V45 96-Core Processor | 82.58 | 89.88 | 8.8 | n/a | 7.20, 0.36, 0.35 |
| pygments | 5346 | AMD EPYC 7763 64-Core Processor | 19.14 | 21.02 | 9.8 | n/a | 6.84, 0.63, 0.58 |
| rich | 981 | AMD EPYC 7763 64-Core Processor | 5.64 | 7.59 | 34.7 | n/a | 8.66, 0.57, 0.57 |
| werkzeug | 1016 | AMD EPYC 7763 64-Core Processor | 10.30 | 21.52 | 108.9 | n/a | 7.96, 0.48, 0.47 |

* Round timings, serial `--det` vs the random-order xdist `-n 2` baseline: median 82.4% — **NOT COMPARABLE** (different parallelism and order; reported only for completeness).
* Deterministic bytecode precompilation, first `--det` run of each repository: median 5.37 s, max 15.69 s; later runs (incremental check): median 0.41 s (MEASURED, NOISY).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 0; unstable in the baseline and stable under `--det`: 406
* stable in both modes but with a different majority outcome: 26
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 118964 (99.4%); not covered: 670 (`time` 293, `entropy` 218, `thread` 147, `fs` 12)

## Per repository (MEASURED)

| repo | pool | py | xdist | tests | unstable | reproduced | seeds explored | broken by det | not covered | IDoFT present / flaky / reproduced |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [idoft-eppy](https://github.com/santoshphilip/eppy) | flaky | 3.9 | yes | 218 | 67 | 66 | 20 | 0 | 0 | 87 / 66 / 66 |
| [idoft-cloudnetpy](https://github.com/tukiains/cloudnetpy) | flaky | 3.9 | yes | 439 | 27 | 27 | 5 | 0 | 1 | 52 / 27 / 27 |
| [idoft-easypy](https://github.com/weka-io/easypy) | flaky | 3.9 | yes | 212 | 44 | 43 | 20 | 1 | 29 | 44 / 44 / 43 |
| [idoft-centreon-sdk-python](https://github.com/guillaumewatteeux/centreon-sdk-python) | flaky | 3.9 | yes | 44 | 41 | 36 | 20 | 0 | 0 | 41 / 41 / 36 |
| [idoft-crom](https://github.com/thegetty/crom) | flaky | 3.9 | yes | 84 | 13 | 11 | 20 | 0 | 21 | 38 / 13 / 11 |
| [idoft-pykicad](https://github.com/dvc94ch/pykicad) | flaky | 3.9 | yes | 48 | 28 | 28 | 2 | 0 | 0 | 28 / 28 / 28 |
| [idoft-flask-multi-redis](https://github.com/max-k/flask-multi-redis) | flaky | 3.9 | yes | 33 | 14 | 14 | 3 | 0 | 0 | 26 / 14 / 14 |
| [idoft-pymq](https://github.com/thrau/pymq) | flaky | 3.9 | yes | 127 | 1 | 0 | 20 | 2 | 47 | 20 / 1 / 0 |
| [idoft-py-autodoc](https://github.com/heavenshell/py-autodoc) | flaky | 3.9 | yes | 27 | 15 | 15 | 15 | 0 | 1 | 15 / 15 / 15 |
| [idoft-freezegun](https://github.com/spulec/freezegun) | flaky | 3.9 | yes | 112 | 8 | 7 | 20 | 0 | 0 | 15 / 6 / 6 |
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
| [idoft-coinbase-commerce-python](https://github.com/coinbase/coinbase-commerce-python) | flaky | 3.9 | yes | 79 | 8 | 8 | 2 | 1 | 0 | 8 / 8 / 8 |
| [idoft-ljson](https://github.com/daknuett/ljson) | flaky | 3.9 | yes | 33 | 4 | 4 | 3 | 0 | 0 | 8 / 4 / 4 |
| [idoft-mdutils](https://github.com/didix21/mdutils) | flaky | 3.9 | yes | 102 | 8 | 8 | 1 | 0 | 0 | 8 / 8 / 8 |
| [pygments](https://github.com/pygments/pygments) | popular | 3.13 | yes | 5346 | 0 | 0 | 0 | 0 | 0 |  |
| [networkx](https://github.com/networkx/networkx) | popular | 3.13 | yes | 10191 | 0 | 0 | 0 | 0 | 62 |  |
| [attrs](https://github.com/python-attrs/attrs) | popular | 3.13 | yes | 1412 | 0 | 0 | 0 | 0 | 1 |  |
| [rich](https://github.com/Textualize/rich) | popular | 3.13 | yes | 981 | 5 | 5 | 1 | 0 | 0 |  |
| [werkzeug](https://github.com/pallets/werkzeug) | popular | 3.13 | yes | 1016 | 0 | 0 | 0 | 0 | 33 |  |
| [flask](https://github.com/pallets/flask) | popular | 3.13 | yes | 494 | 0 | 0 | 0 | 0 | 1 |  |
| [click](https://github.com/pallets/click) | popular | 3.13 | yes | 2651 | 0 | 0 | 0 | 0 | 3 |  |
| [jinja](https://github.com/pallets/jinja) | popular | 3.13 | yes | 911 | 0 | 0 | 0 | 0 | 0 |  |
| [requests](https://github.com/psf/requests) | popular | 3.13 | yes | 635 | 0 | 0 | 0 | 4 | 120 |  |
| [faker](https://github.com/joke2k/faker) | popular | 3.13 | yes | 2470 | 0 | 0 | 0 | 0 | 0 |  |
| [marshmallow](https://github.com/marshmallow-code/marshmallow) | popular | 3.13 | yes | 1210 | 18 | 0 | 20 | 0 | 1 |  |
| [arrow](https://github.com/arrow-py/arrow) | popular | 3.13 | yes | 1904 | 2 | 2 | 2 | 0 | 0 |  |
| [dateutil](https://github.com/dateutil/dateutil) | popular | 3.13 | yes | 5344 | 0 | 0 | 0 | 0 | 0 |  |
| [more-itertools](https://github.com/more-itertools/more-itertools) | popular | 3.13 | yes | 771 | 0 | 0 | 0 | 0 | 1 |  |
| [boltons](https://github.com/mahmoud/boltons) | popular | 3.13 | yes | 621 | 0 | 0 | 0 | 0 | 5 |  |
| [toolz](https://github.com/pytoolz/toolz) | popular | 3.13 | yes | 193 | 0 | 0 | 0 | 0 | 0 |  |
| [sortedcontainers](https://github.com/grantjenks/python-sortedcontainers) | popular | 3.13 | yes | 366 | 0 | 0 | 0 | 0 | 0 |  |
| [packaging](https://github.com/pypa/packaging) | popular | 3.13 | yes | 63798 | 1 | 1 | 10 | 0 | 0 |  |
| [structlog](https://github.com/hynek/structlog) | popular | 3.13 | yes | 921 | 0 | 0 | 0 | 0 | 19 |  |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | popular | 3.13 | yes | 8529 | 2 | 2 | 2 | 0 | 0 |  |
| [sqlparse](https://github.com/andialbrecht/sqlparse) | popular | 3.13 | yes | 540 | 0 | 0 | 0 | 0 | 0 |  |
| [anyio](https://github.com/agronholm/anyio) | popular | 3.13 | yes | 4852 | 16 | 6 | 3 (budget) | 2 | 285 |  |
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
