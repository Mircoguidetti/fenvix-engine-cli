# How many real tests stay PROVABLE if "unobserved" means NOT PROVEN

Measurement only. No product code was changed on this branch; the only new code is the
measurement harness in [`harness/measure_provable/`](../harness/measure_provable/).

## The question

`fenvix verify` today reports IDENTICAL when it saw no difference, including on channels it
does not observe at all. The decided direction is that anything not observed with certainty
must give NOT PROVEN, never IDENTICAL — the rule the Python cache already follows.

* DECLARED (source: the task brief for this session): review R-055 found 16 channels on which
  `verify` reports IDENTICAL without observing them, each a wrong IDENTICAL.
* DECLARED (source: the task brief, quoting DECISIONS 2026-11-21): "whatever the cache cannot
  observe with certainty forces a rerun; it is never reused on something unobserved."
* UNKNOWN here: neither R-055 nor that DECISIONS entry exists in `fenvix-engine-cli`, and
  `fenvix-brain-cli` could not be attached to this session (the attach was refused), so
  neither citation could be checked against its source. They are quoted as given.

This report measures the cost of that rule before it is built: what share of real tests would
become NOT PROVEN, and which channels are responsible.

## The short answer

<!--RESULTS-HEADLINE-->

## What the engine records today (MEASURED)

The accounting needs an exact statement of what a `--det` run pins. Taken from the trace this
engine writes (`docs/TRACE.md`, confirmed by reading a trace header produced here):

* **Run inputs** (`meta.inputs`, compared by the verifier): `runtime` (interpreter, version,
  platform, machine), `runner` (runner and version), `seed`, `shuffle`, `hashseed`, `clock`
  (epoch, tick, adaptive tick, sleep mode), `tz`, `locale`, `env` plus one `env:NAME` digest
  **per environment variable**, `network` (mode, allowed hosts, cassette digest), `fs`,
  `urandom`, `bytecode`, `aslr`, `order`.
* **Events** per test: `time`, `random`, `fs` (directory *enumeration order*), `net`,
  `entropy`, `other` (`env.get/has/list`, `uncontrolled.thread|child|io`), `outcome`, `sched`.
* **No input pins the content of any file.** Not the project source, not the installed
  packages, not the standard library. `docs/LIMITS.md` F1 says so directly: "Only the *order*
  of enumeration is normalised; file contents, sizes, timestamps, inode numbers, free space
  are not observed."
* `files_read_outside_tests` and `not_proven_outside_tests` are **absent on this trunk**
  (MEASURED: `grep -rn "files_read_outside_tests\|not_proven_outside_tests"` over the whole
  checkout returns nothing).

