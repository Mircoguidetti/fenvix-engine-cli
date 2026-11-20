# PY2 notes: Python part 2 (pytest-xdist, plugins, concurrency, native code)

Audited: `claude/release-1` wheel `/home/user/audit/build/dist/detpy-0.1.0-cp39-abi3-linux_x86_64.whl`, CPython 3.13.18,
pytest 9.2.0, pytest-xdist 3.8.0 (venvs under `/home/user/audit/work/PY2/venvs/`, test projects under
`/home/user/audit/work/PY2/p/<name>/`, logs in each project's `out/`). Every run wrapped in `timeout 300`.

## Evidence appendix (keyed by gap id)

### PY2-001 false failure: order-dependent test rerun without its reused predecessors
```
$ cat p/carry/test_c.py
STATE = {}
@pytest.mark.parametrize("i", range(4))
def test_fill(i): STATE[i] = 1
def test_carried_state():
    assert open(os.path.join(HERE, "data.txt")).read().strip() in ("1", "2")
    assert len(STATE) == 4
$ pytest -q                               -> 5 passed
$ pytest -q --det --det-cache=out/c       -> reused 0, ran 5, recorded 5; 5 passed
$ pytest -q --det --det-cache=out/c       -> reused 5; 5 passed
$ echo 2 > data.txt
$ pytest -q --det --det-cache=out/c       -> reused 4 result(s) with proof, ran 1, recorded 0; not reused: data 1
                                             FAILED test_c.py::test_carried_state - assert 0 == 4 ; 1 failed, 4 passed
$ pytest -q ; pytest -q --det             -> 5 passed ; 5 passed
$ pytest -q --det --det-cache=out/c       -> reused 4, ran 1; FAILED test_c.py::test_carried_state (permanent)
```

### PY2-002 xdist `testrun_uid` in serial `--det`: random, unobserved, cached
```
$ pytest -q --det (3 runs, p/ent)   -> test_uid_fixture: passed, failed ('8'), failed ('9')
$ detpy verify e1 e2 e3             -> NOT-COVERED test_e.py::test_uid_fixture [outcome-only] outcomes=passed,failed,failed
                                       identical observed events, different outcome
$ pytest -q --det --det-cache=out/c  (run 1: recorded 1; runs 2..7: "reused 1 result(s) with proof, ran 5")
receipts: {"nodeid": "test_e.py::test_uid_fixture", "reused": true, "outcome": "passed", ...}
xdist/plugin.py:400-407  testrun_uid(): workerinput["testrunuid"] under -n, else `return uuid.uuid4().hex`
python/detpy/_sites.py:58, _level0.py:24  infra = (_pytest, pytest, pluggy, detpy, _hypothesis_pytestplugin, xdist, execnet)
```
Entropy drawn in the user's own code is refused correctly (p/ent2: conftest import, session/module/function fixtures,
module level, helper import: 8 runs, "recorded 0", never reused).

### PY2-003 `--dist each`
```
$ pytest --det -n 2 --dist each --det-cache=out/cache.n2each   (p/xd1, twice)
detpy: pytest-xdist --dist=each is not planned by detpy (xdist's own scheduling)
reused 0 result(s) with proof, ran 40, recorded 40      <- both runs
$ detpy verify serial.1.jsonl n2each.1.jsonl -> "2 runs, 20 tests; order: DIFFERS between runs"
```

### PY2-004 / PY2-005 / PY2-007 placement (p/xd2, p/xd5)
```
plain serial: 15 passed | plain -n2: 3 failed | plain -n4: 4 failed
--det serial: 15 passed
--det -n 2 : plan b64d87… gw0=8 gw1=7 ; FAILED test_wid_env, test_carried_state (3 == 8), test_basetemp
--det -n 4 : plan b34e6c… ; FAILED test_wid_fixture, test_count_env, test_wid_env, test_basetemp, test_carried_state
detpy verify s n2 n4: covered 10, not covered 5, reasons: placement=5
  "placement: ran in worker gw1 without 7 of its serial predecessors (... identical observed events, different outcome)"
cache dir out/c1 recorded serially (15 passed), then:
  --det --det-cache=out/c1 -n 2  -> plan a4c176… gw0=3/11 gw1=4/4, reused 8, "1 failed, 14 passed" (test_carried_state assert 0 == 8)
  same again                      -> plan bbbf8a… gw0=14/14 gw1=1/1, reused 0, 14 withdrawn
  -n 4                            -> 4 failed ; -n 4 again -> plan gw0=0 gw1=9 gw2=0/2 gw3=4
  -n 2 third time                 -> 3 failed (test_wid_fixture gw1, test_wid_env, test_carried_state)
  serial afterwards               -> reused 8, ran 7: FAILED test_carried_state assert 0 == 8 (serial plain passes: PY2-001)
```

