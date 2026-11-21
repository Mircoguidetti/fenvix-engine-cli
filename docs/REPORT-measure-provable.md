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

Under the rule as stated — **every** information-carrying syscall a test's run makes must be
accounted for — **0.0% of 879 real tests stay PROVABLE** (MEASURED, 4 projects, 220 sampled
tests each, seed 20261121). 85.3% are NOT PROVEN for channels that could be recorded with
ordinary work; 14.7% for channels that need the syscall backend.

The rule is therefore not affordable as stated. The reason is not exotic: **every run of every
test reads files whose content no run input pins** — the project's own source, the test data,
`/proc`, `/etc`. The engine pins *which* interpreter, runner, seeds, environment, time zone
and locale a run used; it pins *nothing* about what any file contained.

Counting only what happens between the start and the end of the test — i.e. charging a test
with what it did, not with what importing and collecting it did — **34.9% stay PROVABLE**,
50.4% are NOT PROVEN coverable and 14.7% NOT PROVEN by nature. That view varies enormously by
suite shape: 95.4% of the Node library's tests are provable, 44.5% of the web framework's,
and none of the console library's or the async library's.

Two findings matter more than the headline:

1. **One channel carries most of the cost.** Recording the project's own source files — the
   `stat` the import system makes and the content it reads — takes the test-phase figure from
   34.9% to 72.1% (MEASURED). The next five channels take it to 92.0%. The cost is
   concentrated, not diffuse.
2. **The engine already answers IDENTICAL on channels it misses today.** 14.7% of tests are
   NOT PROVEN by nature (a thread, a child process, a live socket, or a file read by native
   code), but only 6.3% carry an `uncontrolled.*` mark. **8.4% of all tests used a by-nature
   channel with no mark at all**, and for **4.3% that channel is a thread, a child or a live
   socket** — precisely what `uncontrolled.*` claims to catch (anyio: 25.5% and 9.1%). These
   are wrong IDENTICALs that the new rule would fix, and they are the strongest argument
   for it.

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

Per project, with `harness/measure_provable/prepare.py`, which reuses
`harness/detpy_harness.py`'s own `detect_install`:

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

## Results

880 runs, 879 classified (MEASURED). One valibot run is excluded: its `-t` pattern matched no
test, so no test executed. Engine outcomes over the classified runs: 801 passed, 76 skipped,
2 failed (two pre-existing anyio failures, unrelated to this measurement).

### The three percentages

**Rule E, whole run — the literal reading of the rule, and the primary number.**

| project | n | PROVABLE | NOT PROVEN, coverable | NOT PROVEN, by nature |
|---|---:|---:|---:|---:|
| flask | 220 | 0 (0.0%) | 207 (94.1%) | 13 (5.9%) |
| rich | 220 | 0 (0.0%) | 219 (99.5%) | 1 (0.5%) |
| anyio | 220 | 0 (0.0%) | 115 (52.3%) | 105 (47.7%) |
| valibot | 219 | 0 (0.0%) | 209 (95.4%) | 10 (4.6%) |
| **ALL** | **879** | **0 (0.0%)** | **750 (85.3%)** | **129 (14.7%)** |

**Rule E, test phase only — what the test itself did, between the two marks.**

| project | n | PROVABLE | NOT PROVEN, coverable | NOT PROVEN, by nature |
|---|---:|---:|---:|---:|
| flask | 220 | 98 (44.5%) | 109 (49.5%) | 13 (5.9%) |
| rich | 220 | 0 (0.0%) | 219 (99.5%) | 1 (0.5%) |
| anyio | 220 | 0 (0.0%) | 115 (52.3%) | 105 (47.7%) |
| valibot | 219 | 209 (95.4%) | 0 (0.0%) | 10 (4.6%) |
| **ALL** | **879** | **307 (34.9%)** | **443 (50.4%)** | **129 (14.7%)** |

**Rule S, whole run — the sensitivity check (stdlib and dependency *content* also unpinned).**
Identical to Rule E to the test: 0.0% / 85.3% / 14.7% (MEASURED). The headline does not depend
on where that line is drawn, because every run already reads project files and `/proc`
regardless of how the installed environment is treated. Rule S only adds more causes to tests
that were NOT PROVEN anyway.

### The 10 most frequent causes of NOT PROVEN

**Whole run (primary view).** The ranking is degenerate, and that *is* the finding: the top
causes each apply to 750 of 879 tests (85.3%), i.e. to every test that is NOT PROVEN for a
coverable reason. Every run of every test in all four projects reads a project file, a file
under `/etc`, and `/proc`, and stats a native extension. There is no subset of tests that
escapes; the channels are shared by the whole suite.

