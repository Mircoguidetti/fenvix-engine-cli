# The general rule: IDENTICAL only when everything a test did is accounted for

Branch `claude/verifier-cli`. Every number below is labelled MEASURED, ESTIMATED, DECLARED or UNKNOWN.

Founder decision, 2026-11-21:

> Never a green on a doubt. If the engine is not certain, it answers NOT PROVEN and the test is rerun. A test
> reported green that was red is the worst damage we can do to a customer. Speed never buys an exception.

## Verdict

The rule is built, it is in one place in the shared Rust core, both shells feed it, and the test that proves it
does not depend on any list of channels. What is not finished is named in [Still open](#still-open).

## 1. What was wrong

`fenvix verify` decided the verdict the wrong way round. In `verify.rs` the branch for "every run agrees on the
fingerprint" was:

```rust
// before
match recs.iter().find_map(|r| r.filter(|r| !r.uncontrolled.is_empty())) {
    Some(r) => (Status::NotProven, ...),      // an explicit mark pulls it back
    None    => (Status::Stable, None),        // otherwise: IDENTICAL
}
```

So the default was IDENTICAL, and only a channel somebody had already thought of could prevent it. That is a
blacklist over an unbounded world, which is why reviews R-051, R-054, R-055 and R-057 each found new instances:
R-055 alone found 26 wrong IDENTICAL verdicts across 16 channels. Channel number 27 would have been a lie too.

**MEASURED** (the parallel measurement session, `claude/measure-provable`, `docs/REPORT-measure-provable.md`): on
`claude/release-1`, a test that reads the *content* of a file leaves no trace at all — not project source, not
installed packages, not the standard library. Only directory enumeration *order* is recorded. So the engine was
answering IDENTICAL on a channel it does not observe in any way.

## 2. The rule

A test's verdict is IDENTICAL only if every information-carrying thing it did is **accounted for**. Accounted for
means one of four things, and nothing else:

| answer | meaning |
|---|---|
| `Pure` | a function of its arguments: it carries no information from outside the process |
| `Controlled` | `--det` gives every run the same value (virtual clock, seeded generators, pinned host name) |
| `Recorded` | every call produces an event whose value carries what the test saw, so a difference is a different fingerprint |
| `Input` | what it returns is pinned by a run input the verifier compares (`runtime`, `code`, `deps`, `env:NAME`) |

Everything else is `Unaccounted`, **including every name the table does not list**, and a test that touched one is
NOT PROVEN whatever its fingerprint.

### Why this is a closed world and the old list was not

Default-deny is only worth something if the set being denied is bounded. The argument, in full:

1. A test can only obtain outside information by calling into C — a callable of the interpreter and its standard
   library, or one of an extension module. (In Node: a builtin module, a global the engine controls, or a native
   addon.)
2. *Which* callables exist is fixed by the `runtime` run input, which the verifier already compares. The surface is
   finite and auditable and cannot change under us without `runtime` changing with it.
3. So the table carries `AUDITED_RUNTIMES`: the versions its claims were actually audited against. A run on any
   other version is NOT PROVEN **before a single callable is looked at**. A callable that did not exist when the
   table was written therefore cannot be reached while the verdict is still IDENTICAL.
4. Extension modules are pinned by content, not by name: `inputs.deps` digests the bytes of the installed
   packages, so a different extension makes every test of the run diverge.

The old list was a claim about channels in the world, which is unbounded. This one is a claim about named
callables in a pinned interpreter, which is not.

### Where it lives — one implementation, not three

`crates/detpy-core/src/provable.rs` owns both halves of the rule:

* `account(module, qualname)` / `account_node(module, export)` — the accounting table;
* `judge(attestation)` — **the only predicate that may conclude a test is provable**.

| caller | what it used to do | what it does now |
|---|---|---|
| `verify.rs` | its own "any `uncontrolled` mark?" check | calls `judge_record` |
| `cache.rs` | `admit` on `Status::Stable` | `admit` documents that `Stable` *is* the rule's answer; new `admit_record` calls `judge_record` directly for a producer holding one run |
| `record.rs` | `uncacheable()`, a list of flags | the same list, with the general rule's `unacc` flag refused first |

So the cache and the verifier cannot drift apart, which was the point of asking for one implementation.

### The sensor contract

A shell declares what it watched in the trace header, as `meta.provable`:

```json
{"sensor": "py-monitoring/1", "contract": 1, "surface": "<digest of the table>", "runtime": "cpython3.13"}
```

`judge` refuses — NOT PROVEN for **every** test of the run — when that object is absent, when the contract version
is not this core's, when the surface digest is not this table's, or when the runtime is not one the table was
audited against. This is what makes the rule hold against an older shell, a foreign shell, or a shell built
against a different table: a run that cannot say what it watched must not be able to claim a green.

### The order of the clauses

`judge` asks, in order: is there a sensor this core understands → was it an audited runtime → is there a channel
rule that already names the gap → did the wide sensor see anything it could not place → did something happen
outside the tests.

The third clause comes before the fourth on purpose. Both answers are NOT PROVEN, but "the test started a thread"
tells a reader more than "`_thread.start_joinable_thread` is not accounted for". Getting this order wrong was a
real defect: it is what the attack suite caught (section 6).

## 3. The Python sensor: `sys.monitoring`, not `sys.addaudithook`

The brief suggested `sys.addaudithook` as the obvious wide sensor. I judged it and rejected it, with the
measurement:

* **MEASURED**: 200,000 `os.stat` calls raise **zero** audit events. The audit hook fires for about seventeen
  resource-acquisition operations (`open`, `import`, `exec`, `socket.connect`, `subprocess.Popen`,
  `ctypes.dlopen`, `os.listdir`, ...) and is blind to `os.stat`, `os.lstat`, `os.access`, `os.uname`,
  `resource.getrusage`, `os.read` on an open descriptor, extended attributes, and every environment, clock and
  random read. A general rule cannot rest on a sensor that cannot see file metadata.

`sys.monitoring`'s `CALL` event (PEP 669) fires for every callable invoked from Python bytecode, C functions
included, so it sees `posix.stat` like everything else. It needs Python 3.12+, which is no restriction: 3.12 is
the product's floor (3.11 is refused by the installer).

The audit hook is still installed as a **second, independent** sensor, in its own slot: `ctypes.dlopen` loads a
library whose calls never appear as Python calls at all, and an audit event the engine has no rule for is itself a
gap. Two sensors that fail differently are worth more than one.

### `DISABLE` is deliberately not used

`sys.monitoring` lets a callback return `DISABLE` to switch its event off at that one bytecode offset.

* **MEASURED**: with `DISABLE`, the callback fired **10 times for 900,000 calls**, and the steady-state cost was
  below measurement noise (a monitored loop ran at 0.70x the unmonitored one — i.e. nothing).

It is not used, and that is a decision. `DISABLE` is per *call site*, not per callable, so a polymorphic site —
`for fn in (os.stat, os.getxattr): fn(p)` — would be silenced after its first callee and the second would never be
seen. That is a hole in the rule, and speed never buys an exception.

### What the sensor skips, and why that is sound

Two things are not boundary crossings and are skipped:

1. **A callable implemented in Python.** Its body is bytecode, and every call it makes into C fires `CALL` again
   and is classified then. So `re.compile`, `posixpath.join`, `inspect.signature` and `pathlib.Path.stat` need no
   entry in the table — what they *do* is seen one level down, at `posix.stat` and friends. This is what keeps the
   table small enough to be auditable, and it is checked per callable (`__code__`) and per module (a module whose
   file is `.py`, or a frozen module).
2. **A call the test runner makes for its own bookkeeping.** The runner's identity is a run input and nothing
   writes its environment during a run (Rule E of the PROVABLE measurement). Only the runner itself and the engine
   count: a library in site-packages is user code and is watched like any other. This uses the engine's existing
   `_sites` classification, the same one every other observer uses.

## 4. The Node sensor: wrap the surface

Node is the mirror image. Its builtin module exports are **writable**, where CPython's C types are immutable — so
the sensor replaces the exports the table cannot account for with a wrapper that marks the test, instead of
watching every call. The accounted path then costs nothing at all.

* Installed last among the controls and **before** `syncBuiltinESMExports()`, so the engine's own patches are
  already in place and an ESM named import gets the wrapper too.
* Wrapping is a `Proxy` with `apply` and `construct` traps. A plain function calling `real.apply(this, args)`
  breaks `new Worker(...)` with "Class constructor cannot be invoked without 'new'" — a defect this report's
  measurements caught.
* **What the engine already patched is left exactly as it is.** The engine's own wrapper *is* the accounting:
  `children.js` replaces `worker_threads.Worker` so that creating one marks the test `uncontrolled.thread`, and
  wrapping over it hid that mark behind a generic one. `Patcher.saved` is the authority.
* A module the table has no rule for marks the test **on load**; an enumerated module has only its unaccounted
  exports wrapped. `child_process` is entirely unaccounted by design, but loading it is not yet using it, and the
  runner loads it for its own reasons — `node_module_policy` tells the two cases apart.
* Node runs tests in worker processes and merges their traces in the main process, which writes the header, so a
  worker's sensor is not visible where the declaration is built. Every process writes its own declaration into the
  run directory, and the run declares a sensor only when **every** part declared the same one. A part that could
  not start a sensor makes the whole run declare none.

## 5. The declared residual

An in-process sensor cannot see a call made from C to C. A native extension that opens a file or reads the clock
inside its own C code emits no Python-level call and no audit event. Two things narrow it:

* a changed extension changes `inputs.deps`, so it cannot pass as identical;
* **a test that loads a native extension not on the audited list is NOT PROVEN** (`unaccounted.native:<module>`).

What stays truly residual: a *listed* extension reading the real clock through the vDSO. No in-process sensor sees
it, and neither does `strace` — **MEASURED** by the parallel session: 600,000 real clock reads produce **0**
syscalls, while 1,000 `time.process_time()` calls produce exactly 1,000. It is a declared product limit
(`docs/LIMITS.md` C2f, K1), not something this rule pretends to cover.

Also residual, and stated rather than hidden:

* A non-function export of a Node builtin that carries outside state through a getter. Functions are wrapped; a
  module the table has no rule for marks on load, which covers the ones that matter (`node:inspector`, `node:v8`,
  `node:repl`).
* An export reached through a reference captured before the sensor installed. The engine installs its controls
  before any test file is loaded, so a test cannot hold an earlier reference; the runner might, and the runner is
  the declared controlled set.

## 6. What this costs — the numbers

### How many tests become NOT PROVEN

**MEASURED**, a 24-test suite written to exercise what real suites touch (json, re, pathlib, datetime,
dataclasses, collections, itertools, hashlib, base64, urllib, decimal, csv, tempfile, sqlite3, `unittest.mock`,
functools, struct, zlib, pickle, math, random, enum, heapq, uuid, typing, file I/O), two `--det` runs compared with
`fenvix verify`:

| | before the table was filled in | mid-way | final |
|---|---|---|---|
| IDENTICAL | 0 of 24 | 22 of 24 | **23 of 24** |
| NOT PROVEN | 24 of 24 | 2 of 24 | **1 of 24** |

The one remaining refusal is **not the general rule's**: it is the pre-existing `uncontrolled.env` rule firing on a
variable `unittest.mock.patch.dict` sets during the run and the test then reads. On this suite the general rule's
own cost is **0 of 24**, and no test carries an unaccounted entry at all.

**A correction to an earlier figure in this report's own history, because it changes the conclusion.** The mid-way
column counted `pwd.getpwuid` as a channel the rule had found in a test, and that was wrong: the caller was
pytest's own `tmp_path` machinery, reached through `getpass.getuser()`, not the test. Once the sensor walked to the
real caller (section 7b) it disappeared. `pwd.getpwuid` is still a channel the table does not account for, and a
*test* that calls it is still NOT PROVEN — it stays on the list in section 8 for that reason — but it was never
evidence of the rule's cost, and the share it inflated was an artifact of the sensor, not of the rule.

The honest summary of the cost, then: almost all of the over-refusal seen during this night's work was the sensor
misattributing the runner's own work to the test. The rule itself refuses very little on ordinary library code.
The figure that matters for real customer suites is the native-extension decision in section 10, not this one.

### What the sensor costs in time

| measurement | result |
|---|---|
| call-saturated microbenchmark (3 calls per loop iteration, nothing else), naive | **MEASURED** 2.25x |
| the same, with an identity-set fast path | **MEASURED** 1.38x |
| the 24-test suite above, whole process, best of 3 each | **MEASURED** 1.095s → 1.129s, **+3.0%** |

Real code does far more work per call than the microbenchmark, which is why the real figure is near 1.0x.

The switch `FENVIX_NO_PROVABLE_SENSOR=1` turns the sensor off, and it **cannot buy a green**: with no sensor the
header carries no declaration and the core refuses every test of the run. It exists to make the measurement above
possible and is safe by construction — there is no setting that makes the engine claim IDENTICAL on something it
did not watch.

### Two classifications corrected while measuring

Both were cases where the table refused something no test observes, which is noise rather than truth:

* the module loader's internals (`module._load`, `_resolveFilename`, ...) are `Input`: what they load is
  `inputs.code` and `inputs.deps`.
* the runner's worker channel (`process._send`, `_getActiveHandles`, `_tickCallback`) is the declared controlled
  set (Rule E), not a channel any test observes.

### One product change

`--det` now pins the terminal size to 80x24 (`_level0.pin_terminal_size`), the same class as the host name and the
CPU count. The real one differs between machines and between a terminal and a pipe, and the **runner** reads it to
lay out its own output. Leaving it uncontrolled made every run NOT PROVEN for a value no test ever observed.

## 7. The tests

### The general test — the finish line

`tests/test_provable_general_rule.py`, **6 tests, MEASURED 6/6 pass** (Python 3.13). Nothing in it names a channel
the engine knows; that is the point.

| test | what it proves |
|---|---|
| `a_name_the_table_has_never_seen_is_never_accounted` | 500 randomly generated `(module, callable)` pairs all answer `unaccounted`. Default-deny itself, with no list involved. |
| `the_table_only_claims_the_runtimes_it_was_audited_against` | the closed-world argument's third step, as a test |
| `a_run_that_cannot_say_what_it_watched_is_never_identical` | two runs of a genuinely deterministic test with the sensor off — same code, same inputs, same fingerprint — give NOT PROVEN, exit 1. The same two runs with the sensor on give IDENTICAL, so the refusal is the missing sensor and not the test. |
| `a_channel_derived_from_the_engines_own_table_is_not_proven` | the channel is **computed, not written**: the test asks the engine which of `posix`'s callables it cannot account for, calls that one, and asserts NOT PROVEN with the name in the verdict. It keeps working as the table grows. |
| `an_invented_native_channel_is_not_proven_and_not_identical` | **the finish line.** A C extension module built at test time under a name generated at test time (`atk_<random>`) reads a file **in C**. Nothing about it exists anywhere in the engine. The two runs see different bytes, no sensor in the process can see the read, and the engine — which cannot know they differed — answers NOT PROVEN and names the extension, instead of the IDENTICAL it would have answered before. |
| `the_invented_native_channel_is_refused_even_when_nothing_differs` | the same extension with both runs seeing the **same** bytes: still NOT PROVEN. A rule that only refuses when it happens to notice a difference is not a rule. |

Rust unit tests in `provable.rs` and `verify.rs` cover the predicate and the table directly: a trace with no
sensor, an unknown contract, an unknown surface digest, an unaudited runtime, an unaccounted name, the clause
order, and the table's default answer on both halves. **MEASURED: `cargo test -p detpy-core` 181/181.**

### One attack suite, in one place

The attacks had grown up one review at a time and lived in **six** places, so a change could be made and tested
without running most of them. `tests/attacks.py` is the single door:

```
python3 tests/attacks.py                 # every attack, Python and Node
python3 tests/attacks.py --only python
python3 tests/attacks.py --list
```

Nothing is deleted and nothing weakened: each file runs as it is, by its own runner. `tests/test_attack_suite.py`
fails if an attack file exists in the tree that the registry does not name — and it immediately found a **seventh**
file, `node/test/verifier-inputs.test.js`, which the brief's list of six had missed. A new `release-1` CI job runs
the entry point across Python 3.12/3.13/3.14 x Node 22/24/26, so every change now runs every attack.

**MEASURED**, first full local run (12 files): Node 5/5 files pass; Python 91 passed, 1 failed. The failure was a
real finding against my own change — a thread test reported reason `api` instead of `thread`, because the clause
order let the generic sensor hit outrank the specific channel mark. No verdict was wrong (both are NOT PROVEN) but
the report was worse, and the F-03 exam check requires that wording. Fixed by the clause order of section 2.

## 7b. What the reviewer round and CI found, and why it mattered

A reviewer round over the whole range found nine defects, six of them false greens. The pattern was one thing:
**the rule is default-deny in the core, but several of the paths feeding it were not**, so the guarantee leaked
back into IDENTICAL. Those are the blocking class, so they are fixed here rather than recorded.

| defect | why it was a false green |
|---|---|
| the Node sensor's per-test set was never cleared (`startTest` exported, never wired) | a gap was reported for the **first test of a worker only**; every later test came out clean. MEASURED: a file with two tests that each call `v8.getHeapStatistics` now marks both. |
| the Python `check_native` set was process-wide | an unaudited extension marked only the first test, although the module stays loaded for all of them — contradicting that method's own docstring |
| the cache-only declaration rested on `admit_record`, which nothing called | a fully-cached run declared a sensor on a premise that was never true. Made true: a gap now goes through `STATE.onLevel0Gap`, and a process without a sensor stores nothing. |
| `judge` never looked at the run's controls | every `Controlled` answer is a promise kept by a control `--det-disable` can switch off. New `required_controls(sensor)` refuses before a single name is looked at. |
| the Node report filter dropped gaps under `node_modules` | a gap a test reached through an ordinary dependency was invisible |
| lazy arming hooked `module._load`, which is CJS only | a builtin reached by ESM `import` was never armed. MEASURED: ESM default and named imports of `node:v8` are both caught now. |

Then CI found two things this container could not have:

1. **The native-extension rule was by name, and had to be by path.** On the hosted CPython 3.13 the standard
   library's extension modules are separate shared objects; in this container they are built into the interpreter
   binary. **MEASURED** (CI run 44950993706): `native:_asyncio (and 13 more)` on a test that only adds up a range.
   A list of names refused almost every test there and nothing here. The shells now decide by where the extension
   lives, using the engine's own `_sites` classification: the interpreter's own extensions are part of the
   interpreter (pinned by `runtime`), the engine's and the runner's are the declared controlled set, and anything
   else must be on the audited list. MEASURED that it still bites: `numpy/_multiarray_umath`, `lxml/etree` and a
   project's own `.so` all classify as user code and are still refused.
2. **The sensor was charging the test for the runner's own calls**, because it looked at one frame where every
   other observer in the engine walks. pytest's `tmp_path` machinery reaches `pwd.getpwuid` through
   `getpass.getuser()`, so the immediate caller is the standard library and only the frame above it says whose
   call it is. The sensor now uses `_sites.resolve()` — and asks only when a gap is about to be reported, so the
   walk is off the hot path. **MEASURED**: `tests/test_controls_f01.py` plus `tests/test_fingerprint.py` go from
   9 failures to 19/19. `test_controls_f01` is the F-01 row's own evidence, so this was the cluster that mattered.

Both of those are worth stating plainly: the general rule's cost is not where it first appeared to be. Almost all
of the early over-refusal was the sensor misattributing the runner's work to the test, not the rule refusing real
channels.

### The defect that mattered most, and what caught it

Fixing the over-attribution above, I made the Python sensor ask whose call it is through `_sites.resolve(depth)`.
That was right. The depth was not: `resolve` counts from its own frame, so from inside a `sys.monitoring` callback
the frame making the call is at depth **2**, and I passed **1**.

With 1 the sensor saw its own frame, which is the engine's, concluded "infrastructure", and reported **nothing**.
The general rule was dead — and every suite went green, which is the worst way for this to fail: a rule whose
whole purpose is to refuse would have shipped refusing nothing, and nothing in the channel-specific tests could
have noticed, because they each test a channel that has its own rule.

What caught it was `test_a_channel_derived_from_the_engines_own_table_is_not_proven` — the test whose entire job
is to notice this, because it asks the engine which callable it cannot account for, calls that one, and asserts
the engine says so. That is the argument for writing the general test the way this block was asked to, rather
than adding more channel tests. **MEASURED** from inside the callback: `resolve(0)` and `resolve(1)` answer
`None`, `resolve(2)` answers the frame making the call. The depth is now a named constant with that measurement
beside it, and the fix is confirmed from both sides: the derived channel is reported again **and** pytest's own
`pwd.getpwuid` call is still suppressed.

### "Reused" is the same claim as "identical"

A reviewer found that `record.rs`'s `uncacheable()` had an `unacc` clause that nothing ever set, so the Python
cache could store and later reuse a result the rule refuses. That is the blocking class too — the founder's rule
covers `reused` as well as `identical`, and the decision quoted to the parallel measurement session says
whatever the cache cannot observe with certainty forces a rerun.

The sensor now calls a hook the cache installs (`provable.ON_GAP` → `Capture._note_unaccounted` → flag `unacc`),
which is the clause that was dead; a run with no sensor flags every test the same way, so nothing from it is
stored either. The Node side reaches the same refusal through `STATE.onLevel0Gap`, the engine's existing signal.
`test_the_cache_never_reuses_a_test_the_rule_refuses` covers it, with the channel derived from the table so the
test names none.

## 8. Channels to cover later

Per the judging rule, a channel where the engine answers NOT PROVEN is not a defect. These are recorded, not
fixed:

| channel | where | why it is NOT PROVEN today |
|---|---|---|
| `pwd.getpwuid`, `grp.getgrgid` | Python | the user database behind `expanduser`/`getpass`; the home directory differs between machines and no event carries it. A test that calls one is NOT PROVEN; the runner's own call through `getpass.getuser()` is not charged to it (Rule E). |
| `os.getxattr`, `os.listxattr`, `os.setxattr` | Python | extended attributes have no event |
| `sys.settrace`, `sys.setprofile`, `sys._current_frames` of other threads | Python | process state the engine makes no claim about |
| `gc.get_objects`, `gc.get_referrers` | Python | they hand out the heap: object identity and allocation order leak through them |
| `_ssl` trust store and `RAND_*` | Python | the trust store is read from disk; the random pool is the operating system's |
| `sqlite3.load_extension` | Python | what the C library then does is in C |
| `node:v8`, `node:vm`, `node:inspector`, `node:trace_events`, `node:repl`, `node:sqlite`, `node:async_hooks`, `node:cluster`, `node:wasi` | Node | the heap, another realm, the debugger, the tracer, an interactive loop, a bundled database, the async scheduling graph: no event covers any of them |
| `fs.watch`, `fs.watchFile` | Node | the file system as an event source: when a change arrives is not controlled |
| `perf_hooks.monitorEventLoopDelay`, `PerformanceObserver`, `eventLoopUtilization` | Node | the event loop's own timing is scheduling, which Level 0 does not control |
| `process.stdin`, `builtins.input` | both | standard input has no event |
| `tty.isatty`, `node:readline` | Node | whether a descriptor is a terminal is not pinned |

## 9. Still open

Rewritten on 2026-11-22, at the end of the round that closed the four red jobs of CI 44964230574.

| item | state |
|---|---|
| `F-02.py-explore.idoft-py-autodoc` | **blocked by the container, not by the engine.** The check needs the real project cloned with its dependencies installed, and this container's guardrail refuses to build a freshly cloned third-party project. The class is covered by `tests/test_fenvix_cli.py::test_explore_finds_the_target_when_another_module_does_not_import`. The real check is decided by the CI exam. |
| `test_capture_sessions_match_reference` | **green.** The two paths disagreed on cacheability and not on what they record: the round-1 reference loop is older than the general rule, so it reused a test that had run a subprocess. The reference's `_uncacheable` now has the rule as its last branch, with the same flag and the same words as `record.rs`. |
| the full local suites | Python shard 2 of 4 on 3.13 (the red job's own file list): 226 passed, 7 skipped. Node shard 0 of 4: 176 passed. The attack suite, one entry point, 12 files: Python rc=0 AND Node rc=0. `cargo test -p detpy-core` 198/198. |
| the CI matrix | dispatched on this branch at every head; the state at the time of writing is in the session report. |
| the reviewer round | done: R-058, one round, its five false greens fixed in 80f58330 and f564df14. The closing rule allows no second reviewer on the same work. |
| **the founder's decision on compiled extensions** | taken (2026-11-21, route 1) and applied by measurement: see section 12 and docs/NATIVE-AUDITS.md. |

## 11. The open engine test: what it actually was

The previous round's diagnosis was right in kind — a stale reference, not a capture regression — and there were
two causes, both in the fixture.

1. The reference capture (`tests/rust_hotpaths_ref/_ref_proofcache.py`, installed as `detpy.proofcache`) makes its
   own metadata checks from Python, where the Rust capture makes them in C and Level 0 sees nothing. After R-055
   added the `fs.stat` observer, those became `fs.stat` events of whichever test happened to be running. The
   reference now asks through the functions detpy captured before installing its observer (`osstate._real_stat`
   and `_real_lstat`, the latter added for this). What it records as cache dependencies is unchanged — `note()`
   still runs — only the Level 0 event is gone, which is exactly what the Rust capture does.

2. One test still differed after that, and the cause was not stat observation at all. **MEASURED** by diffing the
   two event chains for `test_m.py::test_dns_loopback`: the reference run's test produced 2 events, the Rust run's
   4, the extra two being `fs.stat /usr|dir`. The test calls `socket.getaddrinfo`, which imports
   `encodings.idna` the first time a host name is resolved; that import makes `posixpath.realpath` stat `/usr`.
   The two capture implementations do not import the same modules, so the lazy import landed inside the test in
   one run and before it in the other. The harness plugin (`_capref.py`, loaded in both modes) now warms that
   import. It is a property of the harness: the comparison is about what the captures record, not about which
   modules they happen to pull in.

**MEASURED** after both: sessions 1 to 4 match on every compared facet (stores, receipts, outcomes, summaries,
keys, terminal output). Session 5 differs on `child_entropy_draws`, 3 against 2 — the load-sensitive flake already
recorded in `sessions/2026-11-19-parallel-proof/REPORT.md` ("session 5 counted 2 instead of 3 child entropy draws
while the walk ran on the same 4 cores; it passed 2 of 2 times alone afterwards"). It ran here with the Node suite
on the same 4 cores at load average 3, and is to be re-run alone.

## 9b. The test the decision invalidated, and what it asserts now

`tests/test_f01_gaps.py::test_numpy_imported_lazily_and_unseeded_generators` asserted that two `--det` runs of
a numpy test verify IDENTICAL. Under the native-extension rule numpy is an unaudited third-party compiled
extension, so the verdict is NOT PROVEN and that assertion could not hold.

It now asserts what the decision says, and more than it did before: the seeding still works (the printed values
are equal in both runs), the refusal NAMES numpy, and the test that does not touch numpy stays covered by
Level 0 — a blanket refusal of the whole run would fail it. The new helper `refused()` is the counterpart of
`identical()`: it asserts a NON-ZERO exit, because a clean exit on a run the engine cannot prove is the one
failure this rule exists to prevent.

## 10. The founder's decision on compiled extensions, and how it was applied

The rule refuses any test whose run loads a native extension that is not on an audited list, because a C
extension's own reads are invisible to every in-process sensor. The founder decided on 2026-11-21 (route 1):
*the commonly used compiled extensions are audited one by one by MEASURING what they actually ask the system
for, and only those are listed, with the evidence. An unaudited compiled extension is NOT PROVEN. A hand audit
is our promise, not a proof; only a syscall-level sensor makes it a proof.*

Two had to be settled to close this block, and they came out differently, which is the point of measuring. The
evidence, the method and the limits of each are in `docs/NATIVE-AUDITS.md`.

* **`@unrs/resolver-binding-*` (`unrs-resolver` 1.13.0): audited and listed.** `jest-resolve` depends on it, so
  a jest 30 run loads it before the first test and **every test of every jest 30 suite was NOT PROVEN** —
  MEASURED on a four-file project: `covered by Level 0: 0  not proven: 12`. Nothing could be proven, cached or
  spread across cores. The measurement of the extension itself (`strace`, five specifiers resolved, counted
  between two markers so Node's start-up is not credited to it): `statx 20, openat 7, read 6` and nothing
  else — no `getdents64` (it never enumerates a directory, so no listing order can reach a test), no
  `getrandom`, no clock, no socket, no `getpid`, no `uname`.
* **numpy 2.5.5: measured, NOT listed.** Ordinary array work with a seeded generator:
  `stat 52, openat 23, read 30, mmap 43, getdents64 2, getrandom 2`. The file reads are the lazy import of
  `numpy.random`, which is a run input already. The two `getrandom` calls are not explained: the generator was
  seeded, and a C-level `getrandom` is invisible to the engine's Python-level entropy control. "Most likely
  OpenSSL" is not an attribution, so numpy stays unlisted — clearing it on this evidence would be a green on a
  doubt.

What that costs, said plainly: a Python suite that imports numpy, pydantic-core, lxml or psycopg is NOT PROVEN
today, and finishing numpy's audit is the next step on that list.

The mechanism is `NODE_AUDITED_NATIVE` in the core — so the list is part of `surface_digest` and a trace
written under a different list is refused — `provable_native_audited` over napi, and the `dlopen` hook in
`node/src/provable.js` asking it. The engine's own addon is in the list too: it had been exempt only because it
is loaded before the sensor starts, which is timing, not a reason.

## 12. The round of 2026-11-22: the four red jobs, by cause

The matrix of CI 44964230574 stopped on four jobs. They were four causes, not forty, and three of the four were
the same shape as the `_thread.lock` red of the night before: an entry the table could answer for and did not.

**The instrument came first.** The three fixes of the previous night were each found by a red CI job naming one
callable (`_thread.lock`, `posix.register_at_fork`, `async_hooks.AsyncResource`) — three commits, three names,
and no reason to think the fourth would not arrive the same way. So this round began with a probe: 37
deliberately boring tests (read a file, walk a directory, write a log line, copy a file, open a sqlite
database, run a subprocess, start a thread, await a coroutine), run twice under `--det` and verified. It found
four refusals in half a minute, one of which CI had already hit and three of which it had not yet reached:

| what an ordinary test did | what the engine answered |
|---|---|
| `os.walk` / `os.scandir` | `not accounted for: api:posix.DirEntry.is_dir` |
| one `logging` line | `not accounted for: api:_asyncio.current_task` |
| `shutil.copy` | `not accounted for: audit:shutil.copymode` |
| CPython 3.14, anything | `not accounted for: api:_interpqueues._register_heap_types` |

The first is the sharpest: **every arm of the table that named a type's method was dead code.** `account` hands
the per-module tables the LAST component of a qualified name, so `DirEntry.is_dir` was compared against
`is_dir` and never matched. The second is the widest: since 3.12 every `logging` record carries `taskName`,
which calls `asyncio.current_task()`, so the commonest line in any codebase was unaccounted. MEASURED on the
probe suite: 7 of 37 tests NOT PROVEN before, 4 after, and the 4 that remain are the refusals that are real —
a thread, a child process, an environment variable the test reads, an event loop.

**The 3.12 red was not an attack-suite problem: every `--det` run on 3.12 died.** MEASURED on 3.12.3, a project
with one trivial test: the test passes, the trace is written, and the process exits 139 (SIGSEGV), three runs
out of three, while the same project on 3.13 exits 0. A native backtrace named the cause —
`Py_FinalizeEx -> _core::sysmon::audit_hook -> PyObject_CallFunctionObjArgs`: finalization goes on raising audit
events while it tears the interpreter down, and the sensor's Python callable had already been freed. An audit
hook cannot be removed once installed, so it is made inert instead, by an `atexit` callback registered when the
first slot is set and by the `cpython._PySys_ClearAuditHooks` event. What a customer would have seen is worse
than a red job: a green suite followed by a crash exit code.

**The Node red was in the parallel run, and the timers were innocent.** Only the `timers N` tests differed
between a parallel run and the serial one. MEASURED by diffing the two event chains: the parallel run had one
event the serial run did not, `other/process.pid at <node>`. A Jest worker emits Node's `_channel` deprecation
warning, and Node's warning PRINTER reads `process.pid` for its `(node:NNNN)` prefix; in a parallel run that
lands while a test is awaiting a timer. So a test's fingerprint depended on whether Node happened to print a
warning while it ran.

The first fix for it was too wide — it dropped every event with no user frame — and **the attack suite caught it
within one run**: `fs.promises.access: IDENTICAL although the test observed [true, false]`, and an outside file
with different contents in the two runs called stable. An asynchronous observation completes with nothing but
internal frames on the stack although the test asked for it at call time, so dropping those took real
observations out of the fingerprint. The rule therefore lives where the evidence for it was: `src/facts.js`, the
synchronous reads of this process's and this machine's state, where the frame that asked is on the stack at that
moment. This is the clearest thing the round has to say about the closing rule itself: one entry point for every
earlier reviewer's attack file is what turns a plausible fix into a measured one.

**The Python red was five tests, and three of them were the table.** Once `_asyncio` and the `DirEntry` methods
were accounted for, the reference capture and the current one wrote the same bytes again. Of the other two, one
was the capture-equivalence session (section 9) and one was a defect of the test itself: a `get` whose default
never fires because the key is present and null.

**And one thing the rule had taken from the customer.** While fixing the equivalence session:
`subprocess.run(["true"])` under `--det-cache` was refused with *"did something the engine cannot account for
(NOT PROVEN: see the trace's unaccounted list)"* instead of *"subprocess"*. The refusal is right; the name was
not, and the name is what the customer reads to find out why a test was rerun. The gaps that are the act of
starting a child are now flagged under the child channel, so the receipt says "subprocess" again.
