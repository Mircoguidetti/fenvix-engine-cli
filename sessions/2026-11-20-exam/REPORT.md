FINAL (exam built and run; most rows FAIL on today's engine, as expected)

# Go-live acceptance exam: report

Session 2026-11-20, branch `claude/exam` of fenvix-engine-cli. Plan: `exam/PLAN.md`. Machine-readable result:
`exam/results.json`. Gap map: `exam/gap_map.json`. Labels: **MEASURED** (Actions run id), **ESTIMATED**,
**DECLARED**, **UNKNOWN**. Every number below is MEASURED on GitHub Actions `ubuntu-24.04` (Linux x86_64) unless it
says otherwise.

## 0. Answer

* **5 of 24 rows PASS, 19 FAIL** (MEASURED, runs below). PASS: **PY-01** (CPython
  3.12/3.13/3.14), **PY-08** (native code and subprocesses never reused), **JS-01** (Node 22/24/26), **JS-08**
  (npm, pnpm, yarn classic, yarn berry with node-modules), **JS-09** (child processes, workers, native reads never
  reused). Every other row has at least one failing check. Checks: 235 of 423 pass.
* **Gaps:** 207 in-scope WRONG-RESULT/BLOCKS-USE gaps are each covered by at least one check;
  **38 are closed** (every covering check passed), 169 stay open.
  410 are out of scope, 15 belong to F-14 (listed, not examined),
  7 fit no row (section 5).
* **Scope (founder decision, 2026-11-20, mid-session):** go-live runs only on our machines. The exam installs the single
  Linux x86_64 artifact of the `claude/release-1` CI, as our runner machines do; no PyPI/npm, no GitHub Action, no
  macOS/arm64; F-10 and F-11 out of scope; F-09 = the artifact installs and works on Linux x86_64; F-02 replay runs on
  our machines; F-14 = a remote MCP server (not in this exam's row list). The first plan's arm64/macOS legs and the
  F-10 registry checks were removed; their gaps are out of scope with that reason.
* **What fails most (MEASURED):** the go-live CLI has no `fenvix repro|explore|replay` (F-02, F-18, PY-03); time zone,
  locale, environment variables and host name are not pinned and the verifier calls such runs identical (F-01,
  F-03); Playwright has no shell (JS-04); `--det` forces Vitest and Jest serial (JS-07); skip with proof reuses
  wrong results when umask, RLIMIT_NOFILE, CPU affinity, PYTHONPATH outside the root or PYTHONWARNINGS change (F-05);
  no L1 options (`--det-threads`, `--det-async`) exist (PY-07).

## 1. What was installed (F-09)

One source: artifact `engine-linux-x64` (id 14618872581) of release-1 CI run **44714888645**,
commit `644a455bd19a`, installed with that commit's `release/install-image.sh`. `fenvix version`:
`fenvix release-1;detpy 0.1.0;detjs 0.1.0;fenvix-go present;fenvix-skip present;fenvix-agent.jar present;`. Today's `claude/release-1` head (`1ae6ca25`) differs from that commit only in `sessions/` and two
`harness/node_cache/results` files (MEASURED, `git diff --stat`): no engine code, so this is today's engine.

| artifact file | sha256 |
|---|---|
| `detjs.linux-x64.node` | `051e1e7aff71a4cb7e98ad7c8cbca186eb8bcf3f1858bad1242ca74cc9eb5e45` |
| `detpy-0.1.0-cp39-abi3-linux_x86_64.whl` | `846247d74f42beeff4aa343fcb1c624bd5065c875b98fa174146722eada03d57` |
| `fenvix-agent.jar` | `736d7a58c5ec9e89e6c57dad37a9f1d3121b39b39e3f101a7534403662ab3c89` |
| `fenvix-go` | `1d7a207c4aec5df0f7da95e0eec03cbed6cf9294c3d66b5217a93e9c9d305494` |
| `fenvix-skip` | `821e8864cb65fb608c689fe22583476ec2eb8837ab733e855c15d6ec543dc1a0` |
| `libfenvix_go.a` | `719cdd02525572904404ec608c16abfcba1d48932b26fbc529b091f0d7accc66` |

The artifact ships no version or checksum manifest of its own, and `fenvix version` does not name the release commit
(F-09.artifact-identity FAIL, G-0251).

## 2. Runs

The exam ran as one full round plus targeted reruns; `exam/aggregate.py` takes each row from the newest run that
ran it (`exam/rerun.json`), so every row below names the run its result comes from. Every leg of every run installed
the same artifact (release run 44714888645).

| run | what it ran |
|---|---|
| 44724576354 | full round, all rows (the arm64/macOS/F-10 legs of that round are dropped by the founder decision) |
| 44736459205 | rerun PY-03/04/07, JS-01/02/03/04/05/08, F-09 after harness fixes and the founder decision |
| 44744172110 | rerun PY-03, PY-04, F-02, F-03 |
| 44749567573 | rerun F-01, F-03, F-05, F-06, PY-07, PY-04, JS-05 (checks made discriminating); writes `exam/results.json` |

Earlier runs 44720217778, 44720347544, 44722424318, 44723603952, 44749374335 and 44749402853 were cancelled or
superseded while the harness was calibrated (section 6); they are not used.

## 3. Rows

| row | verdict | checks passed | legs | in-scope gaps (closed / open / no check) | run ids |
|---|---|---|---|---|---|
| PY-01 | **PASS** | 15/15 | 3 | 0 (0 / 0 / 0) | 44724576354 |
| PY-02 | **FAIL** | 8/12 | 2 | 1 (0 / 1 / 0) | 44724576354 |
| PY-03 | **FAIL** | 9/30 | 2 | 8 (0 / 8 / 0) | 44744172110 |
| PY-04 | **FAIL** | 6/8 | 2 | 0 (0 / 0 / 0) | 44749567573 |
| PY-05 | **FAIL** | 6/16 | 2 | 9 (1 / 8 / 0) | 44724576354 |
| PY-06 | **FAIL** | 18/22 | 2 | 0 (0 / 0 / 0) | 44724576354 |
| PY-07 | **FAIL** | 2/14 | 2 | 13 (0 / 13 / 0) | 44749567573 |
| PY-08 | **PASS** | 14/14 | 2 | 6 (6 / 0 / 0) | 44724576354 |
| JS-01 | **PASS** | 15/15 | 3 | 0 (0 / 0 / 0) | 44736459205 |
| JS-02 | **FAIL** | 27/36 | 4 | 13 (9 / 4 / 0) | 44736459205 |
| JS-03 | **FAIL** | 9/18 | 1 | 12 (0 / 12 / 0) | 44736459205 |
| JS-04 | **FAIL** | 0/10 | 1 | 27 (0 / 27 / 0) | 44736459205 |
| JS-05 | **FAIL** | 10/18 | 2 | 0 (0 / 0 / 0) | 44749567573 |
| JS-06 | **FAIL** | 5/12 | 1 | 16 (3 / 13 / 0) | 44724576354 |
| JS-07 | **FAIL** | 4/8 | 2 | 0 (0 / 0 / 0) | 44724576354 |
| JS-08 | **PASS** | 8/8 | 4 | 0 (0 / 0 / 0) | 44736459205 |
| JS-09 | **PASS** | 6/6 | 2 | 1 (1 / 0 / 0) | 44724576354 |
| F-01 | **FAIL** | 9/33 | 1 | 40 (4 / 36 / 0) | 44749567573 |
| F-02 | **FAIL** | 3/17 | 1 | 16 (0 / 16 / 0) | 44744172110 |
| F-03 | **FAIL** | 2/18 | 1 | 11 (0 / 11 / 0) | 44749567573 |
| F-05 | **FAIL** | 34/56 | 2 | 25 (10 / 15 / 0) | 44749567573 |
| F-06 | **FAIL** | 16/24 | 2 | 6 (3 / 3 / 0) | 44749567573 |
| F-09 | **FAIL** | 6/8 | 1 | 2 (0 / 2 / 0) | 44736459205 |
| F-18 | **FAIL** | 3/5 | 1 | 1 (1 / 0 / 0) | 44724576354 |

"In-scope gaps": the audit gaps assigned to the row; "closed" = every check covering the gap passed.

## 4. Failing checks per row (observation of the first failing leg; full text in results.json)

### PY-01: PASS

Every check passed on every leg.

### PY-02: FAIL

* `PY-02.cache2.pytest9.more-itertools` (py3.13/node22/pytest9): run 2 reused 328 of 670 passing (needed >= 335); outcomes vs plain: 671 engine / 671 plain outcomes; differing 0 []; missing in engine 0 []; extra 0
* `PY-02.probe.modifyitems` (py3.13/node22/pytest8, py3.13/node22/pytest9): 2 engine / 2 plain outcomes; differing 1 ['tests/test_exam_modify.py::test_a_slow']; missing in engine 0 []; extra 0
* `PY-02.cache2.pytest8.more-itertools` (py3.13/node22/pytest8): run 2 reused 328 of 670 passing (needed >= 335); outcomes vs plain: 671 engine / 671 plain outcomes; differing 0 []; missing in engine 0 []; extra 0

### PY-03: FAIL

* `PY-03.django.det2` (py3.12/node22, py3.14/node22): verify: rc=1 summary={"runs": 2, "tests": 7, "stable": 2, "diverged": 5, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {"entropy": 4, "thread": 1}}; plain {'rc': 0, 'ran': 7} vs engine {'rc': 0, 'ran': 7}
* `PY-03.django.cache2` (py3.12/node22, py3.14/node22): run 2 reused 0; rc plain=0 run1=0 run2=0
* `PY-03.nose2.det2` (py3.12/node22, py3.14/node22): verify: rc=1 summary={"runs": 2, "tests": 331, "stable": 327, "diverged": 4, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {"entropy": 2, "time": 2}}; plain {'rc': 0, 'ran': 331} vs engine {'rc': 0, 'ran': 331}
* `PY-03.ward.det2` (py3.12/node22, py3.14/node22): verify: rc=1 summary={"runs": 2, "tests": 389, "stable": 275, "diverged": 114, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {"entropy": 114}}; plain {'rc': 0} vs engine {'rc': 0}
* `PY-03.ward.cache2` (py3.12/node22, py3.14/node22): run 2 reused 0; rc plain=0 run1=0 run2=0
* `PY-03.zope.det2` (py3.12/node22, py3.14/node22): verify: rc=0 summary={"runs": 2, "tests": 1365, "stable": 1365, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; plain {'rc': 0, 'ran': 1361} vs engine {'rc': 0, 'ran': 1365}
* `PY-03.doctest.cache2` (py3.12/node22, py3.14/node22): run 2 reused 0; rc plain=0 run1=0 run2=0
* `PY-03.repro` (py3.12/node22, py3.14/node22): `fenvix repro --help` rc=2 (fenvix: unknown command 'repro' (fenvix --help)); engine `python -m detpy repro` has a --runner option: False (pytest only otherwise)
* `PY-03.probe.django-file-cache` (py3.12/node22, py3.14/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `PY-03.probe.ward-fixture` (py3.12/node22, py3.14/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `PY-03.nose2.cache2` (py3.14/node22): run 2 reused 91; rc plain=0 run1=1 run2=1

### PY-04: FAIL

* `PY-04.det2.django-model-utils` (py3.12/node22, py3.14/node22): verify: rc=1 summary={"runs": 2, "tests": 350, "stable": 346, "diverged": 4, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {"entropy": 4}}; outcomes vs plain: 350 engine / 350 plain outcomes; differing 0 []; missing in engine 0 []; e

### PY-05: FAIL

* `PY-05.cache2` (py3.12/node22, py3.14/node22): run 2 reused 0 of 1322 passing (needed >= 661); outcomes vs plain: 1330 engine / 1330 plain outcomes; differing 0 []; missing in engine 0 []; extra 0
* `PY-05.odpair` (py3.12/node22, py3.14/node22): plain {'tests/test_exam_odpair.py::test_a_setter': 'passed', 'tests/test_exam_odpair.py::test_b_victim': 'passed'}; differing modes: {'n2': {'tests/test_exam_odpair.py::test_b_victim': 'failed', 'tests/test_exam_odpair.py::test_a_setter': 'passed'}, 'n4': {'te
* `PY-05.probe.isolate` (py3.12/node22, py3.14/node22): 3 engine / 3 plain outcomes; differing 1 ['tests/test_exam_iso.py::test_b_victim']; missing in engine 0 []; extra 0
* `PY-05.probe.testrun-uid` (py3.12/node22, py3.14/node22): values ["'c954fd8cc79445cabf95608440a7c173'", "'8c1382b90c0a422c8d4e54345242b9a4'"]; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `PY-05.probe.xdist-old` (py3.12/node22, py3.14/node22): rc=3; INTERNALERROR: True; names the xdist version: False

### PY-06: FAIL

* `PY-06.time-machine.det2` (py3.12/node22, py3.14/node22): verify: rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; outcomes vs plain: engine run produced no outcome map
* `PY-06.time-machine.cache2` (py3.12/node22, py3.14/node22): run 2 reused 0 of 97 passing (needed >= 48); outcomes vs plain: engine run produced no outcome map

### PY-07: FAIL

* `PY-07.options` (py3.12/node22, py3.14/node22): options present: {'--det-threads': False, '--det-async': False}
* `PY-07.probe-stable` (py3.12/node22, py3.14/node22): INCONCLUSIVE (the race did not show in 8 plain runs): distinct outcome sets over 8 runs (plain, --det): {'thread_race': (1, 1), 'executor_race': (1, 1)}
* `PY-07.verify-honest` (py3.12/node22, py3.14/node22): INCONCLUSIVE: one outcome over 8 --det runs ((('tests/test_exam_thread_race.py::test_thread_race', 'passed'),)): the race was not exercised, nothing to judge
* `PY-07.probe.lock-type` (py3.12/node22, py3.14/node22): det rc=1; 1 engine / 1 plain outcomes; differing 1 ['tests/test_exam_locktype.py::test_lock']; missing in engine 0 []; extra 0
* `PY-07.probe.repro-sched` (py3.12/node22, py3.14/node22): `fenvix repro` rc=2: fenvix: unknown command 'repro' (fenvix --help)
* `PY-07.anyio-det2` (py3.14/node22): verify: trace missing (False, False); outcomes vs plain: plain run produced no outcomes
* `PY-07.probe.leaked-thread` (py3.14/node22): verify rc=1 summary={"runs": 2, "tests": 2, "stable": 0, "diverged": 2, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {"thread": 2}}; test_b named diverging: True

### PY-08: PASS

Every check passed on every leg.

### JS-01: PASS

Every check passed on every leg.

### JS-02: FAIL

* `JS-02.cache2.vitest3.zustand` (py3.13/node22/vitest3): run 2 reused 0 (needed >= 67 of 135 passing); outcomes vs plain: 12 files / 139 tests in plain; differing files 0 []
* `JS-02.probe.browser-mode` (py3.13/node22/jest29, py3.13/node22/jest30, py3.13/node22/vitest3, py3.13/node22/vitest4): NOT IMPLEMENTED in this exam version: the gap stays open
* `JS-02.probe.jasmine2` (py3.13/node22/jest29, py3.13/node22/jest30, py3.13/node22/vitest3, py3.13/node22/vitest4): NOT IMPLEMENTED in this exam version: the gap stays open

### JS-03: FAIL

* `JS-03.mocha.det2.express` (py3.13/node22): verify: rc=1 summary={"runs": 2, "tests": 1288, "stable": 1265, "diverged": 23, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {"entropy": 23}}; outcomes vs plain: engine rc=1 counts={'passed': 1287, 'failed': 1}; plain rc=0 counts={'
* `JS-03.mocha.cache2.express` (py3.13/node22): run 2 reused 122 (needed >= 1 of 1288 passing); outcomes vs plain: engine rc=1, plain rc=0 counts={'passed': 1288}
* `JS-03.ava.det2.p-map` (py3.13/node22): verify: rc=0 summary={"runs": 2, "tests": 49, "stable": 49, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; outcomes vs plain: engine rc=1 counts={'failed': 1}; plain rc=0 counts={'passed': 49}
* `JS-03.ava.cache2.p-map` (py3.13/node22): run 2 reused 48 (needed >= 1 of 49 passing); outcomes vs plain: engine rc=1, plain rc=0 counts={'passed': 49}
* `JS-03.jasmine.det2.jasmine-npm` (py3.13/node22): verify: rc=0 summary={"runs": 2, "tests": 252, "stable": 252, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; outcomes vs plain: engine rc=3 counts={'failed': 252}; plain rc=0 counts={'passed': 406, 'failed': 0}
* `JS-03.jasmine.cache2.jasmine-npm` (py3.13/node22): run 2 reused 191 (needed >= 1 of 406 passing); outcomes vs plain: engine rc=2, plain rc=0 counts={'passed': 406, 'failed': 0}
* `JS-03.deno-test.det2.oak` (py3.13/node22): verify: rc=0 summary={"runs": 2, "tests": 10, "stable": 10, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; outcomes vs plain: engine rc=1 counts={'passed': 6, 'failed': 0}; plain rc=1 counts={}
* `JS-03.probe.bun-deno-reuse` (py3.13/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `JS-03.probe.file-only-failure` (py3.13/node22): plain bun rc=1; trace outcomes [['passed', 'passed']]

### JS-04: FAIL

* `JS-04.shell` (py3.13/node22): rc=2; prints detjs usage: True
* `JS-04.det2` (py3.13/node22): plain rc=0; verify: trace missing (False, False)
* `JS-04.browser-clock` (py3.13/node22): page values [None, None]
* `JS-04.probe.browser-tz` (py3.13/node22): values [None, None]
* `JS-04.probe.browser-version` (py3.13/node22): trace header: ''
* `JS-04.probe.cache2` (py3.13/node22): runs (rc, reused, refusal named): [(2, 0, False), (2, 0, False)]
* `JS-04.probe.page-apis` (py3.13/node22): values [None, None]
* `JS-04.probe.page-network` (py3.13/node22): values [None, None]
* `JS-04.probe.webserver` (py3.13/node22): values [None, None]
* `JS-04.probe.workers` (py3.13/node22): trace missing (False, False)

### JS-05: FAIL

* `JS-05.esm-ava.det2.p-map` (py3.13/node22, py3.13/node24): verify: rc=0 summary={"runs": 2, "tests": 49, "stable": 49, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; outcomes vs plain: engine rc=1 counts={'failed': 1}; plain rc=0 counts={'passed': 49}
* `JS-05.esm-ava.cache2.p-map` (py3.13/node22, py3.13/node24): run 2 reused 48 (needed >= 1 of 49 passing); outcomes vs plain: engine rc=1, plain rc=0 counts={'passed': 49}
* `JS-05.cjs-mocha.det2.express` (py3.13/node22, py3.13/node24): verify: rc=1 summary={"runs": 2, "tests": 1288, "stable": 1262, "diverged": 26, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {"entropy": 23, "time": 3}}; outcomes vs plain: engine rc=1 counts={'passed': 1287, 'failed': 1}; plain rc=
* `JS-05.cjs-mocha.cache2.express` (py3.13/node22, py3.13/node24): run 2 reused 122 (needed >= 1 of 1288 passing); outcomes vs plain: engine rc=1, plain rc=0 counts={'passed': 1288}

### JS-06: FAIL

* `JS-06.jsdom-vitest.cache2.zustand` (py3.13/node22): run 2 reused 0 (needed >= 67 of 135 passing); outcomes vs plain: 12 files / 139 tests in plain; differing files 0 []
* `JS-06.jsdom-jest.cache2.tabbable` (py3.13/node22): run 2 reused 0 (needed >= 5 of 10 passing); outcomes vs plain: 2 files / 10 tests in plain; differing files 0 []
* `JS-06.tz-locale` (py3.13/node22): values ['["Thu Jan 01 1970 00:00:00 GMT+0000 (Coordinated Universal Time)","UTC","en-US","1,234.5"]', '["Thu Jan 01 1970 09:00:00 GMT+0900 (Japanische Normalzeit)","Asia/Tokyo","de-DE","1.234,5"]']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "div
* `JS-06.probe.global-shape` (py3.13/node22): plain ["undefined","undefined","function"] / det ["function","undefined","function"]
* `JS-06.probe.iframe-realm` (py3.13/node22): values differ ['[1795175061464,0.27921272580877976]', '[1795175062222,0.47181480212676496]']; verify must report divergence: rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons
* `JS-06.probe.jsdom-clock` (py3.13/node22): values differ ['[1735689600016,"01/01/2025 00:00:00",1735689600016,1795175062651.445,16.66966666662597]', '[1735689600016,"01/01/2025 00:00:00",1735689600016,1795175063438.634,16.66966666662597]']; verify must report divergence: rc=0 summary={"runs": 2, "tests
* `JS-06.probe.subtle-key` (py3.13/node22): values differ ['[150,162,89,31,193,18,159,58]', '[143,67,95,132,34,229,46,20]']; verify must report divergence: rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}

### JS-07: FAIL

* `JS-07.kept` (py3.13/node22, py3.13/node26): files announced while the first file ran: 1 (per file: [1, 2, 3, 4]); engine says serial: True
* `JS-07.jest-kept` (py3.13/node22, py3.13/node26): rc=1; engine forces serial/in-band: True

### JS-08: PASS

Every check passed on every leg.

### JS-09: PASS

Every check passed on every leg.

### F-01: FAIL

* `F-01.random.pinned.python` (py3.13/node22): values ["[0.4555560149625728, 'b4c4e182-1716-43ab-b306-9deddd1f3462']", "[0.4555560149625728, '13afd6d1-add1-4a3b-b074-567f2af7ad4d']"]; verify rc=1 summary={"runs": 2, "tests": 1, "stable": 0, "diverged": 1, "missing": 0, "outcome_unstable": 0, "order_identic
* `F-01.env.pinned.python` (py3.13/node22): values ["'a'", "'b'"]; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.env.pinned.node` (py3.13/node22): values ['"a"', '"b"']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.tz.pinned.python` (py3.13/node22): values ["['2024-04-16T21:19:20.000001+00:00', '00 UTC']", "['2024-04-17T06:19:20.000001+09:00', '09 JST']"]; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.tz.pinned.node` (py3.13/node22): values ['["Thu Jan 01 1970 00:00:00 GMT+0000 (Coordinated Universal Time)",0,"UTC"]', '["Thu Jan 01 1970 09:00:00 GMT+0900 (Japan Standard Time)",9,"Asia/Tokyo"]']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_
* `F-01.locale.pinned.python` (py3.13/node22): values ["[('C', 'UTF-8'), '1234.5']", "[('de_DE', 'UTF-8'), '1.234,5']"]; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.locale.pinned.node` (py3.13/node22): values ['["1,234.5","en-US"]', '["1.234,5","de-DE"]']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.hostname.pinned.python` (py3.13/node22): values ["['runnervmeozm8', 'runnervmeozm8']", "['exam-other-host', 'exam-other-host']"]; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.hostname.pinned.node` (py3.13/node22): values ['"runnervmeozm8"', '"exam-other-host"']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.cpu-count.pinned.python` (py3.13/node22): values ['4', '1']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.cpu-count.pinned.node` (py3.13/node22): values ['4', '1']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.real-projects.luxon-tz` (py3.13/node22): outcomes NY vs Kolkata under --det equal: False (rc 1/1); verify rc=1 summary={"runs": 2, "tests": 1116, "stable": 1108, "diverged": 8, "missing": 0, "outcome_unstable": 8, "order_identical": true, "reasons": {"outcome-only": 4, "random": 4}}
* `F-01.probe.c-wait` (py3.13/node22): det rc=1; 1 engine / 1 plain outcomes; differing 1 ['tests/test_exam_cwait.py::test_wait']; missing in engine 0 []; extra 0
* `F-01.probe.cassette` (py3.13/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `F-01.probe.cassette-redact` (py3.13/node22): record rc=0; cassette files ['cassette.json']; secret present in clear/base64: True
* `F-01.probe.cold-warm` (py3.13/node22): values ['[[10, 14, 4, 6, 15, 8, 0, 5, 3, 7, 2, 11, 1, 9, 12, 19, 17, 13, 18, 16], [352, 48992, 1920, 456416, 272]]', '[[12, 14, 4, 8, 3, 19, 15, 10, 0, 5, 9, 2, 13, 1, 11, 6, 17, 7, 18, 16], [352, 48992, 1728, 456608, 272]]']; verify rc=0 summary={"runs": 2, "
* `F-01.probe.fake-timers` (py3.13/node22): values ['1795183770991', '1795183771662']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.probe.mtime` (py3.13/node22): python: det rc=1; 1 engine / 1 plain outcomes; differing 1 ['tests/test_exam_mtime.py::test_mtime']; missing in engine 0 []; extra 0; node: 1 files / 1 tests in plain; differing files 1 ['test/exam-mtime.test.ts']
* `F-01.probe.node-clock-sources` (py3.13/node22): values ['[0.20481392,1795183785869.481,205.338939,1000.001,"1000000002000"]', '[0.206120452,1795183786548.273,206.651858,1000.001,"1000000002000"]']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "
* `F-01.probe.node-vm` (py3.13/node22): values ['[0.2971408587486053,1795183787532]', '[0.9613562695372706,1795183788198]']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-01.probe.replay-clients` (py3.13/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `F-01.probe.service-host` (py3.13/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `F-01.probe.timeit` (py3.13/node22): det rc=timeout; engine run produced no outcome map
* `F-01.probe.timer-consistency` (py3.13/node22): 1 files / 1 tests in plain; differing files 1 ['test/exam-timers.test.ts']

### F-02: FAIL

* `F-02.cli` (py3.12/node22): `fenvix <cmd> --help` exit codes {'repro': 2, 'explore': 2, 'replay': 2}
* `F-02.py-repro.idoft-accessify` (py3.12/node22): `fenvix repro` rc=2 replay command printed: []; (evidence only: `python -m detpy repro` rc=0, replay printed: ['pytest --det --det-seed=5 --det-order=.detpy/repro/test_implements_no_implementation_getter-8f379f06/order.txt'], tail:   first diverging event vs a
* `F-02.py-explore.idoft-accessify` (py3.12/node22): `fenvix explore --budget 5` rc=2; target named: False
* `F-02.py-repro.idoft-mdutils` (py3.12/node22): `fenvix repro` rc=2 replay command printed: []; (evidence only: `python -m detpy repro` rc=0, replay printed: ['pytest --det --det-order=.detpy/repro/test_create_md_file-f87fe7e0/order.txt'], tail:   first diverging event vs a passing run: outcome-only: identi
* `F-02.py-explore.idoft-mdutils` (py3.12/node22): `fenvix explore --budget 5` rc=2; target named: False
* `F-02.py-repro.idoft-krllint` (py3.12/node22): `fenvix repro` rc=2 replay command printed: []; (evidence only: `python -m detpy repro` rc=0, replay printed: ['pytest --det --det-seed=21 --det-order=.detpy/repro/test_rule_without_fix-7173b585/order.txt'], tail:   first diverging event vs a passing run: outc
* `F-02.py-explore.idoft-krllint` (py3.12/node22): `fenvix explore --budget 5` rc=2; target named: False
* `F-02.py-repro.idoft-py-autodoc` (py3.12/node22): `fenvix repro` rc=2 replay command printed: []; (evidence only: `python -m detpy repro` rc=1, replay printed: [], tail: detpy repro: examples/test_gen_each_case.py::TestUnittest::test_foo_bar: not-found /   51 pytest runs, 156.42 s)
* `F-02.py-replay.idoft-py-autodoc` (py3.12/node22): not run: neither `fenvix repro` nor the engine's own repro printed a replay command
* `F-02.py-explore.idoft-py-autodoc` (py3.12/node22): `fenvix explore --budget 5` rc=2; target named: False
* `F-02.node-repro` (py3.12/node22): `fenvix repro` on a Vitest test rc=2; `fenvix node repro` rc=2 (usage: detjs vitest/jest/node-test/mocha/bun-test/deno-test/tap/ava/jasmine/uvu [--det options] [run)
* `F-02.node-replay` (py3.12/node22): `fenvix replay` rc=2; `fenvix node replay` rc=2: no Node bundle to replay exists because no Node repro writes one
* `F-02.node-explore` (py3.12/node22): rc=2: fenvix: unknown command 'explore' (fenvix --help)
* `F-02.probe.numpy-repro` (py3.12/node22): `fenvix repro` rc=2: fenvix: unknown command 'repro' (fenvix --help)

### F-03: FAIL

* `F-03.tz.python` (py3.13/node22): values ["['2024-04-16T21:19:20.000001+00:00', '00 UTC']", "['2024-04-17T06:19:20.000001+09:00', '09 JST']"]; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; f
* `F-03.node-tz` (py3.13/node22): values ['["Thu Jan 01 1970 00:00:00 GMT+0000 (Coordinated Universal Time)",0,"UTC"]', '["Thu Jan 01 1970 09:00:00 GMT+0900 (Japan Standard Time)",9,"Asia/Tokyo"]']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_
* `F-03.locale.python` (py3.13/node22): values ["[('C', 'UTF-8'), '1234.5']", "[('de_DE', 'UTF-8'), '1.234,5']"]; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; first divergent events []
* `F-03.node-locale` (py3.13/node22): values ['["1,234.5","en-US"]', '["1.234,5","de-DE"]']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; first divergent events []
* `F-03.env.python` (py3.13/node22): values ["'a'", "'b'"]; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; first divergent events []
* `F-03.node-env` (py3.13/node22): values ['"a"', '"b"']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; first divergent events []
* `F-03.child` (py3.13/node22): values ['a\n', 'b\n']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; first divergent []
* `F-03.thread` (py3.13/node22): INCONCLUSIVE: one outcome over 6 runs (the race was not exercised); verify rc=0
* `F-03.node-child` (py3.13/node22): values ['"a\\n"', '"b\\n"']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}; first []
* `F-03.node-random` (py3.13/node22): async crypto values differ ['[[108,239,143,188,96,82,1,90],670093]', '[[133,236,165,38,179,13,43,205],366455]']; verify must report divergence: rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identic
* `F-03.node-thread` (py3.13/node22): worker values ['0.8171746970981311', '0.4835741003352225']; verify rc=0 summary={"runs": 2, "tests": 1, "stable": 1, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}}
* `F-03.probe.multi-project` (py3.13/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `F-03.probe.node-sched` (py3.13/node22): 10 completion orders over 10 runs; verify rc=0 (must not be 0)
* `F-03.probe.numpy` (py3.13/node22): values ['0.12916905879044205', '0.12916905879044205']; verify rc=1 summary={"runs": 2, "tests": 1, "stable": 0, "diverged": 1, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {"entropy": 1}}
* `F-03.probe.realm-failure` (py3.13/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `F-03.probe.zero-tests` (py3.13/node22): NOT IMPLEMENTED in this exam version: the gap stays open

### F-05: FAIL

* `F-05.wrong-reuse.cpu-count` (py3.12/node22, py3.14/node22): run1 ['passed']; after changing cpu-count: reused 1; vs plain: 1 engine / 1 plain outcomes; differing 1 ['tests/test_exam_wr_cpu_count.py::test_cpu']; missing in engine 0 []; extra 0
* `F-05.wrong-reuse.umask` (py3.12/node22, py3.14/node22): run1 ['passed']; after changing umask: reused 1; vs plain: 1 engine / 1 plain outcomes; differing 1 ['tests/test_exam_wr_umask.py::test_umask']; missing in engine 0 []; extra 0
* `F-05.wrong-reuse.rlimit` (py3.12/node22, py3.14/node22): run1 ['passed']; after changing rlimit: reused 1; vs plain: 1 engine / 1 plain outcomes; differing 1 ['tests/test_exam_wr_rlimit.py::test_rlimit']; missing in engine 0 []; extra 0
* `F-05.wrong-reuse.hostname` (py3.12/node22, py3.14/node22): run1 ['passed']; after changing hostname: reused 0; vs plain: plain run produced no outcomes
* `F-05.wrong-reuse.pythonpath` (py3.12/node22, py3.14/node22): run1 ['passed']; after changing pythonpath: reused 1; vs plain: 1 engine / 1 plain outcomes; differing 1 ['tests/test_exam_wr_pythonpath.py::test_outside']; missing in engine 0 []; extra 0
* `F-05.wrong-reuse.pythonwarnings` (py3.12/node22, py3.14/node22): run1 ['passed']; after changing pythonwarnings: reused 1; vs plain: 1 engine / 1 plain outcomes; differing 1 ['tests/test_exam_wr_pythonwarnings.py::test_warn']; missing in engine 0 []; extra 0
* `F-05.probe.audit-rerun` (py3.12/node22, py3.14/node22): --det-cache-audit in `fenvix python --help`: False
* `F-05.probe.blockbuster` (py3.12/node22, py3.14/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `F-05.probe.custom-reporter` (py3.12/node22, py3.14/node22): NOT IMPLEMENTED in this exam version: the gap stays open
* `F-05.probe.import-side-effect` (py3.12/node22, py3.14/node22): 2 engine / 2 plain outcomes; differing 1 ['tests/test_exam_ise_b.py::test_dump']; missing in engine 0 []; extra 0
* `F-05.probe.numpy` (py3.12/node22, py3.14/node22): reused 0 of 2 numpy tests on an unchanged checkout

### F-06: FAIL

* `F-06.no-edit` (py3.13/node22, py3.13/node26): run 2 reused 0 (needed >= 121 of 135 passing); outcomes vs plain: 12 files / 139 tests in plain; differing files 0 []
* `F-06.fake-timers` (py3.13/node22, py3.13/node26): deadline passed between runs; run 2 reused 1; vs plain: 1 files / 1 tests in plain; differing files 1 ['test/exam-fake-timers.test.ts']
* `F-06.disable-time` (py3.13/node22, py3.13/node26): deadline passed between runs; run 2 reused 1; vs plain: 1 files / 1 tests in plain; differing files 1 ['test/exam-disable-time.test.ts']
* `F-06.probe.dir-listing` (py3.13/node22, py3.13/node26): NOT IMPLEMENTED in this exam version: the gap stays open

### F-09: FAIL

* `F-09.artifact-identity` (py3.13/node22): checksum/version manifest shipped in the artifact: none; `fenvix version` names the release commit: False (fenvix release-1 / detpy 0.1.0 / detjs 0.1.0)
* `F-09.job-venv` (py3.13/node22): `fenvix python --det` in the job's own venv: rc=4:   rootdir: /home/runner/work/_temp/exam-work/src/itsdangerous-jobvenv

### F-18: FAIL

* `F-18.help` (py3.13/node22): rc=0; commands missing from --help: ['repro', 'explore', 'replay']
* `F-18.subcommands` (py3.13/node22): exit codes {'repro': 2, 'explore': 2, 'replay': 2, 'verify': 0, 'version': 0}



## 5. Gaps

* `exam/gap_map.json` classifies all 639 WRONG-RESULT / BLOCKS-USE gaps of the audit (G-*, `claude/gap-audit`
  37f7de22): 207 in scope (row + check), 410 out of scope (reason each; 46 of them by the founder decision), 15 F-14
  (MCP server: listed, not examined), 7 unassignable: G-0205, G-0242, G-0561 (repository default branch: no engine
  behaviour), G-0252, G-0259, G-0260, G-0273 (documentation of repro/explore/quickstart: no engine behaviour; the
  features are checked by F-02).
* Closed (38): G-0016, G-0018, G-0019, G-0020, G-0022, G-0023, G-0031, G-0034, G-0078, G-0079, G-0080, G-0086, G-0087, G-0088, G-0089, G-0094, G-0095, G-0096, G-0098, G-0103, G-0120, G-0121, G-0127, G-0128, G-0159, G-0173, G-0268, G-0309, G-0310, G-0318, G-0399, G-0401, G-0402, G-0403, G-0404, G-0453, G-0461, G-0513.
  Several of these were closed already on release-1 by fixes after the audit (for example G-0173, G-0453, G-0461).
* Every open gap and the check that keeps it open: `exam/results.json` → `gaps`.

## 6. Limits of this exam (read before trusting a PASS or a FAIL)

* **14 probes are not implemented** (each recorded FAIL "NOT IMPLEMENTED", so its gaps stay open):
  F-01.probe.cassette, replay-clients, service-host; F-03.probe.multi-project, realm-failure, zero-tests;
  F-05.probe.blockbuster, custom-reporter; F-06.probe.dir-listing; JS-02.probe.browser-mode, jasmine2;
  JS-03.probe.bun-deno-reuse; PY-03.probe.django-file-cache, ward-fixture.
* **INCONCLUSIVE (recorded FAIL):** PY-07.probe-stable, PY-07.verify-honest, F-03.thread. The thread and executor races
  did not show even in 8 plain runs on the runners, so the probes could not judge L1 (PY-07 fails anyway: the L1
  options do not exist).
* **Baseline failures (the plain runner fails too, recorded FAIL):** PY-03.ward on Python 3.14 (ward does not run on
  3.14), PY-07.anyio-det2 on 3.14 (the project's test dependencies do not install on 3.14), F-05.wrong-reuse.hostname
  (the plain reference run under `sudo unshare` produced no outcome map: the exam's own limit; F-01.hostname shows the
  engine side: host name not pinned, verify identical).
* **Substitutions after calibration** (PLAN.md records them): PY-02 attrs instead of click (click 8.1.8 does not
  collect under pytest 9), JS-06 tabbable instead of dom-testing-library (no longer installs), uvu via lukeed/clsx with
  `-r tsx/cjs` (the `esm` loader the uvu projects use is broken on Node 22), django-model-utils with its own `SQLITE=1`
  switch, zope.interface installed non-editable.
* **EDIT checks pass on "no stale outcome"**; reuse is measured and reported, and required only when one test file
  is edited (a source module or conftest can legitimately be an input of every test).
* **Virtual-day probes** run both runs under `faketime` (`+0d`, then `+1d`), so only the date differs.
* Runner capacity on the account allowed about one to three Linux jobs at a time; a full round takes about 2 hours
  (ESTIMATED from runs 44724576354 and 44736459205).

## 7. How to run

* Push to `claude/exam` (paths `exam/**`, the workflow) → `.github/workflows/exam.yml`: one job per leg of
  `exam/legs.json` (46 legs), then the aggregate commits `exam/results.json`.
* Rerun some rows on top of earlier runs: `exam/rerun.json` `{"base_runs": [...], "rows": [...]}`.
* Locally: `python3 exam/run.py --rows PY-01 --work /tmp/x --out /tmp/x/out.json` with `fenvix` on PATH and
  `EXAM_WHEEL` set to the artifact's wheel.
* The PR into `claude/release-1` touches only `exam/`, `.github/workflows/exam.yml` and this report.