| # | cause | tests | share |
|---:|---|---:|---:|
| 1 | content read of a project source file | 750 | 85.3% |
| 2 | metadata read (stat) of a project source file | 750 | 85.3% |
| 3 | content read of a project data file | 750 | 85.3% |
| 4 | content read of `/proc` | 750 | 85.3% |
| 5 | metadata read (stat) of a file under `/etc` | 750 | 85.3% |
| 6 | metadata read (stat) of a native extension file | 750 | 85.3% |
| 7 | metadata read (stat) of an installed dependency's data file | 750 | 85.3% |
| 8 | content read of a file under the home directory | 750 | 85.3% |
| 9 | content read of a file outside the engine's controlled set | 750 | 85.3% |
| 10 | metadata read (stat) of a file outside the engine's controlled set | 750 | 85.3% |

**Test phase (the informative ranking).** Shares are of all 879 classified tests; a test can
have several causes, so the column does not sum to the NOT PROVEN total.

| # | cause | tests | share | bucket |
|---:|---|---:|---:|---|
| 1 | metadata read (stat) of a project source file | 407 | 46.3% | coverable |
| 2 | content read of a project source file | 209 | 23.8% | coverable |
| 3 | file read by native code during the test (no Python-level open) | 90 | 10.2% | by nature |
| 4 | metadata read (stat) of a native extension file | 67 | 7.6% | coverable |
| 5 | live socket to another process (AF_UNIX) | 59 | 6.7% | by nature |
| 6 | live socket to another process (inet) | 54 | 6.1% | by nature |
| 7 | thread created during the run | 52 | 5.9% | by nature |
| 8 | content read of a project data file | 27 | 3.1% | coverable |
| 9 | metadata read (stat) of a project data file | 27 | 3.1% | coverable |
| 10 | metadata read (stat) of a file outside the engine's controlled set | 17 | 1.9% | coverable |

Named examples behind the top causes (MEASURED, from the retained strace output):

* **stat / read of a project source file.** The project under test is installed with `-e .`,
  so its modules resolve to the project tree. A module imported lazily *inside* a test is read
  then: rich reads `rich/_emoji_codes.py` during the test in 96 of 220 runs. The import
  system's source `stat` (size and mtime, which decide whether to recompile) happens for 219
  of rich's 220 tests. Nothing in `meta.inputs` records which version of that file was
  imported, so two runs over different project source can still verify as IDENTICAL.
* **file read by native code.** `/proc/version_signature` is read by uvloop's compiled
  extension (`site-packages/uvloop/loop.cpython-313-x86_64-linux-gnu.so`, confirmed by `grep`)
  in 58 runs; glibc's resolver reads `/etc/nsswitch.conf` (43), `/etc/resolv.conf` (17) and
  `/etc/host.conf` (17) inside `getaddrinfo`. These are `docs/LIMITS.md` S1 exactly: a C
  extension reading a file with no Python event.
* **project data file.** flask reads `tests/static/index.html` while serving static files.

### Per project, test-phase view

| project | top cause | share |
|---|---|---:|
| flask | stat of a project source file | 33.2% |
| rich | stat of a project source file | 99.5% |
| anyio | stat of a project source file | 52.3% |
| valibot | live socket to another process (inet) | 4.6% |

anyio's profile is the one the async shape predicts: 46 tests (20.9%) create a thread, 51
(23.2%) use an `AF_UNIX` socket, 44 (20.0%) an inet socket, 3 (1.4%) a child process, and 82
(37.3%) read a file from native code. valibot's is the opposite: with the runner's own
infrastructure excluded, 209 of 219 tests touch **nothing** during the test phase.

### What recording one more channel would buy

Cumulative, test-phase view: each row adds that channel to the recorded set and reports how
many of the 879 tests would then be PROVABLE (MEASURED).