### PY2-006 cached `-n 2`, clean start (p/xd2)
```
run 1: plan b64d87… (8/7), reused 0, recorded 12
run 2: plan 07739c… gw0=12/12 gw1=3/3, reused 0; "12 reuse(s) withdrawn: the plan moved a worker-id reader"; not reused: env 1, new 3, placement 11
run 3,4: same plan, reused 12, ran 3
```

### PY2-008 / PY2-009 worker crash (p/xd3)
```
--det -n 2: "merged trace: 20 tests from 3 worker traces; MISSING 1"; "worker gw1 crashed in test_crash.py::test_crash; its remaining tests went to its replacement"; 1 failed, 20 passed
detpy verify c1 c2: "2 runs, 20 tests ... covered 20 not covered 0 missing 0"
--max-worker-restart=0: "merged trace: 11 tests from 2 worker traces; MISSING 10"; 1 failed, 11 passed
--det-cache -n 2 twice: run 2 "reused 20", the crashing test runs again and crashes again (not reused: new 1) -> correct
```

### PY2-012 anyio/trio hang (p/aio)
```
$ ./pp.py async aio strict -p no:cacheprovider
plain  rc=0: 18 passed in 1.02s
det1   rc=124: test_anyio.py .          <- killed by timeout 120 after the first test
det2   rc=124: test_anyio.py .
```
Files: p/aio/test_anyio.py (anyio_backend params asyncio, trio), test_asyncio_strict.py (pytest-asyncio strict, loop
scopes, gather, wait_for, to_thread), test_trio.py (pytest-trio, autojump_clock). Not isolated: which backend/test
hangs (2nd test in collection order = test_anyio_sleep[trio]); the cache runs of this probe were still running when
the audit was stopped (logs p/aio/out/strict.*.log).

### PY2-013 / PY2-014 options on release-1
`pytest --help` (release-1 wheel): --det --det-allow-host --det-cache --det-cache-dists --det-cache-epoch-window
--det-cache-keys --det-cache-max-age --det-cache-no-follow --det-cache-receipts --det-cache-shared --det-cache-verify
--det-cassette --det-compare --det-disable --det-epoch --det-isolate --det-keep-aslr --det-max-events --det-no-reexec
--det-order --det-outcomes --det-plan --det-plan-worker --det-record --det-seed --det-sleep --det-tick
--det-tick-adapt --det-trace --det-urandom. No --det-threads, no --det-async.

### PY2-015 / PY2-016 seed order vs selection and shards (p/xd1, `--det --det-seed=5`)
```
full      : b[0] wid b[1] b[2] b[4] b[5] uid b[3] env_wid | a[5] g1a a[3] k1 k2 a[0] a[1] reads_file a[2] g1b a[4]
-k test_b : b[0] wid b[1] b[2] b[4] b[5] uid b[3] env_wid          (same)
-k 'not uid'            : b[0] b[5] b[1] env_wid b[4] b[2] b[3] wid
--deselect test_b[0]    : b[1] wid b[2] uid b[5] b[3] b[4] env_wid
pytest-split  --splits 2 --group 2      : b[2] b[3] wid b[5] uid b[4] env_wid
pytest-shard  --shard-id=0 --num-shards=2: b[0] b[1] wid b[5] uid b[2] env_wid a[2] g1b k1 k2 a[5] reads_file
pytest-test-groups --test-group-count 2 --test-group=1: b[5] b[1] b[3] env_wid reads_file a[0] k2 a[2] g1b a[4]
```
Deselection by the shard plugins is kept; the same shard arguments + seed give the same order again.

### PY2-017 / PY2-018 entropy (p/ent, p/ent2): see the outputs quoted in the gap entries; logs in p/ent/out, p/ent2/out.

## Result tables

### xdist mode x result (p/xd1, 20 passing tests; "= serial" means `detpy verify serial.jsonl parallel.jsonl` -> covered 20, not covered 0)

