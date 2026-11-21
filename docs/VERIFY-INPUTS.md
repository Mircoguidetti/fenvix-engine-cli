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

- **C code of an extension or a native addon that calls `getenv` itself** (not through ctypes): not observed. A
  variable read this way and changed between runs can leave the test IDENTICAL. No test.
- **Python: a read outside any test after the trace opened** (a session finalizer after the last test, a
  `pytest_sessionfinish` hook): not listed in the header (the header is written at the end of collection). No test.
- **Node: reads by the runner configuration's dependencies** (a package `vitest.config.*` imports that reads the
  environment): not counted; only the project's own code is. No test.
- **`Deno.env`, `Bun.env`**: covered by the conservative rule above (every differing variable counts as read), but
  no attack test runs here (no Deno or Bun in the test environment).
- **The command line and the working directory** (`sys.argv`, `process.argv`, `os.getcwd()`): the runner and its
  arguments are run inputs on Node (`cli_args`); on Python a test reading `sys.argv` is not observed. No test.
- **Python: a live endpoint is marked, not compared**: a test talking to a local service is never identical, even
  when the service answered the same (Node compares the stream instead). Conservative, not a false IDENTICAL.