A ten-test probe suite run under `--det` makes the gap concrete (MEASURED, reproduced in
`harness/measure_provable`; the engine's events per test, `--det-trace`):

| what the test did | events the engine recorded |
|---|---|
| `time.time()`, `random.random()` | `time.time`, `random.random` ✓ |
| `os.urandom(16)` | `entropy os.urandom` ✓ |
| `os.listdir(".")` | `fs os.listdir` ✓ |
| `os.environ.get("HOME")` | `other env.get` ✓ |
| `threading.Thread(...).start()` | `uncontrolled.thread` ✓ |
| `subprocess.run(["/bin/true"])` | `uncontrolled.child` ✓ |
| **write then read a file under `tmp_path`** | **none** (only `random.state`, `outcome`) |
| **read its own source file** | **none** |
| **read `/proc/self/status`** | **none** |

So file content, file metadata and `/proc` are exactly the channels that leave no trace.

## Method

### Build (MEASURED, every command as run)

```bash
# engine, from claude/release-1 (f84dde7)
pip install "maturin>=1.5,<2"
maturin build --release --compatibility linux -o dist          # fenvix-0.1.0-cp312-abi3-linux_x86_64.whl
python3 -m venv /home/user/venv-measure
pip install pytest pytest-xdist && pip install --no-deps dist/fenvix-*.whl
cp "$(python -c 'import detpy._core as c; print(c.__file__)')" python/detpy/   # as the CI `python` job does

# Node
cargo build -p detpy-node --release
cd node && npm ci && npm run build        # copies detjs.linux-x64.node next to src/native.js
```

Per project, following `harness/detpy_harness.py` conventions
(`harness/measure_provable/../../measure/prepare.py` in this session):

```bash
git clone --depth 1 <url> src/<name>
uv venv --python 3.13 venvs/<name>
uv pip install --python venvs/<name>/bin/python <detect_install(src)> \
    dist/fenvix-*.whl "pytest>=7" pytest-randomly pytest-xdist
```

### The four projects

Chosen for different suite shapes, and all four appear in earlier harness measurements so the
numbers are comparable with them.

| project | shape | runner | commit | date | collected | earlier measurement |
|---|---|---|---|---|---|---|
| flask | large application (web framework: app objects, test client, templates and static files from disk, CLI tests) | pytest | `49943b5a9441` | 2026-10-30 | 494 | `harness/results/block2-head-flask/` |
| rich | plain library (console rendering, almost pure computation) | pytest | `3a109ccdffe5` | 2026-11-07 | 981 | `harness/results/block2-final/` (5 targets) |
| anyio | async / service-heavy (event loops, threads, sockets, subprocesses) | pytest | `37ba52b9137d` | 2026-11-20 | 4857 | `harness/results/block2-final/` (16 targets) |
| valibot | Node (TypeScript validation library, Vitest) | vitest 4.1.8 | `d72f76fcf70c` | 2026-10-28 | 3232 | `harness/node/results/node-final/` (3220 tests) |

valibot is pinned at the commit the earlier Node round used. Its own `test` script is
`vitest --typecheck`; the type-check tasks are not executed tests and have no fingerprint
(the zod finding in `docs/REPORT-node-l0-2.md`), so only the runtime suite is measured.

### Sampling (MEASURED)

220 tests per project, `random.Random(20261121).sample(ids, 220)` over the collected node ids,
then sorted. **Seed: 20261121.** The sampled ids are in `harness/measure_provable/samples/`.
Python ids come from `pytest -p no:randomly --collect-only -q`; Node ids come from one `--det`
run of the whole suite (`file::describe::...::test`).

### The two sensors

Each sampled test is run **alone**, under `--det`, with strace attached:

```bash
# Python
strace -f -q -y -s 512 --seccomp-bpf -o strace.txt \
  -e trace=%file,%process,%network,%clock,getrandom,uname,sysinfo,getrusage,ioctl,sched_getaffinity,getcpu,statfs,fstatfs,getdents64 \
  <venv>/bin/python -m pytest -p no:randomly -p fenvix_sensor --det \
     --det-epoch=2025-01-01T00:00:00Z --det-trace=trace.jsonl -q --no-header \
     -p no:cacheprovider <nodeid>

# Node
strace -f -q -y -s 512 --seccomp-bpf -o strace.txt -e trace=<same set> \
  node node/bin/detjs.js vitest run --det --det-epoch=2025-01-01T00:00:00Z \
     --det-trace=trace.jsonl --setupFiles ./__fenvix_marker.mjs <file> -t '^<full test name>$'
```

1. **strace** — the ground truth of what the run asked the kernel for. The trace set is the
   narrowest that still carries outside information: files (`%file`), processes (`%process`),
   sockets (`%network`), clocks (`%clock`), plus `getrandom`, `uname`, `sysinfo`, `getrusage`,
   `ioctl`, `sched_getaffinity`, `getcpu`, `statfs`, `fstatfs`, `getdents64`. `-y` prints the
   directory behind each fd, so `getdents64` and relative paths resolve.
2. **The engine's own record** — the `--det` trace for that test: its events per source, its
   `uncontrolled.*` marks, its `n_events`, and the header inputs.
3. **An audit hook** (`sys.addaudithook`, in the sensor plugin) — the Python-level operations
   (`open`, `os.listdir`, `os.scandir`, `ctypes.dlopen`, `os.exec*`, `os.fork`,
   `subprocess.Popen`, `socket.connect`, `import`). A content read whose path the hook never
   saw was made by native code, not by Python. This is what separates "a file the test read"
   from "a file an extension read behind the test's back".

`--det-epoch` is fixed instead of `auto` so the engine does not run `git log -1 --format=%ct`
in every run; that child process and its reads are engine machinery, not the test's.

### Attributing a syscall to the test

The sensor plugin marks the test phase with one syscall at each boundary: a `stat` of
`/FENVIXMARK/S` in `pytest_runtest_logstart` and of `/FENVIXMARK/E` in
`pytest_runtest_logfinish` (on Node, `beforeEach`/`afterEach` in an injected setup file).
Both always fail with `ENOENT`, cost one syscall and touch nothing. That splits every run into

* **collection** — the real session's imports, collection and session-scoped setup,
* **test** — between the two marks, i.e. setup, call and teardown of the test,
* **after** — reporting and interpreter shutdown.

**The engine's own bootstrap is excluded.** Before the session it measures, `--det`
precompiles the standard library and site-packages under the fixed hash seed (in a worker
thread), runs `detpy._prewarm` as a child process, and re-executes the interpreter with the
fixed hash seed and ASLR off. The measurement window therefore starts after the last
re-exec of the main process, and every syscall of the engine's own children is dropped
(identified by their `execve` argv). Without this, every test would be charged with a thread
and a child process that belong to the engine (MEASURED: exactly 1 bootstrap thread and
1 `_prewarm` child per Python run).

**Node's runner infrastructure is excluded the same way, measured rather than assumed.** A
baseline run of one valibot file with a pattern matching no test — so that *no test runs at
all* — already makes (MEASURED):

| channel | count with zero tests run |
|---|---|
| threads created | 23 |
| child processes | 2 |
| `execve` | 2 |
| `net.recvmsg` (inet) | 165 |
| `net.socket` / `bind` / `connect` / `getsockname` | 13 / 4 / 3 / 22 |
| `getrandom` | 13 |
| `uname` / `sched_getaffinity` / `sysinfo` / `getrusage` | 15 / 8 / 1 / 8 |

Node always starts a libuv thread pool and Vitest always runs a test file in a worker over a
socket. Those are properties of the runtime and the runner, pinned by the `runtime` and
`runner` inputs, not something a test observed. For Node, the non-file channels present in
that baseline are therefore suppressed **in the collection phase only**; everything from the
test phase on is counted, and file reads are never suppressed.

### The accounting rules

A syscall is **accounted for** when a change in what it carries would be caught: it is
recorded as an event, pinned by a run input, or controlled by `--det`.

**Rule E (primary).** The engine's controlled set is its own machinery, the interpreter and
its standard library, the system libraries the interpreter loads, the *code* of the installed
packages, the bytecode cache, and locale/zoneinfo data. The reasoning: the engine pins the
interpreter and runner identity, precompiles stdlib and site-packages under the fixed hash
seed (`bytecode`), pins `tz` and `locale`, and nothing writes that environment during a run.

**Rule S (sensitivity).** Only the engine's own machinery is controlled. No input pins the
*content* of the standard library or of an installed package either, so reading them counts
too. Rule S is the strictest defensible reading; it is reported alongside Rule E so the
decision does not hang on where that line is drawn.

Under both rules these are treated as carrying no new information, and the choice is stated
rather than hidden:

* **Directory and module lookups** — a `stat`, `access` or `readlink` of a directory or of a
  module path the import system or the runner walks. It carries existence, not content, and
  the cache design already models module lookups as a recorded input
  (`tests/test_proofcache_import_lookups.py`).
* **`ioctl`** (`TIOCGWINSZ`, `TCGETS`) — terminal size and mode, pinned through the
  `env:TERM` and `env:COLUMNS` inputs.
* **`uname`** — pinned by the `runtime` input (platform, machine).
* Writes, `getcwd`, `chdir`, `/dev/null`, `/dev/zero`.

### The three buckets

Each test lands in exactly one bucket; **by nature wins over coverable**, because it is the
binding limit.

* **PROVABLE** — every information-carrying syscall is accounted for.
* **NOT PROVEN, coverable** — the channel could be recorded with ordinary work: a file read
  or `stat` outside the controlled set, an installed dependency's data file, a native
  extension file being loaded, a `/proc` or `/sys` read, an `/etc` read, a non-virtualised
  clock (`getrusage`, `times`, process/thread CPU clocks — `docs/LIMITS.md` C7), `sysinfo`,
  CPU affinity, an OS entropy read with no engine event.
* **NOT PROVEN, by nature** — needs the syscall backend or is an honest product limit:
  a thread, a child process, a live socket to another process, or a file read by native code
  with no Python-level open.

Three views are reported from the same raw data:

* **Rule E, whole run** — the literal reading of the rule: every information-carrying syscall
  the run made, in any phase. This is the primary number.
* **Rule E, test phase only** — only what happened between the two marks. This is where the
  per-test structure lives, and it is the view that says what recording a channel would buy.
* **Rule S, whole run** — the sensitivity check.

### What these sensors cannot see (so the numbers are a floor, not a ceiling)

* **Real wall and monotonic clock reads are invisible to strace.** They are served by the
  vDSO without entering the kernel. MEASURED: 600,000 calls to `time.monotonic()`,
  `time.perf_counter()` and `time.time()` with the real clock produce **0** clock syscalls,
  while 1,000 calls to `time.process_time()` produce exactly **1,000**
  `CLOCK_PROCESS_CPUTIME_ID` syscalls. So native code reading the real clock
  (`docs/LIMITS.md` C2f, K1) is **not** counted anywhere in this report. The `by nature`
  bucket is an under-count for that reason alone.
* **No audit hook on Node**, so for valibot a read made by native code cannot be told from one
  made by JavaScript. Node's `by nature` bucket rests on threads, children and sockets only.
* **Node under-counts test-caused threads and sockets**: anything a test file starts while
  being imported falls in the collection phase, where the runner's own channels are suppressed.
* The audit hook is installed in `pytest_configure`, after the interpreter's own early
  imports, so the Python-vs-native split is established for the collection and test phases,
  not for interpreter startup. Startup reads are classified by path only.
* `read()` itself is not traced; an `open` for reading is taken as the read. A file opened and
  not read is counted as read (over-count), and bytes read from an inherited descriptor are
  not seen (under-count).
* Paths longer than 512 bytes are truncated by `-s 512`.
* The audit hook compares basenames, so a Python open counts even when the hook saw a relative
  path. That makes "read by native code" a conservative under-count.

<!--RESULTS-BODY-->
