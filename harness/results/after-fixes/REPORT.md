# detpy Level 0: measurement report (`after-fixes`)

Generated 2026-11-16 18:27 UTC with detpy 0.1.0. Per repository: 10 baseline runs (random order from pytest-randomly with a different seed per run, pytest-xdist `-n 2` where the suite supports it) interleaved with 10 `--det` runs (fixed order, serial); then, for every test unstable in the baseline, exploration with `--det-seed=1..20` and 10/10 confirmation of the seed that makes it fail. Executor: GitHub Actions matrix, one repository per ubuntu-latest runner (run https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43919160305). Labels: MEASURED (by this harness), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host.

## Main metric

**Baseline-unstable tests made reproducible: 50/82 = 61.0%** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass; a test that fails under every `--det` configuration is broken by Level 0, not reproduced.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IDoFT dataset | 4 | 530 | 61 | 39 | 63.9% | 1 | 20 | 1 |
| popular | 7 | 20671 | 21 | 11 | 52.4% | 10 | 0 | 0 |
| total | 11 | 21201 | 82 | 50 | 61.0% | 11 | 20 | 1 |

**(a, b) Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 0 (fixed order): 29, 1: 6, 2-5: 10, 6-10: 5; median 0.

**(c) First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `time` 30, `random` 20.

## IDoFT known flaky tests (MEASURED)

| known flaky tests (IDoFT, measured projects) | present in the collected suite | flaky in our baseline | reproduced |
|---:|---:|---:|---:|
| 87 | 87 | 59 | 38 |

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). These are false failures. **11 tests** (MEASURED), of which 11 fail in every `--det` run.

Cause: `fixed-order` = the test also fails in a serial fixed-order run *without* `--det` (the baseline hides it with random order and xdist: not a Level 0 failure); otherwise the controls whose `--det-disable` makes it pass again (one ablation run per control); `unexplained` = none does.

| cause (controls) &#124; exception | tests | examples |
|---|---:|---|
| `net | ConnectionError` | 4 | requests: tests/test_requests.py::TestTimeout::test_connect_timeout[timeout0]: requests.exceptions.ConnectionError: HTTPConnectionPool(host='10.255.255.1', port=80): Max retries exceeded with url: / (Caused by NewConnec (first diverging source: -)<br>requests: tests/test_requests.py::TestTimeout::test_connect_timeout[timeout1]: requests.exceptions.ConnectionError: HTTPConnectionPool(host='10.255.255.1', port=80): Max retries exceeded with url: / (Caused by NewConnec (first diverging source: -) |
| `time | AssertionError` | 2 | idoft-pymq: tests/test_provider_ipc.py::IpcQueueTest::test_queue_get_blocking_timeout: AssertionError: 1 != 9.5367431640625e-07 within 0.3 delta (0.9999990463256836 difference) (first diverging source: -)<br>idoft-pymq: tests/test_provider_redis.py::RedisQueueTest::test_queue_get_blocking_timeout: AssertionError: 1 != 9.5367431640625e-07 within 0.3 delta (0.9999990463256836 difference) (first diverging source: -) |
| `fixed-order (fails without --det too) | RecursionError` | 2 | idoft-easypy: tests/test_sync.py::test_logged_condition_exception: RecursionError: maximum recursion depth exceeded (first diverging source: -)<br>idoft-easypy: tests/test_sync.py::test_logged_condition_waited_for: RecursionError: maximum recursion depth exceeded (first diverging source: -) |
| `net | gaierror` | 2 | anyio: tests/test_sockets.py::test_getaddrinfo[asyncio+eager]: socket.gaierror: [Errno -2] detpy: DNS lookup of 'xn--fa-hia.de' blocked (Level 0 closes the network) (first diverging source: -)<br>anyio: tests/test_sockets.py::test_getaddrinfo[asyncio]: socket.gaierror: [Errno -2] detpy: DNS lookup of 'xn--fa-hia.de' blocked (Level 0 closes the network) (first diverging source: -) |
| `fixed-order (fails without --det too) | AssertionError` | 1 | idoft-coinbase-commerce-python: tests/api_resources/base/test_list_api_resource.py::TestListAPIResource::test_list: AssertionError: False is not true (first diverging source: random) |

## Timing

Quiet timing pass: not run yet (UNKNOWN).

* Round timings, serial `--det` vs the random-order xdist `-n 2` baseline: median 86.4% — **NOT COMPARABLE** (different parallelism and order; reported only for completeness).
* Deterministic bytecode precompilation, first `--det` run of each repository: median 7.00 s, max 10.90 s; later runs (incremental check): median 0.44 s (MEASURED, NOISY).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 0; unstable in the baseline and stable under `--det`: 82
* stable in both modes but with a different majority outcome: 18
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 20634 (97.3%); not covered: 567 (`time` 268, `entropy` 148, `thread` 142, `fs` 9)

## Per repository (MEASURED)

| repo | pool | py | xdist | tests | unstable | reproduced | seeds explored | broken by det | not covered | IDoFT present / flaky / reproduced |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [idoft-pymq](https://github.com/thrau/pymq) | flaky | 3.9 | yes | 127 | 1 | 0 | 20 | 2 | 47 | 20 / 1 / 0 |
| [idoft-coinbase-commerce-python](https://github.com/coinbase/coinbase-commerce-python) | flaky | 3.9 | yes | 79 | 8 | 8 | 2 | 1 | 0 | 8 / 8 / 8 |
| [idoft-easypy](https://github.com/weka-io/easypy) | flaky | 3.9 | yes | 212 | 44 | 24 | 2 | 2 | 29 | 44 / 44 / 24 |
| [idoft-freezegun](https://github.com/spulec/freezegun) | flaky | 3.9 | yes | 112 | 8 | 7 | 20 | 0 | 0 | 15 / 6 / 6 |
| [structlog](https://github.com/hynek/structlog) | popular | 3.13 | yes | 921 | 0 | 0 | 0 | 0 | 19 |  |
| [anyio](https://github.com/agronholm/anyio) | popular | 3.13 | yes | 4852 | 16 | 6 | 3 (budget) | 2 | 285 |  |
| [requests](https://github.com/psf/requests) | popular | 3.13 | yes | 635 | 0 | 0 | 0 | 4 | 120 |  |
| [networkx](https://github.com/networkx/networkx) | popular | 3.13 | yes | 10191 | 0 | 0 | 0 | 0 | 62 |  |
| [rich](https://github.com/Textualize/rich) | popular | 3.13 | yes | 981 | 5 | 5 | 1 | 0 | 0 |  |
| [faker](https://github.com/joke2k/faker) | popular | 3.13 | yes | 2470 | 0 | 0 | 0 | 0 | 0 |  |
| [boltons](https://github.com/mahmoud/boltons) | popular | 3.13 | yes | 621 | 0 | 0 | 0 | 0 | 5 |  |

## Reproduction

```bash
gh workflow run harness.yml -f runs=10 -f seeds=20 -f confirm=10
```
Per-test details in `<repo>.csv`, per-run details in `<repo>_runs.csv`; columns in `docs/HARNESS.md`.

## Notes

* The FlaPy dataset (Gruber et al.) is published on Zenodo, which the development environment cannot reach (HTTP 403 from the network proxy): the 'flaky' pool uses the Python section of IDoFT, each project pinned at the commit where its flaky tests were detected.
* Selection: the first 25 candidates per pool (in harness/repos.json and harness/flaky_candidates.json order) that clone, install, collect and finish their first baseline run within 120 s; every rejected candidate is listed above.