| option | `--det` | parallel fp = serial fp (this toy) | `--det-cache` x2 | note |
|---|---|---|---|---|
| `-n 2` (`--dist load`) | accepted, fixed plan, header line printed | yes | run 2 reused 20/20 | |
| `-n 4` | accepted | yes | reused 20/20 | other plan digest than -n 2 (PY2-005) |
| `--dist loadscope` | accepted (atoms module/class) | yes | reused 20/20 | |
| `--dist loadfile` | accepted | yes | reused 20/20 | |
| `--dist loadgroup` + `xdist_group` | accepted | yes | reused 20/20 | node ids stay serial ids |
| `--dist worksteal` | accepted, silently static plan | yes | reused 20/20 | PY2-011 |
| `--dist each` | not planned (header says so) | order differs, 40 runs / 20 records | reused 0, recorded 40, both runs | PY2-003 |
| `-n 2 --dist no` | xdist makes it load; header shows load | yes | reused 20/20 | PY2-019 |
| `-n 0` | serial | yes | reused 20/20 | |
| `-n auto`, `-n logical` | accepted (4 workers here) | yes | not checked | PY2-005 |
| `-n 8 --maxprocesses 2` | accepted (2 workers, same plan as -n 2) | yes | not checked | |
| `--tx popen//python=...` x2, `--tx 2*popen`, `-d --tx 3*popen` | accepted | yes | not checked | |
| `--tx ssh=...`, `--rsyncdir` | not run; unsupported per LIMITS O1 | - | - | PY2-010 (READ) |
| `--looponfail` | accepted, runs with detpy summary, then waits | not checked | not checked | |
| `--forked` (pytest-forked) | could not check: pytest-forked fails 20/20 on plain pytest 9.2 too | - | - | |
| `--boxed` | option no longer exists in xdist 3.8 / pytest-forked | - | - | |
| worker crash, default restart | replacement runs the rest; crashed test MISSING in trace | n/a | run 2 reused 20, crash test rerun | PY2-008 |
| `--max-worker-restart=0` | 10 planned tests never run | n/a | not checked | PY2-009 |
| `worker_id` / `PYTEST_XDIST_WORKER` readers | accepted; outcome depends on plan | NO (placement) | withdrawn/re-run, no wrong reuse seen; plans degrade | PY2-004, 006, 007 |
| `testrun_uid` fixture | derived and stable under -n; random in serial `--det` | n/a | serial: WRONG reuse | PY2-002 |
| session-scoped fixture per worker, `tmp_path_factory` basetemp | accepted; basetemp `popen-gwK` differs from serial | NO for tests that read it | re-run | PY2-004 |
| `pytest_xdist_auto_num_workers` hook | honoured (3 workers) | not checked | not checked | |
| `-n 2 --det-seed=7` | accepted | yes vs serial seed 7 | not checked | |
| `-n 2 -x`, `--maxfail=1` | accepted on a passing suite | yes | not checked | behaviour on failure not checked |
| `--collect-only --det [-n 2]` | collects, prints the detpy summary with a trace path | - | - | whether it overwrites an existing trace: not checked |
| plan stable across worker counts | no (by construction) | - | - | PY2-005 |
| pytest-split / pytest-shard / pytest-test-groups | accepted, deselection kept, per-shard shuffle | not checked | not checked | PY2-016 |
| pytest-parallel | could not check: INTERNALERROR on plain pytest 9.2 (`py.log`) | - | - | |

What docs/PARALLEL-PROOF-DESIGN.md / LIMITS O1 say is not covered: `--dist each`, remote `--tx`, work stealing,
and "a test whose events depend on process state left by tests it no longer follows in its worker diverges from its
serial fingerprint ... nothing prevents it yet (P5 of the design)"; Design B (own lanes, footprint scheduler, P6-P7)
is design only.

### plugin x plain / det / cache

| plugin | plain | `--det` x2 + verify | `--det-cache` x2 | gap |
|---|---|---|---|---|
| pytest-xdist | see table above | | | PY2-002..011 |
| pytest-split, pytest-shard, pytest-test-groups | ok | ok, per-shard order | not checked | PY2-016 |
| pytest-forked | fails plain on pytest 9.2 | could not check | could not check | |
| pytest-parallel | INTERNALERROR plain | could not check | could not check | |
| anyio (asyncio + trio backends) | 18 passed (whole p/aio project) | HANGS (timeout 120, 2 of 2 runs) | not finished | PY2-012 |
| pytest-asyncio (strict), pytest-trio | passed plain (same project) | not reached (behind the hang) | not checked | |
| every other plugin of the task list | not checked | not checked | not checked | see "Not covered" |

### concurrency / native scenario x result

| scenario | result |
|---|---|
| `--det-threads` / `--det-async` on release-1 | absent (PY2-013, PY2-014) |
| `os.urandom`, `uuid4`, `secrets`, `SystemRandom` under `--det` | observed, not controlled; outcomes flip; cache refuses them (PY2-018) |
| `uuid.uuid1()` | stable over 3 `--det` runs in p/ent (covered); cache refused it ("after an earlier test or fixture of this process"); why not analysed |
| entropy at conftest import / session, module, function fixtures / module level / helper import | cache refuses all, whole suite uncacheable (PY2-017) |
| entropy in xdist's `testrun_uid` (plugin code) | not observed, wrongly reused (PY2-002) |
| everything else in sections 3 and 4 of the task | not checked |

## Not covered (task items NOT probed; for the session that finishes this)

