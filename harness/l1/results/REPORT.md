# L1 study: async flaky tests under `--det` and `--det --det-async`

Generated 2026-11-16 17:25 UTC. Per project: 10 baseline / --det / --det --det-async (seed 0) runs of the corpus tests, interleaved, serial, fixed collection order; exploration with --det-async-seed=1..20 (test order fixed); 10/10 confirmation of the first failing seed; 3 timed runs of the full suite per mode.

Run: https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43916381636

## Projects

| project | source | status | python | commit | corpus tests |
|---|---|---|---|---|---|
| anyio | 25+25 round (popular pool, run 43892303433) | ok  | 3.13 | 9df02f0b8362 | 17 |
| idoft-aiopylimit | IDoFT (asyncio,asynctest) | collect-failed (collect with python 3.9: ad
    def acquire(self):

-- Docs: https://docs.pytest) |  | b4075a8ac30d | 0 |
| idoft-aiotasks | IDoFT (asyncio) | install-failed (install with python 3.9: ild backend returned an error
  cause: Call to `setupto) |  | ec485c84db55 | 0 |
| idoft-easypy | 25+25 round (IDoFT pool) + IDoFT | ok  | 3.9 | 9501c3ee03dc | 2 |
| idoft-plcx | IDoFT (asyncio) | install-failed (install with python 3.9: error: No solution found when resolving dependencies
  ) |  | 2756c0ba78c4 | 0 |
| idoft-pyps4-2ndscreen | IDoFT (asyncio,asynctest) | install-failed (install with python 3.9: 2ndscreen/pyps4_2ndscreen/ps4.py", line 8, in <module>
) |  | 457dc9c3f040 | 0 |
| idoft-python-dugong | IDoFT (asyncio) | ok  | 3.10 | 00dd4d5aab6e | 1 |
| idoft-tornado-swirl | IDoFT (tornado) | ok  | 3.10 | b8df27efc3d7 | 2 |
| idoft-webssh | IDoFT (tornado) | collect-failed (collect with python 3.9: d 'six'
===============================================) |  | 51d527fe75a6 | 0 |
| l1-repro | minimal reproductions (this study) | ok  | 3.13 | local | 14 |

## All corpus tests (uvloop parametrisations excluded)

* tests: 29; flaky in the baseline: 0
* `--det` only: stable outcome 27/29; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 29/29
* reproduced with a seed (10/10) and passing with another: 9/29; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 12

## uvloop parametrisations (not covered by the prototype: uvloop is not a BaseEventLoop)

* tests: 7; flaky in the baseline: 0
* `--det` only: stable outcome 7/7; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 7/7
* reproduced with a seed (10/10) and passing with another: 0/7; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 0

## Project anyio

* tests: 10; flaky in the baseline: 0
* `--det` only: stable outcome 10/10; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 10/10
* reproduced with a seed (10/10) and passing with another: 0/10; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 9

## Project idoft-easypy

* tests: 2; flaky in the baseline: 0
* `--det` only: stable outcome 2/2; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 2/2
* reproduced with a seed (10/10) and passing with another: 0/2; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 0

## Project idoft-python-dugong

* tests: 1; flaky in the baseline: 0
* `--det` only: stable outcome 1/1; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 1/1
* reproduced with a seed (10/10) and passing with another: 0/1; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 0

## Project idoft-tornado-swirl

* tests: 2; flaky in the baseline: 0
* `--det` only: stable outcome 2/2; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 2/2
* reproduced with a seed (10/10) and passing with another: 0/2; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 2

## Project l1-repro

* tests: 14; flaky in the baseline: 0
* `--det` only: stable outcome 12/14; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 14/14
* reproduced with a seed (10/10) and passing with another: 9/14; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 1

## Per test

| project | test | cat. | baseline | --det | calm | explore (20 seeds) | repro seed | confirm | passing seed | fingerprint |
|---|---|---|---|---|---|---|---|---|---|---|
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_alpn_negotiation[asyncio+uvloop]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_alpn_negotiation[asyncio]` | round-flaky | passed=10 | passed=10 | failed+teardown-error=10 | failed+teardown-error=20 | 1 | 10/10 |  | stable |
| anyio | `ests/streams/test_tls.py::TestTLSStream::test_cancelled_send_breaks_stream[asyncio+uvloop]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_ragged_eof_on_receive[asyncio+eager]` | round-flaky | passed=10 | passed=10 | failed+teardown-error=10 | failed+teardown-error=20 | 1 | 10/10 |  | stable |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_ragged_eofs[asyncio+uvloop-server_standard]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_ragged_eofs[asyncio-neither_standard]` | round-flaky | passed=10 | passed=10 | failed+teardown-error=10 | failed+teardown-error=20 | 1 | 10/10 |  | stable |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_receive_invalid_max_bytes[asyncio+uvloop-0]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `ts/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio+eager-tlsv12]` | round-flaky | passed=10 | passed=10 | failed+teardown-error=10 | failed=1;failed+teardown-error=19 | 1 | 10/10 |  | stable |
| anyio | `ts/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio+eager-tlsv13]` | round-flaky | passed=10 | passed=10 | failed+teardown-error=10 | error=1;failed+teardown-error=19 | 1 | 10/10 |  | stable |
| anyio | `s/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio+uvloop-tlsv12]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `s/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio+uvloop-tlsv13]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio-tlsv12]` | round-flaky | passed=10 | passed=10 | failed+teardown-error=10 | failed+teardown-error=20 | 1 | 10/10 |  | stable |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio-tlsv13]` | round-flaky | passed=10 | passed=10 | failed+teardown-error=10 | failed+teardown-error=20 | 1 | 10/10 |  | stable |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_send_receive[asyncio+eager]` | round-flaky | passed=10 | passed=10 | failed+teardown-error=10 | failed+teardown-error=20 | 1 | 10/10 |  | stable |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_unicode_hostname_idna2008[asyncio+eager]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `st_sockets.py::TestTCPStream::test_unretrieved_future_exception_server_crash[ipv6-asyncio]` | round-flaky | passed=10 | passed=10 | failed=10 | failed=20 | 1 | 10/10 |  | stable |
| anyio | `tests/test_taskgroups.py::test_host_exception[asyncio+uvloop]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-easypy | `tests/test_signals.py::test_async` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-easypy | `tests/test_signals.py::test_priorities_async` | round-flaky | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-python-dugong | `test/test_aio.py::test_aio_future` | NIO | missing=10 | missing=10 | missing=10 | missing=20 |  |  |  |  |
| idoft-tornado-swirl | `tests/test_swirl.py::TestSampleEndpoints::test_security_scheme1` | OD-Brit | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | stable |
| idoft-tornado-swirl | `tests/test_swirl.py::TestSampleEndpoints::test_security_scheme2` | OD-Brit | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | stable |
| l1-repro | `tests/test_races.py::test_sleep_as_sync_with_executor` | repro | passed=10 | failed=9;passed=1 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_tight_timeout_on_thread` | repro | failed=10 | failed=10 | passed=10 | failed=9;passed=11 | 4 | 10/10 | 1 | stable |
| l1-repro | `tests/test_races.py::test_executor_results_in_submission_order` | repro | passed=10 | passed=10 | passed=10 | failed=16;passed=4 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_as_completed_first_is_first_submitted` | repro | passed=10 | passed=10 | passed=10 | failed=12;passed=8 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_thread_signal_before_timeout` | repro | passed=10 | passed=10 | passed=10 | failed=1;passed=19 | 15 | 10/10 | 1 | stable |
| l1-repro | `tests/test_races.py::test_server_sees_clients_in_order` | repro | passed=10 | failed=3;passed=7 | passed=10 | failed=9;passed=11 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_cancel_before_job_finishes` | repro | failed=10 | failed=10 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_first_completed_job_beats_timer` | repro | passed=10 | passed=10 | passed=10 | failed=13;passed=7 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_subprocess_answers_quickly` | repro | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_queue_fed_by_thread` | repro | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_rate_limiter_window` | repro | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | stable |
| l1-repro | `tests/test_races.py::test_ordered_appends_after_work` | repro | passed=10 | passed=10 | passed=10 | failed=10;passed=10 | 1 | 10/10 | 3 | stable |
| l1-repro | `tests/test_races.py::test_readers_see_writes_in_order` | repro | passed=10 | passed=10 | passed=10 | failed=11;passed=9 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_lock_order_with_thread_work` | repro | passed=10 | passed=10 | passed=10 | failed=10;passed=10 | 1 | 10/10 | 3 | stable |

