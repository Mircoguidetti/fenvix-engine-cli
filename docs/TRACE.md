# Traces and the verifier

Every `--det` run writes a trace: `.detpy/trace.jsonl` by default, `--det-trace=PATH` to choose (Node:
`.detjs/trace.jsonl`). `fenvix verify A B [C...]` compares traces of the same suite. This page specifies both.

## Trace file (JSON Lines, `format: "detpy-trace"`, `version: 1`)

```
{"type":"header","format":"detpy-trace","version":1,"encoding":2,"meta":{...},"order":[...]}
{"type":"test", ...}           one line per executed test, written when the test ends
{"type":"footer","n_tests":N,"order_digest":"..."}
```

A run that crashed has no footer (the verifier marks it `(partial)`).

### Header

| field | meaning |
|---|---|
| `encoding` | event encoding version; traces with different encodings are never compared (`fenvix verify` exits 2) |
| `order` | the planned order of the tests |
| `meta.runtime`, `meta.runtime_version` | `CPython` / `node` and its version |
| `meta.inputs` | **the run inputs the verifier compares** (below) |
| `meta.seed`, `shuffle`, `controls`, `hashseed`, `epoch_ns`, `tick_ns`, `sleep`, `network`, ... | the configuration, for people (the comparable part is in `inputs`) |

`meta.inputs` is a map of text values:

| input | value |
|---|---|
| `runtime` | interpreter, version, platform, machine |
| `runner` | runner and version |
| `seed`, `shuffle` | the seed of every generator and of the shuffle |
| `hashseed` | `PYTHONHASHSEED` |
| `clock` | virtual clock: epoch, tick, adaptive tick, sleep mode (or `real (time control off)`) |
| `tz` | the pinned zone (`UTC (pinned)`), or the machine's when `--det-tz=keep` |
| `locale` | the pinned locale, or the machine's when `--det-locale=keep` |
| `env` | whether environment reads are recorded |
| `env:NAME` | one per environment variable, CI-volatile ones excepted (docs/CLI.md): a digest of `NAME=value` (never the value) |
| `network` | mode (block, record, replay), allowed hosts, cassette digest |
| `fs`, `urandom`, `bytecode`, `aslr`, `order` | the state of those controls. `bytecode` ends with `test modules rewritten from source in this run (cold rewrite cache: N)` when a run compiled test modules from source and did not find them in the cache (a run started without the re-exec, a module outside the project's test files): such a run can lay out memory differently from a later one, so it is never identical to it. The process that starts a `--det` run writes the rewritten test modules into the cache before the re-exec (nothing is imported), so a first run after a checkout or an edit is laid out like every later run |

Engine-internal variables (`DETPY_*`, `PYTEST_XDIST_*`) are not inputs.

### Test line

| field | meaning |
|---|---|
| `nodeid`, `index`, `outcome` | the test, its position, its outcome |
| `fingerprint` | head of a BLAKE3 hash chain over every event and the outcome (128 bits, hex) |
| `n_events`, `truncated`, `checkpoints` | number of events; `events` keeps the first `--det-max-events` (10,000), the chain head every 256 events brackets a later difference |
| `counts` | events per source |
| `events` | `{"t": thread, "s": source, "o": operation, "at": site, "v": value}` |
| `uncontrolled` | sources the test used that this release does not control: `thread`, `child`, `io` |
| `worker`, `worker_index` | parallel runs (merged trace): the worker and the position in it |

Sources: `time`, `random`, `fs`, `net`, `entropy`, `outcome`, `syscall` (reserved), `other`, `sched`. Operations
under `other`: `env.get`, `env.has`, `env.list` (environment reads; value `NAME=set` / `NAME=<unset>`: which variable, not its value), `uncontrolled.thread`,
`uncontrolled.child`, `uncontrolled.io`. The site is `path:line` relative to the project, `<stdlib>/...`,
`<site>/...` for libraries, `<end>` for summaries written when the test ends, `<run>` for run-level events.

## The verifier's verdicts

`fenvix verify` (and `detpy verify`) prints a verdict line, the run inputs, the order, the counters and one block per
test that is not identical:

```
verdict: IDENTICAL: all 12 tests ran with the same inputs and observed the same events
verdict: DIVERGENT: 3 of 12 tests are not identical (the first divergent event of each is named below)
verdict: NOTHING VERIFIED: no test ran in these runs
```

A test is identical only when the run inputs are equal, it ran after the same tests, it used no uncontrolled source
and its fingerprints are equal. The counters keep their historical names: `covered by Level 0` = identical,
`not covered` = divergent, `missing` = not run in every trace, `outcome-unstable` = the outcome differs.

| reason | what diverged first | what to do |
|---|---|---|
| `runtime` | interpreter, version, platform or runner | compare runs of the same environment |
| `seed`, `hashseed` | the seed, the hash seed | same `--det-seed` in both runs |
| `time` | the clock configuration (epoch, tick), or a clock read returned another value | same `--det-epoch`; for a read: what changed the number of clock reads before it |
| `tz`, `locale` | time zone, locale | keep the defaults (`--det-tz=UTC`, `--det-locale=C.UTF-8`) |
| `env` | an environment variable (named), or the test read it (named, with the site) | same environment, or `--ignore-env NAME` |
| `net` | network mode, allowed hosts, cassette, or a network event | same cassette; re-record with `--det-record` |
| `fs` | file-system order control, or a listing returned other entries | the directory content differed (files created by an earlier run, for example) |
| `entropy` | OS entropy (`os.urandom`, `uuid4`, `secrets`) is observed, not controlled | `--det-urandom` |
| `random` | a generator returned another value | an unseeded generator outside `random` / numpy / torch / TensorFlow / Faker |
| `order` | the test ran after different tests | an order dependency: `fenvix repro TEST` names the tests |
| `thread`, `child`, `io` | the test used a thread, a child process, ready I/O: not controlled by this release | the test cannot be proven identical yet (Level 1) |
| `placement` | parallel run: the test ran without some of its serial predecessors | see docs/PARALLEL-PROOF-DESIGN.md |
| `outcome-only` | same events, another outcome: a source that is not observed | `fenvix repro TEST` |
| `beyond-trace` | the stored events agree; the difference is past `--det-max-events` | raise `--det-max-events` |
| `missing` | the test did not run in every trace | |
| `config` | another recorded input differs, or one trace has no inputs | |

A test that read an environment variable whose value differs, and is otherwise identical, has status `input-differs`
(summary `input_differs`; design A). Header `env_reads_recorded: true` says the shell records environment reads (the
Python shells with the env control); without it every test counts as reading every differing variable.

Exit codes: 0 every test identical, 3 the only differences are environment variables tests read (input differs), 1
otherwise (and when no test ran), 2 a trace is missing, unreadable or of another encoding.

## `detpy backends`

`python -m detpy backends` lists the interception backends and what each captures: `python` (the Python-level
hooks, implemented) and `syscall` (reserved: a ptrace/seccomp tracer for native code and child processes, not
implemented).
