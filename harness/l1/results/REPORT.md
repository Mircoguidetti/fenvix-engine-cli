# L1 study: async flaky tests under `--det` and `--det --det-async`

Generated 2026-11-16 18:39 UTC. Per project: 10 baseline / --det / --det --det-async (seed 0) runs of the corpus tests, interleaved, serial, fixed collection order; exploration with --det-async-seed=1..20 (test order fixed); 10/10 confirmation of the first failing seed; 3 timed runs of the full suite per mode.

Run: https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43925910072

## Projects

| project | source | status | python | commit | corpus tests |
|---|---|---|---|---|---|
| anyio | 25+25 round (popular pool, run 43892303433) | ok  | 3.13 | 9df02f0b8362 | 17 |
| idoft-aiopylimit | IDoFT (asyncio,asynctest) | collect-failed (collect with python 3.10: ad
    def acquire(self):

-- Docs: https://docs.pytes) |  | b4075a8ac30d | 0 |
| idoft-aiotasks | IDoFT (asyncio) | install-failed (install with python 3.10: ild backend returned an error
  cause: Call to `setupt) |  | ec485c84db55 | 0 |
| idoft-easypy | 25+25 round (IDoFT pool) + IDoFT | ok  | 3.9 | 9501c3ee03dc | 2 |
| idoft-plcx | IDoFT (asyncio) | install-failed (install with python 3.10: error: No solution found when resolving dependencies
 ) |  | 2756c0ba78c4 | 0 |
| idoft-pyps4-2ndscreen | IDoFT (asyncio,asynctest) | install-failed (install with python 3.10: 2ndscreen/pyps4_2ndscreen/ps4.py", line 8, in <module>) |  | 457dc9c3f040 | 0 |
| idoft-python-dugong | IDoFT (asyncio) | ok  | 3.10 | 00dd4d5aab6e | 1 |
| idoft-tornado-swirl | IDoFT (tornado) | ok  | 3.10 | b8df27efc3d7 | 2 |
| idoft-webssh | IDoFT (tornado) | ok  | 3.10 | 51d527fe75a6 | 29 |
| l1-repro | minimal reproductions (this study) | ok  | 3.13 | local | 14 |

## All corpus tests (uvloop parametrisations excluded)

* tests: 58; flaky in the baseline (quiet or CPU-loaded runs, or different between the two): 8 (quiet only: 2, loaded only: 6)
* `--det --det-async` (calm) under CPU load: same outcome in every loaded run 55/58
* `--det` only: stable outcome 53/58; of the baseline-flaky ones 7/8
* `--det --det-async` (calm, seed 0): stable outcome 56/58
* reproduced with a seed (10/10) and passing with another: 8/58; of the baseline-flaky ones 4/8
* failing with every explored seed (possible false failures or always-failing): 16

## uvloop parametrisations (not covered by the prototype: uvloop is not a BaseEventLoop)

* tests: 7; flaky in the baseline (quiet or CPU-loaded runs, or different between the two): 0 (quiet only: 0, loaded only: 0)
* `--det --det-async` (calm) under CPU load: same outcome in every loaded run 7/7
* `--det` only: stable outcome 7/7; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 7/7
* reproduced with a seed (10/10) and passing with another: 0/7; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 0

## Project anyio

* tests: 10; flaky in the baseline (quiet or CPU-loaded runs, or different between the two): 0 (quiet only: 0, loaded only: 0)
* `--det --det-async` (calm) under CPU load: same outcome in every loaded run 10/10
* `--det` only: stable outcome 10/10; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 10/10
* reproduced with a seed (10/10) and passing with another: 0/10; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 0

## Project idoft-easypy

* tests: 2; flaky in the baseline (quiet or CPU-loaded runs, or different between the two): 0 (quiet only: 0, loaded only: 0)
* `--det --det-async` (calm) under CPU load: same outcome in every loaded run 2/2
* `--det` only: stable outcome 2/2; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 2/2
* reproduced with a seed (10/10) and passing with another: 0/2; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 0

## Project idoft-python-dugong

* tests: 1; flaky in the baseline (quiet or CPU-loaded runs, or different between the two): 0 (quiet only: 0, loaded only: 0)
* `--det --det-async` (calm) under CPU load: same outcome in every loaded run 1/1
* `--det` only: stable outcome 1/1; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 1/1
* reproduced with a seed (10/10) and passing with another: 0/1; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 0

## Project idoft-tornado-swirl

* tests: 2; flaky in the baseline (quiet or CPU-loaded runs, or different between the two): 0 (quiet only: 0, loaded only: 0)
* `--det --det-async` (calm) under CPU load: same outcome in every loaded run 2/2
* `--det` only: stable outcome 2/2; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 2/2
* reproduced with a seed (10/10) and passing with another: 0/2; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 2

## Project idoft-webssh

* tests: 29; flaky in the baseline (quiet or CPU-loaded runs, or different between the two): 0 (quiet only: 0, loaded only: 0)
* `--det --det-async` (calm) under CPU load: same outcome in every loaded run 27/29
* `--det` only: stable outcome 25/29; of the baseline-flaky ones 0/0
* `--det --det-async` (calm, seed 0): stable outcome 28/29
* reproduced with a seed (10/10) and passing with another: 0/29; of the baseline-flaky ones 0/0
* failing with every explored seed (possible false failures or always-failing): 13

## Project l1-repro

* tests: 14; flaky in the baseline (quiet or CPU-loaded runs, or different between the two): 8 (quiet only: 2, loaded only: 6)
* `--det --det-async` (calm) under CPU load: same outcome in every loaded run 13/14
* `--det` only: stable outcome 13/14; of the baseline-flaky ones 7/8
* `--det --det-async` (calm, seed 0): stable outcome 13/14
* reproduced with a seed (10/10) and passing with another: 8/14; of the baseline-flaky ones 4/8
* failing with every explored seed (possible false failures or always-failing): 1

## Per test

| project | test | cat. | baseline | loaded | --det | calm | calm loaded | explore (20 seeds) | repro seed | confirm | passing seed | fingerprint |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_alpn_negotiation[asyncio+uvloop]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_alpn_negotiation[asyncio]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `ests/streams/test_tls.py::TestTLSStream::test_cancelled_send_breaks_stream[asyncio+uvloop]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_ragged_eof_on_receive[asyncio+eager]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_ragged_eofs[asyncio+uvloop-server_standard]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_ragged_eofs[asyncio-neither_standard]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_receive_invalid_max_bytes[asyncio+uvloop-0]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `ts/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio+eager-tlsv12]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `ts/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio+eager-tlsv13]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `s/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio+uvloop-tlsv12]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `s/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio+uvloop-tlsv13]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio-tlsv12]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio-tlsv13]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_send_receive[asyncio+eager]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/streams/test_tls.py::TestTLSStream::test_unicode_hostname_idna2008[asyncio+eager]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `st_sockets.py::TestTCPStream::test_unretrieved_future_exception_server_crash[ipv6-asyncio]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| anyio | `tests/test_taskgroups.py::test_host_exception[asyncio+uvloop]` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-easypy | `tests/test_signals.py::test_async` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-easypy | `tests/test_signals.py::test_priorities_async` | round-flaky | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-python-dugong | `test/test_aio.py::test_aio_future` | NIO | missing=10 | missing=10 | missing=10 | missing=10 | missing=10 | missing=20 |  |  |  |  |
| idoft-tornado-swirl | `tests/test_swirl.py::TestSampleEndpoints::test_security_scheme1` | OD-Brit | failed=10 | failed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | stable |
| idoft-tornado-swirl | `tests/test_swirl.py::TestSampleEndpoints::test_security_scheme2` | OD-Brit | failed=10 | failed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | stable |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_auth_with_invalid_pubkey_for_user_robey` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `s/test_app.py::TestAppBasic::test_app_auth_with_pubkey_cannot_be_decoded_by_multipart_form` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_auth_with_pubkey_exceeds_key_max_size` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_auth_with_valid_pubkey_by_multipart_form` | NOD | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_auth_with_valid_pubkey_by_urlencoded_form` | OD-Vic | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_post_form_with_large_body_size_by_multipart_form` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `ests/test_app.py::TestAppBasic::test_app_post_form_with_large_body_size_by_urlencoded_form` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials_but_empty_id` | OD-Vic | passed=10 | passed=10 | failed=8;passed=2 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials_but_ip_not_matched` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials_but_without_id_argument` | OD-Vic | passed=10 | passed=10 | failed=6;passed=4 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials_but_with_no_port` | OD-Vic | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials_but_wrong_id` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials_timeout` | OD-Vic | passed=10 | passed=10 | failed=1;passed=9 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials_user_bar` | NOD | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_correct_credentials_user_robey` | OD-Vic | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_invalid_form_for_invalid_value` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_invalid_form_for_missing_argument` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_user_keyonly_for_bad_authentication_type` | OD-Vic | passed=10 | passed=10 | failed=1;passed=9 | failed=3;passed=7 | failed=8;passed=2 | failed=2;passed=18 | 1 | 4/10 | 2 | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_user_pass2fa_with_correct_passwords` | NOD | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `ts/test_app.py::TestAppBasic::test_app_with_user_pass2fa_with_wrong_pkey_correct_passwords` | OD-Vic | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_user_pkey2fa_with_correct_passwords` | NOD | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_user_pkey2fa_with_empty_passcode` | NOD | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_user_pkey2fa_with_wrong_passcode` | NOD | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_user_pkey2fa_with_wrong_password` | NOD | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_wrong_credentials` | OD-Vic | passed=10 | passed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | diverged |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_wrong_hostname_domain` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | failed=1;passed=9 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_wrong_hostname_ip` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| idoft-webssh | `tests/test_app.py::TestAppBasic::test_app_with_wrong_port` | NOD | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_sleep_as_sync_with_executor` | repro | passed=10 | passed=10 | failed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_tight_timeout_on_thread` | repro | failed=4;passed=6 | failed=10 | failed=10 | passed=10 | passed=10 | failed=9;passed=11 | 4 | 10/10 | 1 | stable |
| l1-repro | `tests/test_races.py::test_executor_results_in_submission_order` | repro | passed=10 | failed=5;passed=5 | passed=10 | passed=10 | passed=10 | failed=16;passed=4 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_as_completed_first_is_first_submitted` | repro | passed=10 | failed=6;passed=4 | passed=10 | passed=10 | passed=10 | failed=12;passed=8 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_thread_signal_before_timeout` | repro | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | failed=1;passed=19 | 15 | 10/10 | 1 | stable |
| l1-repro | `tests/test_races.py::test_server_sees_clients_in_order` | repro | failed=6;passed=4 | failed=2;passed=8 | failed=4;passed=6 | failed=3;passed=7 | failed=1;passed=9 | failed=8;passed=12 | 5 | 5/10 | 1 | diverged |
| l1-repro | `tests/test_races.py::test_cancel_before_job_finishes` | repro | failed=10 | passed=10 | failed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_first_completed_job_beats_timer` | repro | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | failed=13;passed=7 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_subprocess_answers_quickly` | repro | passed=10 | failed=9;passed=1 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_queue_fed_by_thread` | repro | passed=10 | failed=5;passed=5 | passed=10 | passed=10 | passed=10 | passed=20 |  |  |  |  |
| l1-repro | `tests/test_races.py::test_rate_limiter_window` | repro | failed=10 | failed=10 | failed=10 | failed=10 | failed=10 | failed=20 | 1 | 10/10 |  | stable |
| l1-repro | `tests/test_races.py::test_ordered_appends_after_work` | repro | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | failed=10;passed=10 | 1 | 10/10 | 3 | stable |
| l1-repro | `tests/test_races.py::test_readers_see_writes_in_order` | repro | passed=10 | passed=10 | passed=10 | passed=10 | passed=10 | failed=11;passed=9 | 1 | 10/10 | 2 | stable |
| l1-repro | `tests/test_races.py::test_lock_order_with_thread_work` | repro | passed=10 | failed=4;passed=6 | passed=10 | passed=10 | passed=10 | failed=10;passed=10 | 1 | 10/10 | 3 | stable |