| recorded, cumulatively | PROVABLE | share |
|---|---:|---:|
| (nothing added — today's surface) | 307 | 34.9% |
| + stat of project source files | 499 | 56.8% |
| + content of project source files | 634 | 72.1% |
| + files read by native code | 670 | 76.2% |
| + stat of native extension files | 736 | 83.7% |
| + `AF_UNIX` sockets | 747 | 85.0% |
| + inet sockets | 766 | 87.1% |
| + threads | 809 | 92.0% |
| + project data files (content and stat) | 839 | 95.4% |
| + the remaining six channels | 879 | 100.0% |

The first two rows are the project's own source, and they are ordinary work: a digest of the
files a run imported, added to `meta.inputs`. They more than double the provable share
(34.9% → 72.1%). The two rows after that need the syscall backend.

### What the engine already refuses today

A test with a non-empty `uncontrolled` list is already never reported identical. Comparing
that with the rule's verdict shows where the new rule changes an answer rather than confirming
one (MEASURED).

| project | n | marked today | by nature | **by nature, not marked today** | coverable |
|---|---:|---:|---:|---:|---:|
| flask | 220 | 5 (2.3%) | 13 (5.9%) | 8 (3.6%) | 207 (94.1%) |
| rich | 220 | 1 (0.5%) | 1 (0.5%) | 0 (0.0%) | 219 (99.5%) |
| anyio | 220 | 49 (22.3%) | 105 (47.7%) | 56 (25.5%) | 115 (52.3%) |
| valibot | 219 | 0 (0.0%) | 10 (4.6%) | 10 (4.6%) | 209 (95.4%) |
| **ALL** | **879** | **55 (6.3%)** | **129 (14.7%)** | **74 (8.4%)** | **750 (85.3%)** |

The fourth column is the measured size of the engine's blind spot: 74 tests (8.4%) used a
by-nature channel while the Python-level hooks recorded no `uncontrolled.*` mark, so `verify`
can report them IDENTICAL today. Splitting that column by channel (MEASURED):

| project | by nature, not marked | of which a thread, child or live socket | of which only a native-code read |
|---|---:|---:|---:|
| flask | 8 (3.6%) | 8 (3.6%) | 0 |
| rich | 0 (0.0%) | 0 (0.0%) | 0 |
| anyio | 56 (25.5%) | 20 (9.1%) | 36 |
| valibot | 10 (4.6%) | 10 (4.6%) | 0 |
| **ALL** | **74 (8.4%)** | **38 (4.3%)** | **36** |

The middle column is the sharper number: 38 tests (4.3%) used a thread, a child process or a
live socket that `uncontrolled.*` is meant to mark and did not. The Python hooks see
`threading.Thread.start`, `subprocess`, `selectors` and Python sockets; they do not see a
thread or a socket created inside a C extension. The right-hand column is `docs/LIMITS.md` S1,
which the engine does not claim to catch today.

## Secondary: what a syscall-level sensor would cost

An upper bound for what a syscall-level sensor would cost, since strace stops the traced
process twice per syscall and writes every line to disk, while a seccomp-BPF/ptrace sensor
would only inspect the calls it cares about. Whole suite under `--det`, serially, 5 repeats
per mode, alternating (MEASURED).

| project | tests | `--det` (s, 5 runs) | median | `--det` + strace (s, 5 runs) | median | factor |
|---|---:|---|---:|---|---:|---:|
| flask | 494 | 3.3, 2.4, 2.4, 2.5, 2.5 | 2.5 | 4.3, 4.3, 4.4, 4.9, 4.6 | 4.4 | **1.77×** |
| rich | 981 | 5.6, 5.9, 5.7, 5.5, 5.8 | 5.7 | 8.2, 8.1, 8.4, 7.9, 8.1 | 8.1 | **1.42×** |

**Not NOISY**, with a caveat: the 1-minute load average was 0.32 at the start and 0.76 at the
end, and the per-run spread is tight (±0.5 s), so the factors are stable. The 5- and
15-minute averages were still around 2, decaying from the main measurement, so these numbers
should be read as "about 1.4–1.8× on a mostly idle 4-core machine", not to two decimals.
Both suites ran their full test count under both modes (494 and 981 tests, checked in the
traces).

The factor falls as the suite gets longer (1.77× on flask, 1.42× on rich) because a large
part of the traced work is interpreter start-up and import, which is a fixed cost per run.

For reference, the per-test cost of this measurement itself — one whole `pytest`/`vitest`
start-up per test, under strace, 3 workers on 4 cores (MEASURED, and NOISY by construction
since the workers compete):

| project | median per test | mean | max |
|---|---:|---:|---:|
| flask | 1.64 s | 1.64 s | 2.25 s |
| rich | 1.68 s | 1.67 s | 3.45 s |
| anyio | 2.15 s | 2.13 s | 2.90 s |
| valibot | 3.90 s | 4.12 s | 8.41 s |

## Threats to validity

* **The accounted-for set is a judgment, and it moves the headline.** Rule E treats the
  installed environment, directory and module lookups, `ioctl` and `uname` as controlled.
  Rule S removes the first of those and changes nothing (0.0% either way). What *would* change
  the test-phase figure materially is counting module-lookup `stat`s as lookups rather than
  content: cause #1 (46.3%) is exactly the import system's source `stat`. Both readings are
  reported; the brief lists "a `stat`" as a coverable cause, so it is counted here.
* **One valibot run is excluded** (its `-t` pattern matched no test). 879 of 880 classified.
* **Skipped tests are included** (76 of 879). A skipped test does almost nothing in its test
  phase, so it biases the test-phase PROVABLE share *upward*. Excluding them would lower
  34.9%; the whole-run figure (0.0%) cannot move.
* **The sample is 220 tests of each suite, not the whole suite.** At 220 of 879 the binomial
  standard error on a 50% share is about 3.4 percentage points per project; the 0.0% and
  95%+ figures are far from any boundary, but the per-project middle figures (flask 44.5%)
  carry that uncertainty.
* **Four projects are not the population.** anyio and valibot sit at opposite extremes
  (47.7% by nature vs 4.6%), which is the point of choosing different shapes, but a weighted
  estimate for "all real suites" is not available from four.
* **`by nature` is an under-count**, for three measured reasons: native code reading the real
  wall or monotonic clock is invisible to strace (vDSO, measured above); Node has no audit
  hook, so native reads there are not detected at all; and for Node a thread or socket opened
  while a test file is imported is attributed to the runner.
* **`native read` has a small false-positive rate.** Three of about 90 flagged paths are
  anyio's own `.py` modules, where the audit hook did not see the import's open. That is
  ~3% of that cause.
* **The three Python projects were measured twice**: the first pass is discarded. Its
  classifier misread `openat(".")` as a file (152 false native reads) and
  `.dist-info/METADATA` as a dependency data file. The numbers in this report come from the
  second pass, re-classified offline from the retained strace output with the committed code.

## Reproduce it

```bash
git checkout claude/measure-provable
# build as in the Build section above, then per project:
python3 harness/measure_provable/run.py      --project flask --sample 220 --seed 20261121 --workers 3
python3 harness/measure_provable/run.py      --project rich  --sample 220 --seed 20261121 --workers 3
python3 harness/measure_provable/run.py      --project anyio --sample 220 --seed 20261121 --workers 3
python3 harness/measure_provable/run_node.py --project valibot --src <valibot>/library \
                                             --sample 220 --seed 20261121 --workers 3
python3 harness/measure_provable/aggregate.py --projects flask rich anyio valibot \
        --csv harness/measure_provable/per-test-classification.csv
# change the accounting and re-apply it without running the tests again:
python3 harness/measure_provable/reclassify.py --projects flask rich anyio valibot \
        --infra-baseline harness/measure_provable/node_infra_baseline.json
python3 harness/measure_provable/timing.py --project rich --repeats 5
```

Artefacts on this branch:

* `harness/measure_provable/per-test-classification.csv` — the raw per-test classification:
  880 rows, one per sampled run, with its node id, the engine's own record (sources,
  `uncontrolled` marks, event count, outcome), the bucket and causes under each of the three
  views, the channel counts for the test phase and for the whole run, wall time and exit code.
  All 880 runs are in the file, including the one excluded from the percentages; its `status`
  column says `no-test-ran`, and `status` is how the aggregation excludes it.
