# What `fenvix verify` knows about a test's inputs

`fenvix verify` compares two or more `--det` runs of one checkout. It reports a test IDENTICAL only when the runs had
the same run inputs (the trace header's `inputs`) and the test observed the same events. This page lists every way a
test can read its environment or its inputs, in Python and Node, and the rule verify applies to each.

The invariant every channel is held to: **verify says IDENTICAL only if the test observed the same value in both runs.**
A channel `--det` controls gives the test the same value in every run, so IDENTICAL is true. Every other channel must
make the test differ (an event with the value, a run input the test is known to read, or an uncontrolled-source mark)
whenever what the test saw differs.

Each channel has an attack test that changes only that channel between two runs and checks the invariant:

- Python: `tests/test_verify_inputs_attacks.py` (case name in the table)
- Node: `node/test/verify-inputs-attacks.test.js` (case name in the table)

Environment variables are run inputs (`env:NAME`, a digest of the value; design A: CI-volatile variables are pinned or
never inputs, `docs/CLI.md`). A variable whose value differs makes the tests that read it `input-differs` (exit 3),
never identical. Which tests read it is what the channels below establish.

## Environment variables

| channel | Python | Node | rule | attack test |
|---|---|---|---|---|
| read in the test body | `os.environ[...]`, `.get`, `os.getenv`, `os.environb` | `process.env.X` | an `env.get`/`env.has` event naming the variable at its site | py `body-os.environ`, `body-os.getenv`, `body-os.environb`; node `body process.env` |
| enumeration | `dict(os.environ)`, `os.environ.copy()`, iteration | `{...process.env}`, `Object.entries(process.env)` | an `env.list` event: the test reads every variable | py `body-enumeration`; node `body enumeration`, `body Object.entries` |
| `posix.environ` | `posix.environ.get(b"X")` | n/a | `posix.environ` is a recording view over the same data as `os.environ` | py `body-posix.environ` |
| C `getenv` through ctypes | `CDLL(None).getenv(b"X")` | n/a | ctypes' `getenv`/`secure_getenv` are recorded like `os.getenv` | py `native-getenv` |
| module scope of a test file | `V = os.environ.get(...)` at import | `const V = process.env.X` at the top of the file | a read outside any test: the header lists its name (`env_read_outside_tests`) and verify counts it as read by every test | py `module-scope`; node `module scope` |
| conftest / setup files | `conftest.py` at import, `pytest_configure` and other hooks before the trace opens | Vitest `setupFiles` | read outside any test (as above) | py `conftest-module-scope`, `conftest-hook`; node `vitest setupFiles` |
| hooks and fixtures | fixtures of every scope (`function`, `class`, `module`, `session`) run inside a test's setup: events of that test | `before`/`beforeAll` (outside any test), `beforeEach` (inside the test) | events of the test whose setup runs them, or outside reads | py `fixture-function`, `fixture-class`, `fixture-module`, `fixture-session`; node `before hook`, `vitest beforeAll`, `vitest beforeEach` |
| the runner's configuration | n/a (pytest options are run inputs: `runner`, `seed`, ...) | `vitest.config.*` and globalSetup run in the main process | the project's own reads in the main process are outside reads; the runner's and its dependencies' are not (they are not the project's) | node `vitest config file` |
| a dependency at import | a module the test file imports | a package the test file imports | read outside any test (as above) | py `dependency-at-import`; node `dependency at import` |
| a dependency imported in the test | `import` inside the test | `await import(...)` inside the test | events of the test | py `dependency-lazy-import`; node `dependency imported in the test` |
| a thread | `threading.Thread` | `worker_threads` | the test is marked `uncontrolled.thread`: never identical | py `body-in-a-thread`; node `worker thread` |
| a child process | `subprocess`, `os.system` | `child_process` | the test is marked `uncontrolled.child`: never identical; its output is an event | py `child-process`; node `child process` |
| `Deno.env`, `Bun.env` | n/a | Deno and Bun tests | their environment APIs are not recorded: the header says `env_reads_recorded: false`, and verify counts every differing variable as read by every test | **no test** (Deno, Bun not installed in the test environment) |

## Files

| channel | Python | Node | rule | attack test |
|---|---|---|---|---|
| a file outside the project | `open()` | `fs.readFileSync`, `fs.readFile`, `fs.promises.readFile`, descriptors | an event with the path and the digest of the bytes read | py `file-outside-the-project`; node `file outside the project` |
| a file of the project (fixture, data) | `open()`, `pathlib.read_text()` | as above | an event with the relative path and the digest (`fs.read` on Node) | py `file-in-the-project`; node `file in the project` |

## Time, entropy, machine

| channel | rule | attack test |
|---|---|---|
| wall clock, monotonic clock, timers | virtual under `--det`: the same values in every run | py `time`; node `time` |
| seeded generators | `random`, `Math.random`, numpy... seeded: the same values | node `Math.random` |
| OS entropy | Python: controlled by default (`--det-entropy=observe` leaves it real, and each read is an `[entropy]` event); Node: `crypto.randomBytes` & co. observed unless `--det-urandom`, each read an event | py `entropy`, `entropy-observed`; node `entropy (crypto.randomBytes)` |
| host name | pinned to `localhost` | py `hostname`; node `hostname` |
| CPU count | pinned to 2 (the engine keeps the real one) | py `cpu-count`; node `cpu count` |
| time zone, locale | pinned (`--det-tz=UTC`, `--det-locale=C.UTF-8`), or with `keep` a run input | py `time-zone`, `locale`; node `time zone` |

## Network

| channel | rule | attack test |
|---|---|---|
| an external host | closed: blocked, or recorded and replayed from the cassette (a request that differs from the recording is refused) | `tests/test_network*.py`, `node/test/network-p041.test.js` |
| a live endpoint the closed network lets through (localhost, an allowed host, a unix socket) | Python: the test is marked `uncontrolled.net` (never identical), unless the endpoint is a socket this process listens on (the test's own server). Node: the connection is an event (`net.connect ... local`) and so is its stream (`net.stream`: digests of the bytes sent and received) | py `network-localhost`; node `network localhost` |

## Gaps

Channels the rules above do not cover, or that have no attack test:

- **C code of an extension module that calls `getenv` or reads files itself** (imported normally, not through
  ctypes): not observed. A library loaded through ctypes is (`uncontrolled.native` in a test; the `native` input
  outside one, which makes every test NOT PROVEN). No test for extension modules.
- **Modules imported inside a test** (after the header): not in the `code`/`deps` inputs; their reads are events
  as usual. No test.
- **Node: reads by the runner configuration's dependencies** (a package `vitest.config.*` imports): not counted;
  only the project's own code is. No test.
- **Node: ESM-only dependencies**: the `deps` input lists the CommonJS modules a test process loaded. No test.
- **`Deno.env`, `Bun.env`**: covered by the conservative rule (every differing variable counts as read), but no attack
  test runs here (no Deno or Bun in the test environment).
- **Python: a live endpoint is marked, not compared**: a test talking to a local service is never identical, even
  when the service answered the same (Node compares the stream instead). Conservative, not a false IDENTICAL.
- **`resource.getrusage` (V14)**: its memory and I/O counters are an event; the R-055 attack's precondition (two runs
  with different `ru_maxrss`) did not hold on the local machine (MEASURED: equal), so that case is decided by CI.

## Channels added by review R-055 (2026-11-21, on 688e4fe)

Channels missing from the tables above, or listed with a rule that does not hold. Each has a failing attack test:
Python `tests/test_review_r055_verifier.py` (case `V…`), Node `node/test/review-r055.test.js` (case name). On 688e4fe
every one of them gives IDENTICAL (exit 0) although the test observed two different values (MEASURED).

| # | channel | Python | Node | what happens on 688e4fe |
|---|---|---|---|---|
| V1 | a CI-volatile variable the test reads (`TMPDIR`, `PWD`, `GITHUB_WORKSPACE`, `RUNNER_TEMP`, … `VOLATILE_KEPT`) | `V1-volatile-env-TMPDIR` | `volatile TMPDIR through process.env` | no run input and no value in the event: IDENTICAL |
| V2 | a proxy variable read while the network is closed (`HTTPS_PROXY`, …) | `V2-proxy-env-closed-network` | `proxy variable while the network is closed` | skipped as an input (`PROXY_ENV`), but the test process keeps and reads the real value: IDENTICAL |
| V3 | a file read outside any test: module scope of a test file, `conftest.py` at import, a project data file at import | `V3-file-at-module-scope`, `V3-project-file-at-module-scope`, `V3-file-in-conftest-import` | `file read at module scope`, `project file read at module scope` | file reads are events only inside a test; nothing like `env_read_outside_tests` exists for files: IDENTICAL |
| V4 | the code under test itself (an uncommitted edit; the header names no source digest) | `V4-test-code-changed-dirty-tree` | (same cause, not run) | IDENTICAL for two different test bodies |
| V5 | installed dependencies (site-packages, node_modules) | `V5-installed-dependency-changed` | `a dependency in node_modules changes` | no input covers the installed packages: IDENTICAL |
| V6 | file metadata: existence, mtime | `V6-file-exists`, `V6-file-mtime` | `fs.existsSync` (Node `fs.statSync().mtimeMs` is recorded: passes) | no event: IDENTICAL |
| V7 | a file read by C code (sqlite3) | `V7-sqlite-file` | (not run) | IDENTICAL |
| V8 | a live endpoint over UDP (localhost) | `V8-udp-localhost` | `udp to localhost` | neither marked nor recorded: IDENTICAL |
| V9 | a unix socket to a server of another process (the table above says: marked `uncontrolled.net`) | `V9-unix-socket` | passes (recorded) | Python: not marked: IDENTICAL |
| V10 | the command line (listed gap above) | `V10-runner-options` | passes (`cli_args`) | IDENTICAL |
| V11 | `os.environ._data` (the mapping under `os.environ`) | `V11-os.environ._data` | n/a | IDENTICAL (the header shows `env:ATK_V` differing) |
| V12 | a read after the header is written (`pytest_sessionfinish`; listed gap above) | `V12-pytest_sessionfinish` | Node `process.on('exit')`: passes | IDENTICAL |
| V13 | `str` hash without the re-exec (`--det-no-reexec`, or a machine where re-exec is impossible) | `V13-hash-without-reexec` | n/a | `hashseed: "<random>"` in both headers compares equal: IDENTICAL |
| V14 | resource usage (`resource.getrusage`) | `V14-rusage` | `process.memoryUsage`/`cpuUsage`: controlled (passes) | IDENTICAL |
| V15 | C code calling `getenv` itself (listed gap above) | `V15-native-getenv-in-C` | (not run) | IDENTICAL |
| V16 | `process.loadEnvFile('.env')` (a `.env` file read by C++) | n/a | `process.loadEnvFile (.env read in C++)` | IDENTICAL |

Channels checked that hold on 688e4fe (MEASURED, Python unless said): `os.listdir` outside the project, `os.open`/`os.read`
on a descriptor, `mmap`, `shutil.copyfile` then read, `tmp_path` (sequential runs), `os.getpid` (pinned 10000),
`id()` and set order of plain objects (with and without `--det-keep-aslr`), `uuid.uuid1`, `time.process_time`,
`time.clock_gettime`, `time.monotonic`, `time.perf_counter`, `datetime.now`, `time.thread_time`, `os.sched_getaffinity` /
`os.process_cpu_count`, a module-scope read under xdist (`-n 2`), a session fixture reading a file. Node: `os.tmpdir()`
and `os.homedir()` with `TMPDIR`/`HOME` changed, `fs.statSync().mtimeMs`, `fs.readdirSync`, `crypto.randomUUID`,
`crypto.getRandomValues`, `performance.timeOrigin`, `process.hrtime.bigint`, `process.pid`, `process.memoryUsage`,
`process.cpuUsage`, `os.freemem`, `os.uptime`, `Intl` locale with `LANG`/`LC_ALL` changed, `fetch` and `http.get` to
localhost, a unix socket, an env read in a `process.on('exit')` handler.

### Status of the R-055 channels in this branch

| # | rule now | attack |
|---|---|---|
| V1, V2 | a test that reads a CI-volatile kept variable or (closed network) a proxy variable is `uncontrolled.env`: NOT PROVEN, never identical (a project's `FENVIX_VOLATILE_ENV` names stay readable) | passes (Python, Node) |
| V3 | a file read outside any test is a run input `file:<path>` = its digest (Python: the header, the footer for reads after it, xdist workers through the controller; Node: every process, through the run directory) | passes (Python, Node) |
| V4, V5 | run inputs `code` (the project's modules and test files) and `deps` (other non-standard-library modules; Node: the CommonJS modules under node_modules each process loaded), with content digests | passes (Python, Node) |
| V6 | `os.stat`/`os.lstat` (and through them `os.path.*`, `pathlib`) and Node `existsSync`/`statSync`/`lstatSync` are events with what the caller asked (the kind for exists/is*, size, mtime, or all) | passes (Python, Node) |
| V7, V15 | `sqlite3.connect(file)`: the database file is read like a file (event or input); a library loaded through ctypes: `uncontrolled.native` (NOT PROVEN) | passes |
| V8, V9 | a datagram or a connection to a live endpoint (UDP, unix socket) is `uncontrolled.net`, from the frame that used it | passes (Python, Node) |
| V10 | run input `argv`: the options without per-run paths, parallel options and plugin switches | passes |
| V11 | `os.environ._data`, `os.environb._data` and `posix.environ` are one recording mapping | passes |
| V12 | what is read after the header (a session-finish hook) goes in the trace footer (`late`), merged by verify | passes |
| V13 | an input value `<random>` never compares equal | passes |
| V14 | `resource.getrusage`: an event with its real counters | precondition not met locally (see Gaps) |
| V16 | `process.loadEnvFile`: the `.env` file is read like a file | passes |
| E1 | explore exits 1 when a seed run died with no test result | passes |
| D1 | a verdict whose only differences are uncontrolled sources is NOT PROVEN, not DIVERGENT | Rust verify |
| D3 | repro: a test that kills the process is a failure (from the trace: the first test of the order that did not finish), with a fingerprint of its exit status | `tests/test_fenvix_cli.py::test_repro_finds_a_test_that_crashes_the_process` |
