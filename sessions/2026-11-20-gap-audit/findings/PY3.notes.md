# PY3 notes: Python engine features on release-1 (features, matrix, levels)

Audited: `/home/user/audit/engine` (fenvix-engine-cli @ `claude/release-1`, tip 529c1609), wheel
`/home/user/audit/build/dist/detpy-0.1.0-cp39-abi3-linux_x86_64.whl` installed with `--no-deps` in my own venv
(`/home/user/audit/work/PY3/venv`: CPython 3.13.18, pytest 9.2.0, pytest-xdist 3.8.0, pytest-asyncio 1.5.0, requests
2.34.2, httpx 0.28.1, aiohttp 3.14.5, numpy 2.5.5, hypothesis 6.170.17, websockets 17.4).
Scratch projects (all written by me): `/home/user/audit/work/PY3/proj` (controls, repro, parallel),
`netproj` + `netproj2` (network), `cacheproj` (skip with proof). Machine: 4 cores shared, load average 20-35 during
the audit: every timing below is MEASURED but NOISY.

## A. Real user surface (enumerated, not from docs)

### A.1 pytest options added by the plugin (`pytest --help`, group "deterministic execution (Level 0)")

`--det`, `--det-seed=N`, `--det-order=FILE`, `--det-trace=PATH`, `--det-compare=TRACE`, `--det-record`,
`--det-cassette=PATH`, `--det-allow-host=HOST` (repeatable), `--det-epoch=ISO` (default auto = HEAD commit time, else
2025-01-01), `--det-tick=NS`, `--det-tick-adapt=N`, `--det-sleep={virtual,real}`, `--det-disable=LIST`
(order,seeds,hashseed,bytecode,time,fs,net), `--det-urandom`, `--det-keep-aslr`, `--det-no-reexec`,
`--det-max-events=N`, `--det-outcomes=PATH`, `--det-cache=DIR`, `--det-cache-verify=FRACTION`, `--det-cache-dists`
(PROTOTYPE), `--det-cache-no-follow`, `--det-cache-max-age=DAYS`, `--det-cache-epoch-window=DAYS`,
`--det-cache-shared=DIR`, `--det-cache-keys=PATH`, `--det-cache-receipts=PATH`, `--det-plan=FILE`,
`--det-plan-worker=GWK`, `--det-isolate`.

Not present (searched `pytest --help` and `grep -rn` over `python/detpy`, `crates/`): `--det-threads`, `--det-async`,
`--det-backend`, any `--det-env/--det-tz/--det-locale`, any upload/report option, any replay-command option.

### A.2 `python -m detpy` (also installed as console script `detpy`)