* `harness/measure_provable/samples/*.sample.txt` — the sampled node ids per project.
* `harness/measure_provable/node_infra_baseline.json` — the measured Vitest/Node runner
  baseline (the channels a run opens with no test running).

The retained raw sensor output (gzipped strace, the engine's trace, the audit log per run,
132 MB) stays in the container at `/home/user/measure/raw/<project>/tNNNNN/` and is not
committed; `reclassify.py` reads it.

## What this says about the decision

The rule is right and the measurement does not weaken it: the engine reports IDENTICAL today
on channels it never looked at, and 8.4% of these tests prove it — they used a thread, a child
or a live socket while `verify` recorded no mark and would call them identical.

But "NOT PROVEN whenever anything was unobserved" cannot ship as a flat rule against the
current recording surface, because the honest answer would be NOT PROVEN for 100% of real
tests, which carries no information. The measurement points at the order of work:

1. **Record what a run imported** (a digest per file the run read from the project and from
   site-packages, as an input or as a per-test event). This is ordinary work, it is what the
   cache already does for its own inputs, and it is where the cost is concentrated: it takes
   the test-phase provable share from 34.9% to 72.1%, and it is the only way the whole-run
   figure moves off 0.0% at all.
2. **Make the existing `uncontrolled.*` marks catch what they claim to catch.** 38 tests
   (4.3%) used a thread, a child or a live socket with no mark; closing that is a correctness
   fix to today's verdicts, not new capability, and it needs no new input format.
3. **Then** adopt the flat rule, with the syscall backend behind it for the rest
   (native reads, native threads and sockets: 10.2%, 5.9%, 6.7% + 6.1% of tests).

Doing 3 before 1 and 2 turns every IDENTICAL into NOT PROVEN and the verifier stops saying
anything.