## Slowdown on the full suites (serial)

Medians of the runs; `--det` vs `--det --det-async` (calm) vs `--det --det-async --det-async-seed=1`. MEASURED on GitHub-hosted runners, one dedicated job per project (shared cloud hardware: NOISY for small differences).

| project | runs | --det s | --det-async s | slowdown | seed 1 s | slowdown | outcomes (run 0) |
|---|---|---|---|---|---|---|---|
| anyio | 3 | 87.7 | 95.02 | 8.3% | 95.13 | 8.5% | {"det": {"passed": 3568, "skipped": 1192, "failed": 50, "xfailed": 2}, "det-async": {"passed": 3569, "skipped": 1192, "failed": 49, "xfailed": 2}, "det-async-s1": {"passed": 3569, "skipped": 1192, "failed": 49, "xfailed": 2}} |
| idoft-easypy | 3 | 12.97 | 12.87 | -0.8% | 12.9 | -0.6% | {"det": {"passed": 163, "failed": 48, "error": 1}, "det-async": {"passed": 163, "failed": 48, "error": 1}, "det-async-s1": {"passed": 163, "failed": 48, "error": 1}} |
| idoft-python-dugong | 3 | 44.3 | 44.33 | 0.1% | 44.31 | 0.0% | {"det": {"error": 118}, "det-async": {"error": 118}, "det-async-s1": {"error": 118}} |
| idoft-tornado-swirl | 3 | 0.9 | 0.91 | 1.7% | 0.91 | 1.7% | {"det": {"passed": 43}, "det-async": {"passed": 43}, "det-async-s1": {"passed": 43}} |
| idoft-webssh | 3 | 17.4 | 20.18 | 16.0% | 19.07 | 9.6% | {"det": {"passed": 71, "failed": 18}, "det-async": {"passed": 68, "failed": 21}, "det-async-s1": {"passed": 70, "failed": 19}} |
| l1-repro | 3 | 0.89 | 0.88 | -0.8% | 0.89 | 0.3% | {"det": {"failed": 5, "passed": 9}, "det-async": {"passed": 12, "failed": 2}, "det-async-s1": {"passed": 6, "failed": 8}} |
