# Go-live acceptance exam: plan

Branch `claude/exam` of fenvix-engine-cli. The exam decides "closed" for every go-live row. It takes the customer's
view: the engine is installed the way a customer would install it, it runs real public projects pinned by commit on
GitHub Actions, on every platform and version the row names, and each check states its expected result before it runs.

Labels: **MEASURED** (an Actions run id), **ESTIMATED**, **DECLARED** (with the source), **UNKNOWN**.

## 0. How the exam runs

* **Install source: one switch.** `EXAM_INSTALL=ci-artifact` (today, default): download the artifact
  `engine-linux-x64` of the newest `release-1.yml` run on `claude/release-1` whose `build` job succeeded, check out
  `release/` and `node/` at that run's commit, and run `release/install-image.sh` (the documented runner-image
  install). `EXAM_INSTALL=packages` (later): `pip install fenvix` and `npm install -D fenvix`, nothing else. The
  exam records the release-1 commit and run id it installed. If no artifact exists for the job's platform (today:
  only Linux x86_64 is built), the install fails and every check of that leg is FAIL with reason `install`.
* **Driver:** `exam/run.py --rows ROW[,ROW] --leg LEG --out FILE` runs the checks of the rows on one leg
  (platform x Python x Node x runner version). Each check writes `{id, row, leg, ok, expected, observed, evidence,
  gaps}`; logs are uploaded as artifacts. `exam/aggregate.py` merges every leg into `exam/results.json`:
  per row `PASS` only when every check passed on every leg the row names, with the Actions run id and job ids.
* **Workflow:** `.github/workflows/exam.yml` (push on `claude/exam`, `workflow_dispatch`). One job per row x leg;
  the last job aggregates and commits `exam/results.json` back to `claude/exam`.
* **Commands are the customer's:** every engine call goes through the single entry `fenvix ...` installed on
  `PATH`. Where the go-live promise names a command that the CLI does not offer (for example `fenvix repro`), the check
  calls exactly that command and FAILs; it also records (as evidence, not as a pass) whether the engine has the
  capability under another name (`python -m detpy repro`).
* **Reference result:** "outcome equals" always means: the per-test outcome map of the engine run equals the map of a
  plain run of the same runner on the same checkout (pytest `--junitxml`, Vitest/Jest JSON reporters, TAP/exit status
  and counts for other runners), with the same tests collected.
* **Calibration:** the harness was run locally against a locally built release-1 engine before the Actions rounds; harness bugs found there were fixed, engine behaviour was never "fixed" in the exam.
* **Gap checks:** every in-scope WRONG-RESULT and BLOCKS-USE gap of the audit (2026-11-20, `gaps.jsonl`) is assigned
  to one row in `exam/gap_map.json` and covered by at least one check named there. Gap checks that need a specific
  behaviour (a TZ difference, a changed host name) are *probe tests*: a small test file written into a pinned real
  project's checkout (as a customer's own test would be), run through the customer's commands. Out-of-scope gaps (Go,
  JVM, service, landing, Windows, Python <= 3.11, other CIs, ...) and gaps that fit no row are listed in
  `exam/gap_map.json` with the reason.

Platforms (F-09): `linux-x64` = `ubuntu-24.04`, `linux-arm64` = `ubuntu-24.04-arm`, `macos-arm64` = `macos-15`.
Versions: Python 3.12, 3.13, 3.14; Node 22, 24, 26.

Standard check families used below (each is one check per project and leg):

* **DET2** `fenvix <shell> --det --det-trace=T1 ...` twice, then `fenvix verify T1 T2`: exit 0, 0 divergent,
  0 missing; and the outcome map equals the plain run's.
* **CACHE2** `--det-cache=DIR` twice on an unchanged checkout: the second run reuses >= 1 test (>= 50% of passing
  tests) with proof, and every reused outcome equals the plain run's.
* **EDIT** `--det-cache=DIR` run 1; apply edit X; run 2: the tests that depend on X run (at least the tests that a
  plain run shows changed outcome), the others are reused; every outcome of run 2 equals a plain full run of the edited
  checkout (no stale reuse).

## 1. Python rows

### PY-01 Python versions (CPython 3.12, 3.13, 3.14)

Legs: {linux-x64, linux-arm64, macos-arm64} x {3.12, 3.13, 3.14}.
Projects: `pallets/itsdangerous@096c8d42` (2.2.0), `python-attrs/attrs@3dca08ce` (25.3.0).

