# Python proof cache: precise per-test state tracking (P-061)

Status: **design (phase 1)**. Nothing in this document is implemented yet. The attack tests
(`tests/test_cache_precise.py`) and the measurement harness (`harness/cache_precise/`) are in place. Phase 2
implements the design on top of the R-056 fixes. Every number carries MEASURED / ESTIMATED / DECLARED / UNKNOWN.

## 1. Problem

A test that runs under `--det-cache` must see the in-process state a fresh run of the suite gives it. Today the cache
keeps that sound with a coarse rule (LIMITS 10, "written reuse limit"). A test runs when it:

- fails;
- is new;
- sits in an edited test file;
- or is never cacheable.

Before it runs, every earlier test of its process (worker) runs too, once its carried set reached the library node.
Most real tests reach it, because they import pytest or any library. That state is not tracked per test.

Measured cost, exam run 44925123655 (MEASURED):

| project | situation | reused |
|---|---|---|
| attrs 25.3.0 | unchanged rerun, 2 tests always fail (positions 1,073-1,074) | 256 of 1,322 serial, 0 under `-n 2` |
| attrs 25.3.0 | same suite, every test passing | 1,330 of 1,330 serial and `-n 2` (local) |
| itsdangerous 2.2.0 | one test file edited (a new failing test) | 0 of 298 |

The goal is to rerun only the earlier tests that **modified** something the running test may **read**. When either
side is unknown, the rule stays "every earlier test". The result must never be a wrong reuse, and never a wrong
outcome for a test the cache runs.

## 2. Model

The state of a process is a set of **cells**. A cell is one place where a test can leave something that a later test
in the same process can observe. Section 4 lists every cell family. The baseline is the state of a process when
collection has ended, before its first test. It is the same in every session with the same code and inputs: the code
prefix and import-effect rules (R-052, R-053, R-056 W1/W2) make sure of that, and phase 2 builds on those fixes as
they are.

Each **context** is one of:

- a test (setup, call and teardown of its function-scoped fixtures);
- a wider-scoped fixture's setup or teardown;
- the code between tests.

The capture already switches contexts at these points. For each context `c` of a recording run, phase 2 records:

- **`M(c)`**, the cells `c` modified. These are the cells whose value at `c`'s end differs from their value at `c`'s
  start. A change `c` undid before it ended, such as `monkeypatch` or a `try/finally` restore, is no modification.
  `M(c) = ?` (unknown) when `c` did something section 7 lists.
- **`E(c)`**, the effect digest: the digest of `(cell, value digest)` over `M(c)` after `c`.
- **`R(c)`**, the cells `c` may read, as an over-approximation (section 5).

A test `T` that runs in a session **needs** every earlier context `t` of its process for which one of these holds:

- `M(t) = ?`;
- `R(T) = ?` and `M(t) ≠ ∅`;
- `M(t) ∩ R(T) ≠ ∅`.

The needs are transitive: a needed test runs, so its own needs run before it. An earlier test with `M(t) = ∅` is never
needed. It left nothing behind, so a process that skips it reaches every later test in the same state.

**Why it is sound.** Take a running test `T` and the set `P` of earlier tests that run before it in this session.
Every cell `T` may read was last written, in the fresh run's order, by tests that are all in `P`, because a writer of
a cell in `R(T)` is in `needs(T)`. Each of those tests itself ran after all the writers of the cells it read (by
induction on the order), so it wrote the same values it wrote in the recording run. So every cell in `R(T)` holds, when
`T` starts, the value a fresh run gives it.

Cells outside `R(T)` may differ, because the tests that were skipped did not write them. By the definition of `R`,
`T` cannot observe those cells. A reused test does not run, so its correctness only needs its key and its stored
needs to be unchanged (section 6).

**Wider-scoped fixtures.** A needed context that is a fixture setup or teardown is reproduced when some running test
uses the fixture. That test is the earliest test that used it in the recording run (the first user). If the earliest
running user comes later than the first user did, the first user is added to the needs.

## 3. What changes in the store

These fields are additions to the store of R-056's trunk. The existing keys, the code prefix and import effects stay
as they are.