## Slowdown on the full suites (serial)

Medians of the runs; `--det` vs `--det --det-async` (calm) vs `--det --det-async --det-async-seed=1`. MEASURED on GitHub-hosted runners, one dedicated job per project (shared cloud hardware: NOISY for small differences).

| project | runs | --det s | --det-async s | slowdown | seed 1 s | slowdown | outcomes (run 0) |
|---|---|---|---|---|---|---|---|
| idoft-easypy | 3 | 11.64 | 11.62 | -0.2% | 11.6 | -0.3% | {"det": {"passed": 163, "failed": 48, "error": 1}, "det-async": {"passed": 163, "failed": 48, "error": 1}, "det-async-s1": {"passed": 163, "failed": 48, "error": 1}} |
| idoft-python-dugong | 3 | 44.84 | 44.85 | 0.0% | 44.86 | 0.1% | {"det": {"error": 118}, "det-async": {"error": 118}, "det-async-s1": {"error": 118}} |
| idoft-tornado-swirl | 3 | 0.78 | 0.79 | 1.7% | 0.79 | 1.7% | {"det": {"passed": 43}, "det-async": {"passed": 43}, "det-async-s1": {"passed": 43}} |
| l1-repro | 3 | 0.72 | 0.73 | 0.8% | 0.75 | 3.6% | {"det": {"failed": 5, "passed": 9}, "det-async": {"passed": 12, "failed": 2}, "det-async-s1": {"passed": 6, "failed": 8}} |