| check | expected |
|---|---|
| PY-01.install | install succeeds; `fenvix version` prints the detpy version; `fenvix python --help` lists `--det` |
| PY-01.det2 | DET2 on both projects |
| PY-01.cache2 | CACHE2 on both projects |
| PY-01.gaps | gap probes assigned to PY-01 (`gap_map.json`) |

### PY-02 pytest 8 and 9 (unittest via pytest)

Legs: linux-x64 x Python 3.13 x {pytest 8.4.x, pytest 9.0.x}.
Projects: `python-attrs/attrs@3dca08ce` (25.3.0, pytest), `more-itertools/more-itertools@28ab7367` (v10.7.0,
`unittest.TestCase` suites collected by pytest). (click 8.1.8 was the first choice; it does not collect under pytest 9, plain or not.)

| check | expected |
|---|---|
| PY-02.det2 | DET2 on both projects with each pytest major |
| PY-02.cache2 | CACHE2 on both projects with each pytest major |
| PY-02.seed | `--det --det-seed=7` twice: same executed order digest, outcomes equal |
| PY-02.gaps | assigned gap probes |

### PY-03 other Python runners

Legs: linux-x64 x {3.12, 3.14}.

| runner | project | command (customer) |
|---|---|---|
| unittest (`python -m detpy`) | more-itertools@28ab7367 | `fenvix python-runner unittest --det discover -s tests` |
| Django `manage.py test` | `wagtail/bakerydemo@890285b9` | `fenvix python-runner django manage.py test --det` |
| nose2 | `nose-devs/nose2@9ec19c0c` (0.15.1) | `fenvix python-runner nose2 --det` |
| ward | `darrenburns/ward@f41c6164` (0.68.0b0) | `fenvix python-runner ward --det test` |
| zope.testrunner | `zopefoundation/zope.interface@d860f651` (7.2) | `fenvix python-runner zope-testrunner --det --test-path=src` |
| doctest | `pytoolz/toolz@07f30a9c` (1.0.0) | `fenvix python-runner doctest --det toolz/itertoolz.py ...` |

