# channels.md: what the engine records today, per channel

Static read of `fenvix-engine-cli` `origin/claude/release-1` at 9ac63d6 (2026-11-24). Nothing was run.
Scope: the **default proof run** (Level 0, `--det`, no `--det-cache`). Every cell says where an event lands:
**per-test** (an event in the test's own record), **run-level** (a field of the trace header), **`net.setup`**
(the count:digest carried into every later test of the same file, no host name), or **not recorded**.
`file:line` = release-1 9ac63d6. INFERRED = not shown by one line of code; the reasoning is given.

Each row has an id (`C-NN`). `incidents.csv` `channels_line` cites these ids.

## 1. Channel table

| id | channel | lang | inside a test body | outside test bodies (module import, collection, before-all) |
|---|---|---|---|---|
| C-01 | env read | Node | per-test `env.get` / `env.has` / `env.list` event, value `NAME=set/unset` (never the value) at the reading site, dependency sites included (`node/src/controls.js:182-210`, `:207`); reads whose site is runner infra are dropped (`:190-191`) | test worker process: **run-level**. `noteOutside` writes the name (or `*` for an enumeration) to `<run>/envout` for **every** reader, project or package; only the not-proven note is limited to the project (`node/src/controls.js:124-140`, `:129` vs `:133-138`); the header lists them as `env_read_outside_tests` (`node/src/session.js:384-393`, `:490`). Runner main process (the runner's config file, globalSetup): only reads whose first non-detjs frame is project code outside `node_modules` (`node/src/controls.js:148-176`, `:157`, `:173`), so a payload inside a dependency loaded there is **not recorded** |
| C-02 | env read | Python | per-test `env.get` / `env.has` / `env.list` (`python/detpy/envobs.py:41-74`, `:149-172`, record at `:157`, `:170`) | **run-level**. A read by project code **or a third-party package** (any frame that is not stdlib, detpy, pytest or a plugin: `python/detpy/envobs.py:88-103`) goes to `OUTSIDE` (header `env_read_outside_tests`, `python/detpy/_level0.py:537`), or, for a CI-volatile or proxy name (`ACTIONS_RUNTIME_TOKEN`, `ACTIONS_ID_TOKEN_REQUEST_TOKEN`, `SSH_AUTH_SOCK` ...: `python/detpy/_level0.py:45-53`; test at `python/detpy/envobs.py:126-137`), to `NOT_PROVEN_OUTSIDE` (header `not_proven_outside_tests`, `python/detpy/_level0.py:539-541`) (`python/detpy/envobs.py:113-123`, `:119`). Reads by pytest or a plugin go to `OUTSIDE` by name, but their enumerations (`*`) do not (`:120-123`) |
| C-03 | file read, project | Node | per-test `fs.read` `<path>\|<bytes>:<digest>` (`node/src/outside.js:20-26`, `:49-53`, `:97-99`); `node_modules/` and `.detjs/` excluded (`:26`) | **run-level** `files_read_outside_tests` (`node/src/outside.js:55-101`, header `node/src/session.js:448-454`, `:492`) when the reader is project code, or a dependency reading a project file while a module is being loaded (`node/src/outside.js:74-83`) |
| C-04 | file read, outside the project (`~/.npmrc`, `~/.aws/credentials`, `/home/...`) | Node | per-test `fs.read.outside` (`node/src/outside.js:27-31`, `:49-53`); installed with the `fs` control, on by default (`node/src/controls.js:38`, `node/src/config.js:6`) | project code: **run-level** `files_read_outside_tests` (`node/src/outside.js:80`, `:100`). A **dependency** reading a file outside the project: **not recorded** (`node/src/outside.js:81-83`: a dependency counts only for a project file; `<abs>/...` paths start with `<`) |
| C-05 | file read, project and outside | Python | per-test `fs.read` with path and digest, through an audit hook on `open` (every opener, C code going through Python I/O included) (`python/detpy/osstate.py:23-30`, `:380-392`) | **run-level** `files_read_outside_tests` (`python/detpy/osstate.py:385-386`, `:497-498`, header `python/detpy/_level0.py:529-534`) |
| C-06 | outbound connect | Node | per-test `net.connect` / `tls.connect` with host:port and `allowed` (default `--det-net=open`), `blocked` (`--det-net=closed`), `intercepted`, `record#n` or `replay#n` (`node/src/network.js:551`, `:689`, `:723`, `:735`, `:753`); bytes exchanged become `net.stream` digests at test end (`:21-24`) | test worker: the connection and its bytes go to the current file's set-up bucket (`node/src/network.js:217-223`, `:516-524`, `:339-346`) and appear as **`net.setup`** `file=<count>:<digest>` at the start of every **later test in the same file** (`:25`, `:401-406`, emitted on test start `:1005`). The bucket is reset when the next file starts (`FILE_KEY` reset per file, `:1196-1199`), so a payload that connects at import in a file with no later test leaves **nothing**. Runner main process: only external connections are recorded (`:215`), into the start-up summary that every later test carries as `startup=<count>:<digest>` (`:404`, `:408-410`, `:1201-1203`). No host name in `net.setup`. Connections whose site is runner infra are not tracked (`:721-722`) |
| C-07 | outbound connect | Python | per-test `net` events from the socket wrappers `_connect`, `_connect_ex`, `_sendto`, `_getaddrinfo` (`crates/detpy-py/src/network.rs:5-6`, record at `:385-389`); the connection is refused (closed network) and recorded | **not recorded**: an event is dropped when no test runs (`crates/detpy-py/src/level0.rs:712-713`, `:726-727`); Python has no `net.setup` equivalent (no match for `net.setup` under `python/detpy`, `crates/detpy-py/src`). The closed network still refuses the connection (process-wide policy, `python/detpy/network.py:991-993`), so the send fails, silently for the record |
| C-08 | DNS | Node | per-test `dns.lookup` / `dns.<op>` with `allowed` (open), `replay` or `blocked` (`node/src/network.js:885`, `:890`, `:893`, `:960-961`, `:988`, `:994`) | **not recorded**: `STATE.record` drops events when no test runs (`node/src/state.js:51-56`); DNS is not part of the set-up bucket (only tracked sockets are, `node/src/network.js:516-524`) |
| C-09 | DNS | Python | per-test, `_getaddrinfo` / `gethostbyname` wrappers (`crates/detpy-py/src/network.rs:5-6`) | **not recorded** (`crates/detpy-py/src/level0.rs:712-713`) |
| C-10 | child process | Node | one per-test `uncontrolled.child` event (+ `child.exit` / `child.result` digests); what the child does (its env reads, files, network) is **not traced** (`node/src/children.js:10-12`, `:34-39`, `:96-104`, `:111-115`); a Node process started by a test inherits the shell's preload but is classed `nested` and left alone (`node/src/runners/preload.js:2-5`, `:16`) | **not recorded**: no test id, no site, the wrapper passes through (`node/src/children.js:36`, `:97`, `:112-113`) |
| C-11 | child process | Python | one per-test `uncontrolled.child` event for `subprocess.Popen`, `os.system`, `os.posix_spawn*`, `os.fork*` (`python/detpy/uncontrolled.py:300-320`); the child is not traced | **not recorded** (`python/detpy/uncontrolled.py:127-132`: `_mark` returns when `nodeid is None`) |
| C-12 | native code | Node | a read of the environment or a file by a native addon (C/C++ `getenv`, `open`) does not go through `process.env` or `node:fs` and is **not recorded** (INFERRED: the env hook is on `process.env` only, `node/src/controls.js:47`, `:178-213`; the file hooks are on `node:fs` only, `node/src/outside.js:8-10`) | same: **not recorded** (INFERRED, same reason) |
| C-13 | native code | Python | `getenv` / `secure_getenv` looked up **through ctypes** (`CDLL(None).getenv`) are observed as env events (`python/detpy/envobs.py:175-177`); only **C extension code** calling libc `getenv` itself is not observed (`python/detpy/envobs.py:176-177`, `crates/detpy-py/src/capture.rs:1691`); file opens by C code that go through Python I/O are seen by the audit hook (`python/detpy/osstate.py:23-24`) | ctypes reads: run-level as C-02 (same `_note_value` path, `python/detpy/envobs.py:149-151`); C extension `getenv`: **not recorded**; loading a native library through ctypes outside a test: run-level `not_proven_outside_tests` `native:<name>` (`python/detpy/_level0.py:539`) |
| C-14 | install-time script, npm (`preinstall`, `install`, `postinstall`) | Node | n/a: installs do not run inside a test | **not recorded**. INFERRED: the engine is loaded only into the processes of the test command it starts (`detjs <runner>`: the session sets up its main process at `node/src/session.js:243-260` and the shells load `register` into the runner's processes, `node/src/session.js:246-248`, `node/src/register.js:4`); `npm install` / `npm ci` runs before, in a CI step the engine does not start. No `npm install` in `runner/` |
| C-15 | install-time script, pip (`setup.py`, build backend) | Python | n/a | **not recorded**. MEASURED by static read: the project and its dependencies are installed by `uv pip install` before detpy is used (`runner/ci-project-env.sh:22`, detpy installed at `:23`) |
| C-16 | Python `.pth` start-up file of an installed package | Python | n/a | **not recorded**. INFERRED: `site` executes `.pth` lines when the interpreter starts, before pytest loads its `pytest11` plugins (detpy is one: `pyproject.toml:41-42`), so detpy's hooks are not in place yet |
| C-17 | payload code inside a **runner-infra** package | Node | **not recorded**: an event whose site is runner infrastructure is dropped (`node/src/sites.js:9` `INFRA` = vitest, vite, jest-*, mocha, tap, ava, jasmine, uvu, ... ; `node/src/sites.js:66-69`; `node/src/state.js:66`; env: `node/src/controls.js:190-191`; network: `node/src/network.js:721-722`) | env names still reach `envout` (C-01, no site filter in `noteOutside`); network, files, children: not recorded |
| C-18 | payload code inside a runner-infra package | Python | **not recorded** (runner frames are skipped like pytest's: `python/detpy/envobs.py:100`, `_level0.INFRA_PACKAGES`, `pytest_*` modules) | env: a named read goes to `OUTSIDE` as a runner read (`python/detpy/envobs.py:120-123`), an enumeration does not; files and network: not recorded |

| C-19 | a GitHub Actions step, a CI workflow, a build step or a CLI run outside the test command | both | n/a | **not recorded**: the engine runs only inside the test command's process tree as it starts it (C-14, C-15); a separate CI step, a workflow file, a native build (`node-gyp`) or a CLI invocation is another process tree. INFERRED from the same evidence as C-14 |

Any of these verdicts is the rule the incident rows use as `NOT_FLAGGED (channel)`: C-07 (outside), C-08/C-09 (outside),
C-10/C-11 (outside, and everything the child does in either column), C-12, C-13 (C extension), C-14, C-15, C-16, C-17, C-18, C-19.

## 2. Run-level records (rule 3b `run_level`, note 1)

Every run-level record the default proof run writes, any of which counts for `scope = run_level`:

| record | lang | written at | read into the header at |
|---|---|---|---|
| `<run>/envout/<pid>.txt` -> `env_read_outside_tests` | Node | `node/src/controls.js:124-140` | `node/src/session.js:384-393`, `:490` |
| `<run>/filesout/<pid>.txt` -> `files_read_outside_tests` | Node | `node/src/outside.js:85-95` | `node/src/session.js:448-454`, `:492` |
| `<run>/npout/<pid>.txt` -> `not_proven_outside_tests` | Node | `node/src/controls.js:111-123` | `node/src/session.js:493` |
| run header `inputs` (`env:<NAME>` values of the run) | Node | `node/src/session.js:370-379` | same |
| `env_read_outside_tests` | Python | `python/detpy/envobs.py:113-123` (`OUTSIDE`) | `python/detpy/_level0.py:537` |
| `not_proven_outside_tests` (CI-volatile names: `ACTIONS_RUNTIME_TOKEN`, `ACTIONS_ID_TOKEN_REQUEST_TOKEN`, `SSH_AUTH_SOCK` ...; `native:<lib>`) | Python | `python/detpy/envobs.py:119`, `:126-137`; list `python/detpy/_level0.py:45-53` | `python/detpy/_level0.py:539-541` |
| `files_read_outside_tests` | Python | `python/detpy/osstate.py:385-386`, `:497-498` | `python/detpy/_level0.py:529-534` |

Correction of the spec's Current State sentence on `python/detpy/envobs.py:88-123`: Python env reads outside tests by
project **or third-party** code (not only "project") go to **two** run-level sets: `env_read_outside_tests` for an
ordinary name, and `not_proven_outside_tests` for a CI-volatile or proxy name (`envobs.py:119`, `:126-137`;
`_level0.py:45-53`, `:539-541`). Reads by pytest or a plugin go to `env_read_outside_tests` by name, never `*`.

## 3. Runner-written entries (note 2: cannot differ between base and change)

The base's records are assumed to contain nothing the payload does, except entries the runner itself always writes:

* Node `envout` `*`: `noteOutside` writes `*` for any enumeration of `process.env` outside a test, with no reader
  filter (`node/src/controls.js:126`, `:133-138`). A runner or a runner's dependency that copies the environment in a
  worker (INFERRED, typical for worker spawns) puts `*` there in every run. A payload that only enumerates
  (`JSON.stringify(process.env)`, `Object.keys(process.env)`) outside tests therefore adds nothing new; a payload that
  reads **named** variables (`NPM_TOKEN`, `GITHUB_TOKEN`, `AWS_SECRET_ACCESS_KEY`) adds those names.
* Node `envout` names the runner reads (e.g. `NODE_ENV`, `CI`, `FORCE_COLOR`, `MOCHA_*`; INFERRED, depends on the
  runner): present in base and change alike.
* Python `env_read_outside_tests`: `_runner_env_names()` (pytest's `PYTEST_*` namespace, `python/detpy/_level0.py:535-537`)
  and the names pytest and plugins read (`python/detpy/envobs.py:120-123`). Python never writes a runner's `*`
  (`:120`), so a third-party payload enumerating the environment outside tests adds `*` (`:117-119`).
* Node start-up summary: whatever the runner's own main process connects to (INFERRED: usually nothing in CI).

## 4. Default network mode per language

* Node: **open** under `--det` (`node/src/session.js:26`, `:217`): an external connection is made and recorded `allowed`
  (`node/src/network.js:723`, DNS `:885`); `--det-net=closed` records `blocked` (`:689`, DNS `:893`).
* Python: **closed** (`block`) unless a cassette exists or `--det-record` (`python/detpy/network.py:984-993`): the
  connection is refused with `NetworkBlockedError` (`crates/detpy-py/src/network.rs:447-460`) and, inside a test,
  recorded. A payload's exfiltration from a test process therefore fails under Python's default; the attempt is what
  makes the record differ.

## 5. Supported test runners on release-1 (rule 3a, note 4)

| runtime | runner | test that shows it |
|---|---|---|
| Node | mocha | `node/test/runner-mocha.test.js` |
| Node | node:test | `node/test/runner-node-test.test.js` |
| Node | tap, AVA, Jasmine, uvu | `node/test/runner-tap.test.js`, `runner-ava.test.js`, `runner-jasmine.test.js`, `runner-uvu.test.js`, `node/test/all-runners-2-f6f7.test.js` |
| Node | Jest, Vitest | `node/test/runners-p041.test.js`, `node/test/vitest-cache-deps.test.js` |
| Node | Playwright test | `node/test/playwright-p041.test.js` |
| Bun / Deno | bun test, deno test | `node/test/runner-bun.test.js`, `node/test/runner-deno.test.js` (env reads not recorded: `node/src/session.js:381`, `:489`) |
| Python | pytest (plugin `pytest11 detpy`) | `pyproject.toml:41-42`; `tests/test_django_pytest_cache.py` |
| Python | unittest, nose2, doctest, Django | `tests/test_runners_unittest.py`, `tests/test_runners_nose2.py`, `tests/test_runners_doctest.py`, `tests/test_runners_django.py` |

Rule 3a assumes mocha for Node and pytest for Python (note 4).

## 6. The `--det-cache` layer (information only)

`node/src/cache/capture.js` (`STATE.onEvent`, `:231`) and `crates/detpy-py/src/capture.rs` record the same channels for
`--det-cache`; the cache never reuses a test that started a child or loaded a native addon (`node/src/children.js:16-17`).
Not used for any verdict.