`unittest | django | nose2 | doctest | zope-testrunner | ward` (each: `--det ...` + the runner's own arguments),
`verify [--json] [--show-stable] TRACE TRACE...`, `backends`, `repro TEST [--seeds N] [--seed fixed|N] [--out DIR]
[--confirm N] [--max-runs N] [--timeout S] [--python EXE] [--json] [-- pytest args]`, `explore --budget MINUTES
[--max-seeds N] [--targets FILE] [--no-repro] [common]`, `replay BUNDLE [--runs N] [--python EXE]`.
No subcommand for: cache (inspect/explain/clear/gc), cassette, culprit, dependency verdict, upload, serve.
`python -m detpy.cache_service` is a separate module entry (the shared-cache server, see section J).

### A.3 `fenvix` (release/fenvix)

`fenvix python [pytest args]`, `fenvix python-runner RUNNER [args]` (= `python -m detpy RUNNER`), `fenvix verify A B`,
`fenvix detect`, `fenvix version` (+ node/go/jvm). No `fenvix repro|explore|replay|culprit|deps|cache`.

### A.4 Environment variables read by the Python shell (`grep -rn environ python/detpy`, `env::var` in crates)

User-facing: `DETPY_CACHE_SHARED`, `FENVIX_CACHE_TOKEN`, `FENVIX_CACHE_TOKEN_FD`, `FENVIX_CACHE_TOKEN_FILE`,
`FENVIX_CACHE_LOCAL`, `FENVIX_CACHE_ALLOW_HTTP`, `FENVIX_CACHE_REPORT`, `DETPY_CACHE_DISTS`, `DETPY_CACHE_LINES`,
`DETPY_VERBOSE`, `DETPY_REWRITE_CACHE`, `DETPY_REWRITE_OWN`, `DETPY_PLAN_CHUNK_DIV`, `FENVIX_RUNTIME_MEMO`,
`FENVIX_RUNTIME_ISA`, `XDG_CACHE_HOME`, `PYTEST_ADDOPTS`. Internal (set by detpy): `DETPY_REEXEC`,
`DETPY_PRECOMPILE_S`, `DETPY_PYC_CACHE`, `DETPY_BLOCKED_PLUGINS`, `DETPY_XDIST_ENV`, `PYTHONHASHSEED`,
`PYTHONPYCACHEPREFIX`, `PYTHONDONTWRITEBYTECODE`, `PYTEST_XDIST_*`. Read for identity: `TZ`, `TZDIR`, `LANGUAGE`,
`LOCPATH`, `LD_PRELOAD`, `LD_LIBRARY_PATH`, `PYTHONOPTIMIZE`, `TMPDIR`. None of these is documented in one place.

### A.5 Files written

`<rootdir>/.detpy/trace.jsonl` (+ `trace.gwK.jsonl`, `plan.json`, `durations.json` under `-n`), `.detpy/cassette.json`
(`--det-record`; `cassette.gwK.json` under `-n`), `.detpy/repro/<slug>/{bundle.json,order.txt,fail.trace.jsonl,
pass.trace.jsonl}` + `.detpy/repro/.work/*`, `.detpy/repro/explore.json`; cache DIR: `proof-cache.json`,
`receipts.jsonl` (overwritten each run), `carried.jsonl`, `quarantine.json`, `epoch.json`, `distributions.json`,
`clockshim-<hash>.so`; `~/.cache/detpy/pyc/<tag>-hashseedN/` (precompiled bytecode; 1.2 GB on this machine after the
audit agents' runs, MEASURED `du -sh ~/.cache/detpy`), `--det-outcomes` JSON, `--det-cache-keys` JSON.

## B. Evidence appendix (keyed by gap id)

### PY3-001..004 (environment, timezone, locale)
```
$ TZ=Asia/Tokyo MY_FLAG=bad pytest -q --det --det-trace=/tmp/py3_e1.jsonl tests/test_tzdep.py tests/test_fs.py
FAILED tests/test_tzdep.py::test_tz_hour - AssertionError: assert 17 < 12
FAILED tests/test_fs.py::test_env - AssertionError: assert 'bad' == 'ok'
$ TZ=America/New_York pytest -q --det --det-trace=/tmp/py3_e2.jsonl tests/test_tzdep.py tests/test_fs.py
7 passed in 0.30s
$ python -m detpy verify /tmp/py3_e1.jsonl /tmp/py3_e2.jsonl
covered by Level 0: 5  not covered: 2  missing: 0  outcome-unstable: 2
reasons: outcome-only=2
NOT-COVERED tests/test_tzdep.py::test_tz_hour  [outcome-only] outcomes=failed,passed
    runs 0 vs 1: identical observed events, different outcome (failed vs passed): the cause is a source Level 0 does not observe
NOT-COVERED tests/test_fs.py::test_env  [outcome-only] outcomes=failed,passed
    runs 0 vs 1: identical observed events, different outcome (failed vs passed): the cause is a source Level 0 does not observe
```
Full-suite pair (`TZ=Asia/Tokyo` vs `TZ=America/New_York LANG=de_DE.UTF-8 LC_ALL=C HOME=/tmp USER=bob CI=true`):
`ENV None Asia/Tokyo None /root None` vs `ENV None America/New_York de_DE.UTF-8 /tmp bob`; `LOCALE ('C','UTF-8')`
vs `LOCALE (None, None)`; `now` 17:33:20 vs 03:33:20; fingerprints of test_env (5644e21c...), test_locale_tz
(44c0e26c...), test_time_apis (778d4ef3...) identical in both traces; trace header identical key set (no env/tz).

### PY3-005, 017, 018 (scheduling)
```
$ pytest --help | grep -c -E "det-threads|det-async"   => 0
$ git -C fenvix-engine-cli merge-base --is-ancestor origin/claude/l1-threads-fix origin/claude/release-1 => not ancestor
$ for i in 1..8: pytest -q --det tests/test_race.py
1 failed (test_thread_race assert 60304) | 1 failed (test_async_race) | 2 failed | 1 failed (async) |
1 failed (thread_race 79415) | 1 failed (async) | 2 failed | 1 failed (test_thread_flaky)
$ python -m detpy verify /tmp/py3_race[1-6].jsonl      (runs printed COUNTER 40419, 64012, 20000, 53949, 20000, 45643;
                                                        ASYNCORDER ['b','a'] x5, ['a','b'] x1)
covered by Level 0: 4  not covered: 0  missing: 0  outcome-unstable: 0
```

### PY3-006..008, 016 (clock)
Two `pytest --det` runs of tests/test_time.py:
```
TIMEVALS {'time': 1795163542.000001, ..., 'process_time': 0.873121438, 'thread_time': 0.832434906, 'os_times': 17180579.69, ..., 'rusage': 0.790561}
TIMEVALS {'time': 1795163542.000001, ..., 'process_time': 0.91394441,  'thread_time': 0.867829766, 'os_times': 17180589.29, ..., 'rusage': 0.8315389999999999}
MTIME 1795163580.8495526 NOW 1795163542.000001   |  MTIME 1795163590.4416487 NOW 1795163542.000001
LOOPTIME 1010.770980256 0.0501 walltime 1795163542.050001 | LOOPTIME 1020.369366521 0.0547 walltime 1795163542.050001
```
`--det-disable=time`: header still `sleep=virtual`, `SLEPT 5.002621943000122`.

### PY3-009..014 (randomness, false divergence)
```
RANDVALS {'r': 0.9446665524543929, 'ri': 380147284, 'R': 0.08273873873232274, 'sysr': 0.5052..., 'ur': '39cefb45', 'u4': '66b885ee-...', 'u1': 'fecfc194-...', 'sec': '8d26789a', 'np': 0.438333320309803, 'np_rng': 0.8611262264842099}
RANDVALS {'r': 0.9446665524543929, 'ri': 380147284, 'R': 0.08273873873232274, 'sysr': 0.5537..., 'ur': '2c742c02', 'u4': 'df6b5313-...', 'u1': '048ecc92-...', 'sec': '3c220640', 'np': 0.7994329056418811, 'np_rng': 0.7262259129009949}
NPTOP 0.1765181375744933 0.9549029492405646 0.2784121436361374 0.981806180655805
NPTOP 0.1765181375744933 0.9549029492405646 0.6947782221851677 0.05670534976282593
$ python -m detpy verify /tmp/py3_t1.jsonl /tmp/py3_t2.jsonl      (same commit, same command, twice)
covered by Level 0: 22  not covered: 3  missing: 0  outcome-unstable: 0
NOT-COVERED tests/test_fs.py::test_reads_data  [entropy] outcomes=passed,passed
    runs 0 vs 1: event #0: os.urandom @ <site>/numpy/random/_pickle.py:7 returned different values: ...
```
test_reads_data only reads `tests/data.txt`; the event comes from detpy's `seeds.start_test` (`hasattr(np, "random")`
/ `np.random.seed`) importing numpy.random lazily inside the first test's bracket. With `--det-urandom`: uuid1 still
differs (`106e59f6-...` vs `12b9e900-...`), everything else equal.

### PY3-019..030 (network)
netproj (https://pypi.org/simple/six/ through the sandbox proxy), netproj2 (my own server on the machine's
non-loopback address 192.0.2.2: http 18080, websockets 18081, udp 18082).
```
netproj  --det-record: 12 passed, "network: recorded 5 test(s)"; cassette tests: test_httpx_sync, test_requests_https,
         test_udp_connect_send, test_urllib3_https, test_urllib_https   (no test_httpx_async, no test_aiohttp)
netproj  replay: FAILED test_aiohttp, test_httpx_async (DNS blocked), test_udp_external; CURL 200 (subprocess, real network)
netproj2 --det-record: 6 passed, "network: recorded 2 test(s)": test_requests_plain [(192.0.2.2,18080,False,2)],
         test_tcp_recvmsg [(192.0.2.2,18080,False,0)]
netproj2 replay: PASSED test_requests_plain, test_tcp_recvmsg (prints RECVMSG b''); FAILED test_aiohttp_plain,
         test_httpx_async_plain, test_websocket, test_udp_roundtrip
stale:   test changed to GET /simple/pip/ + other token => `BODYHAS six-1.17 True False`; trace event
         "replay.mismatch ... pypi.org:443#0 expected 192B:ca8d... got 179B:22df..."; nothing on the terminal
secret:  base64-decoded segment: b'GET /simple/six/ HTTP/1.1\r\nHost: pypi.org\r\n...Authorization: Bearer SECRET-TOKEN-12345\r\n\r\n'
```

### PY3-031..034, 039..042, 057 (replay, repro)
```
$ python -m detpy repro tests/test_order.py::test_victim          (proj; 27 tests; 53.5 s, 17 pytest runs, NOISY, load ~30)
detpy repro: tests/test_order.py::test_victim: reproduced
  found with fixed order; order minimised from 13 to 2 test(s)
  polluter(s): tests/test_order.py::test_polluter
  replay: 10/10 failed, identical fingerprint: True
  first diverging event vs a passing run: entropy: event #0: [entropy] os.urandom @ <site>/numpy/random/_pickle.py:7 = 16:f42d...  <>  [random] random.state @ <end> = a523...
  replay: pytest --det --det-order=.detpy/repro/test_victim-c4145a95/order.txt
$ pytest --det --det-order=.detpy/repro/test_victim-c4145a95/order.txt   => 1 failed, 1 passed, 27 deselected  (pasted command works)
$ python -m detpy replay .detpy/repro/test_victim-c4145a95 --runs 3      => fails 3/3, identical_fingerprint true, matches_bundle true, exit 0
$ python -m detpy repro tests/test_random.py::test_flaky_random --seeds 8 --confirm 3
detpy repro: tests/test_random.py::test_flaky_random: replay-unstable
  found with --det-seed=1; order minimised from 3 to 1 test(s) / fails when run alone (no polluter)
  replay: 3/3 failed, identical fingerprint: False            (14 pytest runs, 205 s, NOISY)
$ python -m detpy repro tests/test_race.py::test_async_race --seeds 4 --confirm 6 -- tests/test_race.py
detpy repro: tests/test_race.py::test_async_race: replay-unstable
  found with --det-seed=2; order minimised from 2 to 2 test(s) / polluter(s): tests/test_race.py::test_thread_race
  replay: 5/6 failed, identical fingerprint: False / first diverging event ...: outcome-only
$ python -m detpy repro test_u.T.test_a   (unittest project)  => "not-collected / None pytest runs, None s"
$ python -m detpy explore --budget 0.4 --max-seeds 3 --no-repro --out /tmp/py3_explore -- tests/test_order.py tests/test_fs.py
detpy explore: 3 seeds in 3.51 s; 1 flaky failing tests (0 always failing, not flaky); 0 replay bundles; ...
```

### PY3-033, 051 (parallel, isolate)
```
$ pytest --det --det-seed=7            => 2 failed (test_external_http, test_victim), 25 passed
$ pytest --det --det-seed=7 -n 2       => 1 failed (test_external_http), 26 passed
  plan 61f4b8e5bb38d79c8376ca555a767015: 2 workers (ran/planned gw0=14/14, gw1=13/13), planned makespan 14.0s (LPT 14.0s); reused by the controller: 0
  merged trace: 27 tests from 2 worker traces
$ python -m detpy verify serial7 parallel7
NOT-COVERED tests/test_order.py::test_victim  [placement] outcomes=failed,passed
    runs 0 vs 1: placement: ran in worker gw0 without 11 of its serial predecessors (...)
$ pytest -q --det --det-isolate tests/test_order.py
detpy --det-isolate: 5 tests in forked children; overhead 0.02 s (3.2 ms per test, of which recording 0.0 ms); 0 children failed
5 passed, 5 warnings in 0.13s          (test_victim fails without --det-isolate; no finding printed)
$ pytest --det --det-isolate --det-cache=/tmp/py3_isoc tests/test_order.py  x2  => second run "reused 5 result(s) with proof, ran 0"
```

### PY3-047..050, 052, 053, 063..069 (skip with proof), cacheproj
Sound (changed input => the test reran with a named reason; 17 probes): data file (`data: data/input.txt (f)`),
module constant (`code: app/calc.py (module level)`), env var (`env: environment variable APP_MODE`), function and
session fixtures (`code: tests/conftest.py::base` / `::sess`), file read by a `cat` child (`data: data/sub.txt (f)`),
deleted file checked with exists (`data: qdata/marker (m)`), sqlite database read from C, os.open/os.read, mmap,
directory listing, file outside the repository, symlink retarget, stat size, TZ (wrong reason, PY3-067). Refused
(never cached): ctypes fopen, tests after numpy import entropy. Failures never reused (test_fail reran every time).
```
$ pytest --det --det-cache=.cache/np tests/test_nptop.py   (x2; `import numpy as np` + 4 asserts)
reused 0 result(s) with proof, ran 4, recorded 0 ... not cacheable: after an earlier test or fixture of this process 3, os entropy (not controlled; use --det-urandom) 1
   with `import numpy as np, numpy.random`: not cacheable: os entropy 4;   with --det-urandom: second run "reused 4"
WRONG REUSE (run twice):
record:  P_CPU 4 4 P_UMASK 0o22 P_RLIMIT 20000 P_HOST vm vm   reused 0 ..., ran 4, recorded 4
mutated: (umask 077; ulimit -n 1024; taskset -c 0 unshare --uts sh -c 'hostname otherbox; exec "$@"' sh pytest --det --det-cache=.cache/p2 <4 tests>)
         reused 4 result(s) with proof, ran 0, recorded 0
truth:   same prefix, no cache: P_CPU 1 1 P_UMASK 0o77 P_RLIMIT 1024 P_HOST otherbox otherbox
```
Reproduce: `/home/user/audit/work/PY3/cacheproj`, tests `tests/test_probe2.py::{test_cpu_count,test_umask,test_rlimit,
test_hostname}`, helper `/home/user/audit/work/PY3/tools/probe.sh`.

## C. Could not check / Not covered (20-minute budget cut by the coordinator)

Items of my brief that I did NOT get to, so another session can finish them:

- **a (controls)**: gRPC and HTTP/2 hands-on; DNS record/replay answers (the sandbox has no resolver); IPv6 (no IPv6
  here: `OSError: [Errno 97]` even plain); `--det-allow-host`; `--det-epoch`, `--det-tick*` options; freezegun /
  time-machine interplay; hypothesis under `--det` hands-on.
- **b**: order digest stability across Python versions/platforms (claimed by `order.rs`, not run).
- **c**: replay for the non-pytest runners beyond the unittest `not-collected` result.
- **d (verifier)**: traces of different `encoding`, different test sets (`missing`), truncated traces
  (`--det-max-events` small, `beyond-trace`), `--show-stable`, exit codes beyond 0/1, `fenvix verify` through the
  launcher, trace size on a real project (only my toy: 16.8 KB for 25 tests, MEASURED).
- **e**: failure families / grouping in `explore` with bundles (ran only `--no-repro`); `repro` state-setter
  ("brittle") path; bundle upload to the service (found none in the wheel; fenvix-app side not read).
- **f**: `explore` with repro + dedup by diverging event on a real project; budget overrun behaviour.
- **g**: running `harness/culprit/finder.py` and `--det-cache-keys` output: NOT run.
- **h**: running `harness/dep_verdict/`, `--det-cache-dists`: NOT run.
- **i (cache)**: `--det-cache-verify`, `--det-cache-max-age`, `--det-cache-keys`; site-packages dependency version
  change; pytest.ini / pyproject option change; conftest hook changes; dirty git tree; different path (copy of the
  project) and different user/HOME; two concurrent runs on one cache dir; cache size growth and eviction; Python
  patch-version change; uid/user, cwd, terminal size, locale (LC_ALL), `/proc` reads, warnings filters, `sys.flags`
  probes (tests exist in `cacheproj/tests/test_probe2.py`: test_uid_user, test_cwd, test_termsize, test_locale_c,
  test_proc_read, test_warn, test_python_flags, test_argv, test_free_disk; only cpu, umask, rlimit, hostname, tz
  were run); Python 3.9-3.11 (see PY1-006).
- **j (shared cache)**: starting `python -m detpy.cache_service serve`, tokens, tenant separation, sharing between two
  directories, `--det-cache-shared=DIR`, comparison with fenvix-app's hosted service: NOT run (PY3-054 is READ only).
- **k**: `-n` with `--det-plan` / `--det-plan-worker` replay, `--dist` modes, worker crash, `-n` + `--det-isolate`,
  limits of isolate (session fixtures, threads at fork).
- **l (overhead)**: NOT measured (no clone of a real project; machine load 20-35). Only incidental numbers: toy
  project `--det` 1.4-5.8 s vs plain 7.0 s dominated by a network timeout: not usable.
- **m**: exit codes with reused failures/xfail, `--det-outcomes` schema check, summary lines under `-n` with cache.
- **Matrix**: every cell marked `not checked`; nose2, ward, zope.testrunner, Django were not probed (runners not
  installed in my venv; PY1 had no runner probes yet at 08:54), pytest-bdd and hypothesis not probed.

## D. For the lead: contradictions found

- brain ROADMAP "Block 3 CLOSED" + ARCHITECTURE "L1 ... built": nothing of L1 is on release-1 (PY3-005).
- docs/RELEASE-1.md support table does not mention `repro` / `explore` / `replay` although they are in the wheel.
- DECISIONS 2026-11-19 virtual-day rule "same rule for Python, Node and Go": Python uses the HEAD commit time with a
  30-day window instead (PY3-050).
- DECISIONS 2026-11-20 `--det-isolate` "reports order-dependent tests as findings": it prints none (PY3-051).
- docs/ARCHITECTURE.md (engine) still says the cache is "Not wired into the plugin yet"; it is wired (`--det-cache`).
- `detpy verify` text output shows no thread id; JSON has `t`. Header misses `runtime` / `runtime_version` (PY3-015).
- Area names used in the gaps file beyond the list in my brief: "Python / runners", "Python / overhead".
