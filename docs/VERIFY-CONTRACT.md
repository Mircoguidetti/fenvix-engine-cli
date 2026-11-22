# The trace contract both shells write for `fenvix verify` (review R-055)

This page fixes the exact names of the trace-header fields and test events that the Python shell (`python/detpy`)
and the Node shell (`node/src`) write for the channels of review R-055, and the rule the verifier
(`crates/detpy-core/src/verify.rs`) applies to each. Both shells use these names exactly. A shell that does not yet
write a field leaves it out; it never writes a different name.

The promise: **`fenvix verify` never says IDENTICAL when two runs differed in anything a test could observe.** Each
channel below either makes the runs differ (a run input, a header entry, an event with the value) or marks the test
NOT PROVEN.

Conventions used below (unchanged from today's traces):

- **path**: the shell's machine-independent path, the same one the `fs.read.outside` / `fs.read` events use
  (Node `sites.normPath`, Python the same rules): a project file is relative to the project root (`data.txt`,
  `tests/x.json`); a file elsewhere is `<abs>/<name>` or `<tmp>/<rest>`. The shell itself, `/dev`, `/proc` and
  `/sys` are never recorded.
- **content digest**: `<bytes>:<digest>`, where `<bytes>` is the number of bytes read and `<digest>` is
  `native.digest(bytes)` (Python: `_core.digest`), as in today's `fs.read.outside` values.
- **mark**: a test event whose op starts with `uncontrolled.` (`fingerprint.rs` `UNCONTROLLED_PREFIX`); its kind is
  the rest of the op. Marks are kept even when the event list is truncated.

## 1. Header (`meta` of the trace header line)

| field | type | written by | meaning | verify rule |
|---|---|---|---|---|
| `files_read_outside_tests` | array of `{"path": <path>, "digest": <content digest or stat value>}`, sorted by `path`, then `digest` | both | every file the project's code read while no test was running: module scope of a test file, `conftest.py` / setup files at import, a project module at import, hooks outside a test, `process.loadEnvFile` outside a test. One entry per distinct (path, digest); a file read twice with the same bytes is one entry. A metadata call outside a test (section 2, `fs.stat`) is an entry with `"digest": "stat:<stat value>"`. The module loader's own reads of source files are not entries (they are covered by `inputs.code` and `inputs.deps`). | if the set of entries differs between two runs, **every test diverges**, reason `fs`, and the description names the first differing path (`file read outside any test differs: <path>`). Same rule as a differing non-env run input. Traces without the field compare as an empty set only against each other; a run with the field against a run without it is `fs`-divergent for every test. |
| `inputs.deps` | string `"<n> files <digest>"` | both | the installed dependencies the run loaded: Node, every file under the project's `node_modules/` that the module system loaded (CJS `require` and ESM `import`), by relative path and content digest; Python, every module file loaded from outside the project (site-packages, dist-packages, `.pth` targets), by its path relative to its `sys.path` entry and its content digest. Digest = `digest` of the lines `<relpath>\t<content digest>\n`, sorted. Taken when the header is written (the end of the run). | a run input: a differing value makes **every test diverge**, reason `deps`. |
| `inputs.code` | string `"<n> files <digest>"` | both | the project's own source the run loaded (test files, project modules, `conftest.py`, setup files, the runner config file), same digest form as `deps`, paths relative to the project root. This catches an uncommitted edit (same git HEAD). | a run input: differing → every test diverges, reason `code`. |
| `env_read_outside_tests` | array of names (unchanged) | both | as today. A variable set by `process.loadEnvFile` and then read outside a test is listed too. | as today. |
| `not_proven_outside_tests` | array of `"<kind>:<detail>"` strings, sorted (e.g. `"env:TMPDIR"`, `"env:HTTPS_PROXY"`, `"native:getenv"`) | both | an uncontrolled read (section 3) made while no test was running. | every test is **NOT PROVEN** (section 4), reason of the first entry's kind. |

Every other `inputs.*` key keeps its meaning. A Python run whose `inputs.hashseed` is `"<random>"` is never identical
to any run (Rust rule, V13: `"<random>"` never compares equal, even to itself): every test diverges, reason
`hashseed`.

## 2. Events (inside a test)

| channel | op | source | value | notes |
|---|---|---|---|---|
| file read (unchanged) | `fs.read` (project) / `fs.read.outside` | `fs` | `<path>\|<content digest>` | as today. A `.env` file read by `process.loadEnvFile` inside a test is an `fs.read` of that file, with its content digest. |
| file metadata (V6) | `fs.stat` | `fs` | `<path>\|missing`, or `<path>\|<type>` where `<type>` is `file`, `dir`, `link` or `other`; a call that returns size or mtime appends ` size=<bytes> mtime_ns=<ns>` (the mtime the test saw, virtual or real) | Node: `fs.existsSync`, `fs.exists`, `fs.statSync`, `fs.lstatSync`, `fs.stat`, `fs.lstat`, `fs.promises.stat/lstat`, `fs.accessSync`, `fs.access`, `fs.promises.access` (an access error is `missing`). Python: `os.stat`, `os.lstat`, `os.path.exists/isfile/isdir/islink/getsize/getmtime`, `os.access`, `pathlib.Path.exists/is_file/is_dir/stat`. Only the test's own calls, like `fs.read`. `exists`-style calls record only `<path>\|<type>` or `<path>\|missing`. |
| UDP (V8) | `net.connect` | `net` | `<host>:<port> udp <allowed\|blocked\|intercepted>` at the first send/connect to that peer | then, when the test ends, one `net.stream` per UDP peer, value `udp <host>:<port> sent=<content digest> recv=<content digest>` (all datagrams in order, concatenated). Node records both. Python marks instead (`uncontrolled.net`, below). |
| unix socket (V9) | `net.connect` | `net` | `unix:<path> <allowed\|blocked>` | Node: plus `net.stream` as for TCP. Python: the mark `uncontrolled.net` with value `unix <path>` (unless the socket is one this process listens on). |
| env set by the test process (V16) | `env.get` / `env.has` | `env` | `NAME=<digest of NAME=value>` when NAME is not a run input of the run (it was set during the run, e.g. by `process.loadEnvFile`), else unchanged (`NAME=set\|unset`) | so a value that was never a run input still makes the fingerprint differ. |

## 3. Marks: NOT PROVEN reads

| channel | op | value | when |
|---|---|---|---|
| CI-volatile variable (V1) | `uncontrolled.env` | `<NAME>` | the test reads (`env.get`, `env.has`, or enumerates with `env.list`) a variable in the KEPT list (`node/src/volatile.js`, `python/detpy/_level0.py` `VOLATILE_KEPT`) or added by `FENVIX_VOLATILE_ENV`, **and it is not pinned**. Pinned variables (PINNED) are controlled and get no mark. Enumeration marks with value `*`. Engine variables (`DETJS_*`, `DETPY_*`, ...) get no mark. |
| proxy variable while the network is closed (V2) | `uncontrolled.env` | `<NAME>` | the test reads a variable of `PROXY_ENV` while the network control is on and not recording. While recording the proxy variables are run inputs (unchanged), no mark. |
| C-level `getenv` (V15) | `uncontrolled.native` | `getenv` | Python: a native extension known to call `getenv` was loaded by the test; best effort, no promise beyond the attack test. |
| file read by C code (V7) | `uncontrolled.native` | `file:<path>` | Python: sqlite3 `connect` to a file outside the project, best effort. |

A read outside any test of a volatile or proxy variable goes in `not_proven_outside_tests` as `env:<NAME>`, not in
`env_read_outside_tests`.

Note: the existing marks (`uncontrolled.thread`, `uncontrolled.child`, `uncontrolled.io`, `uncontrolled.native`,
`uncontrolled.net`) keep their op and value.

## 4. Verdict (Rust; for the shells' information)

- New test status `not-proven` (`Status::NotProven`), summary counter `summary.not_proven`. A test with any mark in
  any run, or any entry in `not_proven_outside_tests`, and no other difference, is `not-proven`: never `stable`,
  never counted in `summary.identical`. A test whose events or inputs also differ stays `diverged` / `input-differs`.
- Headline: `IDENTICAL` only when every test is `stable`. Otherwise `DIVERGENT` if any test is `diverged` or
  `missing`, else `INPUT DIFFERS` if any is `input-differs`, else `NOT PROVEN` (D1: unchanged runs of a test that
  uses a thread or a child process headline NOT PROVEN, not DIVERGENT). Exit codes: section 6. The Node test
  helpers read `summary.not_proven` (0 when absent in older reports).
- New reasons (`summary.reasons` keys and `divergence.reason`): `deps`, `code`, and `env` for `uncontrolled.env`.
  The `fs` reason covers `files_read_outside_tests`.
- `summary.inputs_recorded` stays as today.
- Implemented in `crates/detpy-core/src/verify.rs` (`Status::NotProven`, `compared_inputs`, `FILE_INPUT_PREFIX`,
  `Reason::Deps`, `Reason::Code`); unit tests `r055_*`.

## 5. What each shell owns

| item | Python (`python/detpy`) | Node (`node/src`) | Rust (`crates/detpy-core`) |
|---|---|---|---|
| V1, V2 marks | yes | yes | NotProven status |
| V3 `files_read_outside_tests` | yes | yes | compare rule |
| V4 `inputs.code` | yes | yes | reason `code` |
| V5 `inputs.deps` | yes | yes | reason `deps` |
| V6 `fs.stat` | yes | yes | none (an ordinary event) |
| V7, V15 `uncontrolled.native` | yes | n/a | none |
| V8 UDP | mark | events | none |
| V9 unix socket | mark | events (already pass) | none |
| V13 `"<random>"` hashseed | none | n/a | never equal |
| V16 `.env` read + env digest | n/a | yes | none |
| E1, D3 (explore, repro crash) | yes, with Rust | n/a | yes |

## 6. Exit codes

`verify` (`fenvix verify` and `detjs verify`: one rule, `python/detpy/fenvix.py` `verify_exit_code` and
`node/src/exit-status.js` `verifyExit`, checked against each other by `node/test/fixtures/exit-cases.json`):

| exit | `detjs verify --json` `status` | when |
|---|---|---|
| 0 | `identical` | every test identical |
| 3 | `input_differs` | the only differences are environment variables tests read (input differs) |
| 1 | `diverged` | a test diverged or is missing |
| 1 | `not_proven` | a test is NOT PROVEN, no test ran, or the traces do not record their run inputs |
| 2 | (no report) | a trace is missing or unreadable, fewer than two traces, a usage error |

When several hold, `status` is the first of `diverged`, `not_proven`, `input_differs`, `identical`.

A deterministic run (`detjs <runner> --det`, `fenvix <node runner>`): one rule, `node/src/exit-status.js` `runExit`,
on every path of `node/bin/detjs.js` (the normal path, the TZ/locale restart, and the cross-worker hazard re-run wrapper `node/src/parallel-rerun.js`). First match wins:

| exit | when |
|---|---|
| 2 | a usage or internal error of detjs, or the runner shell returned 2 |
| 1 | at least one test failed (outcome failed or error; an outcome other than passed, skipped or todo, such as interrupted, counts as failed), at least one test is NOT PROVEN (a hazard re-run that did not account for a file's first-pass tests), or the runner shell returned any other non-zero code |
| 0 | otherwise |

A signal that killed the runner is re-raised on detjs. The process that writes the run's final trace prints one line
on stderr, `detjs: status: failed=N not_proven=M passed=K skipped=S`, and writes the same counts into the trace header
as `meta.status` (`{"failed":N,"not_proven":M,"passed":K,"skipped":S}`; skipped counts skipped and todo).