1. xdist: `--tx ssh=` (only READ), `--looponfail` beyond start-up, pytest-forked on pytest 7/8, `-x`/`--maxfail` on
   failing suites under `-n`, `--det-plan` / `--det-plan-worker` replay, `--det-isolate` with `-n`, cache under
   `-n auto`/`--maxprocesses`/`--tx`, `--det-cache-shared` under `-n`, isolating the anyio hang.
2. Plugins not probed at all (venvs are installed and ready under work/PY2/venvs: async, time, order, cov, http, web,
   report, native): pytest-asyncio auto mode and loop scopes, pytest-trio, pytest-timeout (signal and thread),
   pytest-rerunfailures, flaky, pytest-randomly ("switched off": told to the user?), pytest-random-order,
   pytest-order, pytest-ordering, pytest-dependency, pytest-benchmark, pytest-cov / coverage.py (`sys.monitoring`
   tool id conflict; coverage of skipped-with-proof tests), pytest-mock, freezegun, time-machine, vcrpy,
   pytest-recording, responses, requests-mock, httpx + respx, aioresponses, pytest-httpserver, pytest-localserver,
   pytest-socket, pytest-django, pytest-flask, FastAPI/Starlette TestClient, SQLAlchemy (sqlite, postgres),
   pytest-postgresql, testing.postgresql, testcontainers, moto, celery, factory-boy, Faker, syrupy, pytest-snapshot,
   inline-snapshot (`--snapshot-update`), pytest-html, junitxml, pytest-json-report (how skipped-with-proof tests are
   reported), pytest-sugar, pytest-instafail, pytest-xprocess, pytest-env, pytest-dotenv, pytest-subtests,
   pytest-check, pytest-cases, pytest-lazy-fixture, parametrize ids with object reprs/addresses, `--lf/--ff/--sw/-m/
   -x/--maxfail/-p no:...` with order, seed and cache (`-k`, `--deselect` only for the order: PY2-015),
   `pytest_collection_modifyitems` reordering in conftest, `addopts`, hypothesis (PY1).
3. Concurrency: asyncio (gather order, `asyncio.sleep` under the virtual clock, `wait_for`, `loop.time`,
   `run_in_executor`, `to_thread`, uvloop: test file written at p/aio/test_asyncio_strict.py, never reached under
   `--det`), threads (racy counter, ThreadPoolExecutor, queue, `threading.Timer`, switch interval), multiprocessing
   (fork/spawn/forkserver, Pool.map, children's clock/random/hash seed, child file reads in the cache key),
   ProcessPoolExecutor, `subprocess.run` (python and non-python children, with and without strace on PATH),
   `os.fork`, signals/`signal.alarm`, select/selectors, `time.sleep` in threads, `--det-urandom`, `hash()` of str,
   `id()`-ordered containers, dict/set order, `os.environ` iteration, locale, timezone, `os.getpid`, hostname,
   `tempfile` names, `os.cpu_count`, file mtimes, inode order, BLAS threads.
4. Native code: numpy, pandas, scipy, torch, grpcio, sqlite3, psycopg, mysqlclient, cryptography/OpenSSL, lxml,
   Pillow, Cython, and the ctypes test (libc `time`/`clock_gettime`/`rand`/`getrandom`, C-level file read) against
   `--det` and `--det-cache`: the "important one" of the task was NOT run. LIMITS S1 and section 9 A1/A2 describe the
   intended handling (repository native code refused; system libraries' C reads stay unseen), unverified here.

## Could not check

- pytest-forked / `--boxed`: pytest-forked 1.6.0 fails every test on plain pytest 9.2 ("running the test EXITED with
  status 3"); needs a pytest 7/8 venv.
- pytest-parallel 0.1.1: INTERNALERROR on plain pytest 9.2 (`module 'py' has no attribute 'log'`).
- `--tx ssh=`: no second host.
- Docker-based items (postgres, testcontainers): not tried.
- Whether `--collect-only --det` overwrites an existing trace file: it prints "trace: .detpy/trace.jsonl"; not compared.

## For the lead

- The audit was stopped by budget after the xdist section and the first plugin probe: 19 gaps, all from sections 1
  and a small part of 2/3; sections 2 (plugins), 3 and 4 are essentially open.
- PY2-001 is independent of xdist: plain serial `--det-cache` turns a passing order-dependent test into a permanent
  failure. Brain DECISIONS 2026-11-20 states "a reused result equals a deterministic run of the suite as the user runs
  it"; the reported result here does not.
- LIMITS P4 says "fixtures implemented in third-party pytest plugins are recorded", but xdist (and execnet,
  hypothesis' pytest plugin) are on the infrastructure list, so their draws are invisible (PY2-002).
- Brain DECISIONS 2026-11-18 records L1 threads as closed (`--det --det-threads`); the option is not on release-1.
- Labels: every count above is MEASURED on this machine (4 vCPU), single runs unless "x2/x3" is stated.