| field | where | content |
|---|---|---|
| `mods` | per test entry, and per loose entry (a test with no stored result) | the sorted cell ids of `M(t)`, or `"?"`; also for each fixture context |
| `effect` | same | `E(t)` |
| `reads` | same | `R(t)` as a set of cell-family masks plus module ids, or `"?"` |
| `cells` | per store | the interned cell names, as `(family, module or object path, attribute)` |
| `needs` | per entry (exists) | stays, now derived from `mods`/`reads` and no longer from the static closure alone |

For the size: `mods` is empty for most tests (ESTIMATED, to be MEASURED in phase 2). The cell table is shared.

## 4. What each test records as MODIFIED

The cells are observed by a **diff at context switches**. The state is digested at a context's start and at its end
(in practice once per switch: the end of one context is the start of the next). Each family below says how its cells
are observed and digested.

| family | cells | how observed | digest | attack (`tests/test_cache_precise.py`, channel) |
|---|---|---|---|---|
| module globals | `(module, name)` for every module in `sys.modules` except the infrastructure modules (below) | dict watcher (`PyDict_AddWatcher`, 3.12+) on every module `__dict__`: binding, rebinding, deletion. Exact, no cost without writes | value digest (below) | global-rebind, import-side-effect |
| in-place changes of objects reachable from a module global | the module global through which they are reached | a deep **value digest** of each global's value, taken at the switch | structural: containers (dict, list, tuple, set, frozenset, deque, OrderedDict, defaultdict, Counter, array, bytearray, memoryview of those), instance `__dict__` and `__slots__`, class `__dict__` (a class attribute set is also seen by a type watcher), function `__defaults__`, `__kwdefaults__`, `__dict__` and closure cell contents, `functools.partial` arguments, `lru_cache` wrappers by `cache_info()` and their contents through `__wrapped__` and the cache (`cache_parameters()`), shared objects by identity once visited. Immutable scalars by value; code objects and builtins by identity | dict-item, nested-list, set-add, class-attr, instance-attr, slots-attr, default-arg, closure-cell, func-attr, lru-impure, restore-chain, read-chain, deque, array, bytearray |
| C objects held by a module | the global that reaches them | a **state probe** per type: `sqlite3.Connection` by `total_changes` and `in_transaction`; `io` objects by `tell()`, `closed` and, for `StringIO`/`BytesIO`, `getvalue()`; generators by `gi_frame.f_lasti` and their frame locals; `itertools` iterators and other C types that pickle, by `__reduce_ex__(4)`; `random.Random` by `getstate()`; `hashlib` objects by `copy().hexdigest()`; locks by `locked()`; sockets by `fileno()` and the peer; `ssl.SSLContext` by `cert_store_stats()`, options and verify mode; `decimal.Context` by its fields, flags included | the probe's value | sqlite-memory, stringio, itertools-count, generator, random-instance, hash-object |
| C objects without a probe | the global that reaches them | not observable: the cell is **opaque** (section 7) | — | — |
| `sys` | `path`, `meta_path`, `path_hooks`, `modules` (the key set, and each module's identity), `getrecursionlimit()`, `get_int_max_str_digits()`, `getswitchinterval()`, `dont_write_bytecode`, `excepthook`, `unraisablehook`, `displayhook`, `breakpointhook`, `gettrace()`, `getprofile()`, `get_asyncgen_hooks()`, `std{in,out,err}` identity (at switches where pytest's capture is resumed), `flags` | read at the switch | value / identity | recursion-limit, int-max-str-digits, sys-path, sys-modules, excepthook |
| first import of a module | `(module, *)`: a module that enters `sys.modules` during `t` | the `sys.modules` key set | the module's dict digest | import-side-effect |
| builtins | `builtins.__dict__` | dict watcher | value | builtins |
| gc | `isenabled()`, `get_threshold()`, `get_freeze_count()`, `get_debug()` | read | value | gc-disabled, gc-threshold |
| warnings and logging | `warnings.filters` (pytest's plugin restores it per test; still a cell), `logging.root.manager.disable` and the logger tree | module globals | value | logging-disable |
| decimal | the main thread's context | probe | fields | decimal-context |
| locale | each category through `setlocale(cat)` | read | value | locale |
| signals | `getsignal(n)` for every signal, `pthread_sigmask` blocked set, `getitimer` | read | value | signal-handler |
| socket | `getdefaulttimeout()` | read | value | socket-timeout |
| environment | `os.environ` (dict watcher on its `_data`), `putenv`/`unsetenv` (audit events `os.putenv`, `os.unsetenv`) | events | value | environ, putenv |
| process | cwd, umask (from `/proc/self/status`, no race), resource limits, open descriptor table (`/proc/self/fd`: number and target) | read | value | chdir, umask |
| codecs | the search function registry | `codecs.register` / `unregister` wrapped: a call marks `M(t) = ?` (the registry is not readable) | — | codecs-register |
| audit hooks | `sys.addaudithook` | the `sys.addaudithook` audit event: `M(t) = ?` (a hook cannot be removed or listed) | — | audit-hook |
| at-fork hooks | `os.register_at_fork` | wrapped: `M(t) = ?` | — | at-fork |
| files | `(file, path)` for every path the context wrote, created, renamed or removed and that still differs at its end | the capture's write events (in-process and children: R-023b data edges, `plan.writers`) | content digest | file-written, file-by-child |
| child processes | a child still alive at the context's end | the capture | — | `M(t) = ?` (section 7) |
| threads | a thread started by the context and alive at its end | `threading.enumerate()` and the native thread list | — | live-thread: `M(t) = ?` |

**Infrastructure modules** are pytest, pluggy, xdist, detpy and the `_pytest` tree. They are not walked: their state
changes with every test (reports, nodes, capture), and the existing rules already cover what a test can leave in them.
The R-023c E5 markers (`request`, `config`, `cache`, `stash`, the session-scoped factories) connect through the static
closure, and those tests keep `R = ?`. Session- and module-scoped fixture values are cells of their own,
`(fixture, name)`, walked like a module global.

**Declared pure memos (DECLARED).** Some caches change as tests run but only memoize a pure function of their key. A
fill of one of these is not a modification. The list is closed. An entry is added only with an attack test that shows
the impure case still counts.

- `re._cache` and `re._cache2`;
- `functools._lru_cache_wrapper` instances in the standard library whose wrapped function is pure: `fnmatch._compile_pattern`, `ipaddress`, `typing`'s `_tp_cache`;
- `typing._caches` and `typing._cleanups`;
- `linecache.cache`;
- `sys.path_importer_cache` and `importlib._bootstrap_external` path caches;
- `abc` caches (`_abc_cache`, `_abc_negative_cache`, the C ABC data);
- `encodings._cache`, `struct`'s cache and `inspect`'s module caches;
- `__warningregistry__` (pytest resets the filters version per test).

A third-party `lru_cache` is a modification (channel lru-impure).

**Value digest.** One walk per switch, from the roots: the module dicts, the `sys` cells, the fixture values. A
per-walk memo by `id` covers objects shared between roots. The walk is in Rust (`detpy-core`), over the object graph
read through the C API. Its cost is part of the phase-2 measurement (section 9). Its budget: if one walk visits more
than `DETPY_PRECISE_MAX_OBJECTS` objects (default 2,000,000), or a root's walk fails, the context gets `M(c) = ?`.
The cost never makes a result wrong; it only lowers reuse. A large static object graph, such as botocore's service
models, is walked once per switch. Phase 2 measures whether the dict watchers allow skipping the subtrees of watched
dicts that did not change. Containers without watchers (lists, sets, instances with inline values) keep being walked.

## 5. What each test records as READ

`R(T)` needs to over-approximate only the **in-memory** cells. The external channels below are read dynamically by
the capture already.

| family | how `R(T)` is bounded |
|---|---|
| module globals and objects reached from them | the existing static **reference closure** (`record.rs::reference_closure_with`): the repository files `T`'s contexts executed and everything they import, transitively, plus the library node. A test whose closure reaches the library node reads every library module cell. A file with a dynamic-access marker (R-032b F1, R-023c E5) has `R = ?` |
| interpreter, process, environment and locale cells (`sys`, gc, signals, cwd, umask, environ, decimal, locale, socket, codecs, descriptors) | always read: every test reads them (`R` contains these families for every test) |
| files | the capture's recorded reads (paths and contents). For a test that never ran (new), unknown: every earlier test whose `M` holds a file cell is needed |
| fixture values | the fixtures `T` requests (its fixture closure, from pytest) |

So for a typical test, which reaches a library, `R(T)` is effectively "everything", and the precision comes from `M`.
Only the earlier tests that left something behind are needed. Section 9 measures how many tests those are.

## 6. How needs are derived, per situation

| situation | before (today) | P-061 |
|---|---|---|
| `T` fails (no stored result) | every earlier test of its process | `needs(T)` from the stored `mods`/`reads` of the earlier tests and `T`'s loose `reads`, transitively |
| `T` is new | every earlier test of its process | `needs(T)` with `R(T)` from the static closure of its file, or `?` when the file cannot be analysed, and the file family unknown |
| `T`'s test file was edited; `T`'s own unit is unchanged | every earlier test, and every later test of the process | `T` reruns only if its key (units, code prefix as fixed by R-056) says so; its needs as above |
| an earlier test `t` changed (it runs: new code, new test, failing) | every later test of the process reruns (code prefix) | **conditional reuse** (below) |
| an earlier test was deselected or removed | prefix digest mismatch: later tests rerun | a later test is reused if the removed tests had `M = ∅`, or their `M` does not intersect its `R`; otherwise it reruns with its needs |
| `-n N` | the same rules per worker list | the same, per worker list: the controller computes needs from the stored fields; workers report `M`/`E` in their shards |

**Conditional reuse.** When an earlier test `t` runs because its code changed (or it is new), its new effect `E'(t)`
is known only after it has run. A later test `L` whose key is unchanged is marked as a conditional hit when it depends
on `t` (`M(t) ∩ R(L) ≠ ∅`, or `M(t)` was unknown or empty before, since a new effect may appear). At `L`'s turn the
condition is checked:

- `E'(t) = E(t)` for every such `t`: the state `L` reads is the recorded one. `L` is reused, and its stored result is
  reported.
- Otherwise `L` must run, but the tests it needs may already have been skipped in this session. `L` is then replayed in
  a fresh child process after every earlier test of its process: the placement-replay path of LIMITS 10, which already
  runs "the earlier tests of the session (or the worker)". This is a **late demotion**. Its count is reported in the
  summary line, and phase 2 measures how often it happens.

Serial sessions check the condition in `ProofSession.recheck` (the existing at-turn hook). Under `-n`, the controller
sends a conditional hit to its worker with the expected `E` digests, and the worker checks them at the test's turn and
reports either the stored result or a run.

## 7. What stays unknown, so every earlier test reruns

A context gets `M(c) = ?` when it:

- leaves a **thread** running, or a **child process** alive (state keeps changing after it ended);
- registers a **codec search function**, an **audit hook** or an **at-fork hook** (state that cannot be read back);
- is refused by the cache for native code or `ctypes` (LIMITS 9 A1/A2): C code can write any memory;
- holds or reaches an **opaque C object** (a C type without a state probe that does not pickle) in a cell the context
  may have modified. That means the context's static closure reaches the module holding it, or the object is new;
- exceeds the walk budget, or the walk fails;
- runs while the dict watchers or type watchers could not be installed (Python < 3.12 is not supported by the cache
  anyway).

A test gets `R(T) = ?` when:

- its file holds a dynamic-access marker (R-032b F1, R-023c E5);
- its file cannot be parsed;
- it is new and its imports cannot be resolved.

`R = ?` alone does not mean every earlier test reruns: only the earlier tests with `M ≠ ∅` do. `M = ?` makes that
earlier context needed by every later test that runs. The list of opaque types met in a session is written to the
summary (`opaque cells: <type> x N`) so that the residual cost is visible.

Still out of reach (DECLARED): **state written by C code without a Python-visible effect**, such as an extension's
static variables or a C library's global (`setlocale` aside, which is read back). This is LIMITS S1. Today's rule
covers it only by accident, by rerunning everything. With P-061 such a write by an earlier test that is otherwise
quiet (`M = ∅`) is not seen. The mitigation is the refusal of repository native code (A1). For installed extensions,
phase 2 adds this rule: a context that called into an extension module not on a short list of stateless or probed
modules gets `M = ?`. A `sys.monitoring` `CALL` event on calls to C functions of non-listed extension modules marks
the context. Its cost is part of the phase-2 measurement. If the cost is too high, the rule falls back to marking
every context that executed code in a file that imports such an extension.

## 8. Attack tests

`tests/test_cache_precise.py::test_running_victim_sees_the_state_of_the_full_prefix` runs one scenario per
(channel, trigger, mode):

- 48 channels × 3 triggers (`fail`: the victim fails because of the polluter; `new`: the victim is added and passes
  only after the polluter; `edit`: the victim's file is edited and the victim passes only after the polluter);
- 2 modes: serial, and `-n 2 --dist loadgroup` with the polluter and the victim in one group.

Each scenario asserts its precondition (uncached `--det` gives the victim the trigger's outcome) and then that every
cached outcome equals uncached `--det`. The channels with two polluters (lru-impure, restore-chain, read-chain) attack
a partial prefix, where only the second writer runs. On the current engine every scenario passes, since every earlier
test reruns. Phase 2 must keep all of them green.

The reuse targets of phase 2 are `test_reuse_*`, marked `xfail(strict=True)` until phase 2:

- a failing test reruns alone, or with its one modifier;
- a new test runs alone;
- an edited test file reruns at most its own tests.

### Finding of phase 1: `putenv` and children under the cache (a wrong outcome, not a wrong reuse)

All 6 putenv scenarios fail on 0fbf228: 3 triggers, serial and `-n 2` (MEASURED, 3.13). An earlier test calls
`os.putenv('P061P', '1')`, and a later test starts `sh -c 'printf %s "$P061P"'` (it inherits the environment).

| run | victim |
|---|---|
| plain pytest | passed |
| uncached `--det` | passed |
| `--det --det-cache`, cold (nothing reused; serial, `--det-cache-in-process` too) | **failed**: the child sees no `P061P` |

Cause (read, not changed in phase 1): `python/detpy/follow.py:337` adds the clock shim to `LD_PRELOAD` for a followed
child. To do that it replaces an inherited environment (`env=None`) with one built from `os.environb._data`, which
does not hold the variables set with `os.putenv` (they live only in the C `environ`). Variables removed with
`os.unsetenv` come back in the child the same way.

Whether the child's whole-environment read (`env_read_ctx(ctx, "*")`) keys the C `environ` or `os.environ` is
UNKNOWN (not traced in phase 1). Fix direction: build the child's environment, and its key, from the C `environ`, through
`_core` (`std::env::vars_os`, which reads it) rather than `os.environ`. This file is not one of the three under
repair, but it is cache code: the fix is left for the coordinator to assign. The attack stays failing until then.

## 9. Measurement

`harness/cache_precise/measure.py`, dispatched with `.github/workflows/cache-precise.yml`, runs per project and mode:

- projects: attrs 25.3.0 and itsdangerous 2.2.0 at the exam's pins, and moto 96f50b1a with `tests/test_s3` and
  `tests/test_sqs`, `--dist loadscope`;
- modes: serial and `-n 4`;
- scenarios: unchanged, add a test, edit a test file (a new failing test), and a test that always fails.

It reports reused, ran and wall times, and every result that differs from uncached `--det`, with a second uncached run
to separate a wrong result from a flaky test. Phase 2 also reports the cost: the walk time per switch, the number of
`M = ?` contexts by cause, and the late demotions.

Done (from the prompt, MEASURED on GitHub Actions):

- the exam's F-05.no-edit (≥ 90 % reused on attrs), F-05.edit-test.itsdangerous (and `.n2`) and PY-05.cache2 pass;
- every other F-05, PY-05 and PY-08 check still passes;
- `tests/test_review_r050*/r052/r053/r056_pycache.py` and this file are green;
- 0 wrong results in the harness, serial and `-n 4`.