| check | expected |
|---|---|
| PY-03.<runner>.det2 | DET2 (trace verify identical; exit status and pass/fail counts equal the plain runner's) |
| PY-03.<runner>.cache2 | CACHE2 |
| PY-03.<runner>.repro | `fenvix repro <test id> --runner <runner>` exists and, on an injected order-dependent pair, fails 10/10 with one fingerprint and prints a replay command (go-live: repro is a product feature, not pytest only) |
| PY-03.gaps | assigned gap probes |

### PY-04 pytest-django

Legs: linux-x64 x {3.12, 3.14}. Project: `jazzband/django-model-utils@aeef1088` (5.0.0, pytest-django, sqlite).

| check | expected |
|---|---|
| PY-04.det2 | DET2 |
| PY-04.cache2 | CACHE2 |
| PY-04.edit | EDIT: change one model's default in `tests/models.py`; dependent tests rerun, outcomes equal a plain rerun |
| PY-04.order | `--det-seed=3`: pytest-django's group order kept (TestCase before TransactionTestCase), outcomes equal |
| PY-04.gaps | assigned gap probes |

### PY-05 pytest-xdist parallel

Legs: linux-x64 x {3.12, 3.14}, linux-arm64 x 3.13. Project: attrs@3dca08ce and an injected order-dependent pair
(probe `odpair`: `test_a` sets a module global, `test_b` asserts it; in collection order b passes).

| check | expected |
|---|---|
| PY-05.det2 | `--det -n 2` twice: traces verify identical; outcomes equal the serial `--det` run |
| PY-05.n4 | `--det -n 4` outcomes equal `-n 2` and serial |
| PY-05.cache2 | `--det --det-cache -n 2` twice: reuse >= 1, outcomes equal serial plain |
| PY-05.odpair | the order-dependent pair has the same verdict serial, `-n 2`, `-n 4`, `--det-cache -n 2` (G-0172, G-0175, G-0176) or the engine refuses with a named reason |
| PY-05.gaps | assigned gap probes |

### PY-06 plugins (pytest-asyncio, pytest-mock, pytest-cov, freezegun, time-machine)

Legs: linux-x64 x {3.12, 3.14}.

| plugin | project |
|---|---|
| pytest-asyncio | `aio-libs/aiosignal@f90f6d41` (v1.3.2) |
| pytest-mock | `pytest-dev/pytest-mock@8733134b` (v3.14.0) |
| pytest-cov | itsdangerous@096c8d42 with `--cov=itsdangerous` |
| freezegun | `spulec/freezegun@3f9fac48` (1.5.1) |
| time-machine | `adamchainz/time-machine@731c9456` (2.16.0) |

| check | expected |
|---|---|
| PY-06.<plugin>.det2 | DET2 |
| PY-06.<plugin>.cache2 | CACHE2 |
| PY-06.cov-report | under `--det` the coverage report is produced and equals the plain run's covered lines |
| PY-06.gaps | assigned gap probes |

### PY-07 asyncio and threads (Level 1)

Legs: linux-x64 x {3.12, 3.14}. Projects: `agronholm/anyio@a6e9ebb7` (4.9.0, Block 2 flaky set), plus probes
`thread_race` (two threads increment a shared counter without a lock, assert == 40000) and `async_executor_race`
(two `run_in_executor` jobs append to a list; assert order) (G-0180, G-0518).

| check | expected |
|---|---|
| PY-07.options | the L1 options exist (`--det-threads`, `--det-async`) in `fenvix python --help` |
| PY-07.probe-stable | 8 runs of each probe under `--det` (with the L1 options): one outcome and one fingerprint |
| PY-07.verify-honest | without L1, `fenvix verify` of runs whose thread / executor order differed reports divergence (never "identical") |
| PY-07.anyio-det2 | DET2 on anyio `tests/test_taskgroups.py tests/test_synchronization.py` (asyncio backend) |
| PY-07.gaps | assigned gap probes |

### PY-08 native code and subprocesses are never reused

Legs: linux-x64 x {3.12, 3.14}, macos-arm64 x 3.13. Probes injected into itsdangerous@096c8d42:
`child_reads_file` (a test asserts the output of `subprocess.run(["cat", F])`), `ctypes_clock` (`libc.time()`
compared with a fixed date), `ctypes_getenv` (`libc.getenv("X")`), `native_ext` (a C extension, `_testcapi`/`zlib`
with an input file outside the root).

| check | expected |
|---|---|
| PY-08.child | run 1 cache (pass); change F; run 2: the test is not reused (it reruns and fails like a plain run) |
| PY-08.ctypes-env | run 1 with X=a (pass); run 2 with X=b: not reused, fails like plain |
| PY-08.ctypes-clock | a test reading the C clock is never reused with proof |
| PY-08.gaps | assigned gap probes |

## 2. Node rows

### JS-01 Node versions (22, 24, 26)

Legs: {linux-x64, linux-arm64, macos-arm64} x {22, 24, 26}.
Projects: `simple-statistics/simple-statistics@f9d368f4` (v7.9.3, node:test-compatible), `unjs/ufo@0f15ddc6`
(v1.5.4, Vitest).

| check | expected |
|---|---|
| JS-01.install | install succeeds; `fenvix version` prints detjs |
| JS-01.det2 | DET2 on both |
| JS-01.cache2 | CACHE2 on both |
| JS-01.gaps | assigned gap probes |

### JS-02 Vitest 3/4, Jest 29/30

Legs: linux-x64 x Node 22 x {vitest 3, vitest 4, jest 29, jest 30}.
Projects: ufo@0f15ddc6 and `pmndrs/zustand@3f9127f4` (v5.0.3) for Vitest; `moment/luxon@a4044fe6` (3.5.0) and
`typestack/class-validator@adffae38` (v0.14.1) for Jest. The runner major is installed over the project's pin
(`npm i -D vitest@3` / `@4`, `jest@29` / `@30`).

| check | expected |
|---|---|
| JS-02.<runner>.det2 | DET2 |
| JS-02.<runner>.cache2 | CACHE2 |
| JS-02.<runner>.seed | `--det --det-seed=5` twice: same order digest, outcomes equal |
| JS-02.gaps | assigned gap probes |

### JS-03 other JS runners

Legs: linux-x64 x Node 22 (Bun latest 1.x, Deno 2.x).

| runner | project |
|---|---|
| Mocha | `expressjs/express@1faf2289` (4.21.2) |
| node:test | simple-statistics@f9d368f4 |
| AVA | `sindresorhus/p-map@2ba3a002` (v7.0.3) |
| tap | `isaacs/minimatch@0569cd33` (v10.0.1) |
| uvu | `lukeed/dequal@37d4f27d` (v2.0.3) |
| Jasmine | `jasmine/jasmine-npm@2cd62ca5` (v5.5.0, with `jasmine@5` installed as a customer would) |
| Bun | `elysiajs/elysia@353efd2a` (1.2.10) |
| Deno | `oakserver/oak@08a7eb1c` (v17.1.4) |

| check | expected |
|---|---|
| JS-03.<runner>.det2 | DET2 (exit status and counts equal plain) |
| JS-03.<runner>.cache2 | CACHE2, and the cached run keeps the runner's process model (G-0145..G-0149: no failure that plain does not show) |
| JS-03.gaps | assigned gap probes |

### JS-04 Playwright Test with Chromium

Legs: linux-x64 x Node 22. Project: `mxschmitt/playwright-test-coverage@910da570` (Playwright Test, Chromium).

| check | expected |
|---|---|
| JS-04.shell | `fenvix node playwright test --det` exists (not the usage text) |
| JS-04.det2 | DET2 on the Chromium project |
| JS-04.browser-clock | a probe spec reading `Date.now()` and `Math.random()` in the page gives the same values in two `--det` runs |
| JS-04.gaps | assigned gap probes |

### JS-05 ESM, CommonJS, TypeScript via the runner

Legs: linux-x64 x {22, 24}. ESM: p-map@2ba3a002 (AVA) and ufo (Vitest, TS); CJS: express@1faf2289 (Mocha);
TS: class-validator@adffae38 (Jest + ts-jest).

| check | expected |
|---|---|
| JS-05.<kind>.det2 | DET2 |
| JS-05.<kind>.cache2 | CACHE2 |
| JS-05.ts-edit | EDIT on class-validator: change one decorator's message in `src/`; dependent test files rerun, outcomes equal plain |
| JS-05.gaps | assigned gap probes |

### JS-06 jsdom and happy-dom

Legs: linux-x64 x Node 22. Projects: zustand@3f9127f4 (Vitest + jsdom; and the same suite with
`--environment happy-dom`), `focus-trap/tabbable@8e8df70b` (master 2026-11-20, Jest 30 + jsdom; dom-testing-library v10.4.0 was the first choice and no longer installs without a lockfile).

| check | expected |
|---|---|
| JS-06.<env>.det2 | DET2 |
| JS-06.<env>.cache2 | CACHE2 |
| JS-06.tz-locale | a probe test printing `new Date().toString()` and `Intl.DateTimeFormat().resolvedOptions()` in jsdom gives the same values under TZ=UTC/LANG=C and TZ=Asia/Tokyo/LANG=de_DE.UTF-8 |
| JS-06.gaps | assigned gap probes |

### JS-07 JS parallel

Legs: linux-x64 x {22, 26}. Projects: ufo (Vitest, threads/forks pools), luxon (Jest `-w 2`).

| check | expected |
|---|---|
| JS-07.kept | under `--det` the run uses more than one worker (a probe records `process.pid` / `VITEST_POOL_ID` / `JEST_WORKER_ID` per file: >= 2 distinct) |
| JS-07.det2 | DET2 with the parallel run |
| JS-07.cache2 | CACHE2 with the parallel run |
| JS-07.gaps | assigned gap probes |

### JS-08 package managers (npm, pnpm, yarn without PnP)

Legs: linux-x64 x Node 22 x {npm, pnpm, yarn classic, yarn berry `nodeLinker: node-modules`}. Project: ufo.

| check | expected |
|---|---|
| JS-08.<pm>.add | `<pm> add -D fenvix` succeeds and `<pm> exec fenvix version` runs (packages; fails today: nothing published) |
| JS-08.<pm>.det2 | with the project installed by that manager, DET2 through `fenvix node vitest` |
| JS-08.<pm>.cache2 | CACHE2 |
| JS-08.gaps | assigned gap probes |

### JS-09 native addons, worker threads, child processes are never reused

Legs: linux-x64 x {22, 26}. Probes injected into ufo (Vitest): `child_random` (a test asserts the stdout of
`execFileSync("cat", [F])`), `worker_reads_file` (a `worker_threads` worker reads F and posts it), `native_env`
(`process.binding`-free native read: `os.hostname()` and an env var read in a child).

| check | expected |
|---|---|
| JS-09.child | run 1 cache (pass); change F; run 2: not reused, fails like plain |
| JS-09.worker | same through a worker thread |
| JS-09.native | a test whose result depends on a native read that changed is not reused |
| JS-09.gaps | assigned gap probes |

## 3. Feature rows

### F-01 deterministic run: clock, randomness, order, network, files, env, TZ, locale

Legs: linux-x64 x Python 3.13 x Node 22, plus macos-arm64. Probes, each written into itsdangerous (Python) and ufo
(Vitest) and luxon (Jest): `clock` (prints `time.time()` / `Date.now()`), `random` (`random.random()` /
`Math.random()`, `uuid4` / `crypto.randomUUID`), `order` (asserts collection order; seed run), `network` (connects to
an external host), `files` (`os.listdir` / `fs.readdirSync` of a directory created in reverse order), `env` (reads an
env var `EXAM_X`), `tz` (`datetime.now().astimezone()`, `new Date().toString()`), `locale`
(`locale.setlocale(LC_ALL,"")`, `Intl.NumberFormat().format(1234.5)`), `hostname`, `cpu-count`.

| check | expected |
|---|---|
| F-01.<source>.pinned | two `--det` runs whose machines differ only in that source (real time 2 s apart; env `EXAM_X=a/b`; `TZ=UTC/Asia/Tokyo`; `LANG=C.UTF-8/de_DE.UTF-8`; files created in two orders; network reachable vs not) give the same printed value and the same outcome, and `fenvix verify` says identical |
| F-01.real-projects | DET2 on luxon (TZ- and locale-heavy) under TZ=America/New_York vs TZ=Asia/Kolkata: outcomes equal and traces identical |
| F-01.gaps | assigned gap probes |

### F-02 flaky test to reproducible defect (`fenvix repro`, `fenvix explore`, `fenvix replay`)

Legs: linux-x64 x Python 3.12 x Node 22, plus macos-arm64 (replay of a Linux bundle on a Mac). Python: the Block 2
sets (harness/flaky_candidates.json, pins from Block 1): `dmytrostriletskyi/accessify@6b7cf865`,
`didix21/mdutils@2ef859ec`, `d4nuu8/krllint@2f9376cd`, `heavenshell/py-autodoc@001d5ff0` with their Block 2
targets (harness/block2_targets.json). Node: an order-dependent pair injected into ufo (Vitest) and luxon (Jest),
and the Node flaky set of harness/node (Block 2 Node) where it installs.

| check | expected |
|---|---|
| F-02.cli | `fenvix repro`, `fenvix explore`, `fenvix replay` exist (`--help` exit 0) |
| F-02.py-repro | for each Python target: `fenvix repro <test>` fails 10/10 with one fingerprint, names the polluter, prints a replay command |
| F-02.py-replay | the printed replay command (printed by `fenvix repro`, or else by the engine's internal `python -m detpy repro`, recorded as such), run 10 times through `fenvix python`, fails 10/10 and the 10 traces verify identical |
| F-02.py-explore | `fenvix explore --budget 5` on the project finds the target and writes a bundle |
| F-02.node-repro / node-replay / node-explore | the same for the Node pairs |
| F-02.mac-replay | the Linux bundle replays on macOS with the same fingerprint (or the engine says why not) |
| F-02.gaps | assigned gap probes |

### F-03 verifier: first divergent event

Legs: linux-x64 x Python 3.13 x Node 22.

| check | expected |
|---|---|
| F-03.identical | two identical `--det` runs: identical, exit 0 |
| F-03.tz | two runs differing only in TZ: divergent, and the first divergent event is the TZ / local-time event |
| F-03.locale | same for LANG |
| F-03.env | same for an env var the test reads |
| F-03.child | same for a child process whose output differs |
| F-03.thread | same for a thread order that differs |
| F-03.random | a test using unseeded `os.urandom` (beyond L0) in two runs: divergent at the entropy event |
| F-03.node-* | the same five for Node |
| F-03.gaps | assigned gap probes |

### F-05 cache with proof, Python, serial and parallel

Legs: linux-x64 x {3.12, 3.14}. Projects: itsdangerous@096c8d42, click@934813e4, attrs@3dca08ce.

| check | expected |
|---|---|
| F-05.edit-src | EDIT: change one function in `src/` (a real behaviour change that flips >= 1 test); serial and `-n 2` |
| F-05.edit-test | EDIT on one test file |
| F-05.edit-conftest | EDIT on `conftest.py` / a fixture |
| F-05.edit-data | EDIT on a data file read by a test |
| F-05.dep-bump | change an installed dependency's version: dependent tests rerun |
| F-05.no-edit | CACHE2: >= 90% reused, 0 differing outcomes |
| F-05.wrong-reuse probes | G-0160 cpu count, G-0161 umask, G-0162 rlimit, G-0163 host name, G-0164 PYTHONPATH outside the root, LD_PRELOAD, PYTHONWARNINGS: a test whose result depends on the input is not reused when the input changes (outcome equals plain) |
| F-05.order-dep | G-0173: a passing order-dependent test stays passing under `--det-cache` when its dependency must rerun |
| F-05.gaps | assigned gap probes |

### F-06 cache with proof, Node

Legs: linux-x64 x {22, 26}. Projects: ufo (Vitest), zustand (Vitest), luxon (Jest), class-validator (Jest).

| check | expected |
|---|---|
| F-06.edit-src / edit-test / no-edit | as F-05 |
| F-06.fake-timers | G-0122: a test reading the real clock through fake timers is not reused across days |
| F-06.disable-time | G-0123 |
| F-06.wrong-reuse probes | env var, host name, cpu count, child process output, worker output |
| F-06.gaps | assigned gap probes |

### F-09 platforms (Linux x86_64 and arm64, macOS Apple Silicon)

Legs: {linux-x64, linux-arm64, macos-arm64} x Python 3.13 x Node 22.

| check | expected |
|---|---|
| F-09.install-py / install-node | the install source provides the platform's engine and it installs |
| F-09.py-det2 / py-cache2 | DET2 / CACHE2 on itsdangerous |
| F-09.node-det2 / node-cache2 | DET2 / CACHE2 on ufo |
| F-09.cross-replay | a trace from linux-x64 verifies identical against the same run on the other platform (or the engine names the platform difference) |
| F-09.gaps | assigned gap probes |

### F-10 install (`pip install fenvix`, `npm install -D fenvix`)

Legs: every platform x {Python 3.12, 3.14} x {Node 22, 26}. Always from the public registries, regardless of the
switch.

| check | expected |
|---|---|
| F-10.pip | `pip install fenvix` in a fresh venv succeeds; the installed package is ours (`fenvix version` prints the engine) and `pytest --det` works |
| F-10.npm | `npm install -D fenvix` in a fresh project succeeds; `npx fenvix version` prints the engine |
| F-10.not-foreign | `pip install detpy` does not shadow ours (G-0170): after `pip install fenvix`, `import detpy` is our module |
| F-10.gaps | assigned gap probes |

### F-18 one `fenvix` CLI

Legs: linux-x64 x Python 3.13 x Node 22.

| check | expected |
|---|---|
| F-18.on-path | after the install, `fenvix` is on `PATH` |
| F-18.help | `fenvix --help` lists python, node, repro, explore, replay, verify, version |
| F-18.subcommands | each of `fenvix repro --help`, `fenvix explore --help`, `fenvix replay --help`, `fenvix verify --help`, `fenvix version` exits 0 |
| F-18.detect | `fenvix detect` on a Python and a Node project names the language |
| F-18.one-verify | `fenvix verify` reads a Python trace and a Node trace (same format) |
| F-18.gaps | assigned gap probes |

## 4. Outputs

* `exam/results.json`: `{installed: {source, release_commit, release_run}, rows: {ROW: {status: PASS|FAIL, legs, checks:
  [{id, leg, ok, expected, observed, run_id, job}], gaps: [G-xxxx]}}, unassigned_gaps: [...]}`.
* `exam/gap_map.json`: every WRONG-RESULT / BLOCKS-USE gap: `{row, check}` or `{out_of_scope: reason}` or
  `{unassignable: reason}`.
* Report: `sessions/2026-11-20-exam/REPORT.md` on `claude/exam`.

## 5. Gap probes

`exam/gap_map.json` names 62 probe checks (`<ROW>.probe.<slug>`, spec in the file). `exam/probes.py` implements most
of them; a probe that is not implemented is recorded as FAIL with the observation "NOT IMPLEMENTED", so the gaps it
covers stay open. The virtual-day probes (F-05.probe.real-clock, F-06.probe.virtual-day) move the clock one day with
`faketime` (installed on the Linux legs).
